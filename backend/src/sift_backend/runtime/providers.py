import json
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any

import httpx

from sift_backend.runtime.anthropic_messages_driver import AnthropicMessagesDriver
from sift_backend.runtime.gemini_driver import GeminiDriver
from sift_backend.runtime.payload_mappers import build_chat_completions_payload
from sift_backend.runtime.provider_presets import MODEL_PROVIDER_PRESETS
from sift_backend.runtime.responses_driver import ResponsesDriver
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


class ChatCompletionsDriver:
    """Runtime driver for chat-completions-compatible endpoints.

    This is protocol-owned, not provider-owned. Provider-specific differences
    are resolved by capability policy and payload mappers before the HTTP body
    is sent.
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
        data = await self._request(
            "POST",
            "/chat/completions",
            json=_chat_payload(
                request,
                provider_name=self.provider_name,
                base_url=self.base_url,
            ),
        )
        return _parse_chat_completion(data, self.provider_name, request.model)

    async def stream(self, request: RuntimeModelRequest) -> AsyncIterator[RuntimeModelStreamEvent]:
        payload = _chat_payload(
            request,
            provider_name=self.provider_name,
            base_url=self.base_url,
        ) | {"stream": True}
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


OpenAICompatibleRuntimeProvider = ChatCompletionsDriver


AnthropicMessagesRuntimeProvider = AnthropicMessagesDriver


def _chat_payload(
    request: RuntimeModelRequest,
    *,
    provider_name: str,
    base_url: str | None = None,
) -> dict[str, Any]:
    return build_chat_completions_payload(
        request,
        provider_name=provider_name,
        base_url=base_url,
    )


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
    api_mode: str = "chat_completions"
    protocol_driver: str = "ChatCompletionsDriver"
    hermes_plugin_path: str | None = None
    exposure_tier: str = "plannedStable"
    supports_model_listing: bool = True
    description: str = ""
    requires_api_key: bool = True
    status: str = "available"
    is_advanced: bool = False

    def __post_init__(self) -> None:
        if self.exposure_tier == "advanced" and not self.is_advanced:
            object.__setattr__(self, "is_advanced", True)


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
        if profile.adapter == "responses":
            return ResponsesDriver(
                base_url=base_url.strip().rstrip("/") or profile.default_base_url,
                api_key=api_key,
                timeout=timeout,
                provider_name=profile.name,
            )
        if profile.adapter == "gemini":
            return GeminiDriver(
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
        return ChatCompletionsDriver(
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
    for preset in MODEL_PROVIDER_PRESETS:
        registry.register(
            RuntimeModelProviderProfile(**preset["profile"]),
            aliases=tuple(preset.get("aliases", ())),
        )
    return registry


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
