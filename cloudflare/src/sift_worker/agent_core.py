from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, replace
from typing import Any

from sift_worker.tool_contracts import (
    WEB_TOOL_CONTRACTS,
    canonical_tool_name,
    tool_contract_hash,
)

AgentEventSink = Callable[[str, dict[str, Any]], Awaitable[None]]
CancellationProbe = Callable[[], Awaitable[bool]]
MAX_MODEL_OUTPUT_TOKENS = 4_096


class AgentControlError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass(frozen=True)
class AgentSpec:
    name: str
    version: str
    prompt_version: str
    allowed_tools: frozenset[str]
    max_model_calls: int
    max_tool_calls: int
    max_steps: int
    max_model_output_tokens: int
    tool_contract_hash: str = ""

    def budget(self) -> dict[str, int]:
        return {
            "maxModelCalls": self.max_model_calls,
            "maxToolCalls": self.max_tool_calls,
            "maxSteps": self.max_steps,
            "maxModelOutputTokens": self.max_model_output_tokens,
        }


_WEB_TOOL_NAMES = frozenset(contract.name for contract in WEB_TOOL_CONTRACTS)
_WEB_TOOL_CONTRACT_HASH = tool_contract_hash(_WEB_TOOL_NAMES)

INITIAL_AGENT_SPEC = AgentSpec(
    name="sift.initial-concept",
    version="1.4",
    prompt_version="initial-concept-v3",
    allowed_tools=_WEB_TOOL_NAMES,
    max_model_calls=6,
    max_tool_calls=4,
    max_steps=4,
    max_model_output_tokens=MAX_MODEL_OUTPUT_TOKENS,
    tool_contract_hash=_WEB_TOOL_CONTRACT_HASH,
)
FOLLOW_UP_AGENT_SPEC = AgentSpec(
    name="sift.follow-up",
    version="1.4",
    prompt_version="follow-up-v3",
    allowed_tools=_WEB_TOOL_NAMES,
    max_model_calls=6,
    max_tool_calls=4,
    max_steps=4,
    max_model_output_tokens=MAX_MODEL_OUTPUT_TOKENS,
    tool_contract_hash=_WEB_TOOL_CONTRACT_HASH,
)
CONTINUITY_AGENT_SPEC = AgentSpec(
    name="sift.continuity-summary",
    version="1.1",
    prompt_version="continuity-summary-v2",
    allowed_tools=frozenset(),
    max_model_calls=2,
    max_tool_calls=0,
    max_steps=3,
    max_model_output_tokens=MAX_MODEL_OUTPUT_TOKENS,
)
KNOWLEDGE_REVIEW_AGENT_SPEC = AgentSpec(
    name="sift.knowledge-review",
    version="1.1",
    prompt_version="knowledge-review-v2",
    allowed_tools=frozenset(),
    max_model_calls=3,
    max_tool_calls=0,
    max_steps=3,
    max_model_output_tokens=MAX_MODEL_OUTPUT_TOKENS,
)

AGENT_SPECS = {
    "initialConcept": INITIAL_AGENT_SPEC,
    "followUp": FOLLOW_UP_AGENT_SPEC,
    "continuitySummary": CONTINUITY_AGENT_SPEC,
    "knowledgeReview": KNOWLEDGE_REVIEW_AGENT_SPEC,
}
_PREVIOUS_INITIAL_AGENT_SPEC = replace(
    INITIAL_AGENT_SPEC,
    version="1.3",
    prompt_version="initial-concept-v2",
)
_PREVIOUS_FOLLOW_UP_AGENT_SPEC = replace(
    FOLLOW_UP_AGENT_SPEC,
    version="1.3",
    prompt_version="follow-up-v2",
)
_LEGACY_INITIAL_AGENT_SPEC = replace(
    _PREVIOUS_INITIAL_AGENT_SPEC,
    version="1.2",
    tool_contract_hash="",
)
_LEGACY_FOLLOW_UP_AGENT_SPEC = replace(
    _PREVIOUS_FOLLOW_UP_AGENT_SPEC,
    version="1.2",
    tool_contract_hash="",
)
_AGENT_SPEC_HISTORY = {
    (kind, spec.version): spec
    for kind, specs in {
        "initialConcept": (
            _LEGACY_INITIAL_AGENT_SPEC,
            _PREVIOUS_INITIAL_AGENT_SPEC,
            INITIAL_AGENT_SPEC,
        ),
        "followUp": (
            _LEGACY_FOLLOW_UP_AGENT_SPEC,
            _PREVIOUS_FOLLOW_UP_AGENT_SPEC,
            FOLLOW_UP_AGENT_SPEC,
        ),
        "continuitySummary": (CONTINUITY_AGENT_SPEC,),
        "knowledgeReview": (KNOWLEDGE_REVIEW_AGENT_SPEC,),
    }.items()
    for spec in specs
}

