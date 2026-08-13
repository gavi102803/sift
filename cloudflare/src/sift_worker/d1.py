from __future__ import annotations

from typing import Any

ACTIVE_RUN_STATUSES = ("queued", "waitingForCredential", "running")


class D1WorkerStore:
    def __init__(self, database: Any) -> None:
        self.database = database

    async def get_invite(self, code_hash: str) -> dict[str, Any] | None:
        return _row(
            await self.database.prepare(
                """
                SELECT code_hash, owner_id, installation_id, revoked_at
                FROM beta_invites
                WHERE code_hash = ?
                """
            )
            .bind(code_hash)
            .first()
        )

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
        update_invite = self.database.prepare(
            """
            UPDATE beta_invites
            SET owner_id = COALESCE(owner_id, ?),
                installation_id = COALESCE(installation_id, ?),
                consumed_at = COALESCE(consumed_at, ?)
            WHERE code_hash = ?
              AND revoked_at IS NULL
              AND (installation_id IS NULL OR installation_id = ?)
            """
        ).bind(owner_id, installation_id, now, code_hash, installation_id)
        insert_session = self.database.prepare(
            """
            INSERT INTO beta_sessions (
                id, token_hash, owner_id, installation_id, expires_at, created_at
            )
            SELECT ?, ?, owner_id, installation_id, ?, ?
            FROM beta_invites
            WHERE code_hash = ?
              AND owner_id = ?
              AND installation_id = ?
              AND revoked_at IS NULL
            """
        ).bind(
            session_id,
            token_hash,
            expires_at,
            now,
            code_hash,
            owner_id,
            installation_id,
        )
        await self.database.batch([update_invite, insert_session])
        return await self.get_session(token_hash)

    async def get_session(self, token_hash: str) -> dict[str, Any] | None:
        return _row(
            await self.database.prepare(
                """
                SELECT token_hash, owner_id, installation_id, expires_at, revoked_at
                FROM beta_sessions
                WHERE token_hash = ?
                """
            )
            .bind(token_hash)
            .first()
        )

    async def rotate_session(
        self,
        *,
        current_token_hash: str,
        session_id: str,
        token_hash: str,
        expires_at: str,
        now: str,
    ) -> dict[str, Any] | None:
        revoke_current = self.database.prepare(
            """
            UPDATE beta_sessions
            SET revoked_at = ?
            WHERE token_hash = ? AND revoked_at IS NULL
            """
        ).bind(now, current_token_hash)
        insert_replacement = self.database.prepare(
            """
            INSERT INTO beta_sessions (
                id, token_hash, owner_id, installation_id,
                expires_at, revoked_at, created_at
            )
            SELECT ?, ?, owner_id, installation_id, ?, NULL, ?
            FROM beta_sessions
            WHERE token_hash = ? AND revoked_at = ?
            """
        ).bind(
            session_id,
            token_hash,
            expires_at,
            now,
            current_token_hash,
            now,
        )
        await self.database.batch([revoke_current, insert_replacement])
        return await self.get_session(token_hash)

    async def owner_is_revoked(self, owner_id: str) -> bool:
        result = await self.database.prepare(
            "SELECT owner_id FROM owner_revocations WHERE owner_id = ?"
        ).bind(owner_id).first()
        return result is not None

    async def get_provider_connection(self, owner_id: str) -> dict[str, Any] | None:
        return _row(
            await self.database.prepare(
                """
                SELECT owner_id, provider_id, base_url, model, created_at, updated_at
                FROM managed_provider_connections
                WHERE owner_id = ?
                """
            )
            .bind(owner_id)
            .first()
        )

    async def save_provider_connection(
        self,
        connection: dict[str, Any],
    ) -> dict[str, Any]:
        await self.database.prepare(
            """
            INSERT INTO managed_provider_connections (
                owner_id, provider_id, base_url, model, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(owner_id) DO UPDATE SET
                provider_id = excluded.provider_id,
                base_url = excluded.base_url,
                model = excluded.model,
                updated_at = excluded.updated_at
            """
        ).bind(
            connection["owner_id"],
            connection["provider_id"],
            connection["base_url"],
            connection["model"],
            connection["created_at"],
            connection["updated_at"],
        ).run()
        stored = await self.get_provider_connection(str(connection["owner_id"]))
        if stored is None:
            raise RuntimeError("D1 did not persist the provider connection")
        return stored

    async def get_web_provider_settings(self, owner_id: str) -> dict[str, Any]:
        stored = _row(
            await self.database.prepare(
                """
                SELECT provider_type, web_search_enabled
                FROM managed_web_provider_settings
                WHERE owner_id = ?
                """
            )
            .bind(owner_id)
            .first()
        )
        return stored or {
            "provider_type": "ddgs",
            "web_search_enabled": 1,
        }

    async def save_web_provider_settings(
        self,
        *,
        owner_id: str,
        provider_type: str,
        web_search_enabled: bool,
        now: str,
    ) -> dict[str, Any]:
        await self.database.prepare(
            """
            INSERT INTO managed_web_provider_settings (
                owner_id, provider_type, web_search_enabled, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(owner_id) DO UPDATE SET
                provider_type = excluded.provider_type,
                web_search_enabled = excluded.web_search_enabled,
                updated_at = excluded.updated_at
            """
        ).bind(
            owner_id,
            provider_type,
            1 if web_search_enabled else 0,
            now,
            now,
        ).run()
        return await self.get_web_provider_settings(owner_id)

    async def create_model_run(
        self,
        *,
        run: dict[str, Any],
        event: dict[str, Any],
        pending_concept: dict[str, Any] | None = None,
        input_turn: dict[str, Any] | None = None,
    ) -> tuple[dict[str, Any], bool]:
        existing = await self._get_model_run_by_key(
            str(run["owner_id"]),
            str(run["kind"]),
            str(run["idempotency_key"]),
        )
        if existing is not None:
            return existing, False

        insert_run = self.database.prepare(
            """
            INSERT OR IGNORE INTO model_runs (
                id, owner_id, kind, status, concept_id, client_draft_id,
                idempotency_key, payload_hash, payload_json, provider_snapshot_json,
                agent_spec, agent_spec_version, prompt_version, budget_json,
                tool_contract_hash,
                current_step, model_call_count, tool_call_count, termination_reason,
                dependency_run_id, checkpoint, checkpoint_json, result_json,
                result_ref, error_code, error_message, created_at, updated_at
            ) VALUES (
                ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                ?, ?, ?, ?, ?, ?, ?
            )
            """
        ).bind(
            *[
                run[key]
                for key in (
                    "id",
                    "owner_id",
                    "kind",
                    "status",
                    "concept_id",
                    "client_draft_id",
                    "idempotency_key",
                    "payload_hash",
                    "payload_json",
                    "provider_snapshot_json",
                    "agent_spec",
                    "agent_spec_version",
                    "prompt_version",
                    "budget_json",
                    "tool_contract_hash",
                    "current_step",
                    "model_call_count",
                    "tool_call_count",
                    "termination_reason",
                    "dependency_run_id",
                    "checkpoint",
                    "checkpoint_json",
                    "result_json",
                    "result_ref",
                    "error_code",
                    "error_message",
                    "created_at",
                    "updated_at",
                )
            ]
        )
        insert_event = self.database.prepare(
            """
            INSERT OR IGNORE INTO model_run_events (
                run_id, sequence, event_type, data_json, created_at
            )
            SELECT ?, ?, ?, ?, ?
            WHERE EXISTS (SELECT 1 FROM model_runs WHERE id = ?)
            """
        ).bind(
            event["run_id"],
            event["sequence"],
            event["event_type"],
            event["data_json"],
            event["created_at"],
            event["run_id"],
        )
        statements = [insert_run]
        if pending_concept is not None:
            statements.append(
                self.database.prepare(
                    """
                    INSERT OR IGNORE INTO concepts (
                        id, owner_id, canonical_title, display_title,
                        one_line_explanation, initial_answer, maturity,
                        capture_status, note_revision, answer_source_json,
                        document_json, created_at, updated_at
                    )
                    SELECT ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
                    WHERE EXISTS (
                        SELECT 1 FROM model_runs WHERE id = ? AND owner_id = ?
                    )
                    """
                ).bind(
                    pending_concept["id"],
                    run["owner_id"],
                    pending_concept["canonical_title"],
                    pending_concept["display_title"],
                    pending_concept["one_line_explanation"],
                    pending_concept["initial_answer"],
                    pending_concept["maturity"],
                    pending_concept["capture_status"],
                    pending_concept["note_revision"],
                    pending_concept["answer_source_json"],
                    pending_concept["document_json"],
                    pending_concept["created_at"],
                    pending_concept["updated_at"],
                    run["id"],
                    run["owner_id"],
                )
            )
        if input_turn is not None:
            statements.append(
                self.database.prepare(
                    """
                    INSERT OR IGNORE INTO concept_turns (
                        id, concept_id, owner_id, operation_key, role,
                        content, answer_source_json, created_at
                    )
                    SELECT ?, ?, ?, ?, ?, ?, ?, ?
                    WHERE EXISTS (
                        SELECT 1 FROM model_runs WHERE id = ? AND owner_id = ?
                    ) AND EXISTS (
                        SELECT 1 FROM concepts WHERE id = ? AND owner_id = ?
                    )
                    """
                ).bind(
                    input_turn["id"],
                    input_turn["concept_id"],
                    run["owner_id"],
                    input_turn["operation_key"],
                    input_turn["role"],
                    input_turn["content"],
                    input_turn["answer_source_json"],
                    input_turn["created_at"],
                    run["id"],
                    run["owner_id"],
                    input_turn["concept_id"],
                    run["owner_id"],
                )
            )
        statements.append(insert_event)
        await self.database.batch(statements)
        stored = await self._get_model_run_by_key(
            str(run["owner_id"]),
            str(run["kind"]),
            str(run["idempotency_key"]),
        )
        if stored is None:
            raise RuntimeError("D1 did not persist the model run")
        return stored, stored["id"] == run["id"]

    async def get_model_run(self, run_id: str, owner_id: str) -> dict[str, Any] | None:
        row = _row(
            await self.database.prepare(
                "SELECT * FROM model_runs WHERE id = ? AND owner_id = ?"
            )
            .bind(run_id, owner_id)
            .first()
        )
        if row is None:
            return None
        children = await self.database.prepare(
            """
            SELECT id FROM model_runs
            WHERE owner_id = ? AND dependency_run_id = ?
            ORDER BY created_at
            """
        ).bind(owner_id, run_id).run()
        row["child_run_ids"] = [str(item["id"]) for item in _rows(children)]
        return row

    async def list_model_runs(
        self,
        owner_id: str,
        *,
        active: bool,
    ) -> list[dict[str, Any]]:
        if active:
            statement = self.database.prepare(
                """
                SELECT * FROM model_runs
                WHERE owner_id = ? AND status IN (?, ?, ?)
                ORDER BY created_at
                """
            ).bind(owner_id, *ACTIVE_RUN_STATUSES)
        else:
            statement = self.database.prepare(
                "SELECT * FROM model_runs WHERE owner_id = ? ORDER BY created_at"
            ).bind(owner_id)
        result = await statement.run()
        return _rows(result)

    async def list_model_run_events(
        self,
        run_id: str,
        owner_id: str,
        after_sequence: int,
    ) -> list[dict[str, Any]] | None:
        if await self.get_model_run(run_id, owner_id) is None:
            return None
        result = await self.database.prepare(
            """
            SELECT sequence, event_type, data_json, created_at
            FROM model_run_events
            WHERE run_id = ? AND sequence > ?
            ORDER BY sequence
            """
        ).bind(run_id, after_sequence).run()
        return _rows(result)

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
        if worker_id is None:
            if await self.get_model_run(run_id, owner_id) is None:
                return None
            await self._append_event(run_id, event_type, data_json, now)
            return await self._max_event_sequence(run_id)
        before = await self._max_event_sequence(run_id)
        await self._event_statement(
            run_id,
            event_type,
            data_json,
            now,
            required_status="running",
            owner_id=owner_id,
            lease_owner=worker_id,
        ).run()
        after = await self._max_event_sequence(run_id)
        return after if after is not None and after != before else None

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
        before = await self._max_event_sequence(run_id)
        update = self.database.prepare(
            """
            UPDATE model_runs
            SET current_step = CASE WHEN ? = 1 THEN ? ELSE current_step END,
                model_call_count = COALESCE(?, model_call_count),
                tool_call_count = COALESCE(?, tool_call_count),
                step_count = COALESCE(?, step_count),
                model_latency_ms = model_latency_ms + COALESCE(?, 0),
                input_token_count = input_token_count + COALESCE(?, 0),
                output_token_count = output_token_count + COALESCE(?, 0),
                updated_at = ?
            WHERE id = ? AND owner_id = ? AND status = 'running' AND lease_owner = ?
            """
        ).bind(
            1 if update_current_step else 0,
            current_step,
            model_call_count,
            tool_call_count,
            step_count,
            model_latency_ms,
            input_token_count,
            output_token_count,
            now,
            run_id,
            owner_id,
            worker_id,
        )
        event = self._event_statement(
            run_id,
            event_type,
            data_json,
            now,
            required_status="running",
            owner_id=owner_id,
            lease_owner=worker_id,
        )
        await self.database.batch([update, event])
        after = await self._max_event_sequence(run_id)
        if after is None or after == before:
            return None
        return after

    async def claim_model_run(
        self,
        run_id: str,
        owner_id: str,
        *,
        now: str,
        worker_id: str,
        lease_expires_at: str,
    ) -> tuple[dict[str, Any] | None, bool]:
        previous = await self.get_model_run(run_id, owner_id)
        resumed = bool(
            previous
            and (
                previous.get("status") == "running"
                or previous.get("checkpoint")
                or previous.get("current_step")
            )
        )
        resumed_step = (
            str(previous.get("current_step") or "providerCall")
            if resumed and previous is not None
            else "providerCall"
        )
        result = await self.database.prepare(
            """
            UPDATE model_runs
            SET status = 'running',
                current_step = ?,
                lease_owner = ?,
                lease_expires_at = ?,
                cancel_requested_at = NULL,
                started_at = COALESCE(started_at, ?),
                error_code = NULL,
                error_message = NULL,
                updated_at = ?
            WHERE id = ?
              AND owner_id = ?
              AND (
                  status IN ('queued', 'waitingForCredential', 'failed')
                  OR (status = 'running' AND lease_expires_at <= ?)
              )
            """
        ).bind(
            resumed_step,
            worker_id,
            lease_expires_at,
            now,
            now,
            run_id,
            owner_id,
            now,
        ).run()
        claimed = _changes(result) == 1
        if claimed:
            await self._append_event(
                run_id,
                (
                    "restarted" if resumed else "started"
                ),
                _json_data(
                    {
                        "step": resumed_step,
                        "resumed": resumed,
                    }
                ),
                now,
            )
        return await self.get_model_run(run_id, owner_id), claimed

    async def renew_model_run_lease(
        self,
        run_id: str,
        owner_id: str,
        *,
        worker_id: str,
        lease_expires_at: str,
        now: str,
    ) -> bool:
        result = await self.database.prepare(
            """
            UPDATE model_runs
            SET lease_expires_at = ?, updated_at = ?
            WHERE id = ? AND owner_id = ? AND status = 'running' AND lease_owner = ?
            """
        ).bind(lease_expires_at, now, run_id, owner_id, worker_id).run()
        return _changes(result) == 1

    async def snapshot_model_run_provider(
        self,
        run_id: str,
        owner_id: str,
        *,
        worker_id: str,
        provider_snapshot_json: str,
        now: str,
    ) -> bool:
        result = await self.database.prepare(
            """
            UPDATE model_runs
            SET provider_snapshot_json = ?, updated_at = ?
            WHERE id = ?
              AND owner_id = ?
              AND status = 'running'
              AND lease_owner = ?
              AND (provider_snapshot_json IS NULL OR provider_snapshot_json = '{}')
            """
        ).bind(
            provider_snapshot_json,
            now,
            run_id,
            owner_id,
            worker_id,
        ).run()
        return _changes(result) == 1

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
        update = self.database.prepare(
            """
            UPDATE model_runs
            SET checkpoint = ?, checkpoint_json = ?, updated_at = ?
            WHERE id = ? AND owner_id = ? AND status = 'running' AND lease_owner = ?
            """
        ).bind(checkpoint, checkpoint_json, now, run_id, owner_id, worker_id)
        event = self._event_statement(
            run_id,
            "checkpoint",
            _json_data({"name": checkpoint}),
            now,
            required_status="running",
            owner_id=owner_id,
            lease_owner=worker_id,
        )
        results = await self.database.batch([update, event])
        return bool(results and _changes(results[0]) == 1)

    async def cancel_model_run(
        self,
        run_id: str,
        owner_id: str,
        *,
        now: str,
    ) -> dict[str, Any] | None:
        if await self.get_model_run(run_id, owner_id) is None:
            return None
        update = self.database.prepare(
            """
            UPDATE model_runs
            SET status = 'cancelled',
                cancel_requested_at = ?,
                termination_reason = 'cancelled',
                current_step = NULL,
                lease_owner = NULL,
                lease_expires_at = NULL,
                completed_at = ?,
                updated_at = ?
            WHERE id = ? AND owner_id = ?
              AND status IN ('queued', 'waitingForCredential', 'running')
            """
        ).bind(now, now, now, run_id, owner_id)
        mark_initial_concept_failed = self.database.prepare(
            """
            UPDATE concepts
            SET capture_status = 'generationFailed',
                document_json = json_set(
                    document_json,
                    '$.captureStatus', 'generationFailed',
                    '$.updatedAt', ?
                ),
                updated_at = ?
            WHERE id = (
                SELECT concept_id FROM model_runs
                WHERE id = ? AND owner_id = ? AND kind = 'initialConcept'
                  AND status = 'cancelled' AND cancel_requested_at = ?
            ) AND owner_id = ?
            """
        ).bind(now, now, run_id, owner_id, now, owner_id)
        event = self.database.prepare(
            """
            INSERT INTO model_run_events (
                run_id, sequence, event_type, data_json, created_at
            )
            SELECT ?, (
                SELECT COALESCE(MAX(sequence), 0) + 1
                FROM model_run_events WHERE run_id = ?
            ), 'cancelled', ?, ?
            WHERE EXISTS (
                SELECT 1 FROM model_runs
                WHERE id = ? AND owner_id = ? AND status = 'cancelled'
                  AND cancel_requested_at = ?
            )
              AND NOT EXISTS (
                SELECT 1 FROM model_run_events
                WHERE run_id = ? AND event_type = 'cancelled'
            )
            """
        ).bind(
            run_id,
            run_id,
            _json_data({"code": "agent_cancelled"}),
            now,
            run_id,
            owner_id,
            now,
            run_id,
        )
        await self.database.batch([update, mark_initial_concept_failed, event])
        return await self.get_model_run(run_id, owner_id)

    async def model_run_is_cancelled(
        self,
        run_id: str,
        owner_id: str,
        *,
        worker_id: str,
    ) -> bool:
        run = await self.get_model_run(run_id, owner_id)
        del worker_id
        return bool(run is not None and run.get("status") == "cancelled")

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
        update = self.database.prepare(
            """
            UPDATE model_runs
            SET status = 'failed',
                error_code = ?,
                error_message = ?,
                termination_reason = ?,
                lease_expires_at = NULL,
                completed_at = ?,
                updated_at = ?
            WHERE id = ? AND owner_id = ? AND status = 'running' AND lease_owner = ?
            """
        ).bind(code, message, code, now, now, run_id, owner_id, worker_id)
        event = self._event_statement(
            run_id,
            "failed",
            _json_data({"code": code, "message": message}),
            now,
            required_status="failed",
            owner_id=owner_id,
            lease_owner=worker_id,
        )
        mark_initial_concept_failed = self.database.prepare(
            """
            UPDATE concepts
            SET capture_status = 'generationFailed',
                document_json = json_set(
                    document_json,
                    '$.captureStatus', 'generationFailed',
                    '$.updatedAt', ?
                ),
                updated_at = ?
            WHERE id = (
                SELECT concept_id FROM model_runs
                WHERE id = ? AND owner_id = ? AND kind = 'initialConcept'
                  AND status = 'failed' AND lease_owner = ?
            ) AND owner_id = ?
            """
        ).bind(now, now, run_id, owner_id, worker_id, owner_id)
        await self.database.batch(
            [
                update,
                mark_initial_concept_failed,
                event,
                self._release_lease_statement(run_id, owner_id, worker_id),
            ]
        )
        return await self.get_model_run(run_id, owner_id)

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
        statements = [
            self.database.prepare(
                """
                INSERT INTO concepts (
                    id, owner_id, canonical_title, display_title,
                    one_line_explanation, initial_answer, maturity,
                    capture_status, note_revision, answer_source_json,
                    document_json, created_at, updated_at
                )
                SELECT ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
                WHERE EXISTS (
                    SELECT 1 FROM model_runs
                    WHERE id = ? AND owner_id = ? AND status = 'running'
                      AND lease_owner = ?
                )
                ON CONFLICT(id) DO UPDATE SET
                    canonical_title = excluded.canonical_title,
                    display_title = excluded.display_title,
                    one_line_explanation = excluded.one_line_explanation,
                    initial_answer = excluded.initial_answer,
                    maturity = excluded.maturity,
                    capture_status = excluded.capture_status,
                    note_revision = excluded.note_revision,
                    answer_source_json = excluded.answer_source_json,
                    document_json = excluded.document_json,
                    updated_at = excluded.updated_at
                WHERE concepts.owner_id = excluded.owner_id
                """
            ).bind(
                concept["id"],
                owner_id,
                concept["canonical_title"],
                concept["display_title"],
                concept["one_line_explanation"],
                concept["initial_answer"],
                concept["maturity"],
                concept["capture_status"],
                concept["note_revision"],
                concept["answer_source_json"],
                concept["document_json"],
                concept["created_at"],
                concept["updated_at"],
                run_id,
                owner_id,
                worker_id,
            )
        ]
        statements.extend(
            self.database.prepare(
                """
                INSERT OR IGNORE INTO note_blocks (
                    id, concept_id, block_type, content, source,
                    is_user_locked, revision, supported_claim_ids_json,
                    position, created_at, updated_at
                )
                SELECT ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
                WHERE EXISTS (
                    SELECT 1 FROM model_runs
                    WHERE id = ? AND owner_id = ? AND status = 'running'
                      AND lease_owner = ?
                )
                """
            ).bind(
                block["id"],
                concept["id"],
                block["block_type"],
                block["content"],
                block["source"],
                block["is_user_locked"],
                block["revision"],
                block["supported_claim_ids_json"],
                block["position"],
                block["created_at"],
                block["updated_at"],
                run_id,
                owner_id,
                worker_id,
            )
            for block in blocks
        )
        statements.extend(
            self.database.prepare(
                """
                INSERT OR IGNORE INTO concept_tags (concept_id, name)
                SELECT ?, ? WHERE EXISTS (
                    SELECT 1 FROM model_runs
                    WHERE id = ? AND owner_id = ? AND status = 'running'
                      AND lease_owner = ?
                )
                """
            ).bind(concept["id"], tag, run_id, owner_id, worker_id)
            for tag in tags
        )
        statements.extend(
            self.database.prepare(
                """
                INSERT OR IGNORE INTO concept_topics (concept_id, name)
                SELECT ?, ? WHERE EXISTS (
                    SELECT 1 FROM model_runs
                    WHERE id = ? AND owner_id = ? AND status = 'running'
                      AND lease_owner = ?
                )
                """
            ).bind(concept["id"], topic, run_id, owner_id, worker_id)
            for topic in topics
        )
        statements.append(
            self.database.prepare(
                """
                INSERT OR IGNORE INTO note_revisions (
                    concept_id, revision, snapshot_json, actor, event_type, created_at
                )
                SELECT ?, ?, ?, ?, ?, ?
                WHERE EXISTS (
                    SELECT 1 FROM model_runs
                    WHERE id = ? AND owner_id = ? AND status = 'running'
                      AND lease_owner = ?
                )
                """
            ).bind(
                concept["id"],
                revision["revision"],
                revision["snapshot_json"],
                revision["actor"],
                revision["event_type"],
                revision["created_at"],
                run_id,
                owner_id,
                worker_id,
            )
        )
        statements.extend(
            self.database.prepare(
                """
                INSERT OR IGNORE INTO concept_turns (
                    id, concept_id, owner_id, operation_key, role,
                    content, answer_source_json, created_at
                )
                SELECT ?, ?, ?, ?, ?, ?, ?, ?
                WHERE EXISTS (
                    SELECT 1 FROM model_runs
                    WHERE id = ? AND owner_id = ? AND status = 'running'
                      AND lease_owner = ?
                )
                """
            ).bind(
                turn["id"],
                concept["id"],
                owner_id,
                turn["operation_key"],
                turn["role"],
                turn["content"],
                turn["answer_source_json"],
                turn["created_at"],
                run_id,
                owner_id,
                worker_id,
            )
            for turn in turns
        )
        statements.extend(
            self.database.prepare(
                """
                INSERT INTO concept_sources (
                    id, concept_id, owner_id, title, url, source_type,
                    retrieved_at, published_at, content_hash
                )
                SELECT ?, ?, ?, ?, ?, ?, ?, ?, ?
                WHERE EXISTS (
                    SELECT 1 FROM model_runs
                    WHERE id = ? AND owner_id = ? AND status = 'running'
                      AND lease_owner = ?
                )
                ON CONFLICT(concept_id, url) DO UPDATE SET
                    title = excluded.title,
                    source_type = excluded.source_type,
                    retrieved_at = excluded.retrieved_at
                """
            ).bind(
                source["id"],
                concept["id"],
                owner_id,
                source["title"],
                source["url"],
                source["source_type"],
                source["retrieved_at"],
                source["published_at"],
                source["content_hash"],
                run_id,
                owner_id,
                worker_id,
            )
            for source in sources
        )
        statements.append(
            self.database.prepare(
                """
                UPDATE model_runs
                SET status = 'succeeded',
                    concept_id = ?,
                    provider_snapshot_json = ?,
                    result_json = ?,
                    result_ref = ?,
                    model_call_count = ?,
                    tool_call_count = ?,
                    termination_reason = 'completed',
                    current_step = NULL,
                    lease_expires_at = NULL,
                    completed_at = ?,
                    error_code = NULL,
                    error_message = NULL,
                    updated_at = ?
                WHERE id = ? AND owner_id = ? AND status = 'running'
                  AND lease_owner = ?
                """
            ).bind(
                concept["id"],
                provider_snapshot_json,
                result_json,
                concept["id"],
                model_call_count,
                tool_call_count,
                now,
                now,
                run_id,
                owner_id,
                worker_id,
            )
        )
        statements.append(
            self._event_statement(
                run_id,
                "completed",
                result_json,
                now,
                required_status="succeeded",
                owner_id=owner_id,
                lease_owner=worker_id,
            )
        )
        statements.append(self._release_lease_statement(run_id, owner_id, worker_id))
        await self.database.batch(statements)
        return await self.get_model_run(run_id, owner_id)

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
        statements = []
        if replacing_turn_index is not None:
            statements.append(
                self.database.prepare(
                    """
                    DELETE FROM concept_turns
                    WHERE concept_id = ?
                      AND owner_id = ?
                      AND rowid >= (
                          SELECT rowid
                          FROM concept_turns
                          WHERE concept_id = ? AND owner_id = ?
                          ORDER BY created_at, rowid
                          LIMIT 1 OFFSET ?
                      )
                      AND EXISTS (
                          SELECT 1 FROM model_runs
                          WHERE id = ? AND owner_id = ? AND status = 'running'
                            AND lease_owner = ?
                      )
                    """
                ).bind(
                    concept_id,
                    owner_id,
                    concept_id,
                    owner_id,
                    replacing_turn_index,
                    run_id,
                    owner_id,
                    worker_id,
                )
            )
        statements.extend(
            self.database.prepare(
                """
                INSERT OR IGNORE INTO concept_turns (
                    id, concept_id, owner_id, operation_key, role,
                    content, answer_source_json, created_at
                )
                SELECT ?, ?, ?, ?, ?, ?, ?, ?
                WHERE EXISTS (
                    SELECT 1 FROM model_runs
                    WHERE id = ? AND owner_id = ? AND status = 'running'
                      AND lease_owner = ?
                )
                """
            ).bind(
                turn["id"],
                concept_id,
                owner_id,
                turn["operation_key"],
                turn["role"],
                turn["content"],
                turn["answer_source_json"],
                turn["created_at"],
                run_id,
                owner_id,
                worker_id,
            )
            for turn in turns
        )
        if proposal is not None:
            statements.append(
                self.database.prepare(
                    """
                    INSERT INTO update_proposals (
                        id, concept_id, owner_id, base_note_revision,
                        patch_operations_json, rationale, confidence, status,
                        origin, source_run_id, created_at, resolved_at
                    )
                    SELECT ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL
                    WHERE EXISTS (
                        SELECT 1 FROM model_runs
                        WHERE id = ? AND owner_id = ? AND status = 'running'
                          AND lease_owner = ?
                    )
                    """
                ).bind(
                    proposal["id"],
                    concept_id,
                    owner_id,
                    proposal["base_note_revision"],
                    proposal["patch_operations_json"],
                    proposal["rationale"],
                    proposal["confidence"],
                    proposal["status"],
                    proposal["origin"],
                    run_id,
                    proposal["created_at"],
                    run_id,
                    owner_id,
                    worker_id,
                )
            )
        statements.extend(
            self.database.prepare(
                """
                INSERT INTO concept_sources (
                    id, concept_id, owner_id, title, url, source_type,
                    retrieved_at, published_at, content_hash
                )
                SELECT ?, ?, ?, ?, ?, ?, ?, ?, ?
                WHERE EXISTS (
                    SELECT 1 FROM model_runs
                    WHERE id = ? AND owner_id = ? AND status = 'running'
                      AND lease_owner = ?
                )
                ON CONFLICT(concept_id, url) DO UPDATE SET
                    title = excluded.title,
                    source_type = excluded.source_type,
                    retrieved_at = excluded.retrieved_at
                """
            ).bind(
                source["id"],
                concept_id,
                owner_id,
                source["title"],
                source["url"],
                source["source_type"],
                source["retrieved_at"],
                source["published_at"],
                source["content_hash"],
                run_id,
                owner_id,
                worker_id,
            )
            for source in sources
        )
        statements.append(
            self.database.prepare(
                """
                UPDATE model_runs
                SET status = 'succeeded',
                    provider_snapshot_json = ?,
                    result_json = ?,
                    result_ref = ?,
                    model_call_count = ?,
                    tool_call_count = ?,
                    termination_reason = 'completed',
                    current_step = NULL,
                    lease_expires_at = NULL,
                    completed_at = ?,
                    error_code = NULL,
                    error_message = NULL,
                    updated_at = ?
                WHERE id = ? AND owner_id = ? AND status = 'running'
                  AND lease_owner = ?
                """
            ).bind(
                provider_snapshot_json,
                result_json,
                concept_id,
                model_call_count,
                tool_call_count,
                now,
                now,
                run_id,
                owner_id,
                worker_id,
            )
        )
        statements.append(
            self._event_statement(
                run_id,
                "completed",
                result_json,
                now,
                required_status="succeeded",
                owner_id=owner_id,
                lease_owner=worker_id,
            )
        )
        statements.append(self._release_lease_statement(run_id, owner_id, worker_id))
        await self.database.batch(statements)
        return await self.get_model_run(run_id, owner_id)

    async def list_update_proposals(
        self,
        concept_id: str,
        owner_id: str,
        status: str | None,
    ) -> list[dict[str, Any]] | None:
        if await self.get_concept(concept_id, owner_id) is None:
            return None
        if status is None:
            statement = self.database.prepare(
                """
                SELECT *
                FROM update_proposals
                WHERE concept_id = ? AND owner_id = ?
                ORDER BY created_at DESC
                """
            ).bind(concept_id, owner_id)
        else:
            statement = self.database.prepare(
                """
                SELECT *
                FROM update_proposals
                WHERE concept_id = ? AND owner_id = ? AND status = ?
                ORDER BY created_at DESC
                """
            ).bind(concept_id, owner_id, status)
        return _rows(await statement.run())

    async def get_update_proposal(
        self,
        proposal_id: str,
        owner_id: str,
    ) -> dict[str, Any] | None:
        return _row(
            await self.database.prepare(
                """
                SELECT *
                FROM update_proposals
                WHERE id = ? AND owner_id = ?
                """
            )
            .bind(proposal_id, owner_id)
            .first()
        )

    async def resolve_update_proposal(
        self,
        proposal_id: str,
        owner_id: str,
        *,
        status: str,
        now: str,
    ) -> bool:
        result = await self.database.prepare(
            """
            UPDATE update_proposals
            SET status = ?, resolved_at = ?
            WHERE id = ? AND owner_id = ? AND status = 'proposed'
            """
        ).bind(status, now, proposal_id, owner_id).run()
        return _changes(result) == 1

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
        concept_id = str(concept["id"])
        new_revision = int(concept["note_revision"])
        owner_guard = (
            "SELECT 1 FROM concepts "
            "WHERE id = ? AND owner_id = ? AND note_revision = ? "
            "AND EXISTS (SELECT 1 FROM model_runs "
            "WHERE id = ? AND owner_id = ? AND status = 'running' "
            "AND lease_owner = ?)"
        )
        owner_guard_bindings = (
            concept_id,
            owner_id,
            new_revision,
            run_id,
            owner_id,
            worker_id,
        )
        statements = [
            self.database.prepare(
                """
                UPDATE concepts
                SET canonical_title = ?,
                    display_title = ?,
                    one_line_explanation = ?,
                    initial_answer = ?,
                    maturity = ?,
                    capture_status = ?,
                    note_revision = ?,
                    answer_source_json = ?,
                    document_json = ?,
                    updated_at = ?
                WHERE id = ? AND owner_id = ? AND note_revision = ?
                  AND EXISTS (
                      SELECT 1 FROM model_runs
                      WHERE id = ? AND owner_id = ? AND status = 'running'
                        AND lease_owner = ?
                  )
                """
            ).bind(
                concept["canonical_title"],
                concept["display_title"],
                concept["one_line_explanation"],
                concept["initial_answer"],
                concept["maturity"],
                concept["capture_status"],
                new_revision,
                concept["answer_source_json"],
                concept["document_json"],
                concept["updated_at"],
                concept_id,
                owner_id,
                expected_revision,
                run_id,
                owner_id,
                worker_id,
            ),
            self.database.prepare(
                f"""
                DELETE FROM note_blocks
                WHERE concept_id = ? AND EXISTS ({owner_guard})
                """
            ).bind(concept_id, *owner_guard_bindings),
            self.database.prepare(
                f"""
                DELETE FROM concept_tags
                WHERE concept_id = ? AND EXISTS ({owner_guard})
                """
            ).bind(concept_id, *owner_guard_bindings),
            self.database.prepare(
                f"""
                DELETE FROM concept_topics
                WHERE concept_id = ? AND EXISTS ({owner_guard})
                """
            ).bind(concept_id, *owner_guard_bindings),
            self.database.prepare(
                f"""
                DELETE FROM concept_turns
                WHERE concept_id = ? AND owner_id = ?
                  AND EXISTS ({owner_guard})
                """
            ).bind(concept_id, owner_id, *owner_guard_bindings),
        ]
        statements.extend(
            self.database.prepare(
                f"""
                INSERT INTO note_blocks (
                    id, concept_id, block_type, content, source,
                    is_user_locked, revision, supported_claim_ids_json,
                    position, created_at, updated_at
                )
                SELECT ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
                WHERE EXISTS ({owner_guard})
                """
            ).bind(
                block["id"],
                concept_id,
                block["block_type"],
                block["content"],
                block["source"],
                block["is_user_locked"],
                block["revision"],
                block["supported_claim_ids_json"],
                block["position"],
                block["created_at"],
                block["updated_at"],
                *owner_guard_bindings,
            )
            for block in blocks
        )
        statements.extend(
            self.database.prepare(
                f"""
                INSERT INTO concept_tags (concept_id, name)
                SELECT ?, ? WHERE EXISTS ({owner_guard})
                """
            ).bind(concept_id, tag, *owner_guard_bindings)
            for tag in tags
        )
        statements.extend(
            self.database.prepare(
                f"""
                INSERT INTO concept_topics (concept_id, name)
                SELECT ?, ? WHERE EXISTS ({owner_guard})
                """
            ).bind(concept_id, topic, *owner_guard_bindings)
            for topic in topics
        )
        statements.append(
            self.database.prepare(
                f"""
                INSERT INTO note_revisions (
                    concept_id, revision, snapshot_json, actor, event_type,
                    created_at, snapshot_schema_version, restored_from_revision
                )
                SELECT ?, ?, ?, ?, ?, ?, ?, NULL
                WHERE EXISTS ({owner_guard})
                """
            ).bind(
                concept_id,
                revision["revision"],
                revision["snapshot_json"],
                revision["actor"],
                revision["event_type"],
                revision["created_at"],
                revision["snapshot_schema_version"],
                *owner_guard_bindings,
            )
        )
        statements.extend(
            self.database.prepare(
                f"""
                INSERT INTO concept_turns (
                    id, concept_id, owner_id, operation_key, role,
                    content, answer_source_json, created_at
                )
                SELECT ?, ?, ?, ?, ?, ?, ?, ?
                WHERE EXISTS ({owner_guard})
                """
            ).bind(
                turn["id"],
                concept_id,
                owner_id,
                turn["operation_key"],
                turn["role"],
                turn["content"],
                turn["answer_source_json"],
                turn["created_at"],
                *owner_guard_bindings,
            )
            for turn in turns
        )
        statements.extend(
            [
                self.database.prepare(
                    f"""
                    UPDATE model_runs
                    SET status = 'succeeded',
                        provider_snapshot_json = ?,
                        result_json = ?,
                        result_ref = ?,
                        model_call_count = ?,
                        tool_call_count = ?,
                        termination_reason = 'completed',
                        current_step = NULL,
                        lease_expires_at = NULL,
                        completed_at = ?,
                        error_code = NULL,
                        error_message = NULL,
                        updated_at = ?
                    WHERE id = ? AND owner_id = ? AND status = 'running'
                      AND lease_owner = ?
                      AND EXISTS ({owner_guard})
                    """
                ).bind(
                    provider_snapshot_json,
                    result_json,
                    concept_id,
                    model_call_count,
                    tool_call_count,
                    now,
                    now,
                    run_id,
                    owner_id,
                    worker_id,
                    *owner_guard_bindings,
                ),
                self._event_statement(
                    run_id,
                    "completed",
                    result_json,
                    now,
                    required_status="succeeded",
                    owner_id=owner_id,
                    lease_owner=worker_id,
                ),
                self._release_lease_statement(run_id, owner_id, worker_id),
            ]
        )
        results = _to_python(await self.database.batch(statements))
        first_result = results[0] if isinstance(results, list) and results else None
        if first_result is None or _changes(first_result) != 1:
            return None
        return await self.get_model_run(run_id, owner_id)

    async def get_concept(self, concept_id: str, owner_id: str) -> dict[str, Any] | None:
        row = _row(
            await self.database.prepare(
                "SELECT document_json FROM concepts WHERE id = ? AND owner_id = ?"
            )
            .bind(concept_id, owner_id)
            .first()
        )
        document = _json_row(row.get("document_json")) if row is not None else None
        if document is None:
            return None
        relations = await self.database.prepare(
            """
            SELECT r.*
            FROM concept_relations AS r
            JOIN concepts AS source ON source.id = r.source_concept_id
            JOIN concepts AS target ON target.id = r.target_concept_id
            WHERE (r.source_concept_id = ? OR r.target_concept_id = ?)
              AND source.owner_id = ?
              AND target.owner_id = ?
            ORDER BY r.created_at, r.id
            """
        ).bind(concept_id, concept_id, owner_id, owner_id).run()
        document["relations"] = [
            _relation_document(row) for row in _rows(relations)
        ]
        sources = await self.database.prepare(
            """
            SELECT *
            FROM concept_sources
            WHERE concept_id = ? AND owner_id = ?
            ORDER BY retrieved_at, id
            """
        ).bind(concept_id, owner_id).run()
        document["sources"] = [_source_document(row) for row in _rows(sources)]
        claims = await self.database.prepare(
            """
            SELECT * FROM concept_claims
            WHERE concept_id = ? AND owner_id = ?
            ORDER BY created_at, id
            """
        ).bind(concept_id, owner_id).run()
        document["claims"] = [_claim_document(row) for row in _rows(claims)]
        learning = await self.database.prepare(
            """
            SELECT * FROM learning_state_entries
            WHERE concept_id = ? AND owner_id = ?
            ORDER BY created_at, id
            """
        ).bind(concept_id, owner_id).run()
        document["learningState"] = _learning_state_document(
            concept_id,
            _rows(learning),
        )
        return document

    async def list_concepts(self, owner_id: str) -> list[dict[str, Any]]:
        result = await self.database.prepare(
            """
            SELECT document_json
            FROM concepts
            WHERE owner_id = ?
            ORDER BY created_at
            """
        ).bind(owner_id).run()
        documents = [
            parsed
            for row in _rows(result)
            if (parsed := _json_row(row.get("document_json"))) is not None
        ]
        relations = await self.database.prepare(
            """
            SELECT r.*
            FROM concept_relations AS r
            JOIN concepts AS source ON source.id = r.source_concept_id
            JOIN concepts AS target ON target.id = r.target_concept_id
            WHERE source.owner_id = ? AND target.owner_id = ?
            ORDER BY r.created_at, r.id
            """
        ).bind(owner_id, owner_id).run()
        by_concept: dict[str, list[dict[str, Any]]] = {
            str(document["id"]): [] for document in documents
        }
        for row in _rows(relations):
            relation = _relation_document(row)
            for key in ("sourceConceptId", "targetConceptId"):
                concept_relations = by_concept.get(str(relation[key]))
                if concept_relations is not None:
                    concept_relations.append(relation)
        for document in documents:
            document["relations"] = by_concept.get(str(document["id"]), [])
        source_result = await self.database.prepare(
            """
            SELECT *
            FROM concept_sources
            WHERE owner_id = ?
            ORDER BY retrieved_at, id
            """
        ).bind(owner_id).run()
        sources_by_concept: dict[str, list[dict[str, Any]]] = {
            str(document["id"]): [] for document in documents
        }
        for row in _rows(source_result):
            sources_by_concept.setdefault(str(row["concept_id"]), []).append(
                _source_document(row)
            )
        for document in documents:
            document["sources"] = sources_by_concept.get(str(document["id"]), [])
        claims_result = await self.database.prepare(
            """
            SELECT * FROM concept_claims
            WHERE owner_id = ?
            ORDER BY created_at, id
            """
        ).bind(owner_id).run()
        claims_by_concept: dict[str, list[dict[str, Any]]] = {
            str(document["id"]): [] for document in documents
        }
        for row in _rows(claims_result):
            claims_by_concept.setdefault(str(row["concept_id"]), []).append(
                _claim_document(row)
            )
        learning_result = await self.database.prepare(
            """
            SELECT * FROM learning_state_entries
            WHERE owner_id = ?
            ORDER BY created_at, id
            """
        ).bind(owner_id).run()
        learning_by_concept: dict[str, list[dict[str, Any]]] = {
            str(document["id"]): [] for document in documents
        }
        for row in _rows(learning_result):
            learning_by_concept.setdefault(str(row["concept_id"]), []).append(row)
        for document in documents:
            concept_id = str(document["id"])
            document["claims"] = claims_by_concept.get(concept_id, [])
            document["learningState"] = _learning_state_document(
                concept_id,
                learning_by_concept.get(concept_id, []),
            )
        return documents

    async def set_concepts_archived(
        self,
        concept_ids: list[str],
        owner_id: str,
        *,
        archived: bool,
        now: str,
    ) -> list[dict[str, Any]] | None:
        if archived:
            statements = [
                self.database.prepare(
                    """
                    UPDATE concepts
                    SET archived_from_status = CASE
                            WHEN capture_status != 'archived' THEN capture_status
                            ELSE archived_from_status
                        END,
                        capture_status = 'archived',
                        document_json = json_set(
                            document_json,
                            '$.captureStatus', 'archived',
                            '$.updatedAt', ?
                        ),
                        updated_at = ?
                    WHERE id = ? AND owner_id = ?
                    """
                ).bind(now, now, concept_id, owner_id)
                for concept_id in concept_ids
            ]
        else:
            statements = [
                self.database.prepare(
                    """
                    UPDATE concepts
                    SET capture_status = COALESCE(archived_from_status, 'ready'),
                        document_json = json_set(
                            document_json,
                            '$.captureStatus', COALESCE(archived_from_status, 'ready'),
                            '$.updatedAt', ?
                        ),
                        archived_from_status = NULL,
                        updated_at = ?
                    WHERE id = ? AND owner_id = ?
                    """
                ).bind(now, now, concept_id, owner_id)
                for concept_id in concept_ids
            ]
        results = _to_python(await self.database.batch(statements))
        if not isinstance(results, list) or any(_changes(result) != 1 for result in results):
            return None
        concepts = []
        for concept_id in concept_ids:
            concept = await self.get_concept(concept_id, owner_id)
            if concept is None:
                return None
            concepts.append(concept)
        return concepts

    async def add_concept_relation(
        self,
        *,
        relation: dict[str, Any],
        owner_id: str,
    ) -> dict[str, Any] | None:
        await self.database.prepare(
            """
            INSERT OR IGNORE INTO concept_relations (
                id, source_concept_id, target_concept_id, relation_type,
                status, confidence, source, created_at
            )
            SELECT ?, source.id, target.id, ?, ?, ?, ?, ?
            FROM concepts AS source
            JOIN concepts AS target ON target.id = ?
            WHERE source.id = ?
              AND source.owner_id = ?
              AND target.owner_id = ?
            """
        ).bind(
            relation["id"],
            relation["relation_type"],
            relation["status"],
            relation["confidence"],
            relation["source"],
            relation["created_at"],
            relation["target_concept_id"],
            relation["source_concept_id"],
            owner_id,
            owner_id,
        ).run()
        return await self.get_concept(str(relation["source_concept_id"]), owner_id)

    async def remove_concept_relation(
        self,
        *,
        concept_id: str,
        relation_id: str,
        owner_id: str,
    ) -> dict[str, Any] | None:
        result = await self.database.prepare(
            """
            DELETE FROM concept_relations
            WHERE id = ?
              AND (source_concept_id = ? OR target_concept_id = ?)
              AND EXISTS (
                  SELECT 1
                  FROM concepts AS source
                  JOIN concepts AS target
                    ON target.id = concept_relations.target_concept_id
                  WHERE source.id = concept_relations.source_concept_id
                    AND source.owner_id = ?
                    AND target.owner_id = ?
              )
            """
        ).bind(relation_id, concept_id, concept_id, owner_id, owner_id).run()
        if _changes(result) != 1:
            return None
        return await self.get_concept(concept_id, owner_id)

    async def list_concept_turns(
        self,
        concept_id: str,
        owner_id: str,
    ) -> list[dict[str, Any]] | None:
        if await self.get_concept(concept_id, owner_id) is None:
            return None
        result = await self.database.prepare(
            """
            SELECT role, content, answer_source_json, created_at
            FROM concept_turns
            WHERE concept_id = ? AND owner_id = ?
            ORDER BY created_at, rowid
            """
        ).bind(concept_id, owner_id).run()
        return _rows(result)

    async def get_continuity_summary(
        self,
        concept_id: str,
        owner_id: str,
    ) -> dict[str, Any] | None:
        return _row(
            await self.database.prepare(
                """
                SELECT * FROM concept_continuity_summaries
                WHERE concept_id = ? AND owner_id = ?
                """
            )
            .bind(concept_id, owner_id)
            .first()
        )

    async def get_maintenance_status(
        self,
        concept_id: str,
        owner_id: str,
    ) -> dict[str, Any] | None:
        return _row(
            await self.database.prepare(
                """
                SELECT
                    COUNT(turns.id) AS turn_count,
                    SUM(CASE WHEN turns.role = 'user' THEN 1 ELSE 0 END)
                        AS user_turn_count,
                    COALESCE(summary.through_turn_count, 0)
                        AS summarized_turn_count,
                    COALESCE(state.reviewed_user_turn_count, 1)
                        AS reviewed_user_turn_count,
                    COALESCE(state.review_due, 0) AS review_due,
                    EXISTS (
                        SELECT 1 FROM update_proposals AS proposal
                        WHERE proposal.concept_id = concept.id
                          AND proposal.owner_id = concept.owner_id
                          AND proposal.status = 'proposed'
                    ) AS has_pending_proposal
                FROM concepts AS concept
                LEFT JOIN concept_turns AS turns
                  ON turns.concept_id = concept.id AND turns.owner_id = concept.owner_id
                LEFT JOIN concept_continuity_summaries AS summary
                  ON summary.concept_id = concept.id AND summary.owner_id = concept.owner_id
                LEFT JOIN concept_maintenance_state AS state
                  ON state.concept_id = concept.id AND state.owner_id = concept.owner_id
                WHERE concept.id = ? AND concept.owner_id = ?
                GROUP BY concept.id
                """
            )
            .bind(concept_id, owner_id)
            .first()
        )

    async def complete_continuity_summary_run(
        self,
        *,
        run_id: str,
        owner_id: str,
        worker_id: str,
        concept_id: str,
        summary: str,
        through_turn_count: int,
        source_turns_hash: str,
        provider_snapshot_json: str,
        result_json: str,
        now: str,
    ) -> dict[str, Any] | None:
        statements = [
            self.database.prepare(
                """
                INSERT INTO concept_continuity_summaries (
                    concept_id, owner_id, summary, through_turn_count,
                    source_turns_hash, version, generated_at
                )
                SELECT ?, ?, ?, ?, ?, 1, ?
                WHERE EXISTS (
                    SELECT 1 FROM concepts WHERE id = ? AND owner_id = ?
                )
                  AND EXISTS (
                    SELECT 1 FROM model_runs
                    WHERE id = ? AND owner_id = ? AND status = 'running'
                      AND lease_owner = ?
                  )
                ON CONFLICT(concept_id) DO UPDATE SET
                    owner_id = excluded.owner_id,
                    summary = excluded.summary,
                    through_turn_count = excluded.through_turn_count,
                    source_turns_hash = excluded.source_turns_hash,
                    version = concept_continuity_summaries.version + 1,
                    generated_at = excluded.generated_at
                """
            ).bind(
                concept_id,
                owner_id,
                summary,
                through_turn_count,
                source_turns_hash,
                now,
                concept_id,
                owner_id,
                run_id,
                owner_id,
                worker_id,
            ),
            self._complete_model_run_statement(
                run_id,
                owner_id,
                worker_id,
                concept_id,
                provider_snapshot_json,
                result_json,
                now,
            ),
            self._event_statement(
                run_id,
                "completed",
                result_json,
                now,
                required_status="succeeded",
                owner_id=owner_id,
                lease_owner=worker_id,
            ),
            self._release_lease_statement(run_id, owner_id, worker_id),
        ]
        await self.database.batch(statements)
        return await self.get_model_run(run_id, owner_id)

    async def complete_knowledge_review_run(
        self,
        *,
        run_id: str,
        owner_id: str,
        worker_id: str,
        concept_id: str,
        reviewed_user_turn_count: int,
        proposal: dict[str, Any] | None,
        claims: list[dict[str, Any]],
        learning_state_updates: list[dict[str, Any]],
        provider_snapshot_json: str,
        result_json: str,
        now: str,
    ) -> dict[str, Any] | None:
        statements = []
        if proposal is not None:
            statements.append(
                self.database.prepare(
                    """
                    INSERT INTO update_proposals (
                        id, concept_id, owner_id, base_note_revision,
                        patch_operations_json, rationale, confidence, status,
                        origin, source_run_id, created_at, resolved_at
                    )
                    SELECT ?, ?, ?, ?, ?, ?, ?, 'proposed',
                           'periodicReview', ?, ?, NULL
                    WHERE EXISTS (
                        SELECT 1 FROM concepts WHERE id = ? AND owner_id = ?
                    )
                      AND EXISTS (
                        SELECT 1 FROM model_runs
                        WHERE id = ? AND owner_id = ? AND status = 'running'
                          AND lease_owner = ?
                      )
                      AND NOT EXISTS (
                        SELECT 1 FROM update_proposals
                        WHERE concept_id = ? AND owner_id = ? AND status = 'proposed'
                    )
                    """
                ).bind(
                    proposal["id"],
                    concept_id,
                    owner_id,
                    proposal["base_note_revision"],
                    proposal["patch_operations_json"],
                    proposal["rationale"],
                    proposal["confidence"],
                    run_id,
                    now,
                    concept_id,
                    owner_id,
                    run_id,
                    owner_id,
                    worker_id,
                    concept_id,
                    owner_id,
                )
            )
        statements.extend(
            self.database.prepare(
                """
                INSERT OR IGNORE INTO concept_claims (
                    id, concept_id, owner_id, statement, claim_type,
                    evidence_status, time_sensitivity, source_ids_json,
                    verified_at, superseded_by_claim_id, created_at
                )
                SELECT ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, ?
                WHERE EXISTS (
                    SELECT 1 FROM concepts WHERE id = ? AND owner_id = ?
                )
                  AND EXISTS (
                    SELECT 1 FROM model_runs
                    WHERE id = ? AND owner_id = ? AND status = 'running'
                      AND lease_owner = ?
                  )
                """
            ).bind(
                claim["id"],
                concept_id,
                owner_id,
                claim["statement"],
                claim["claim_type"],
                claim["evidence_status"],
                claim["time_sensitivity"],
                claim["source_ids_json"],
                claim["verified_at"],
                claim["created_at"],
                concept_id,
                owner_id,
                run_id,
                owner_id,
                worker_id,
            )
            for claim in claims
        )
        statements.extend(
            self.database.prepare(
                """
                INSERT OR IGNORE INTO learning_state_entries (
                    id, concept_id, owner_id, field, content, origin, created_at
                )
                SELECT ?, ?, ?, ?, ?, ?, ?
                WHERE EXISTS (
                    SELECT 1 FROM concepts WHERE id = ? AND owner_id = ?
                )
                  AND EXISTS (
                    SELECT 1 FROM model_runs
                    WHERE id = ? AND owner_id = ? AND status = 'running'
                      AND lease_owner = ?
                  )
                """
            ).bind(
                update["id"],
                concept_id,
                owner_id,
                update["field"],
                update["content"],
                update["origin"],
                update["created_at"],
                concept_id,
                owner_id,
                run_id,
                owner_id,
                worker_id,
            )
            for update in learning_state_updates
        )
        statements.extend(
            [
                self.database.prepare(
                    """
                    INSERT INTO concept_maintenance_state (
                        concept_id, owner_id, reviewed_user_turn_count,
                        review_due, updated_at
                    )
                    SELECT ?, ?, ?, 0, ?
                    WHERE EXISTS (
                        SELECT 1 FROM model_runs
                        WHERE id = ? AND owner_id = ? AND status = 'running'
                          AND lease_owner = ?
                    )
                    ON CONFLICT(concept_id) DO UPDATE SET
                        owner_id = excluded.owner_id,
                        reviewed_user_turn_count = excluded.reviewed_user_turn_count,
                        review_due = 0,
                        updated_at = excluded.updated_at
                    """
                ).bind(
                    concept_id,
                    owner_id,
                    reviewed_user_turn_count,
                    now,
                    run_id,
                    owner_id,
                    worker_id,
                ),
                self._complete_model_run_statement(
                    run_id,
                    owner_id,
                    worker_id,
                    concept_id,
                    provider_snapshot_json,
                    result_json,
                    now,
                ),
                self._event_statement(
                    run_id,
                    "completed",
                    result_json,
                    now,
                    required_status="succeeded",
                    owner_id=owner_id,
                    lease_owner=worker_id,
                ),
                self._release_lease_statement(run_id, owner_id, worker_id),
            ]
        )
        await self.database.batch(statements)
        return await self.get_model_run(run_id, owner_id)

    async def list_note_revisions(
        self,
        concept_id: str,
        owner_id: str,
    ) -> list[dict[str, Any]] | None:
        if await self.get_concept(concept_id, owner_id) is None:
            return None
        result = await self.database.prepare(
            """
            SELECT r.revision, r.event_type, r.created_at,
                   r.snapshot_schema_version, r.restored_from_revision,
                   c.note_revision AS current_revision
            FROM note_revisions AS r
            JOIN concepts AS c ON c.id = r.concept_id
            WHERE r.concept_id = ? AND c.owner_id = ?
            ORDER BY r.revision DESC
            """
        ).bind(concept_id, owner_id).run()
        return _rows(result)

    async def get_note_revision(
        self,
        concept_id: str,
        revision: int,
        owner_id: str,
    ) -> dict[str, Any] | None:
        return _row(
            await self.database.prepare(
                """
                SELECT r.revision, r.snapshot_json, r.event_type, r.created_at,
                       r.snapshot_schema_version, r.restored_from_revision,
                       c.note_revision AS current_revision
                FROM note_revisions AS r
                JOIN concepts AS c ON c.id = r.concept_id
                WHERE r.concept_id = ? AND r.revision = ? AND c.owner_id = ?
                """
            )
            .bind(concept_id, revision, owner_id)
            .first()
        )

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
        new_revision = int(concept["note_revision"])
        owner_guard = (
            "SELECT 1 FROM concepts "
            "WHERE id = ? AND owner_id = ? AND note_revision = ? "
            "AND (? IS NULL OR EXISTS ("
            "SELECT 1 FROM update_proposals "
            "WHERE id = ? AND owner_id = ? AND status = 'proposed' "
            "AND base_note_revision = ?))"
        )
        guard_params = (
            concept_id,
            owner_id,
            new_revision,
            proposal_id,
            proposal_id,
            owner_id,
            expected_revision,
        )
        statements = [
            self.database.prepare(
                """
                UPDATE concepts
                SET canonical_title = ?,
                    display_title = ?,
                    one_line_explanation = ?,
                    maturity = ?,
                    note_revision = ?,
                    document_json = ?,
                    updated_at = ?
                WHERE id = ? AND owner_id = ? AND note_revision = ?
                  AND (? IS NULL OR EXISTS (
                      SELECT 1 FROM update_proposals
                      WHERE id = ? AND owner_id = ? AND status = 'proposed'
                        AND base_note_revision = ?
                  ))
                """
            ).bind(
                concept["canonical_title"],
                concept["display_title"],
                concept["one_line_explanation"],
                concept["maturity"],
                new_revision,
                concept["document_json"],
                concept["updated_at"],
                concept_id,
                owner_id,
                expected_revision,
                proposal_id,
                proposal_id,
                owner_id,
                expected_revision,
            ),
            self.database.prepare(
                f"""
                DELETE FROM note_blocks
                WHERE concept_id = ?
                  AND EXISTS ({owner_guard})
                """
            ).bind(concept_id, *guard_params),
            self.database.prepare(
                f"""
                DELETE FROM concept_tags
                WHERE concept_id = ?
                  AND EXISTS ({owner_guard})
                """
            ).bind(concept_id, *guard_params),
            self.database.prepare(
                f"""
                DELETE FROM concept_topics
                WHERE concept_id = ?
                  AND EXISTS ({owner_guard})
                """
            ).bind(concept_id, *guard_params),
        ]
        statements.extend(
            self.database.prepare(
                f"""
                INSERT INTO note_blocks (
                    id, concept_id, block_type, content, source,
                    is_user_locked, revision, supported_claim_ids_json,
                    position, created_at, updated_at
                )
                SELECT ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
                WHERE EXISTS ({owner_guard})
                """
            ).bind(
                block["id"],
                concept_id,
                block["block_type"],
                block["content"],
                block["source"],
                block["is_user_locked"],
                block["revision"],
                block["supported_claim_ids_json"],
                block["position"],
                block["created_at"],
                block["updated_at"],
                *guard_params,
            )
            for block in blocks
        )
        statements.extend(
            self.database.prepare(
                f"""
                INSERT INTO concept_tags (concept_id, name)
                SELECT ?, ?
                WHERE EXISTS ({owner_guard})
                """
            ).bind(concept_id, tag, *guard_params)
            for tag in tags
        )
        statements.extend(
            self.database.prepare(
                f"""
                INSERT INTO concept_topics (concept_id, name)
                SELECT ?, ?
                WHERE EXISTS ({owner_guard})
                """
            ).bind(concept_id, topic, *guard_params)
            for topic in topics
        )
        statements.append(
            self.database.prepare(
                f"""
                INSERT INTO note_revisions (
                    concept_id, revision, snapshot_json, actor, event_type,
                    created_at, snapshot_schema_version, restored_from_revision
                )
                SELECT ?, ?, ?, ?, ?, ?, ?, ?
                WHERE EXISTS ({owner_guard})
                """
            ).bind(
                concept_id,
                revision["revision"],
                revision["snapshot_json"],
                revision["actor"],
                revision["event_type"],
                revision["created_at"],
                revision["snapshot_schema_version"],
                revision["restored_from_revision"],
                *guard_params,
            )
        )
        if idempotency is not None:
            statements.append(
                self.database.prepare(
                    f"""
                    INSERT INTO mutation_idempotency (
                        owner_id, scope, idempotency_key, payload_hash,
                        response_json, created_at
                    )
                    SELECT ?, ?, ?, ?, ?, ?
                    WHERE EXISTS ({owner_guard})
                    """
                ).bind(
                    owner_id,
                    idempotency["scope"],
                    idempotency["idempotency_key"],
                    idempotency["payload_hash"],
                    idempotency["response_json"],
                    idempotency["created_at"],
                    *guard_params,
                )
            )
        if proposal_id is not None:
            statements.append(
                self.database.prepare(
                    f"""
                    UPDATE update_proposals
                    SET status = 'accepted', resolved_at = ?
                    WHERE id = ? AND owner_id = ? AND status = 'proposed'
                      AND EXISTS ({owner_guard})
                    """
                ).bind(
                    concept["updated_at"],
                    proposal_id,
                    owner_id,
                    *guard_params,
                )
            )
        results = _to_python(await self.database.batch(statements))
        first_result = results[0] if isinstance(results, list) and results else None
        if first_result is None or _changes(first_result) != 1:
            return None
        return await self.get_concept(concept_id, owner_id)

    async def get_mutation_idempotency(
        self,
        owner_id: str,
        scope: str,
        idempotency_key: str,
    ) -> dict[str, Any] | None:
        return _row(
            await self.database.prepare(
                """
                SELECT payload_hash, response_json
                FROM mutation_idempotency
                WHERE owner_id = ? AND scope = ? AND idempotency_key = ?
                """
            )
            .bind(owner_id, scope, idempotency_key)
            .first()
        )

    async def _get_model_run_by_key(
        self,
        owner_id: str,
        kind: str,
        idempotency_key: str,
    ) -> dict[str, Any] | None:
        return _row(
            await self.database.prepare(
                """
                SELECT * FROM model_runs
                WHERE owner_id = ? AND kind = ? AND idempotency_key = ?
                """
            )
            .bind(owner_id, kind, idempotency_key)
            .first()
        )

    async def _append_event(
        self,
        run_id: str,
        event_type: str,
        data_json: str | None,
        now: str,
    ) -> None:
        await self.database.prepare(
            """
            INSERT INTO model_run_events (
                run_id, sequence, event_type, data_json, created_at
            )
            SELECT ?, COALESCE(MAX(sequence), 0) + 1, ?, ?, ?
            FROM model_run_events
            WHERE run_id = ?
            """
        ).bind(run_id, event_type, data_json, now, run_id).run()

    async def _max_event_sequence(self, run_id: str) -> int | None:
        row = _row(
            await self.database.prepare(
                "SELECT MAX(sequence) AS sequence FROM model_run_events WHERE run_id = ?"
            ).bind(run_id).first()
        )
        return int(row["sequence"]) if row and row.get("sequence") is not None else None

    def _complete_model_run_statement(
        self,
        run_id: str,
        owner_id: str,
        worker_id: str,
        result_ref: str,
        provider_snapshot_json: str,
        result_json: str,
        now: str,
    ) -> Any:
        return self.database.prepare(
            """
            UPDATE model_runs
            SET status = 'succeeded',
                provider_snapshot_json = ?,
                result_json = ?,
                result_ref = ?,
                model_call_count = 1,
                termination_reason = 'completed',
                current_step = NULL,
                lease_expires_at = NULL,
                completed_at = ?,
                error_code = NULL,
                error_message = NULL,
                updated_at = ?
            WHERE id = ? AND owner_id = ? AND status = 'running'
              AND lease_owner = ?
            """
        ).bind(
            provider_snapshot_json,
            result_json,
            result_ref,
            now,
            now,
            run_id,
            owner_id,
            worker_id,
        )

    def _release_lease_statement(
        self,
        run_id: str,
        owner_id: str,
        worker_id: str,
    ) -> Any:
        return self.database.prepare(
            """
            UPDATE model_runs
            SET lease_owner = NULL
            WHERE id = ? AND owner_id = ? AND lease_owner = ?
              AND status IN ('succeeded', 'failed')
            """
        ).bind(run_id, owner_id, worker_id)

    def _event_statement(
        self,
        run_id: str,
        event_type: str,
        data_json: str | None,
        now: str,
        *,
        required_status: str,
        owner_id: str | None = None,
        lease_owner: str | None = None,
    ) -> Any:
        owner_guard = "AND owner_id = ?" if owner_id is not None else ""
        lease_guard = "AND lease_owner = ?" if lease_owner is not None else ""
        bindings: list[Any] = [
            run_id,
            run_id,
            event_type,
            data_json,
            now,
            run_id,
            required_status,
        ]
        if owner_id is not None:
            bindings.append(owner_id)
        if lease_owner is not None:
            bindings.append(lease_owner)
        return self.database.prepare(
            f"""
            INSERT INTO model_run_events (
                run_id, sequence, event_type, data_json, created_at
            )
            SELECT ?, (
                SELECT COALESCE(MAX(sequence), 0) + 1
                FROM model_run_events
                WHERE run_id = ?
            ), ?, ?, ?
            WHERE EXISTS (
                SELECT 1 FROM model_runs
                WHERE id = ? AND status = ?
                {owner_guard}
                {lease_guard}
            )
            """
        ).bind(*bindings)


