from __future__ import annotations

import pytest

from sift_backend.model_runtime.harness import (
    AgentBudgetExceeded,
    SiftAgentRunner,
    agent_spec_for_kind,
)
from sift_backend.runtime.execution_observer import (
    observe_runtime,
    record_model_call,
    record_tool_call,
)
from sift_backend.schemas.model_runs import ModelRunKind


class RecordingSink:
    def __init__(self) -> None:
        self.events: list[tuple[str, object]] = []

    def step_started(self, step: str, label: str) -> None:
        self.events.append(("stepStarted", step))

    def step_completed(self, step: str) -> None:
        self.events.append(("stepCompleted", step))

    def usage_updated(self, model_calls: int, tool_calls: int) -> None:
        self.events.append(("usage", (model_calls, tool_calls)))


def test_every_model_run_kind_has_a_versioned_agent_spec() -> None:
    specs = [agent_spec_for_kind(kind) for kind in ModelRunKind]

    assert len({spec.name for spec in specs}) == len(ModelRunKind)
    assert all(spec.version == "1.0" for spec in specs)
    assert all(spec.prompt_version for spec in specs)
    assert all(spec.max_model_calls > 0 for spec in specs)


def test_harness_rejects_tools_outside_agent_policy_before_dispatch() -> None:
    sink = RecordingSink()
    runner = SiftAgentRunner(
        agent_spec_for_kind(ModelRunKind.knowledge_review),
        sink,
    )

    with observe_runtime(runner.observer), pytest.raises(
        AgentBudgetExceeded,
        match="tool policy",
    ):
        record_tool_call("web.search")

    assert sink.events == []


def test_harness_stops_before_exceeding_model_call_budget() -> None:
    sink = RecordingSink()
    spec = agent_spec_for_kind(ModelRunKind.continuity_summary)
    runner = SiftAgentRunner(spec, sink)

    with observe_runtime(runner.observer):
        for _ in range(spec.max_model_calls):
            record_model_call()
        with pytest.raises(AgentBudgetExceeded, match="model-call budget"):
            record_model_call()

    assert sink.events[-1] == ("usage", (spec.max_model_calls, 0))


def test_retrieval_agents_allow_three_searches_and_one_extract() -> None:
    sink = RecordingSink()
    spec = agent_spec_for_kind(ModelRunKind.initial_concept)
    runner = SiftAgentRunner(spec, sink)

    with observe_runtime(runner.observer):
        for _ in range(3):
            record_tool_call("web.search")
        record_tool_call("web.extract")
        with pytest.raises(AgentBudgetExceeded, match="tool-call budget"):
            record_tool_call("web.search")

    assert sink.events[-1] == ("usage", (0, 4))
