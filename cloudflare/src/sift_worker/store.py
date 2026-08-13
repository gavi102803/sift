from __future__ import annotations

from typing import Any, Protocol


class WorkerStore(Protocol):
    async def get_invite(self, code_hash: str) -> dict[str, Any] | None:
        ...

    async def activate_invite(
        self,
        *,
        code_hash: str,
        owner_id: str,
        installation_id: str,
        session_id: str,
        token_hash: str,
        expires_at: str,
        now: str,
    ) -> dict[str, Any] | None:
        ...

    async def get_session(self, token_hash: str) -> dict[str, Any] | None:
        ...

    async def rotate_session(
        self,
        *,
        current_token_hash: str,
        session_id: str,
        token_hash: str,
        expires_at: str,
        now: str,
    ) -> dict[str, Any] | None:
        ...

    async def owner_is_revoked(self, owner_id: str) -> bool:
        ...

    async def get_provider_connection(self, owner_id: str) -> dict[str, Any] | None:
        ...

    async def save_provider_connection(
        self,
        connection: dict[str, Any],
    ) -> dict[str, Any]:
        ...

    async def get_web_provider_settings(self, owner_id: str) -> dict[str, Any]:
        ...

    async def save_web_provider_settings(
        self,
        *,
        owner_id: str,
        provider_type: str,
        web_search_enabled: bool,
        now: str,
    ) -> dict[str, Any]:
        ...

    async def create_model_run(
        self,
        *,
        run: dict[str, Any],
        event: dict[str, Any],
        pending_concept: dict[str, Any] | None = None,
        input_turn: dict[str, Any] | None = None,
    ) -> tuple[dict[str, Any], bool]:
        ...

    async def get_model_run(self, run_id: str, owner_id: str) -> dict[str, Any] | None:
        ...

    async def list_model_runs(
        self,
        owner_id: str,
        *,
        active: bool,
    ) -> list[dict[str, Any]]:
        ...

    async def list_model_run_events(
        self,
        run_id: str,
        owner_id: str,
        after_sequence: int,
    ) -> list[dict[str, Any]] | None:
        ...

    async def append_model_run_event(
        self,
        run_id: str,
        owner_id: str,
        *,
        event_type: str,
        data_json: str,
        now: str,
        worker_id: str | None = None,
    ) -> int | None:
        ...

    async def record_agent_event(
        self,
        run_id: str,
        owner_id: str,
        *,
        worker_id: str,
        event_type: str,
        data_json: str,
        now: str,
        current_step: str | None = None,
        update_current_step: bool = False,
        model_call_count: int | None = None,
        tool_call_count: int | None = None,
        step_count: int | None = None,
        model_latency_ms: int | None = None,
        input_token_count: int | None = None,
        output_token_count: int | None = None,
    ) -> int | None:
        ...

    async def claim_model_run(
        self,
        run_id: str,
        owner_id: str,
        *,
        now: str,
        worker_id: str,
        lease_expires_at: str,
    ) -> tuple[dict[str, Any] | None, bool]:
        ...

    async def renew_model_run_lease(
        self,
        run_id: str,
        owner_id: str,
        *,
        worker_id: str,
        lease_expires_at: str,
        now: str,
    ) -> bool:
        ...

    async def snapshot_model_run_provider(
        self,
        run_id: str,
        owner_id: str,
        *,
        worker_id: str,
        provider_snapshot_json: str,
        now: str,
    ) -> bool:
        ...

    async def checkpoint_model_run(
        self,
        run_id: str,
        owner_id: str,
        *,
        worker_id: str,
        checkpoint: str,
        checkpoint_json: str,
        now: str,
    ) -> bool:
        ...

    async def cancel_model_run(
        self,
        run_id: str,
        owner_id: str,
        *,
        now: str,
    ) -> dict[str, Any] | None:
        ...

    async def model_run_is_cancelled(
        self,
        run_id: str,
        owner_id: str,
        *,
        worker_id: str,
    ) -> bool:
        ...

    async def fail_model_run(
        self,
        run_id: str,
        owner_id: str,
        *,
        worker_id: str,
        code: str,
        message: str,
        now: str,
    ) -> dict[str, Any] | None:
        ...

    async def complete_initial_run(
        self,
        *,
        run_id: str,
        owner_id: str,
        worker_id: str,
        concept: dict[str, Any],
        blocks: list[dict[str, Any]],
        tags: list[str],
        topics: list[str],
        revision: dict[str, Any],
        turns: list[dict[str, Any]],
        sources: list[dict[str, Any]],
        provider_snapshot_json: str,
        result_json: str,
        now: str,
        model_call_count: int = 1,
        tool_call_count: int = 0,
    ) -> dict[str, Any] | None:
        ...

    async def complete_follow_up_run(
        self,
        *,
        run_id: str,
        owner_id: str,
        worker_id: str,
        concept_id: str,
        replacing_turn_index: int | None,
        turns: list[dict[str, Any]],
        proposal: dict[str, Any] | None,
        sources: list[dict[str, Any]],
        provider_snapshot_json: str,
        result_json: str,
        now: str,
        model_call_count: int = 1,
        tool_call_count: int = 0,
    ) -> dict[str, Any] | None:
        ...

    async def list_update_proposals(
        self,
        concept_id: str,
        owner_id: str,
        status: str | None,
    ) -> list[dict[str, Any]] | None:
        ...

    async def get_update_proposal(
        self,
        proposal_id: str,
        owner_id: str,
    ) -> dict[str, Any] | None:
        ...

    async def resolve_update_proposal(
        self,
        proposal_id: str,
        owner_id: str,
        *,
        status: str,
        now: str,
    ) -> bool:
        ...

    async def complete_regenerated_follow_up_run(
        self,
        *,
        run_id: str,
        owner_id: str,
        worker_id: str,
        expected_revision: int,
        concept: dict[str, Any],
        blocks: list[dict[str, Any]],
        tags: list[str],
        topics: list[str],
        revision: dict[str, Any],
        turns: list[dict[str, Any]],
        provider_snapshot_json: str,
        result_json: str,
        now: str,
        model_call_count: int = 1,
        tool_call_count: int = 0,
    ) -> dict[str, Any] | None:
        ...

    async def get_concept(self, concept_id: str, owner_id: str) -> dict[str, Any] | None:
        ...

    async def list_concepts(self, owner_id: str) -> list[dict[str, Any]]:
        ...

    async def set_concepts_archived(
        self,
        concept_ids: list[str],
        owner_id: str,
        *,
        archived: bool,
        now: str,
    ) -> list[dict[str, Any]] | None:
        ...

    async def add_concept_relation(
        self,
        *,
        relation: dict[str, Any],
        owner_id: str,
    ) -> dict[str, Any] | None:
        ...

    async def remove_concept_relation(
        self,
        *,
        concept_id: str,
        relation_id: str,
        owner_id: str,
    ) -> dict[str, Any] | None:
        ...

    async def list_concept_turns(
        self,
        concept_id: str,
        owner_id: str,
    ) -> list[dict[str, Any]] | None:
        ...

    async def get_continuity_summary(
        self,
        concept_id: str,
        owner_id: str,
    ) -> dict[str, Any] | None:
        ...

    async def get_maintenance_status(
        self,
        concept_id: str,
        owner_id: str,
    ) -> dict[str, Any] | None:
        ...

    async def complete_continuity_summary_run(
        self,
        **kwargs: Any,
    ) -> dict[str, Any] | None:
        ...

    async def complete_knowledge_review_run(
        self,
        **kwargs: Any,
    ) -> dict[str, Any] | None:
        ...

    async def list_note_revisions(
        self,
        concept_id: str,
        owner_id: str,
    ) -> list[dict[str, Any]] | None:
        ...

    async def get_note_revision(
        self,
        concept_id: str,
        revision: int,
        owner_id: str,
    ) -> dict[str, Any] | None:
        ...

    async def save_concept_revision(
        self,
        *,
        concept_id: str,
        owner_id: str,
        expected_revision: int,
        concept: dict[str, Any],
        blocks: list[dict[str, Any]],
        tags: list[str],
        topics: list[str],
        revision: dict[str, Any],
        proposal_id: str | None = None,
        idempotency: dict[str, Any] | None = None,
    ) -> dict[str, Any] | None:
        ...

    async def get_mutation_idempotency(
        self,
        owner_id: str,
        scope: str,
        idempotency_key: str,
    ) -> dict[str, Any] | None:
        ...
