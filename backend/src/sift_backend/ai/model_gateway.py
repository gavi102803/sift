import json
import time
from typing import Protocol

from pydantic import ValidationError

from sift_backend.ai.context_pack import RecentTurn, build_concept_turn_context_pack
from sift_backend.ai.litellm_client import (
    LiteLLMClientError,
    LiteLLMCompletionRequest,
    LiteLLMCompletionResponse,
)
from sift_backend.schemas.concepts import ConceptDTO
from sift_backend.schemas.model_outputs import ConceptTurnResult


class ConceptModelGatewayError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


class LiteLLMCompletionClient(Protocol):
    async def create_chat_completion(
        self,
        request: LiteLLMCompletionRequest,
    ) -> LiteLLMCompletionResponse:
        ...


class ConceptModelGateway:
    def __init__(self, client: LiteLLMCompletionClient) -> None:
        self.client = client

    async def answer_concept_turn(
        self,
        concept: ConceptDTO,
        card_memory: str,
        recent_turns: list[RecentTurn],
        user_query: str,
        model_alias: str = "sift-explain",
    ) -> ConceptTurnResult:
        context_pack = build_concept_turn_context_pack(
            concept=concept,
            card_memory=card_memory,
            recent_turns=recent_turns,
            user_query=user_query,
        )
        started_at = time.perf_counter()
        try:
            completion = await self.client.create_chat_completion(
                LiteLLMCompletionRequest(
                    model_alias=model_alias,
                    messages=context_pack.messages,
                    response_format=context_pack.response_format,
                )
            )
        except LiteLLMClientError as error:
            raise ConceptModelGatewayError(
                "provider_error",
                "Model provider request failed.",
            ) from error

        latency_ms = round((time.perf_counter() - started_at) * 1000)
        payload = self._parse_content(completion.content)
        result = self._validate_payload(payload)
        return self._with_observed_model_meta(result, completion, latency_ms)

    def _parse_content(self, content: str) -> dict:
        try:
            payload = json.loads(content)
        except json.JSONDecodeError as error:
            raise ConceptModelGatewayError(
                "invalid_json",
                "Model response was not valid JSON.",
            ) from error

        if not isinstance(payload, dict):
            raise ConceptModelGatewayError(
                "invalid_json",
                "Model response JSON must be an object.",
            )
        return payload

    def _validate_payload(self, payload: dict) -> ConceptTurnResult:
        try:
            return ConceptTurnResult.model_validate(payload)
        except ValidationError as error:
            raise ConceptModelGatewayError(
                "invalid_schema",
                "Model response did not match the concept turn schema.",
            ) from error

    def _with_observed_model_meta(
        self,
        result: ConceptTurnResult,
        completion: LiteLLMCompletionResponse,
        latency_ms: int,
    ) -> ConceptTurnResult:
        provider = completion.provider or result.model_meta.provider
        meta = result.model_meta.model_copy(
            update={
                "provider": provider,
                "model": completion.model,
                "latency_ms": latency_ms,
                "input_tokens": completion.input_tokens,
                "output_tokens": completion.output_tokens,
            }
        )
        return result.model_copy(update={"model_meta": meta})
