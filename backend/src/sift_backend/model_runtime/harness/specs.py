from __future__ import annotations

from dataclasses import dataclass

from sift_backend.schemas.model_runs import ModelRunKind


@dataclass(frozen=True)
class AgentSpec:
    name: str
    version: str
    prompt_version: str
    allowed_tools: frozenset[str]
    max_model_calls: int
    max_tool_calls: int
    max_steps: int

    def budget(self) -> dict[str, int]:
        return {
            "maxModelCalls": self.max_model_calls,
            "maxToolCalls": self.max_tool_calls,
            "maxSteps": self.max_steps,
        }


_SPECS = {
    ModelRunKind.initial_concept: AgentSpec(
        name="sift.initial-concept",
        version="1.0",
        prompt_version="initial-concept-v1",
        allowed_tools=frozenset({"web.search", "web.extract"}),
        max_model_calls=4,
        max_tool_calls=4,
        max_steps=4,
    ),
    ModelRunKind.follow_up: AgentSpec(
        name="sift.follow-up",
        version="1.0",
        prompt_version="follow-up-v1",
        allowed_tools=frozenset({"web.search", "web.extract"}),
        max_model_calls=4,
        max_tool_calls=4,
        max_steps=4,
    ),
    ModelRunKind.continuity_summary: AgentSpec(
        name="sift.continuity-summary",
        version="1.0",
        prompt_version="continuity-summary-v1",
        allowed_tools=frozenset(),
        max_model_calls=2,
        max_tool_calls=0,
        max_steps=3,
    ),
    ModelRunKind.knowledge_review: AgentSpec(
        name="sift.knowledge-review",
        version="1.0",
        prompt_version="knowledge-review-v1",
        allowed_tools=frozenset(),
        max_model_calls=3,
        max_tool_calls=0,
        max_steps=3,
    ),
}


def agent_spec_for_kind(kind: ModelRunKind) -> AgentSpec:
    return _SPECS[kind]
