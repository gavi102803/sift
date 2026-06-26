import json
import time
from collections.abc import AsyncIterator
from dataclasses import dataclass

from pydantic import ValidationError

from sift_backend.ai.context_pack import (
    RecentTurn,
    build_concept_turn_context_pack,
    build_initial_concept_context_pack,
)
from sift_backend.runtime.tools import (
    RuntimeCitation,
    RuntimeWebSearchTool,
    build_runtime_tool_registry,
)
from sift_backend.runtime.types import (
    RuntimeMessage,
    RuntimeModelCompleted,
    RuntimeModelDelta,
    RuntimeModelProvider,
    RuntimeModelRequest,
    RuntimeModelResponse,
    SiftRuntimeError,
)
from sift_backend.schemas.common import AnswerSourceType
from sift_backend.schemas.concepts import CitationDTO, ConceptDTO
from sift_backend.schemas.model_outputs import ConceptInitialResult, ConceptTurnResult


@dataclass(frozen=True)
class ConceptRuntimeDelta:
    content: str


@dataclass(frozen=True)
class ConceptRuntimeResult:
    result: ConceptTurnResult


ConceptRuntimeStreamEvent = ConceptRuntimeDelta | ConceptRuntimeResult


class LightweightHermesRuntime:
    """Trimmed, Sift-owned agent runtime.

    It keeps the parts Sift needs from a Hermes-style runtime: model routing,
    session-shaped context, restricted tools, retrieval-first policy, streaming
    events, and structured outputs. Product truth still lives in Sift's domain
    store and patch engine.
    """

    def __init__(
        self,
        model_provider: RuntimeModelProvider,
        model: str,
        web_search_tool: RuntimeWebSearchTool,
        web_search_enabled: bool = True,
    ) -> None:
        self.model_provider = model_provider
        self.model = model
        self.web_search_tool = web_search_tool
        self.tool_registry = build_runtime_tool_registry(web_search_tool)
        self.web_search_enabled = web_search_enabled

    async def generate_initial_concept(
        self,
        raw_capture: str,
        locale: str,
    ) -> ConceptInitialResult:
        context_pack = build_initial_concept_context_pack(raw_capture=raw_capture, locale=locale)
        citations = await self._retrieve(raw_capture)
        request = RuntimeModelRequest(
            model=self.model,
            messages=_messages_with_retrieval(context_pack.messages, citations),
            response_format=context_pack.response_format,
        )
        started_at = time.perf_counter()
        completion = await self.model_provider.complete(request)
        latency_ms = round((time.perf_counter() - started_at) * 1000)
        result = _validate_initial(_parse_json(completion.content))
        return _initial_with_runtime_metadata(result, completion, latency_ms, citations)

    async def answer_concept_turn(
        self,
        concept: ConceptDTO,
        card_memory: str,
        recent_turns: list[RecentTurn],
        user_query: str,
    ) -> ConceptTurnResult:
        context_pack = build_concept_turn_context_pack(
            concept=concept,
            card_memory=card_memory,
            recent_turns=recent_turns,
            user_query=user_query,
        )
        citations = await self._retrieve(user_query)
        request = RuntimeModelRequest(
            model=self.model,
            messages=_messages_with_retrieval(context_pack.messages, citations),
            response_format=context_pack.response_format,
        )
        started_at = time.perf_counter()
        completion = await self.model_provider.complete(request)
        latency_ms = round((time.perf_counter() - started_at) * 1000)
        result = _validate_turn(_parse_json(completion.content))
        return _turn_with_runtime_metadata(result, completion, latency_ms, citations)

    async def stream_concept_turn_answer(
        self,
        concept: ConceptDTO,
        card_memory: str,
        recent_turns: list[RecentTurn],
        user_query: str,
    ) -> AsyncIterator[ConceptRuntimeStreamEvent]:
        context_pack = build_concept_turn_context_pack(
            concept=concept,
            card_memory=card_memory,
            recent_turns=recent_turns,
            user_query=user_query,
        )
        citations = await self._retrieve(user_query)
        request = RuntimeModelRequest(
            model=self.model,
            messages=_messages_with_retrieval(context_pack.messages, citations),
            response_format=context_pack.response_format,
        )
        started_at = time.perf_counter()
        extractor = _JSONAnswerFieldExtractor()
        completed: RuntimeModelResponse | None = None
        chunks: list[str] = []
        async for event in self.model_provider.stream(request):
            if isinstance(event, RuntimeModelDelta):
                chunks.append(event.content)
                delta = extractor.feed(event.content)
                if delta:
                    yield ConceptRuntimeDelta(delta)
            if isinstance(event, RuntimeModelCompleted):
                completed = event.response
        if completed is None:
            completed = RuntimeModelResponse(
                content="".join(chunks),
                provider=self.model_provider.provider_name,
                model=self.model,
            )
        latency_ms = round((time.perf_counter() - started_at) * 1000)
        result = _validate_turn(_parse_json(completed.content))
        yield ConceptRuntimeResult(
            _turn_with_runtime_metadata(result, completed, latency_ms, citations)
        )

    async def _retrieve(self, query: str) -> list[RuntimeCitation]:
        if not self.web_search_enabled:
            return []
        try:
            citations = await self.tool_registry.dispatch("web.search", {"query": query})
        except SiftRuntimeError:
            raise
        except Exception as error:
            raise SiftRuntimeError("tool_error", "Runtime web search failed.") from error
        if not isinstance(citations, list) or not all(
            isinstance(citation, RuntimeCitation) for citation in citations
        ):
            raise SiftRuntimeError("tool_error", "Runtime web search returned invalid results.")
        return citations