def _row(value: Any) -> dict[str, Any] | None:
    if value is None:
        return None
    converted = _to_python(value)
    if isinstance(converted, dict):
        return converted
    return dict(converted)


def _rows(result: Any) -> list[dict[str, Any]]:
    converted = _to_python(result)
    raw_rows = converted.get("results", []) if isinstance(converted, dict) else result.results
    return [_row(item) or {} for item in raw_rows]


def _to_python(value: Any) -> Any:
    if hasattr(value, "to_py"):
        return value.to_py()
    return value


def _changes(result: Any) -> int:
    converted = _to_python(result)
    if isinstance(converted, dict):
        meta = converted.get("meta")
        return int(meta.get("changes", 0)) if isinstance(meta, dict) else 0
    return int(getattr(getattr(result, "meta", None), "changes", 0))


def _json_row(value: Any) -> dict[str, Any] | None:
    if not isinstance(value, str):
        return None
    import json

    parsed = json.loads(value)
    return parsed if isinstance(parsed, dict) else None


def _json_data(value: dict[str, Any]) -> str:
    import json

    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _relation_document(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": str(row["id"]),
        "sourceConceptId": str(row["source_concept_id"]),
        "targetConceptId": str(row["target_concept_id"]),
        "relationType": str(row["relation_type"]),
        "status": str(row["status"]),
        "confidence": float(row["confidence"]),
        "source": str(row["source"]),
    }


