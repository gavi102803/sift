import json
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any

import httpx

from sift_backend.runtime.types import (
    RuntimeMessage,
    RuntimeModelCompleted,
    RuntimeModelDelta,
    RuntimeModelProvider,
    RuntimeModelRequest,
    RuntimeModelResponse,
    RuntimeModelStreamEvent,
    SiftRuntimeError,
)


class MockRuntimeModelProvider:
    provider_name = "mock"

    async def complete(self, request: RuntimeModelRequest) -> RuntimeModelResponse:
        return RuntimeModelResponse(
            content=_mock_content(request),
            provider=self.provider_name,
            model=request.model,
        )

    async def stream(self, request: RuntimeModelRequest) -> AsyncIterator[RuntimeModelStreamEvent]:
        response = await self.complete(request)
        yield RuntimeModelDelta(response.content)
        yield RuntimeModelCompleted(response)

    async def list_models(self) -> list[str]:
        return ["mock-runtime"]


class OpenAICompatibleRuntimeProvider:
    """Runtime model adapter for chat-completions-compatible endpoints.

    This is intentionally owned by the Sift runtime layer instead of the old
    app-level LLM gateway. OpenAI, DeepSeek, local gateways, OpenRouter, and
    compatible routers are all just runtime model endpoints here.
    """

    provider_name = "custom"

    def __init__(
        self,
        base_url: str,
        api_key: str,
        timeout: float = 60,
        provider_name: str = "custom",
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.timeout = timeout
        self.provider_name = provider_name

    async def complete(self, request: RuntimeModelRequest) -> RuntimeModelResponse:
        data = await self._request("POST", "/chat/completions", json=_chat_payload(request))
        return _parse_chat_completion(data, self.provider_name, request.model)

    async def stream(self, request: RuntimeModelRequest) -> AsyncIterator[RuntimeModelStreamEvent]:
        payload = _chat_payload(request) | {"stream": True}
        chunks: list[str] = []
        async for data in self._stream_request("/chat/completions", payload):
            delta = _stream_delta(data)
            if delta:
                chunks.append(delta)
                yield RuntimeModelDelta(delta)
        yield RuntimeModelCompleted(
            RuntimeModelResponse(
                content="".join(chunks),
                provider=self.provider_name,
                model=request.model,
            )
        )

    async def list_models(self) -> list[str]:
        data = await self._request("GET", "/models")
        raw_models = data.get("data")
        if not isinstance(raw_models, list):
            raise SiftRuntimeError("provider_error", "Runtime provider did not return models.")
        models: list[str] = []
        for raw_model in raw_models:
            if isinstance(raw_model, dict) and isinstance(raw_model.get("id"), str):
                models.append(raw_model["id"])
        return models

    async def _request(self, method: str, path: str, **kwargs: Any) -> dict[str, Any]:
        headers = self._headers()
        async with httpx.AsyncClient(base_url=self.base_url, timeout=self.timeout) as client:
            try:
                response = await client.request(method, path, headers=headers, **kwargs)
                response.raise_for_status()
                data = response.json()
            except httpx.HTTPStatusError as error:
                raise SiftRuntimeError(
                    "provider_error",
                    f"Runtime provider returned HTTP {error.response.status_code}: "
                    f"{_error_detail(error.response)}",
                ) from error
            except httpx.TimeoutException as error:
                raise SiftRuntimeError("provider_timeout", "Runtime provider timed out.") from error
            except (httpx.HTTPError, json.JSONDecodeError) as error:
                raise SiftRuntimeError(
                    "provider_error",
                    "Runtime provider request failed.",
                ) from error
        if not isinstance(data, dict):
            raise SiftRuntimeError("provider_error", "Runtime provider returned invalid JSON.")
        return data

    async def _stream_request(
        self,
        path: str,
        payload: dict[str, Any],
    ) -> AsyncIterator[dict[str, Any]]:
        headers = self._headers() | {"Accept": "text/event-stream"}
        async with httpx.AsyncClient(base_url=self.base_url, timeout=self.timeout) as client:
            try:
                async with client.stream("POST", path, headers=headers, json=payload) as response:
                    response.raise_for_status()
                    async for line in response.aiter_lines():
                        line = line.strip()
                        if not line or not line.startswith("data:"):
                            continue
                        raw_data = line.removeprefix("data:").strip()
                        if raw_data == "[DONE]":
                            break
                        data = json.loads(raw_data)
                        if isinstance(data, dict):
                            yield data
            except httpx.HTTPStatusError as error:
                raise SiftRuntimeError(
                    "provider_error",
                    f"Runtime provider returned HTTP {error.response.status_code}: "
                    f"{await _async_error_detail(error.response)}",
                ) from error
            except httpx.TimeoutException as error:
                raise SiftRuntimeError("provider_timeout", "Runtime provider timed out.") from error
            except (httpx.HTTPError, json.JSONDecodeError) as error:
                raise SiftRuntimeError(
                    "provider_error",
                    "Runtime provider stream failed.",
                ) from error

    def _headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        return headers


class AnthropicMessagesRuntimeProvider:
    """Runtime model adapter for Anthropic-compatible Messages endpoints."""

    provider_name = "anthropic"

    def __init__(
        self,
        base_url: str,
        api_key: str,
        timeout: float = 60,
        provider_name: str = "anthropic",
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.timeout = timeout
        self.provider_name = provider_name

    async def complete(self, request: RuntimeModelRequest) -> RuntimeModelResponse:
        data = await self._request("POST", "/v1/messages", json=_anthropic_payload(request))
        return _parse_anthropic_message(data, self.provider_name, request.model)

    async def stream(self, request: RuntimeModelRequest) -> AsyncIterator[RuntimeModelStreamEvent]:
        payload = _anthropic_payload(request) | {"stream": True}
        chunks: list[str] = []
        async for data in self._stream_request("/v1/messages", payload):
            delta = _anthropic_stream_delta(data)
            if delta:
                chunks.append(delta)
                yield RuntimeModelDelta(delta)
        yield RuntimeModelCompleted(
            RuntimeModelResponse(
                content="".join(chunks),
                provider=self.provider_name,
                model=request.model,
            )
        )

    async def list_models(self) -> list[str]:
        data = await self._request("GET", "/v1/models")
        raw_models = data.get("data")
        if not isinstance(raw_models, list):
            raise SiftRuntimeError("provider_error", "Runtime provider did not return models.")
        return [
            raw_model["id"]
            for raw_model in raw_models
            if isinstance(raw_model, dict) and isinstance(raw_model.get("id"), str)
        ]

    async def _request(self, method: str, path: str, **kwargs: Any) -> dict[str, Any]:
        headers = self._headers()
        async with httpx.AsyncClient(base_url=self.base_url, timeout=self.timeout) as client:
            try:
                response = await client.request(method, path, headers=headers, **kwargs)
                response.raise_for_status()
                data = response.json()
            except httpx.HTTPStatusError as error:
                raise SiftRuntimeError(
                    "provider_error",
                    f"Runtime provider returned HTTP {error.response.status_code}: "
                    f"{_error_detail(error.response)}",
                ) from error
            except httpx.TimeoutException as error:
                raise SiftRuntimeError("provider_timeout", "Runtime provider timed out.") from error
            except (httpx.HTTPError, json.JSONDecodeError) as error:
                raise SiftRuntimeError(
                    "provider_error",
                    "Runtime provider request failed.",
                ) from error
        if not isinstance(data, dict):
            raise SiftRuntimeError("provider_error", "Runtime provider returned invalid JSON.")
        return data

    async def _stream_request(
        self,
        path: str,
        payload: dict[str, Any],
    ) -> AsyncIterator[dict[str, Any]]:
        headers = self._headers() | {"Accept": "text/event-stream"}
        async with httpx.AsyncClient(base_url=self.base_url, timeout=self.timeout) as client:
            try:
                async with client.stream("POST", path, headers=headers, json=payload) as response:
                    response.raise_for_status()
                    async for line in response.aiter_lines():
                        line = line.strip()
                        if not line or not line.startswith("data:"):
                            continue
                        raw_data = line.removeprefix("data:").strip()
                        if raw_data == "[DONE]":
                            break
                        data = json.loads(raw_data)
                        if isinstance(data, dict):
                            yield data
            except httpx.HTTPStatusError as error:
                raise SiftRuntimeError(
                    "provider_error",
                    f"Runtime provider returned HTTP {error.response.status_code}: "
                    f"{await _async_error_detail(error.response)}",
                ) from error
            except httpx.TimeoutException as error:
                raise SiftRuntimeError("provider_timeout", "Runtime provider timed out.") from error
            except (httpx.HTTPError, json.JSONDecodeError) as error:
                raise SiftRuntimeError(
                    "provider_error",
                    "Runtime provider stream failed.",
                ) from error

    def _headers(self) -> dict[str, str]:
        headers = {
            "Content-Type": "application/json",
            "anthropic-version": "2023-06-01",
        }
        if self.api_key:
            headers["x-api-key"] = self.api_key
        return headers


def _chat_payload(request: RuntimeModelRequest) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "model": request.model,
        "messages": [
            {"role": message.role, "content": message.content}
            for message in request.messages
        ],
        "temperature": request.temperature,
    }
    if request.response_format:
        payload["response_format"] = request.response_format
    return payload


def _anthropic_payload(request: RuntimeModelRequest) -> dict[str, Any]:
    messages: list[dict[str, str]] = []
    system_parts: list[str] = []
    for message in request.messages:
        if message.role == "system":
            system_parts.append(message.content)
            continue
        role = "assistant" if message.role == "assistant" else "user"
        messages.append({"role": role, "content": message.content})

    payload: dict[str, Any] = {
        "model": request.model,
        "messages": messages,
        "max_tokens": 4096,
        "temperature": request.temperature,
    }
    if system_parts:
        payload["system"] = "\n\n".join(system_parts)
    if request.response_format:
        payload["system"] = (
            (payload.get("system", "") + "\n\n") if payload.get("system") else ""
        ) + "Return only valid JSON matching the requested schema."
    return payload


def _parse_chat_completion(
    data: dict[str, Any],
    provider: str,
    fallback_model: str,
) -> RuntimeModelResponse:
    choices = data.get("choices")
    if not isinstance(choices, list) or not choices:
        raise SiftRuntimeError("provider_error", "Runtime provider returned no choices.")
    first = choices[0]
    if not isinstance(first, dict):
        raise SiftRuntimeError("provider_error", "Runtime provider returned invalid choices.")
    message = first.get("message")
    content = message.get("content") if isinstance(message, dict) else None
    if not isinstance(content, str) or not content:
        raise SiftRuntimeError("provider_error", "Runtime provider returned no content.")
    usage = data.get("usage") if isinstance(data.get("usage"), dict) else {}
    return RuntimeModelResponse(
        content=content,
        provider=provider,
        model=data.get("model") if isinstance(data.get("model"), str) else fallback_model,
        input_tokens=(
            usage.get("prompt_tokens")
            if isinstance(usage.get("prompt_tokens"), int)
            else None
        ),
        output_tokens=(
            usage.get("completion_tokens")
            if isinstance(usage.get("completion_tokens"), int)
            else None
        ),
    )


def _stream_delta(data: dict[str, Any]) -> str:
    choices = data.get("choices")
    if not isinstance(choices, list) or not choices:
        return ""
    first = choices[0]
    if not isinstance(first, dict):
        return ""
    delta = first.get("delta")
    if not isinstance(delta, dict):
        return ""
    content = delta.get("content")
    return content if isinstance(content, str) else ""


def _parse_anthropic_message(
    data: dict[str, Any],
    provider: str,
    fallback_model: str,
) -> RuntimeModelResponse:
    raw_content = data.get("content")
    if not isinstance(raw_content, list):
        raise SiftRuntimeError("provider_error", "Runtime provider returned no content.")
    text_parts: list[str] = []
    for block in raw_content:
        if not isinstance(block, dict):
            continue
        if block.get("type") == "text" and isinstance(block.get("text"), str):
            text_parts.append(block["text"])
    content = "\n".join(text_parts).strip()
    if not content:
        raise SiftRuntimeError("provider_error", "Runtime provider returned no text content.")
    usage = data.get("usage") if isinstance(data.get("usage"), dict) else {}
    return RuntimeModelResponse(
        content=content,
        provider=provider,
        model=data.get("model") if isinstance(data.get("model"), str) else fallback_model,
        input_tokens=(
            usage.get("input_tokens") if isinstance(usage.get("input_tokens"), int) else None
        ),
        output_tokens=(
            usage.get("output_tokens") if isinstance(usage.get("output_tokens"), int) else None
        ),
    )


def _anthropic_stream_delta(data: dict[str, Any]) -> str:
    if data.get("type") != "content_block_delta":
        return ""
    delta = data.get("delta")
    if not isinstance(delta, dict):
        return ""
    text = delta.get("text")
    return text if isinstance(text, str) else ""


def _error_detail(response: httpx.Response) -> str:
    try:
        data = response.json()
    except json.JSONDecodeError:
        return response.text[:500]
    if isinstance(data, dict):
        detail = data.get("error") or data.get("detail") or data
        return json.dumps(detail, ensure_ascii=False)[:500]
    return str(data)[:500]


async def _async_error_detail(response: httpx.Response) -> str:
    try:
        await response.aread()
    except httpx.HTTPError:
        pass
    return _error_detail(response)


def _mock_content(request: RuntimeModelRequest) -> str:
    user_message = _last_user_message(request.messages)
    if "Create a Sift concept card" in user_message:
        title = user_message.split("'rawCapture':", 1)[-1].split(",", 1)[0].strip(" {}'\"")
        return json.dumps(
            {
                "canonicalTitle": title or "Untitled Concept",
                "displayTitle": title or "Untitled Concept",
                "oneLineExplanation": f"{title or 'This concept'} is ready to be refined.",
                "blocks": [
                    {
                        "blockType": "whatItIs",
                        "content": f"{title or 'This'} is a captured concept.",
                    },
                    {
                        "blockType": "whyItMatters",
                        "content": "Sift can deepen it with follow-up questions and sources.",
                    },
                ],
                "suggestedTags": [],
                "suggestedTopics": [],
                "answerSource": {
                    "sourceType": "modelKnowledge",
                    "confidence": 0.5,
                    "uncertaintyNote": "Mock runtime response.",
                    "retrievalUsed": False,
                    "freshnessNote": None,
                    "citations": [],
                },
                "modelMeta": {
                    "provider": "mock",
                    "model": request.model,
                    "latencyMs": None,
                    "inputTokens": None,
                    "outputTokens": None,
                },
            }
        )
    return json.dumps(
        {
            "answer": f"Draft runtime answer for: {user_message}",
            "answerSource": {
                "sourceType": "modelKnowledge",
                "confidence": 0.5,
                "uncertaintyNote": "Mock runtime response.",
                "retrievalUsed": False,
                "freshnessNote": None,
                "citations": [],
            },
            "updateDecision": {
                "mode": "none",
                "reason": "Mock runtime does not mutate durable notes.",
            },
            "autoPatch": [],
            "proposal": None,
            "relations": [],
            "suggestedTags": [],
            "suggestedTopics": [],
            "memoryPatch": {
                "confirmedUnderstanding": [],
                "openQuestions": [user_message],
                "userPreferences": [],
            },
            "modelMeta": {
                "provider": "mock",
                "model": request.model,
                "latencyMs": None,
                "inputTokens": None,
                "outputTokens": None,
            },
        }
    )


def _last_user_message(messages: tuple[RuntimeMessage, ...]) -> str:
    for message in reversed(messages):
        if message.role == "user":
            return message.content
    return ""


@dataclass(frozen=True)
class RuntimeModelProviderProfile:
    name: str
    display_name: str
    adapter: str
    default_base_url: str
    default_model: str
    supports_model_listing: bool = True
    description: str = ""
    requires_api_key: bool = True
    status: str = "available"
    is_advanced: bool = False


class ModelProviderRegistry:
    """Hermes-style provider profile registry trimmed for Sift's runtime."""

    def __init__(self) -> None:
        self._profiles: dict[str, RuntimeModelProviderProfile] = {}
        self._aliases: dict[str, str] = {}

    def register(
        self,
        profile: RuntimeModelProviderProfile,
        *,
        aliases: tuple[str, ...] = (),
    ) -> None:
        normalized = _normalize_provider_key(profile.name)
        self._profiles[normalized] = profile
        self._aliases[normalized] = normalized
        for alias in aliases:
            self._aliases[_normalize_provider_key(alias)] = normalized

    def normalize(self, provider_name: str) -> str:
        key = _normalize_provider_key(provider_name)
        return self._aliases.get(key, key)

    def profile(self, provider_name: str) -> RuntimeModelProviderProfile:
        normalized = self.normalize(provider_name)
        profile = self._profiles.get(normalized)
        if profile is None:
            raise SiftRuntimeError(
                "provider_not_configured",
                f"Runtime model provider is not registered: {provider_name}.",
            )
        return profile

    def create_provider(
        self,
        provider_name: str,
        *,
        base_url: str,
        api_key: str,
        timeout: float = 60,
    ) -> RuntimeModelProvider:
        profile = self.profile(provider_name)
        if profile.adapter == "mock":
            return MockRuntimeModelProvider()
        if profile.adapter == "anthropic_messages":
            return AnthropicMessagesRuntimeProvider(
                base_url=base_url.strip().rstrip("/") or profile.default_base_url,
                api_key=api_key,
                timeout=timeout,
                provider_name=profile.name,
            )
        if profile.adapter != "openai_compatible":
            raise SiftRuntimeError(
                "provider_not_supported",
                f"Runtime model provider adapter is not supported: {profile.adapter}.",
            )
        return OpenAICompatibleRuntimeProvider(
            base_url=base_url.strip().rstrip("/") or profile.default_base_url,
            api_key=api_key,
            timeout=timeout,
            provider_name=profile.name,
        )

    def resolve_model(self, provider_name: str, configured_model: str) -> str:
        profile = self.profile(provider_name)
        return configured_model.strip() or profile.default_model

    def resolve_base_url(self, provider_name: str, configured_base_url: str) -> str:
        profile = self.profile(provider_name)
        return configured_base_url.strip().rstrip("/") or profile.default_base_url

    def names(self) -> list[str]:
        return sorted(self._profiles)

    def profiles(self) -> list[RuntimeModelProviderProfile]:
        return [self._profiles[name] for name in sorted(self._profiles)]


def build_model_provider_registry() -> ModelProviderRegistry:
    registry = ModelProviderRegistry()
    registry.register(
        RuntimeModelProviderProfile(
            name="mock",
            display_name="Mock Runtime",
            adapter="mock",
            default_base_url="",
            default_model="mock-runtime",
            supports_model_listing=False,
            description="Local deterministic runtime for development.",
            requires_api_key=False,
            status="development",
            is_advanced=True,
        )
    )
    registry.register(
        RuntimeModelProviderProfile(
            name="openai",
            display_name="OpenAI",
            adapter="openai_compatible",
            default_base_url="https://api.openai.com/v1",
            default_model="gpt-5.5",
            description="OpenAI API via the OpenAI-compatible chat adapter.",
        ),
        aliases=("openai_responses",),
    )
    registry.register(
        RuntimeModelProviderProfile(
            name="deepseek",
            display_name="DeepSeek",
            adapter="openai_compatible",
            default_base_url="https://api.deepseek.com/v1",
            default_model="deepseek-chat",
            description="DeepSeek via OpenAI-compatible chat completions.",
        )
    )
    registry.register(
        RuntimeModelProviderProfile(
            name="openrouter",
            display_name="OpenRouter",
            adapter="openai_compatible",
            default_base_url="https://openrouter.ai/api/v1",
            default_model="openai/gpt-5.5",
            description="OpenRouter aggregator via OpenAI-compatible chat completions.",
        )
    )
    registry.register(
        RuntimeModelProviderProfile(
            name="nous",
            display_name="Nous",
            adapter="openai_compatible",
            default_base_url="https://inference-api.nousresearch.com/v1",
            default_model="Hermes-4-405B",
            description="Nous Research inference endpoint.",
        )
    )
    registry.register(
        RuntimeModelProviderProfile(
            name="kimi",
            display_name="Kimi",
            adapter="openai_compatible",
            default_base_url="https://api.moonshot.ai/v1",
            default_model="kimi-k2-0711-preview",
            description="Moonshot Kimi via OpenAI-compatible chat completions.",
        )
    )
    registry.register(
        RuntimeModelProviderProfile(
            name="custom",
            display_name="Custom OpenAI-compatible",
            adapter="openai_compatible",
            default_base_url="https://api.openai.com/v1",
            default_model="gpt-5.5",
            description="Custom, local, or self-hosted OpenAI-compatible endpoint.",
            is_advanced=True,
        ),
        aliases=("sift_runtime", "hermes_lite", "openai_compatible"),
    )
    for profile in _upstream_model_provider_profiles():
        registry.register(profile)
    return registry


def _upstream_model_provider_profiles() -> list[RuntimeModelProviderProfile]:
    return [
        RuntimeModelProviderProfile(
            name="alibaba",
            display_name="Alibaba DashScope",
            adapter="openai_compatible",
            default_base_url="https://dashscope-intl.aliyuncs.com/compatible-mode/v1",
            default_model="qwen3-coder-plus",
            description="Alibaba DashScope OpenAI-compatible endpoint.",
        ),
        RuntimeModelProviderProfile(
            name="alibaba-coding-plan",
            display_name="Alibaba Coding Plan",
            adapter="openai_compatible",
            default_base_url="https://coding-intl.dashscope.aliyuncs.com/v1",
            default_model="qwen3-coder-plus",
            description="Alibaba Cloud Coding Plan OpenAI-compatible endpoint.",
            is_advanced=True,
        ),
        RuntimeModelProviderProfile(
            name="anthropic",
            display_name="Anthropic",
            adapter="anthropic_messages",
            default_base_url="https://api.anthropic.com",
            default_model="claude-haiku-4-5-20251001",
            description="Claude native Messages API provider.",
            supports_model_listing=True,
        ),
        RuntimeModelProviderProfile(
            name="arcee",
            display_name="Arcee AI",
            adapter="openai_compatible",
            default_base_url="https://api.arcee.ai/api/v1",
            default_model="auto",
            description="Arcee AI OpenAI-compatible endpoint.",
        ),
        RuntimeModelProviderProfile(
            name="azure-foundry",
            display_name="Microsoft Foundry",
            adapter="openai_compatible",
            default_base_url="",
            default_model="",
            description="Azure Foundry OpenAI-compatible endpoint; provide your resource URL.",
            supports_model_listing=False,
            is_advanced=True,
        ),
        RuntimeModelProviderProfile(
            name="gemini",
            display_name="Google Gemini",
            adapter="openai_compatible",
            default_base_url="https://generativelanguage.googleapis.com/v1beta/openai",
            default_model="gemini-3.5-flash",
            description="Google Gemini through its OpenAI-compatible endpoint.",
        ),
        RuntimeModelProviderProfile(
            name="gmi",
            display_name="GMI Cloud",
            adapter="openai_compatible",
            default_base_url="https://api.gmi-serving.com/v1",
            default_model="google/gemini-3.1-flash-lite-preview",
            description="GMI Cloud OpenAI-compatible endpoint.",
        ),
        RuntimeModelProviderProfile(
            name="huggingface",
            display_name="HuggingFace",
            adapter="openai_compatible",
            default_base_url="https://router.huggingface.co/v1",
            default_model="openai/gpt-oss-120b",
            description="HuggingFace Inference Providers router.",
        ),
        RuntimeModelProviderProfile(
            name="kilocode",
            display_name="Kilo Code",
            adapter="openai_compatible",
            default_base_url="https://api.kilo.ai/api/gateway",
            default_model="google/gemini-3-flash-preview",
            description="Kilo Code OpenAI-compatible gateway.",
        ),
        RuntimeModelProviderProfile(
            name="kimi-coding",
            display_name="Kimi Coding",
            adapter="openai_compatible",
            default_base_url="https://api.moonshot.ai/v1",
            default_model="kimi-k2-turbo-preview",
            description="Moonshot Kimi Coding OpenAI-compatible endpoint.",
        ),
        RuntimeModelProviderProfile(
            name="minimax",
            display_name="MiniMax",
            adapter="anthropic_messages",
            default_base_url="https://api.minimax.io/anthropic",
            default_model="MiniMax-M3",
            description="MiniMax Anthropic-compatible Messages endpoint.",
        ),
        RuntimeModelProviderProfile(
            name="novita",
            display_name="NovitaAI",
            adapter="openai_compatible",
            default_base_url="https://api.novita.ai/openai/v1",
            default_model="deepseek/deepseek-v3-0324",
            description="NovitaAI OpenAI-compatible endpoint.",
        ),
        RuntimeModelProviderProfile(
            name="nvidia",
            display_name="NVIDIA NIM",
            adapter="openai_compatible",
            default_base_url="https://integrate.api.nvidia.com/v1",
            default_model="nvidia/llama-3.3-nemotron-super-49b-v1",
            description="NVIDIA NIM OpenAI-compatible endpoint.",
        ),
        RuntimeModelProviderProfile(
            name="ollama-cloud",
            display_name="Ollama Cloud",
            adapter="openai_compatible",
            default_base_url="https://ollama.com/v1",
            default_model="gpt-oss:120b",
            description="Ollama Cloud OpenAI-compatible endpoint.",
        ),
        RuntimeModelProviderProfile(
            name="opencode-zen",
            display_name="OpenCode Zen",
            adapter="openai_compatible",
            default_base_url="https://opencode.ai/zen/v1",
            default_model="gemini-3-flash",
            description="OpenCode Zen OpenAI-compatible endpoint.",
        ),
        RuntimeModelProviderProfile(
            name="stepfun",
            display_name="StepFun",
            adapter="openai_compatible",
            default_base_url="https://api.stepfun.ai/step_plan/v1",
            default_model="step-3.5-flash",
            description="StepFun Step Plan OpenAI-compatible endpoint.",
        ),
        RuntimeModelProviderProfile(
            name="xiaomi",
            display_name="Xiaomi MiMo",
            adapter="openai_compatible",
            default_base_url="https://api.xiaomimimo.com/v1",
            default_model="mimo-v1",
            description="Xiaomi MiMo OpenAI-compatible endpoint.",
        ),
        RuntimeModelProviderProfile(
            name="zai",
            display_name="Z.AI / GLM",
            adapter="openai_compatible",
            default_base_url="https://api.z.ai/api/paas/v4",
            default_model="glm-4.5-flash",
            description="Z.AI / GLM OpenAI-compatible endpoint.",
        ),
    ]


def _coming_soon_profile(
    name: str,
    display_name: str,
    description: str,
) -> RuntimeModelProviderProfile:
    return RuntimeModelProviderProfile(
        name=name,
        display_name=display_name,
        adapter="not_implemented",
        default_base_url="",
        default_model="",
        supports_model_listing=False,
        description=description,
        status="comingSoon",
        is_advanced=True,
    )


def build_runtime_model_provider(
    provider_name: str,
    *,
    base_url: str,
    api_key: str,
    timeout: float = 60,
) -> RuntimeModelProvider:
    return build_model_provider_registry().create_provider(
        provider_name,
        base_url=base_url,
        api_key=api_key,
        timeout=timeout,
    )


def resolve_runtime_model(provider_name: str, configured_model: str) -> str:
    return build_model_provider_registry().resolve_model(provider_name, configured_model)


def resolve_runtime_base_url(provider_name: str, configured_base_url: str) -> str:
    return build_model_provider_registry().resolve_base_url(provider_name, configured_base_url)


def normalize_runtime_provider(provider_name: str) -> str:
    return build_model_provider_registry().normalize(provider_name)


def _normalize_provider_key(provider_name: str) -> str:
    return provider_name.strip().lower()
