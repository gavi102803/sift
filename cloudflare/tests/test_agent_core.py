from __future__ import annotations

from typing import Any

import pytest

from sift_worker.agent_core import (
    FOLLOW_UP_AGENT_SPEC,
    INITIAL_AGENT_SPEC,
    AgentControlError,
    AgentExecution,
    agent_spec_for_kind,
    agent_spec_from_snapshot,
    explicit_retrieval_required,
)


def test_persisted_agent_contract_must_match_supported_spec() -> None:
    spec = agent_spec_for_kind("initialConcept")
    assert agent_spec_from_snapshot(
        "initialConcept",
        name=spec.name,
        version=spec.version,
        prompt_version=spec.prompt_version,
        budget=spec.budget(),
        tool_contract_hash=spec.tool_contract_hash,
    ) is spec

    with pytest.raises(AgentControlError) as failure:
        agent_spec_from_snapshot(
            "initialConcept",
            name=spec.name,
            version="0.9",
            prompt_version=spec.prompt_version,
            budget=spec.budget(),
            tool_contract_hash=spec.tool_contract_hash,
        )

    assert failure.value.code == "agent_spec_unsupported"


class EventRecorder:
    def __init__(self) -> None:
        self.events: list[tuple[str, dict[str, Any]]] = []

    async def __call__(self, event_type: str, data: dict[str, Any]) -> None:
        self.events.append((event_type, data))


@pytest.mark.asyncio
async def test_agent_core_enforces_model_tool_and_step_budgets() -> None:
    events = EventRecorder()
    execution = AgentExecution(INITIAL_AGENT_SPEC, events)

    for index in range(INITIAL_AGENT_SPEC.max_steps):
        await execution.start_step(f"step-{index}", f"Step {index}")
        await execution.complete_step()
    with pytest.raises(AgentControlError, match="step budget") as step_error:
        await execution.start_step("too-many", "Too many")
    assert step_error.value.code == "agent_budget_exceeded"

    for _ in range(INITIAL_AGENT_SPEC.max_model_calls):
        await execution.model_call_started()
    with pytest.raises(AgentControlError, match="model-call budget") as model_error:
        await execution.model_call_started()
    assert model_error.value.code == "agent_budget_exceeded"

    for index in range(INITIAL_AGENT_SPEC.max_tool_calls):
        await execution.tool_call_started("web_search", f"call-{index}")
    with pytest.raises(AgentControlError, match="tool-call budget") as tool_error:
        await execution.tool_call_started("web.search", "call-too-many")
    assert tool_error.value.code == "agent_budget_exceeded"

    assert any(event_type == "stepCompleted" for event_type, _ in events.events)
    assert events.events[-2][0] == "budgetUpdated"
    assert events.events[-1][0] == "toolStarted"


@pytest.mark.asyncio
async def test_agent_core_rejects_unknown_tools_instead_of_ignoring_them() -> None:
    execution = AgentExecution(FOLLOW_UP_AGENT_SPEC, EventRecorder())

    with pytest.raises(AgentControlError, match="does not allow") as error:
        await execution.tool_call_started("filesystem.write", "unsafe-call")

    assert error.value.code == "tool_not_allowed"
    assert execution.tool_calls == 0


@pytest.mark.asyncio
async def test_agent_core_records_tool_failure_without_exposing_error_text() -> None:
    events = EventRecorder()
    execution = AgentExecution(INITIAL_AGENT_SPEC, events)

    await execution.tool_call_started("web_search", "call-search")
    await execution.tool_call_failed(
        "web_search",
        call_id="call-search",
        code="tool_timeout",
    )

    assert events.events[-1] == (
        "toolFailed",
        {
            "tool": "web.search",
            "callId": "call-search",
            "code": "tool_timeout",
        },
    )


@pytest.mark.asyncio
async def test_agent_core_observes_cancellation_at_every_boundary() -> None:
    cancelled = False

    async def cancellation_probe() -> bool:
        return cancelled

    execution = AgentExecution(
        INITIAL_AGENT_SPEC,
        EventRecorder(),
        cancellation_probe=cancellation_probe,
    )
    await execution.start_step("retrieval", "Researching")
    cancelled = True

    with pytest.raises(AgentControlError, match="cancelled") as error:
        await execution.model_call_started()

    assert error.value.code == "agent_cancelled"


@pytest.mark.asyncio
async def test_agent_core_records_model_call_lifecycle_and_run_aggregates() -> None:
    events = EventRecorder()
    execution = AgentExecution(INITIAL_AGENT_SPEC, events)

    call_index = await execution.model_call_started()
    await execution.model_call_completed(
        call_index,
        latency_ms=125,
        input_tokens=20,
        output_tokens=8,
        succeeded=True,
    )

    assert call_index == 1
    assert execution.model_latency_ms == 125
    assert execution.input_tokens == 20
    assert execution.output_tokens == 8
    assert events.events[-1] == (
        "modelCallCompleted",
        {
            "callIndex": 1,
            "latencyMs": 125,
            "inputTokens": 20,
            "outputTokens": 8,
            "succeeded": True,
            "totalLatencyMs": 125,
            "totalInputTokens": 20,
            "totalOutputTokens": 8,
        },
    )


def test_agent_specs_are_the_single_versioned_source_for_all_workflows() -> None:
    assert agent_spec_for_kind("initialConcept") is INITIAL_AGENT_SPEC
    assert INITIAL_AGENT_SPEC.version == "1.4"
    assert INITIAL_AGENT_SPEC.prompt_version == "initial-concept-v3"
    assert INITIAL_AGENT_SPEC.tool_contract_hash.startswith("sha256:")
    assert INITIAL_AGENT_SPEC.budget()["maxModelOutputTokens"] == 4_096
    assert agent_spec_for_kind("followUp") is FOLLOW_UP_AGENT_SPEC
    assert agent_spec_for_kind("continuitySummary").allowed_tools == frozenset()
    assert agent_spec_for_kind("knowledgeReview").max_model_calls == 3


def test_legacy_agent_spec_remains_resumable_after_contract_upgrade() -> None:
    legacy = agent_spec_from_snapshot(
        "initialConcept",
        name="sift.initial-concept",
        version="1.2",
        prompt_version="initial-concept-v2",
        budget={
            "maxModelCalls": 6,
            "maxToolCalls": 4,
            "maxSteps": 4,
            "maxModelOutputTokens": 4_096,
        },
        tool_contract_hash="",
    )

    assert legacy.version == "1.2"

    previous = agent_spec_from_snapshot(
        "initialConcept",
        name="sift.initial-concept",
        version="1.3",
        prompt_version="initial-concept-v2",
        budget=INITIAL_AGENT_SPEC.budget(),
        tool_contract_hash=INITIAL_AGENT_SPEC.tool_contract_hash,
    )
    assert previous.version == "1.3"


@pytest.mark.parametrize(
    "query_text",
    [
        "Search the web and cite sources for the latest Workers release.",
        "Summarize https://example.com/runtime",
        "请联网查一下今天的 Cloudflare Workers 更新并给出引用",
        "Verify this claim with citations.",
    ],
)
def test_explicit_retrieval_requests_are_contractually_required(query_text: str) -> None:
    assert explicit_retrieval_required(query_text) is True


@pytest.mark.parametrize(
    "query_text",
    [
        "Explain what a durable agent runtime is.",
        "Why didn't you use web search for that answer?",
        "为什么不用 web search 能力？",
    ],
)
def test_stable_or_meta_questions_do_not_force_retrieval(query_text: str) -> None:
    assert explicit_retrieval_required(query_text) is False
