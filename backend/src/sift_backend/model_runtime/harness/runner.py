from __future__ import annotations

from collections.abc import Callable
from typing import Protocol
from uuid import UUID

from sift_backend.ai.context_pack import RecentTurn
from sift_backend.concepts.service import (
    ConceptService,
    ConceptTurnStreamDelta,
    PreparedTurnResult,
)
from sift_backend.model_runtime.harness.specs import AgentSpec
from sift_backend.runtime.execution_observer import RuntimeExecutionPolicyError, observe_runtime
from sift_backend.schemas.concepts import ConceptDTO, ConceptTurnRequest, CreateConceptRequest
from sift_backend.schemas.model_outputs import ConceptTurnResult, ContinuitySummaryResult


class AgentBudgetExceeded(RuntimeExecutionPolicyError):
    pass


class AgentRunSink(Protocol):
    def step_started(self, step: str, label: str) -> None: ...

    def step_completed(self, step: str) -> None: ...

    def usage_updated(self, model_calls: int, tool_calls: int) -> None: ...


class _ExecutionObserver:
    def __init__(self, spec: AgentSpec, sink: AgentRunSink) -> None:
        self.spec = spec
        self.sink = sink
        self.model_calls = 0
        self.tool_calls = 0

    def model_call_started(self) -> None:
        if self.model_calls >= self.spec.max_model_calls:
            raise AgentBudgetExceeded("Agent model-call budget was exhausted.")
        self.model_calls += 1
        self.sink.usage_updated(self.model_calls, self.tool_calls)

    def tool_call_started(self, tool_name: str) -> None:
        if tool_name not in self.spec.allowed_tools:
            raise AgentBudgetExceeded(f"Agent tool policy rejected {tool_name}.")
        if self.tool_calls >= self.spec.max_tool_calls:
            raise AgentBudgetExceeded("Agent tool-call budget was exhausted.")
        self.tool_calls += 1
        self.sink.usage_updated(self.model_calls, self.tool_calls)


class SiftAgentRunner:
    """Bounded harness for Sift's four durable agent workflows.

    The runner owns execution policy and observability. Domain commits remain in
    the ModelRun coordinator so model output cannot bypass Concept invariants.
    """

    def __init__(self, spec: AgentSpec, sink: AgentRunSink) -> None:
        self.spec = spec
        self.sink = sink
        self.observer = _ExecutionObserver(spec, sink)
        self.steps = 0

    def _start(self, step: str, label: str) -> None:
        if self.steps >= self.spec.max_steps:
            raise AgentBudgetExceeded("Agent step budget was exhausted.")
        self.steps += 1
        self.sink.step_started(step, label)

    def _complete(self, step: str) -> None:
        self.sink.step_completed(step)

    async def prepare_initial(
        self,
        service: ConceptService,
        request: CreateConceptRequest,
        on_delta: Callable[[str], None],
    ) -> ConceptDTO:
        self._start("prepareContext", "Preparing context")
        self._complete("prepareContext")
        self._start("generate", "Generating card")
        concept: ConceptDTO | None = None
        with observe_runtime(self.observer):
            async for event in service.prepare_initial_concept_stream(request):
                if isinstance(event, ConceptTurnStreamDelta):
                    on_delta(event.content)
                else:
                    concept = event
        self._complete("generate")
        self._start("validate", "Validating card")
        if concept is None:
            raise RuntimeError("Initial concept stream ended before its result.")
        self._complete("validate")
        return concept

    async def prepare_follow_up(
        self,
        service: ConceptService,
        concept_id: UUID,
        request: ConceptTurnRequest,
        on_delta: Callable[[str], None],
    ) -> PreparedTurnResult:
        self._start("prepareContext", "Preparing card memory")
        self._complete("prepareContext")
        self._start("generate", "Answering follow-up")
        prepared: PreparedTurnResult | None = None
        with observe_runtime(self.observer):
            async for event in service.prepare_turn_stream(concept_id, request):
                if isinstance(event, ConceptTurnStreamDelta):
                    on_delta(event.content)
                else:
                    prepared = event
        self._complete("generate")
        self._start("validate", "Validating update")
        if prepared is None:
            raise RuntimeError("Follow-up stream ended before its result.")
        self._complete("validate")
        return prepared

    async def summarize(
        self,
        service: ConceptService,
        concept: ConceptDTO,
        source_turns: list[tuple[int, RecentTurn]],
    ) -> ContinuitySummaryResult:
        self._start("prepareContext", "Preparing continuity context")
        self._complete("prepareContext")
        self._start("summarize", "Updating continuity memory")
        with observe_runtime(self.observer):
            result = await service.model_service.summarize_continuity(concept, source_turns)
        self._complete("summarize")
        self._start("validate", "Validating source turns")
        allowed_ids = {turn_id for turn_id, _ in source_turns}
        if any(
            not set(entry.source_turn_ids).issubset(allowed_ids) for entry in result.entries
        ):
            raise RuntimeError("Continuity summary cited an unknown source turn.")
        self._complete("validate")
        return result

    async def review(
        self,
        service: ConceptService,
        concept: ConceptDTO,
        recent_turns: list[RecentTurn],
        card_memory: str,
    ) -> ConceptTurnResult:
        self._start("prepareContext", "Preparing review context")
        self._complete("prepareContext")
        self._start("review", "Reviewing durable knowledge")
        with observe_runtime(self.observer):
            result = await service.model_service.answer_maintenance_review(
                concept,
                recent_turns,
                card_memory,
            )
        self._complete("review")
        self._start("validate", "Validating proposal")
        self._complete("validate")
        return result
