from dataclasses import dataclass
from typing import Any

import httpx


class LiteLLMClientError(RuntimeError):
    pass


@dataclass(frozen=True)
class LiteLLMMessage:
    role: str
    content: str


@dataclass(frozen=True)
class LiteLLMCompletionRequest:
    model_alias: str
    messages: tuple[LiteLLMMessage, ...]
    response_format: dict[str, Any] | None = None
    temperature: float = 0.2


@dataclass(frozen=True)
class LiteLLMCompletionResponse:
    content: str
    provider: str | None
    model: str
    input_tokens: int | None
    output_tokens: int | None


class LiteLLMClient:
    def __init__(
        self,
        base_url: str,
        api_key: str,
        http_client: httpx.AsyncClient | None = None,
        timeout: float = 30,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.http_client = http_client
        self.timeout = timeout

    async def create_chat_completion(
        self,
        request: LiteLLMCompletionRequest,
    ) -> LiteLLMCompletionResponse:
        payload: dict[str, Any] = {
            "model": request.model_alias,
            "messages": [
                {"role": message.role, "content": message.content}
                for message in request.messages
            ],
            "temperature": request.temperature,
        }
        if request.response_format is not None:
            payload["response_format"] = request.response_format

        response = await self._post("/v1/chat/completions", payload)
        return self._parse_completion_response(response, fallback_model=request.model_alias)

    async def _post(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        owns_client = self.http_client is None
        client = self.http_client or httpx.AsyncClient(timeout=self.timeout)
        try:
            response = await client.post(
                f"{self.base_url}{path}",
                json=payload,
                headers={"Authorization": f"Bearer {self.api_key}"},
            )
            response.raise_for_status()
            data = response.json()
            if not isinstance(data, dict):
                raise LiteLLMClientError("LiteLLM returned a non-object JSON response.")
            return data
        except httpx.HTTPStatusError as error:
            raise LiteLLMClientError(
                f"LiteLLM returned HTTP {error.response.status_code}."
            ) from error
        except httpx.HTTPError as error:
            raise LiteLLMClientError("LiteLLM request failed.") from error
        finally:
            if owns_client:
                await client.aclose()

    def _parse_completion_response(
        self,
        data: dict[str, Any],
        fallback_model: str,
    ) -> LiteLLMCompletionResponse:
        choices = data.get("choices")
        if not isinstance(choices, list) or not choices:
            raise LiteLLMClientError("LiteLLM response did not include choices.")

        first_choice = choices[0]
        if not isinstance(first_choice, dict):
            raise LiteLLMClientError("LiteLLM choice was not an object.")

        message = first_choice.get("message")
        if not isinstance(message, dict) or not isinstance(message.get("content"), str):
            raise LiteLLMClientError("LiteLLM response did not include message content.")

        usage = data.get("usage") if isinstance(data.get("usage"), dict) else {}
        provider = data.get("provider")
        model = data.get("model")

        return LiteLLMCompletionResponse(
            content=message["content"],
            provider=provider if isinstance(provider, str) else None,
            model=model if isinstance(model, str) else fallback_model,
            input_tokens=_optional_int(usage.get("prompt_tokens")),
            output_tokens=_optional_int(usage.get("completion_tokens")),
        )


def _optional_int(value: Any) -> int | None:
    return value if isinstance(value, int) else None