_EXPLICIT_RETRIEVAL_MARKERS = (
    "https://",
    "search the web",
    "web search",
    "browse the web",
    "look up",
    "latest",
    "current",
    "today",
    "verify",
    "sources",
    "citations",
    "搜索",
    "搜一下",
    "查一下",
    "检索",
    "联网",
    "最新",
    "今天",
    "核实",
    "验证",
    "来源",
    "引用",
)
_RETRIEVAL_META_MARKERS = (
    "why didn't you search",
    "why did not you search",
    "why not search",
    "why didn't you use web search",
    "为什么不用web search",
    "为什么不用 web search",
    "为什么没有搜索",
    "为什么没搜索",
)


def agent_spec_for_kind(kind: str) -> AgentSpec:
    try:
        return AGENT_SPECS[kind]
    except KeyError as error:
        raise ValueError(f"Unsupported agent workflow: {kind}") from error


def agent_spec_from_snapshot(
    kind: str,
    *,
    name: str,
    version: str,
    prompt_version: str,
    budget: dict[str, Any],
    tool_contract_hash: str = "",
) -> AgentSpec:
    """Resolve a persisted run without silently changing its execution contract."""

    spec = _AGENT_SPEC_HISTORY.get((kind, version))
    if (
        spec is None
        or name != spec.name
        or prompt_version != spec.prompt_version
        or budget != spec.budget()
        or tool_contract_hash != spec.tool_contract_hash
    ):
        raise AgentControlError(
            "agent_spec_unsupported",
            "This agent run uses an execution contract that is no longer available.",
        )
    return spec


def explicit_retrieval_required(request: str) -> bool:
    normalized = " ".join(request.strip().lower().split())
    if any(marker in normalized for marker in _RETRIEVAL_META_MARKERS):
        return False
    return any(marker in normalized for marker in _EXPLICIT_RETRIEVAL_MARKERS)