def _source_document(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": str(row["id"]),
        "conceptId": str(row["concept_id"]),
        "title": str(row["title"]),
        "url": _optional_text(row.get("url")),
        "sourceType": str(row["source_type"]),
        "retrievedAt": _optional_text(row.get("retrieved_at")),
        "publishedAt": _optional_text(row.get("published_at")),
        "contentHash": _optional_text(row.get("content_hash")),
    }


def _claim_document(row: dict[str, Any]) -> dict[str, Any]:
    import json

    source_ids = json.loads(str(row.get("source_ids_json") or "[]"))
    return {
        "id": str(row["id"]),
        "conceptId": str(row["concept_id"]),
        "statement": str(row["statement"]),
        "type": str(row["claim_type"]),
        "evidenceStatus": str(row["evidence_status"]),
        "timeSensitivity": str(row["time_sensitivity"]),
        "sourceIds": source_ids if isinstance(source_ids, list) else [],
        "verifiedAt": _optional_text(row.get("verified_at")),
        "supersededByClaimId": _optional_text(row.get("superseded_by_claim_id")),
    }


def _learning_state_document(
    concept_id: str,
    rows: list[dict[str, Any]],
) -> dict[str, Any] | None:
    if not rows:
        return None
    fields = {
        "userContext": [],
        "confirmedUnderstanding": [],
        "openQuestions": [],
        "recurringConfusions": [],
    }
    for row in rows:
        field = str(row.get("field"))
        if field not in fields:
            continue
        fields[field].append(
            {
                "content": str(row["content"]),
                "origin": str(row["origin"]),
                "createdAt": str(row["created_at"]),
            }
        )
    return {"conceptId": concept_id, **fields}


def _optional_text(value: Any) -> str | None:
    return None if value is None else str(value)