def _messages_with_retrieval(
    messages: tuple[RuntimeMessage, ...],
    citations: list[RuntimeCitation],
) -> tuple[RuntimeMessage, ...]:
    if not citations:
        return messages
    retrieval_payload = [
        {"title": citation.title, "url": citation.url, "snippet": citation.snippet}
        for citation in citations
    ]
    retrieval_message = RuntimeMessage(
        role="system",
        content=(
            "Runtime retrieval results. Use only these sources for web-verified claims "
            f"and cite them concisely:\n{json.dumps(retrieval_payload, ensure_ascii=False)}"
        ),
    )
    return messages[:-1] + (retrieval_message, messages[-1])


def _parse_json(content: str) -> dict:
    try:
        payload = json.loads(content)
    except json.JSONDecodeError as error:
        raise SiftRuntimeError("invalid_json", "Runtime response was not valid JSON.") from error
    if not isinstance(payload, dict):
        raise SiftRuntimeError("invalid_json", "Runtime response JSON must be an object.")
    return payload


def _validate_turn(payload: dict) -> ConceptTurnResult:
    try:
        return ConceptTurnResult.model_validate(payload)
    except ValidationError as error:
        raise SiftRuntimeError(
            "invalid_schema",
            "Runtime response did not match the concept turn schema.",
        ) from error


def _validate_initial(payload: dict) -> ConceptInitialResult:
    try:
        return ConceptInitialResult.model_validate(payload)
    except ValidationError as error:
        raise SiftRuntimeError(
            "invalid_schema",
            "Runtime response did not match the initial concept schema.",
        ) from error


def _initial_with_runtime_metadata(
    result: ConceptInitialResult,
    completion: RuntimeModelResponse,
    latency_ms: int,
    citations: list[RuntimeCitation],
) -> ConceptInitialResult:
    return result.model_copy(
        update={
            "answer_source": _answer_source_with_citations(
                result.answer_source,
                citations,
            ),
            "model_meta": result.model_meta.model_copy(
                update={
                    "provider": completion.provider,
                    "model": completion.model,
                    "latency_ms": latency_ms,
                    "input_tokens": completion.input_tokens,
                    "output_tokens": completion.output_tokens,
                }
            ),
        }
    )


def _turn_with_runtime_metadata(
    result: ConceptTurnResult,
    completion: RuntimeModelResponse,
    latency_ms: int,
    citations: list[RuntimeCitation],
) -> ConceptTurnResult:
    return result.model_copy(
        update={
            "answer_source": _answer_source_with_citations(
                result.answer_source,
                citations,
            ),
            "model_meta": result.model_meta.model_copy(
                update={
                    "provider": completion.provider,
                    "model": completion.model,
                    "latency_ms": latency_ms,
                    "input_tokens": completion.input_tokens,
                    "output_tokens": completion.output_tokens,
                }
            ),
        }
    )


def _answer_source_with_citations(answer_source, citations: list[RuntimeCitation]):
    if not citations:
        return answer_source
    merged = list(answer_source.citations)
    seen = {citation.url for citation in merged}
    for citation in citations:
        if citation.url in seen:
            continue
        merged.append(CitationDTO(title=citation.title, url=citation.url))
        seen.add(citation.url)
    return answer_source.model_copy(
        update={
            "source_type": AnswerSourceType.web_verified,
            "retrieval_used": True,
            "citations": merged,
        }
    )


class _JSONAnswerFieldExtractor:
    def __init__(self) -> None:
        self.buffer = ""
        self.answer_started = False
        self.answer_complete = False
        self.escape = False

    def feed(self, chunk: str) -> str:
        if self.answer_complete:
            return ""
        self.buffer += chunk
        if not self.answer_started:
            marker = '"answer"'
            marker_index = self.buffer.find(marker)
            if marker_index < 0:
                self.buffer = self.buffer[-32:]
                return ""
            colon_index = self.buffer.find(":", marker_index + len(marker))
            if colon_index < 0:
                return ""
            quote_index = self.buffer.find('"', colon_index + 1)
            if quote_index < 0:
                return ""
            self.buffer = self.buffer[quote_index + 1 :]
            self.answer_started = True

        output: list[str] = []
        keep_from = len(self.buffer)
        for index, character in enumerate(self.buffer):
            if self.escape:
                output.append(_decode_escape(character))
                self.escape = False
                continue
            if character == "\\":
                self.escape = True
                continue
            if character == '"':
                self.answer_complete = True
                keep_from = index + 1
                break
            output.append(character)
        else:
            keep_from = len(self.buffer)

        self.buffer = self.buffer[keep_from:]
        return "".join(output)


def _decode_escape(character: str) -> str:
    return {
        "n": "\n",
        "r": "\r",
        "t": "\t",
        '"': '"',
        "\\": "\\",
        "/": "/",
    }.get(character, character)