class AgentExecution:
    """Provider-neutral control plane for one bounded Sift agent run."""

    def __init__(
        self,
        spec: AgentSpec,
        event_sink: AgentEventSink,
        *,
        cancellation_probe: CancellationProbe | None = None,
        model_calls: int = 0,
        tool_calls: int = 0,
        steps: int = 0,
        current_step: str | None = None,
        model_latency_ms: int = 0,
        input_tokens: int = 0,
        output_tokens: int = 0,
    ) -> None:
        self.spec = spec
        self.event_sink = event_sink
        self.cancellation_probe = cancellation_probe
        self.model_calls = model_calls
        self.tool_calls = tool_calls
        self.steps = steps
        self.current_step = current_step
        self.model_latency_ms = model_latency_ms
        self.input_tokens = input_tokens
        self.output_tokens = output_tokens

    async def start_step(self, step: str, label: str) -> None:
        await self.check_cancelled()
        if self.current_step == step:
            await self.event_sink(
                "stepRestarted",
                {"step": step, "label": label, "stepCount": self.steps},
            )
            return
        if self.current_step is not None:
            await self.complete_step(self.current_step)
        if self.steps >= self.spec.max_steps:
            raise self._budget_error("step")
        self.steps += 1
        self.current_step = step
        await self.event_sink(
            "stepStarted",
            {"step": step, "label": label, "stepCount": self.steps},
        )

    async def complete_step(self, step: str | None = None) -> None:
        resolved = step or self.current_step
        if resolved is None:
            return
        await self.event_sink("stepCompleted", {"step": resolved})
        if self.current_step == resolved:
            self.current_step = None

    async def model_call_started(self) -> int:
        await self.check_cancelled()
        if self.model_calls >= self.spec.max_model_calls:
            raise self._budget_error("model-call")
        self.model_calls += 1
        await self._emit_usage()
        await self.event_sink(
            "modelCallStarted",
            {"callIndex": self.model_calls},
        )
        return self.model_calls

    async def model_call_completed(
        self,
        call_index: int,
        latency_ms: int,
        input_tokens: int | None,
        output_tokens: int | None,
        succeeded: bool,
    ) -> None:
        latency = max(0, latency_ms)
        input_count = max(0, input_tokens) if input_tokens is not None else None
        output_count = max(0, output_tokens) if output_tokens is not None else None
        self.model_latency_ms += latency
        if input_count is not None:
            self.input_tokens += input_count
        if output_count is not None:
            self.output_tokens += output_count
        await self.event_sink(
            "modelCallCompleted",
            {
                "callIndex": call_index,
                "latencyMs": latency,
                "inputTokens": input_count,
                "outputTokens": output_count,
                "succeeded": succeeded,
                "totalLatencyMs": self.model_latency_ms,
                "totalInputTokens": self.input_tokens,
                "totalOutputTokens": self.output_tokens,
            },
        )

    async def tool_call_started(self, tool_name: str, call_id: str | None = None) -> str:
        await self.check_cancelled()
        canonical = canonical_tool_name(tool_name)
        if canonical not in self.spec.allowed_tools:
            raise AgentControlError(
                "tool_not_allowed",
                f"The agent workflow does not allow tool {tool_name}.",
            )
        if self.tool_calls >= self.spec.max_tool_calls:
            raise self._budget_error("tool-call")
        self.tool_calls += 1
        await self._emit_usage()
        await self.event_sink(
            "toolStarted",
            {
                "tool": canonical,
                "callId": call_id,
                "toolCallCount": self.tool_calls,
            },
        )
        return canonical

    async def tool_call_completed(
        self,
        tool_name: str,
        *,
        call_id: str | None = None,
        result_count: int | None = None,
    ) -> None:
        await self.event_sink(
            "toolCompleted",
            {
                "tool": canonical_tool_name(tool_name),
                "callId": call_id,
                "resultCount": result_count,
            },
        )

    async def tool_call_failed(
        self,
        tool_name: str,
        *,
        call_id: str | None = None,
        code: str,
    ) -> None:
        await self.event_sink(
            "toolFailed",
            {
                "tool": canonical_tool_name(tool_name),
                "callId": call_id,
                "code": code,
            },
        )

    async def tool_loop_completed(
        self,
        *,
        reason: str,
        rounds: int,
        evidence_count: int,
    ) -> None:
        await self.event_sink(
            "toolLoopCompleted",
            {
                "reason": reason,
                "rounds": rounds,
                "evidenceCount": evidence_count,
            },
        )

    async def check_cancelled(self) -> None:
        if self.cancellation_probe is not None and await self.cancellation_probe():
            raise AgentControlError("agent_cancelled", "The agent run was cancelled.")

    async def finish(self) -> None:
        await self.complete_step()

    async def _emit_usage(self) -> None:
        await self.event_sink(
            "budgetUpdated",
            {
                "modelCalls": self.model_calls,
                "toolCalls": self.tool_calls,
                "steps": self.steps,
            },
        )

    @staticmethod
    def _budget_error(kind: str) -> AgentControlError:
        return AgentControlError(
            "agent_budget_exceeded",
            f"The agent stopped because its {kind} budget was exhausted.",
        )
