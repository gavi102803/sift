from __future__ import annotations

import asyncio
import hashlib
import json
import secrets
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta
from typing import Any, Protocol
from urllib.parse import urlparse
from uuid import NAMESPACE_URL, uuid4, uuid5

from sift_worker.agent_core import (
    CONTINUITY_AGENT_SPEC,
    FOLLOW_UP_AGENT_SPEC,
    INITIAL_AGENT_SPEC,
    KNOWLEDGE_REVIEW_AGENT_SPEC,
    AgentControlError,
    AgentExecution,
    AgentSpec,
    agent_spec_from_snapshot,
    explicit_retrieval_required,
)
from sift_worker.errors import PublicError
from sift_worker.models import (
    AppendPatchOutput,
    ConceptHistoryTurnResponse,
    ConceptResponse,
    ConceptTurnResponse,
    ContinuitySummaryResult,
    CreateConceptRelationRequest,
    CreateConceptRunRequest,
    CreateTurnRunRequest,
    CurrentPrincipal,
    FollowUpResult,
    InitialConceptResult,
    IssuedSession,
    KnowledgeReviewResult,
    ModelRunEventResponse,
    ModelRunResponse,
    NoteBlockResponse,
    NoteRevisionResponse,
    NoteRevisionSummaryResponse,
    ProviderConnectionResponse,
    ReplacePatchOutput,
    UpdateConceptNoteRequest,
    UpdateConceptOrganizationRequest,
    UpdateConceptSummaryRequest,
    UpdateNoteBlockRequest,
    UpdateProposalResponse,
)
from sift_worker.runtime import (
    ProviderConnection,
    RuntimeToolCall,
    WorkerProviderClient,
    provider_supports_tools,
    validate_provider_connection,
)
from sift_worker.store import WorkerStore
from sift_worker.tools import web_tool_registry
from sift_worker.web_search import WorkerWebSearchClient

ACTIVE_RUN_STATUSES = {"queued", "waitingForCredential", "running"}
WEB_SEARCH_TIMEOUT_SECONDS = 12


class ProviderClientFactory(Protocol):
    def __call__(
        self,
        connection: ProviderConnection,
        api_key: str,
    ) -> WorkerProviderClient:
        ...


ModelRunEventSink = Callable[[ModelRunEventResponse], Awaitable[None]]
LiveDeltaSink = Callable[[str], Awaitable[None]]
AnswerStream = Callable[[LiveDeltaSink], Awaitable[str]]
ToolPlanner = Callable[
    [list[dict[str, Any]]], Awaitable[tuple[RuntimeToolCall, ...]]
]
RECOVERY_DELTA_CHARS = 256
TRANSIENT_STREAM_RETRY_CODES = {"provider_timeout", "provider_unreachable"}
RUN_LEASE_SECONDS = 60
RUN_LEASE_HEARTBEAT_SECONDS = 10
MAX_TOOL_PLANNER_ROUNDS = 2
MAX_RETRIEVAL_EVIDENCE_ITEMS = 8
MAX_TOOL_RESULT_ITEMS = 5
MAX_TOOL_TITLE_CHARS = 500
MAX_TOOL_URL_CHARS = 4_096
MAX_TOOL_SNIPPET_CHARS = 4_000


class AuthService:
    def __init__(
        self,
        store: WorkerStore,
        *,
        token_ttl_days: int = 30,
        clock: Callable[[], datetime] | None = None,
        token_factory: Callable[[], str] | None = None,
    ) -> None:
        self.store = store
        self.token_ttl_days = token_ttl_days
        self.clock = clock or (lambda: datetime.now(UTC))
        self.token_factory = token_factory or (lambda: secrets.token_urlsafe(32))

    async def activate(self, invite_code: str, installation_id: str) -> IssuedSession:
        code = invite_code.strip()
        installation = installation_id.strip()
        if not code or not installation:
            raise PublicError("invite_invalid", "The invite code is invalid.", 400)

        code_hash = _hash_secret(code)
        invite = await self.store.get_invite(code_hash)
        if invite is None or invite.get("revoked_at") is not None:
            raise PublicError("invite_invalid", "The invite code is invalid.", 400)
        if invite.get("installation_id") not in {None, installation}:
            raise PublicError("invite_consumed", "The invite code has already been used.", 409)

        owner_id = str(invite.get("owner_id") or uuid4())
        now = _as_utc(self.clock())
        expires_at = now + timedelta(days=self.token_ttl_days)
        token = self.token_factory()
        created = await self.store.activate_invite(
            code_hash=code_hash,
            owner_id=owner_id,
            installation_id=installation,
            session_id=str(uuid4()),
            token_hash=_hash_secret(token),
            expires_at=_utc_isoformat(expires_at),
            now=_utc_isoformat(now),
        )
        if created is None:
            raise PublicError("invite_consumed", "The invite code has already been used.", 409)
        return IssuedSession(
            token=token,
            owner_id=str(created["owner_id"]),
            expires_at=str(created["expires_at"]),
        )

    async def authenticate(self, token: str, installation_id: str) -> CurrentPrincipal:
        raw_token = token.strip()
        installation = installation_id.strip()
        if not raw_token or not installation:
            raise PublicError("authentication_required", "Beta activation is required.", 401)
        session = await self.store.get_session(_hash_secret(raw_token))
        if session is None:
            raise PublicError("authentication_required", "Beta activation is required.", 401)
        if session.get("revoked_at") is not None or await self.store.owner_is_revoked(
            str(session["owner_id"])
        ):
            raise PublicError("beta_token_revoked", "Beta access has been revoked.", 401)
        if _parse_utc(str(session["expires_at"])) <= _as_utc(self.clock()):
            raise PublicError("beta_token_expired", "Beta access has expired.", 401)
        if session["installation_id"] != installation:
            raise PublicError("beta_token_revoked", "Beta access is not valid on this device.", 401)
        return CurrentPrincipal(
            owner_id=str(session["owner_id"]),
            installation_id=installation,
        )

    async def refresh(self, token: str, installation_id: str) -> IssuedSession:
        principal = await self.authenticate(token, installation_id)
        now = _as_utc(self.clock())
        expires_at = now + timedelta(days=self.token_ttl_days)
        replacement = self.token_factory()
        stored = await self.store.rotate_session(
            current_token_hash=_hash_secret(token.strip()),
            session_id=str(uuid4()),
            token_hash=_hash_secret(replacement),
            expires_at=_utc_isoformat(expires_at),
            now=_utc_isoformat(now),
        )
        if stored is None:
            raise PublicError(
                "authentication_required",
                "Beta activation is required.",
                401,
            )
        return IssuedSession(
            token=replacement,
            owner_id=principal.owner_id,
            expires_at=str(stored["expires_at"]),
        )


class ProviderConnectionService:
    def __init__(
        self,
        store: WorkerStore,
        *,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self.store = store
        self.clock = clock or (lambda: datetime.now(UTC))

    async def get(self, owner_id: str) -> ProviderConnection:
        row = await self.store.get_provider_connection(owner_id)
        if row is None:
            raise PublicError(
                "provider_not_configured",
                "Connect an AI provider before continuing.",
                404,
            )
        return _provider_connection(row)

    async def save(
        self,
        owner_id: str,
        provider_id: str,
        base_url: str | None,
        model: str,
        *,
        allow_local_http: bool = False,
    ) -> ProviderConnection:
        connection = validate_provider_connection(
            owner_id,
            provider_id,
            base_url,
            model,
            allow_local_http=allow_local_http,
        )
        now = _utc_isoformat(self.clock())
        row = await self.store.save_provider_connection(
            {
                "owner_id": owner_id,
                "provider_id": connection.provider_id,
                "base_url": connection.base_url,
                "model": connection.model,
                "created_at": now,
                "updated_at": now,
            }
        )
        return _provider_connection(row)

    @staticmethod
    def response(connection: ProviderConnection) -> ProviderConnectionResponse:
        return ProviderConnectionResponse(
            providerId=connection.provider_id,
            baseURL=connection.base_url,
            model=connection.model,
        )


class ModelRunService:
    def __init__(
        self,
        store: WorkerStore,
        *,
        clock: Callable[[], datetime] | None = None,
        web_search_client: WorkerWebSearchClient | None = None,
    ) -> None:
        self.store = store
        self.clock = clock or (lambda: datetime.now(UTC))
        self.web_search_client = web_search_client

    async def _claim_execution(
        self,
        run_id: str,
        owner_id: str,
    ) -> tuple[dict[str, Any] | None, bool, str]:
        worker_id = str(uuid4())
        now = self.clock()
        claimed, did_claim = await self.store.claim_model_run(
            run_id,
            owner_id,
            now=_utc_isoformat(now),
            worker_id=worker_id,
            lease_expires_at=_utc_isoformat(now + timedelta(seconds=RUN_LEASE_SECONDS)),
        )
        return claimed, did_claim, worker_id

    def _start_lease_heartbeat(
        self,
        run_id: str,
        owner_id: str,
        worker_id: str,
    ) -> asyncio.Task[None]:
        owner_task = asyncio.current_task()
        assert owner_task is not None

        async def heartbeat() -> None:
            while True:
                await asyncio.sleep(RUN_LEASE_HEARTBEAT_SECONDS)
                now = self.clock()
                renewed = await self.store.renew_model_run_lease(
                    run_id,
                    owner_id,
                    worker_id=worker_id,
                    lease_expires_at=_utc_isoformat(
                        now + timedelta(seconds=RUN_LEASE_SECONDS)
                    ),
                    now=_utc_isoformat(now),
                )
                if not renewed:
                    owner_task.cancel()
                    return

        return asyncio.create_task(heartbeat())

    @staticmethod
    async def _stop_lease_heartbeat(task: asyncio.Task[None]) -> None:
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

    def _agent_execution(
        self,
        *,
        run_id: str,
        owner_id: str,
        worker_id: str,
        kind: str,
        run: dict[str, Any],
        event_sink: ModelRunEventSink | None,
    ) -> AgentExecution:
        async def emit(event_type: str, data: dict[str, Any]) -> None:
            now = _utc_isoformat(self.clock())
            update_step = event_type in {"stepStarted", "stepCompleted"}
            sequence = await self.store.record_agent_event(
                run_id,
                owner_id,
                worker_id=worker_id,
                event_type=event_type,
                data_json=json.dumps(data, ensure_ascii=False, separators=(",", ":")),
                now=now,
                current_step=data.get("step") if event_type == "stepStarted" else None,
                update_current_step=update_step,
                model_call_count=(
                    int(data["modelCalls"]) if event_type == "budgetUpdated" else None
                ),
                tool_call_count=(
                    int(data["toolCalls"]) if event_type == "budgetUpdated" else None
                ),
                step_count=(
                    int(data["stepCount"])
                    if event_type in {"stepStarted", "stepRestarted"}
                    else None
                ),
                model_latency_ms=(
                    int(data["latencyMs"])
                    if event_type == "modelCallCompleted"
                    else None
                ),
                input_token_count=(
                    int(data["inputTokens"])
                    if event_type == "modelCallCompleted"
                    and data.get("inputTokens") is not None
                    else None
                ),
                output_token_count=(
                    int(data["outputTokens"])
                    if event_type == "modelCallCompleted"
                    and data.get("outputTokens") is not None
                    else None
                ),
            )
            if sequence is None:
                cancelled = await self.store.model_run_is_cancelled(
                    run_id,
                    owner_id,
                    worker_id=worker_id,
                )
                code = "agent_cancelled" if cancelled else "agent_lease_lost"
                raise AgentControlError(code, "The agent run no longer owns execution.")
            if event_sink is not None:
                await event_sink(
                    ModelRunEventResponse(
                        sequence=sequence,
                        type=event_type,
                        data=data,
                        createdAt=now,
                    )
                )

        async def cancelled() -> bool:
            return await self.store.model_run_is_cancelled(
                run_id,
                owner_id,
                worker_id=worker_id,
            )

        spec = agent_spec_from_snapshot(
            kind,
            name=str(run.get("agent_spec") or ""),
            version=str(run.get("agent_spec_version") or ""),
            prompt_version=str(run.get("prompt_version") or ""),
            budget=_json_object(run.get("budget_json")),
            tool_contract_hash=str(run.get("tool_contract_hash") or ""),
        )
        return AgentExecution(
            spec,
            emit,
            cancellation_probe=cancelled,
            model_calls=int(run.get("model_call_count") or 0),
            tool_calls=int(run.get("tool_call_count") or 0),
            steps=int(run.get("step_count") or 0),
            current_step=_optional_str(run.get("current_step")),
            model_latency_ms=int(run.get("model_latency_ms") or 0),
            input_tokens=int(run.get("input_token_count") or 0),
            output_tokens=int(run.get("output_token_count") or 0),
        )

    async def _checkpoint(
        self,
        *,
        run_id: str,
        owner_id: str,
        worker_id: str,
        name: str,
        data: dict[str, Any],
    ) -> None:
        saved = await self.store.checkpoint_model_run(
            run_id,
            owner_id,
            worker_id=worker_id,
            checkpoint=name,
            checkpoint_json=json.dumps(data, ensure_ascii=False, separators=(",", ":")),
            now=_utc_isoformat(self.clock()),
        )
        if not saved:
            cancelled = await self.store.model_run_is_cancelled(
                run_id,
                owner_id,
                worker_id=worker_id,
            )
            code = "agent_cancelled" if cancelled else "agent_lease_lost"
            raise AgentControlError(code, "The agent run could not save its checkpoint.")

    async def _provider_connection_for_run(
        self,
        *,
        run: dict[str, Any],
        owner_id: str,
        worker_id: str,
        fallback: ProviderConnection | None = None,
    ) -> ProviderConnection:
        snapshot = _provider_connection_from_snapshot(
            owner_id,
            run.get("provider_snapshot_json"),
        )
        if snapshot is not None:
            return snapshot

        connection = fallback or await ProviderConnectionService(self.store).get(owner_id)
        snapshot_json = _provider_snapshot_json(connection)
        saved = await self.store.snapshot_model_run_provider(
            str(run["id"]),
            owner_id,
            worker_id=worker_id,
            provider_snapshot_json=snapshot_json,
            now=_utc_isoformat(self.clock()),
        )
        if not saved:
            cancelled = await self.store.model_run_is_cancelled(
                str(run["id"]),
                owner_id,
                worker_id=worker_id,
            )
            code = "agent_cancelled" if cancelled else "agent_lease_lost"
            raise AgentControlError(code, "The agent run could not freeze its provider.")
        run["provider_snapshot_json"] = snapshot_json
        return connection

    @staticmethod
    def _checkpoint_data(run: dict[str, Any]) -> tuple[str | None, dict[str, Any]]:
        name = _optional_str(run.get("checkpoint"))
        data = _json_object(run.get("checkpoint_json"))
        return name, data

    async def submit_initial(
        self,
        principal: CurrentPrincipal,
        payload: CreateConceptRunRequest,
        *,
        idempotency_key: str | None,
        has_provider_credential: bool,
    ) -> tuple[ModelRunResponse, bool]:
        canonical_payload = json.dumps(
            payload.model_dump(mode="json", by_alias=True),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        now = _utc_isoformat(self.clock())
        run_id = str(uuid4())
        key = idempotency_key.strip() if idempotency_key else str(uuid4())
        status = "queued" if has_provider_credential else "waitingForCredential"
        run = {
            "id": run_id,
            "owner_id": principal.owner_id,
            "kind": "initialConcept",
            "status": status,
            "concept_id": run_id,
            "client_draft_id": payload.client_draft_id,
            "idempotency_key": key,
            "payload_hash": hashlib.sha256(canonical_payload.encode()).hexdigest(),
            "payload_json": canonical_payload,
            "provider_snapshot_json": "{}",
            "agent_spec": INITIAL_AGENT_SPEC.name,
            "agent_spec_version": INITIAL_AGENT_SPEC.version,
            "prompt_version": INITIAL_AGENT_SPEC.prompt_version,
            "budget_json": json.dumps(INITIAL_AGENT_SPEC.budget(), separators=(",", ":")),
            "tool_contract_hash": INITIAL_AGENT_SPEC.tool_contract_hash,
            "current_step": None,
            "model_call_count": 0,
            "tool_call_count": 0,
            "termination_reason": None,
            "dependency_run_id": None,
            "checkpoint": None,
            "checkpoint_json": None,
            "result_json": None,
            "result_ref": None,
            "error_code": None,
            "error_message": None,
            "created_at": now,
            "updated_at": now,
        }
        event = {
            "run_id": run_id,
            "sequence": 1,
            "event_type": "checkpoint" if has_provider_credential else "waitingForCredential",
            "data_json": json.dumps({"status": status}, separators=(",", ":")),
            "created_at": now,
        }
        pending_concept = _pending_concept_record(
            concept_id=run_id,
            raw_capture=payload.capture.raw_capture,
            now=now,
        )
        stored, created = await self.store.create_model_run(
            run=run,
            event=event,
            pending_concept=pending_concept,
            input_turn=_input_turn_record(
                run_id=run_id,
                concept_id=run_id,
                operation_key=key,
                content=payload.capture.raw_capture,
                now=now,
            ),
        )
        if stored["payload_hash"] != run["payload_hash"]:
            raise PublicError(
                "idempotency_payload_conflict",
                "Idempotency key was already used with a different payload.",
                409,
            )
        return _model_run_response(stored), created

    async def submit_follow_up(
        self,
        principal: CurrentPrincipal,
        concept_id: str,
        payload: CreateTurnRunRequest,
        *,
        idempotency_key: str | None,
        has_provider_credential: bool,
    ) -> tuple[ModelRunResponse, bool]:
        if await self.store.get_concept(concept_id, principal.owner_id) is None:
            raise PublicError("owner_scope_not_found", "Resource not found.", 404)
        canonical_payload = json.dumps(
            payload.model_dump(mode="json", by_alias=True),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        now = _utc_isoformat(self.clock())
        run_id = str(uuid4())
        key = idempotency_key.strip() if idempotency_key else str(uuid4())
        status = "queued" if has_provider_credential else "waitingForCredential"
        run = {
            "id": run_id,
            "owner_id": principal.owner_id,
            "kind": "followUp",
            "status": status,
            "concept_id": concept_id,
            "client_draft_id": None,
            "idempotency_key": key,
            "payload_hash": hashlib.sha256(canonical_payload.encode()).hexdigest(),
            "payload_json": canonical_payload,
            "provider_snapshot_json": "{}",
            "agent_spec": FOLLOW_UP_AGENT_SPEC.name,
            "agent_spec_version": FOLLOW_UP_AGENT_SPEC.version,
            "prompt_version": FOLLOW_UP_AGENT_SPEC.prompt_version,
            "budget_json": json.dumps(FOLLOW_UP_AGENT_SPEC.budget(), separators=(",", ":")),
            "tool_contract_hash": FOLLOW_UP_AGENT_SPEC.tool_contract_hash,
            "current_step": None,
            "model_call_count": 0,
            "tool_call_count": 0,
            "termination_reason": None,
            "dependency_run_id": None,
            "checkpoint": None,
            "checkpoint_json": None,
            "result_json": None,
            "result_ref": None,
            "error_code": None,
            "error_message": None,
            "created_at": now,
            "updated_at": now,
        }
        event = {
            "run_id": run_id,
            "sequence": 1,
            "event_type": "checkpoint" if has_provider_credential else "waitingForCredential",
            "data_json": json.dumps({"status": status}, separators=(",", ":")),
            "created_at": now,
        }
        stored, created = await self.store.create_model_run(
            run=run,
            event=event,
        )
        if stored["payload_hash"] != run["payload_hash"]:
            raise PublicError(
                "idempotency_payload_conflict",
                "Idempotency key was already used with a different payload.",
                409,
            )
        return _model_run_response(stored), created

    async def execute_initial(
        self,
        run_id: str,
        principal: CurrentPrincipal,
        api_key: str,
        *,
        web_provider_key: str = "",
        client_factory: ProviderClientFactory | None = None,
        event_sink: ModelRunEventSink | None = None,
        live_delta_sink: LiveDeltaSink | None = None,
    ) -> ModelRunResponse:
        if not api_key.strip():
            return await self.get(run_id, principal.owner_id)

        claimed, did_claim, worker_id = await self._claim_execution(
            run_id,
            principal.owner_id,
        )
        if claimed is None:
            raise PublicError("owner_scope_not_found", "Resource not found.", 404)
        if not did_claim:
            return _model_run_response(claimed)

        heartbeat = self._start_lease_heartbeat(run_id, principal.owner_id, worker_id)
        execution = self._agent_execution(
            run_id=run_id,
            owner_id=principal.owner_id,
            worker_id=worker_id,
            kind="initialConcept",
            run=claimed,
            event_sink=event_sink,
        )
        try:
            connection = await self._provider_connection_for_run(
                run=claimed,
                owner_id=principal.owner_id,
                worker_id=worker_id,
            )
            payload = CreateConceptRunRequest.model_validate(
                json.loads(str(claimed["payload_json"]))
            )
            factory = client_factory or WorkerProviderClient
            client = factory(connection, api_key)
            _bind_model_call_observer(
                client,
                execution.model_call_started,
                execution.model_call_completed,
            )
            web_settings = await self.store.get_web_provider_settings(principal.owner_id)
            checkpoint_name, checkpoint_data = self._checkpoint_data(claimed)
            evidence = _checkpoint_evidence(checkpoint_data)
            if checkpoint_name in {None, "retrievalInProgress"}:
                await execution.start_step("retrieval", "Checking whether research is needed")
                evidence, checkpoint_data = await self._run_web_tool_loop(
                    run_id=run_id,
                    owner_id=principal.owner_id,
                    worker_id=worker_id,
                    request=payload.capture.raw_capture,
                    provider_id=connection.provider_id,
                    planner=lambda observations: client.request_initial_tool_calls(
                        payload.capture.raw_capture,
                        payload.capture.locale,
                        tool_observations=observations,
                    ),
                    checkpoint_data=checkpoint_data,
                    web_settings=web_settings,
                    web_provider_key=web_provider_key,
                    event_sink=event_sink,
                    execution=execution,
                )
                checkpoint_name = "retrievalCompleted"

            answer = str(checkpoint_data.get("answer") or "").strip()
            if checkpoint_name not in {"answerCompleted", "modelCompleted"}:
                await execution.start_step("answer", "Writing first answer")
                if checkpoint_name == "answerStreaming":
                    await self._emit(
                        run_id,
                        principal.owner_id,
                        "deltaReset",
                        {"reason": "restarted"},
                        event_sink,
                        worker_id,
                    )
                if evidence:
                    await self._emit(
                        run_id,
                        principal.owner_id,
                        "sourcesReady",
                        {"citations": _evidence_citations(evidence)},
                        event_sink,
                        worker_id,
                    )
                await self._checkpoint(
                    run_id=run_id,
                    owner_id=principal.owner_id,
                    worker_id=worker_id,
                    name="answerStreaming",
                    data={"evidence": evidence},
                )
                answer = await self._stream_answer(
                    run_id,
                    principal.owner_id,
                    lambda on_delta: client.stream_initial_answer(
                        payload.capture.raw_capture,
                        payload.capture.locale,
                        evidence,
                        on_delta,
                    ),
                    event_sink,
                    live_delta_sink,
                    worker_id=worker_id,
                    execution=execution,
                )
                checkpoint_data = {"evidence": evidence, "answer": answer}
                await self._checkpoint(
                    run_id=run_id,
                    owner_id=principal.owner_id,
                    worker_id=worker_id,
                    name="answerCompleted",
                    data=checkpoint_data,
                )
                checkpoint_name = "answerCompleted"

            if checkpoint_name == "modelCompleted":
                result = InitialConceptResult.model_validate(checkpoint_data["modelResult"])
            else:
                await execution.start_step("structure", "Building card")
                result = await client.generate_initial_concept(
                    payload.capture.raw_capture,
                    payload.capture.locale,
                    answer=answer,
                    retrieval_evidence=evidence,
                )
                checkpoint_data = {
                    "evidence": evidence,
                    "answer": answer,
                    "modelResult": result.model_dump(mode="json", by_alias=True),
                }
                await self._checkpoint(
                    run_id=run_id,
                    owner_id=principal.owner_id,
                    worker_id=worker_id,
                    name="modelCompleted",
                    data=checkpoint_data,
                )
            concept, blocks, tags, topics, revision, turns = _initial_concept_records(
                run=claimed,
                payload=payload,
                result=result,
                now=_utc_isoformat(self.clock()),
                evidence=evidence,
            )
            sources = _source_records(
                evidence,
                result.answer_source.citations,
                now=_utc_isoformat(self.clock()),
            )
            document = json.loads(str(concept["document_json"]))
            result_json = json.dumps(
                {"concept": document},
                ensure_ascii=False,
                separators=(",", ":"),
            )
            await execution.start_step("commit", "Saving card")
            completed = await self.store.complete_initial_run(
                run_id=run_id,
                owner_id=principal.owner_id,
                worker_id=worker_id,
                concept=concept,
                blocks=blocks,
                tags=tags,
                topics=topics,
                revision=revision,
                turns=turns,
                sources=sources,
                provider_snapshot_json=_provider_snapshot_json(connection),
                result_json=result_json,
                now=_utc_isoformat(self.clock()),
                model_call_count=execution.model_calls,
                tool_call_count=execution.tool_calls,
            )
        except AgentControlError as error:
            if error.code != "agent_cancelled":
                await self.store.fail_model_run(
                    run_id,
                    principal.owner_id,
                    worker_id=worker_id,
                    code=error.code,
                    message=error.message,
                    now=_utc_isoformat(self.clock()),
                )
            raise PublicError(error.code, error.message, 409) from error
        except asyncio.CancelledError as error:
            cancelled = await self.store.model_run_is_cancelled(
                run_id,
                principal.owner_id,
                worker_id=worker_id,
            )
            code = "agent_cancelled" if cancelled else "agent_lease_lost"
            if not cancelled:
                await self.store.fail_model_run(
                    run_id,
                    principal.owner_id,
                    worker_id=worker_id,
                    code=code,
                    message="The agent run stopped safely.",
                    now=_utc_isoformat(self.clock()),
                )
            raise PublicError(code, "The agent run stopped safely.", 409) from error
        except PublicError as error:
            await self.store.fail_model_run(
                run_id,
                principal.owner_id,
                worker_id=worker_id,
                code=error.code,
                message=error.message,
                now=_utc_isoformat(self.clock()),
            )
            raise
        except Exception as error:
            safe = PublicError(
                "backend_unavailable",
                "Sift is temporarily unavailable.",
                503,
            )
            await self.store.fail_model_run(
                run_id,
                principal.owner_id,
                worker_id=worker_id,
                code=safe.code,
                message=safe.message,
                now=_utc_isoformat(self.clock()),
            )
            raise safe from error
        finally:
            await self._stop_lease_heartbeat(heartbeat)
        if completed is None or completed["status"] != "succeeded":
            raise PublicError("request_conflict", "The model run could not be completed.", 409)
        return _model_run_response(completed)

    async def execute_follow_up(
        self,
        run_id: str,
        principal: CurrentPrincipal,
        api_key: str,
        *,
        web_provider_key: str = "",
        client_factory: ProviderClientFactory | None = None,
        event_sink: ModelRunEventSink | None = None,
        live_delta_sink: LiveDeltaSink | None = None,
        run_maintenance: bool = True,
    ) -> ModelRunResponse:
        if not api_key.strip():
            return await self.get(run_id, principal.owner_id)
        claimed, did_claim, worker_id = await self._claim_execution(
            run_id,
            principal.owner_id,
        )
        if claimed is None:
            raise PublicError("owner_scope_not_found", "Resource not found.", 404)
        if not did_claim:
            return _model_run_response(claimed)
        if claimed["kind"] != "followUp" or not claimed.get("concept_id"):
            await self.store.fail_model_run(
                run_id,
                principal.owner_id,
                worker_id=worker_id,
                code="request_conflict",
                message="The model run kind is not supported by this operation.",
                now=_utc_isoformat(self.clock()),
            )
            raise PublicError("request_conflict", "The model run cannot be resumed.", 409)

        heartbeat = self._start_lease_heartbeat(run_id, principal.owner_id, worker_id)
        execution = self._agent_execution(
            run_id=run_id,
            owner_id=principal.owner_id,
            worker_id=worker_id,
            kind="followUp",
            run=claimed,
            event_sink=event_sink,
        )
        try:
            connection = await self._provider_connection_for_run(
                run=claimed,
                owner_id=principal.owner_id,
                worker_id=worker_id,
            )
            payload = CreateTurnRunRequest.model_validate(
                json.loads(str(claimed["payload_json"]))
            )
            concept_row = await self.store.get_concept(
                str(claimed["concept_id"]),
                principal.owner_id,
            )
            turn_rows = await self.store.list_concept_turns(
                str(claimed["concept_id"]),
                principal.owner_id,
            )
            if concept_row is None or turn_rows is None:
                raise PublicError("owner_scope_not_found", "Resource not found.", 404)
            replacement = payload.turn.replacing_turn_index
            if replacement is not None and (
                replacement >= len(turn_rows)
                or str(turn_rows[replacement]["role"]) != "user"
            ):
                raise PublicError(
                    "invalid_turn_replacement",
                    "Turn is not replaceable.",
                    409,
                )
            factory = client_factory or WorkerProviderClient
            checkpoint_name, checkpoint_data = self._checkpoint_data(claimed)
            if replacement == 0:
                client = factory(connection, api_key)
                _bind_model_call_observer(
                    client,
                    execution.model_call_started,
                    execution.model_call_completed,
                )
                answer = str(checkpoint_data.get("answer") or "").strip()
                if checkpoint_name not in {"answerCompleted", "modelCompleted"}:
                    await execution.start_step("answer", "Writing first answer")
                    if checkpoint_name == "answerStreaming":
                        await self._emit(
                            run_id,
                            principal.owner_id,
                            "deltaReset",
                            {"reason": "restarted"},
                            event_sink,
                            worker_id,
                        )
                    await self._checkpoint(
                        run_id=run_id,
                        owner_id=principal.owner_id,
                        worker_id=worker_id,
                        name="answerStreaming",
                        data={},
                    )
                    answer = await self._stream_answer(
                        run_id,
                        principal.owner_id,
                        lambda on_delta: client.stream_initial_answer(
                            payload.turn.question.strip(),
                            "en",
                            [],
                            on_delta,
                        ),
                        event_sink,
                        live_delta_sink,
                        worker_id=worker_id,
                        execution=execution,
                    )
                    checkpoint_data = {"answer": answer}
                    await self._checkpoint(
                        run_id=run_id,
                        owner_id=principal.owner_id,
                        worker_id=worker_id,
                        name="answerCompleted",
                        data=checkpoint_data,
                    )
                    checkpoint_name = "answerCompleted"
                if checkpoint_name == "modelCompleted":
                    regenerated = InitialConceptResult.model_validate(
                        checkpoint_data["modelResult"]
                    )
                else:
                    await execution.start_step("structure", "Rebuilding card")
                    regenerated = await client.generate_initial_concept(
                        payload.turn.question.strip(),
                        "en",
                        answer=answer,
                    )
                    checkpoint_data = {
                        "answer": answer,
                        "modelResult": regenerated.model_dump(mode="json", by_alias=True),
                    }
                    await self._checkpoint(
                        run_id=run_id,
                        owner_id=principal.owner_id,
                        worker_id=worker_id,
                        name="modelCompleted",
                        data=checkpoint_data,
                    )
                (
                    concept_record,
                    block_records,
                    tags,
                    topics,
                    revision,
                    replacement_turns,
                    concept,
                ) = _regenerated_concept_records(
                    current=ConceptResponse.model_validate(concept_row),
                    result=regenerated,
                    operation_key=str(claimed["idempotency_key"]),
                    question=payload.turn.question.strip(),
                    now=_utc_isoformat(self.clock()),
                )
                response = ConceptTurnResponse(
                    answer=regenerated.answer.strip(),
                    answerSource=regenerated.answer_source,
                    updateMode="none",
                    concept=concept,
                    proposal=None,
                )
                result_json = json.dumps(
                    {"response": response.model_dump(mode="json", by_alias=True)},
                    ensure_ascii=False,
                    separators=(",", ":"),
                )
                await execution.start_step("commit", "Saving rebuilt card")
                completed = await self.store.complete_regenerated_follow_up_run(
                    run_id=run_id,
                    owner_id=principal.owner_id,
                    worker_id=worker_id,
                    expected_revision=int(concept_row["noteRevision"]),
                    concept=concept_record,
                    blocks=block_records,
                    tags=tags,
                    topics=topics,
                    revision=revision,
                    turns=replacement_turns,
                    provider_snapshot_json=_provider_snapshot_json(connection),
                    result_json=result_json,
                    now=_utc_isoformat(self.clock()),
                    model_call_count=execution.model_calls,
                    tool_call_count=execution.tool_calls,
                )
                if completed is None or completed["status"] != "succeeded":
                    raise PublicError(
                        "concept_revision_changed",
                        "The card changed after model generation; start a new follow-up.",
                        409,
                    )
                return _model_run_response(completed)
            recent_rows = (
                turn_rows[-10:]
                if replacement is None
                else turn_rows[:replacement][-10:]
            )
            continuity = await self.store.get_continuity_summary(
                str(claimed["concept_id"]),
                principal.owner_id,
            )
            recent_turns = [
                {"role": str(row["role"]), "content": str(row["content"])}
                for row in recent_rows
            ]
            continuity_summary = (
                str(continuity["summary"]) if continuity is not None else ""
            )
            client = factory(connection, api_key)
            _bind_model_call_observer(
                client,
                execution.model_call_started,
                execution.model_call_completed,
            )
            web_settings = await self.store.get_web_provider_settings(
                principal.owner_id
            )
            evidence = _checkpoint_evidence(checkpoint_data)
            if checkpoint_name not in {
                "retrievalCompleted",
                "answerStreaming",
                "answerCompleted",
                "modelCompleted",
            }:
                await execution.start_step(
                    "retrieval", "Checking whether research is needed"
                )
                evidence, checkpoint_data = await self._run_web_tool_loop(
                    run_id=run_id,
                    owner_id=principal.owner_id,
                    worker_id=worker_id,
                    request=payload.turn.question,
                    provider_id=connection.provider_id,
                    planner=lambda observations: client.request_follow_up_tool_calls(
                        concept_row,
                        payload.turn.question.strip(),
                        recent_turns,
                        continuity_summary,
                        tool_observations=observations,
                    ),
                    checkpoint_data=checkpoint_data,
                    web_settings=web_settings,
                    web_provider_key=web_provider_key,
                    event_sink=event_sink,
                    execution=execution,
                )
                checkpoint_name = "retrievalCompleted"

            answer = str(checkpoint_data.get("answer") or "").strip()
            if checkpoint_name not in {"answerCompleted", "modelCompleted"}:
                await execution.start_step("answer", "Writing answer")
                if checkpoint_name == "answerStreaming":
                    await self._emit(
                        run_id,
                        principal.owner_id,
                        "deltaReset",
                        {"reason": "restarted"},
                        event_sink,
                        worker_id,
                    )
                if evidence:
                    await self._emit(
                        run_id,
                        principal.owner_id,
                        "sourcesReady",
                        {"citations": _evidence_citations(evidence)},
                        event_sink,
                        worker_id,
                    )
                await self._checkpoint(
                    run_id=run_id,
                    owner_id=principal.owner_id,
                    worker_id=worker_id,
                    name="answerStreaming",
                    data={"evidence": evidence},
                )
                answer = await self._stream_answer(
                    run_id,
                    principal.owner_id,
                    lambda on_delta: client.stream_follow_up_answer(
                        concept_row,
                        payload.turn.question.strip(),
                        recent_turns,
                        evidence,
                        continuity_summary,
                        on_delta,
                    ),
                    event_sink,
                    live_delta_sink,
                    worker_id=worker_id,
                    execution=execution,
                )
                checkpoint_data = {"evidence": evidence, "answer": answer}
                await self._checkpoint(
                    run_id=run_id,
                    owner_id=principal.owner_id,
                    worker_id=worker_id,
                    name="answerCompleted",
                    data=checkpoint_data,
                )
                checkpoint_name = "answerCompleted"
            if checkpoint_name == "modelCompleted":
                result = FollowUpResult.model_validate(checkpoint_data["modelResult"])
            else:
                await execution.start_step("structure", "Checking card update")
                result = await client.generate_follow_up(
                    concept_row,
                    payload.turn.question.strip(),
                    recent_turns,
                    evidence,
                    continuity_summary,
                    answer=answer,
                )
                checkpoint_data = {
                    "evidence": evidence,
                    "answer": answer,
                    "modelResult": result.model_dump(mode="json", by_alias=True),
                }
                await self._checkpoint(
                    run_id=run_id,
                    owner_id=principal.owner_id,
                    worker_id=worker_id,
                    name="modelCompleted",
                    data=checkpoint_data,
                )
            concept = ConceptResponse.model_validate(concept_row)
            proposal_record, proposal_response = await self._follow_up_proposal(
                run_id,
                principal.owner_id,
                concept,
                result.proposal,
            )
            response = ConceptTurnResponse(
                answer=result.answer.strip(),
                answerSource=result.answer_source,
                updateMode="none",
                concept=concept,
                proposal=(
                    proposal_response.model_dump(mode="json", by_alias=True)
                    if proposal_response is not None
                    else None
                ),
            )
            result_json = json.dumps(
                {"response": response.model_dump(mode="json", by_alias=True)},
                ensure_ascii=False,
                separators=(",", ":"),
            )
            operation_key = str(claimed["idempotency_key"])
            sources = _source_records(
                evidence,
                result.answer_source.citations,
                now=_utc_isoformat(self.clock()),
            )
            await execution.start_step("commit", "Saving answer")
            completed = await self.store.complete_follow_up_run(
                run_id=run_id,
                owner_id=principal.owner_id,
                worker_id=worker_id,
                concept_id=concept.id,
                replacing_turn_index=replacement,
                turns=[
                    {
                        "id": str(uuid4()),
                        "operation_key": operation_key,
                        "role": "user",
                        "content": payload.turn.question.strip(),
                        "answer_source_json": None,
                        "created_at": _utc_isoformat(self.clock()),
                    },
                    {
                        "id": str(uuid4()),
                        "operation_key": operation_key,
                        "role": "assistant",
                        "content": result.answer.strip(),
                        "answer_source_json": json.dumps(
                            result.answer_source.model_dump(
                                mode="json",
                                by_alias=True,
                            ),
                            ensure_ascii=False,
                            separators=(",", ":"),
                        ),
                        "created_at": _utc_isoformat(self.clock()),
                    },
                ],
                proposal=proposal_record,
                sources=sources,
                provider_snapshot_json=_provider_snapshot_json(connection),
                result_json=result_json,
                now=_utc_isoformat(self.clock()),
                model_call_count=execution.model_calls,
                tool_call_count=execution.tool_calls,
            )
        except AgentControlError as error:
            if error.code != "agent_cancelled":
                await self.store.fail_model_run(
                    run_id,
                    principal.owner_id,
                    worker_id=worker_id,
                    code=error.code,
                    message=error.message,
                    now=_utc_isoformat(self.clock()),
                )
            raise PublicError(error.code, error.message, 409) from error
        except asyncio.CancelledError as error:
            cancelled = await self.store.model_run_is_cancelled(
                run_id,
                principal.owner_id,
                worker_id=worker_id,
            )
            code = "agent_cancelled" if cancelled else "agent_lease_lost"
            if not cancelled:
                await self.store.fail_model_run(
                    run_id,
                    principal.owner_id,
                    worker_id=worker_id,
                    code=code,
                    message="The agent run stopped safely.",
                    now=_utc_isoformat(self.clock()),
                )
            raise PublicError(code, "The agent run stopped safely.", 409) from error
        except PublicError as error:
            await self.store.fail_model_run(
                run_id,
                principal.owner_id,
                worker_id=worker_id,
                code=error.code,
                message=error.message,
                now=_utc_isoformat(self.clock()),
            )
            raise
        except Exception as error:
            safe = PublicError(
                "backend_unavailable",
                "Sift is temporarily unavailable.",
                503,
            )
            await self.store.fail_model_run(
                run_id,
                principal.owner_id,
                worker_id=worker_id,
                code=safe.code,
                message=safe.message,
                now=_utc_isoformat(self.clock()),
            )
            raise safe from error
        finally:
            await self._stop_lease_heartbeat(heartbeat)
        if completed is None or completed["status"] != "succeeded":
            raise PublicError("request_conflict", "The model run could not be completed.", 409)
        if run_maintenance:
            await self._run_due_maintenance(
                parent_run_id=run_id,
                owner_id=principal.owner_id,
                concept_id=str(completed["concept_id"]),
                connection=connection,
                api_key=api_key,
                client_factory=factory,
            )
        refreshed = await self.store.get_model_run(run_id, principal.owner_id)
        return _model_run_response(refreshed or completed)

    async def run_due_maintenance_for_follow_up(
        self,
        run_id: str,
        owner_id: str,
        api_key: str,
        *,
        client_factory: ProviderClientFactory | None = None,
    ) -> None:
        if not api_key.strip():
            return
        run = await self.store.get_model_run(run_id, owner_id)
        if (
            run is None
            or run.get("kind") != "followUp"
            or run.get("status") != "succeeded"
            or not run.get("concept_id")
        ):
            return
        connection = _provider_connection_from_snapshot(
            owner_id,
            run.get("provider_snapshot_json"),
        )
        if connection is None:
            return
        await self._run_due_maintenance(
            parent_run_id=run_id,
            owner_id=owner_id,
            concept_id=str(run["concept_id"]),
            connection=connection,
            api_key=api_key,
            client_factory=client_factory or WorkerProviderClient,
        )

    async def _run_due_maintenance(
        self,
        *,
        parent_run_id: str,
        owner_id: str,
        concept_id: str,
        connection: ProviderConnection,
        api_key: str,
        client_factory: ProviderClientFactory,
    ) -> None:
        status = await self.store.get_maintenance_status(concept_id, owner_id)
        if status is None:
            return
        turn_count = int(status.get("turn_count") or 0)
        user_turn_count = int(status.get("user_turn_count") or 0)
        summarized = int(status.get("summarized_turn_count") or 0)
        reviewed = int(status.get("reviewed_user_turn_count") or 1)
        summary_due = turn_count >= 12 and (summarized == 0 or turn_count - summarized >= 6)
        review_due = user_turn_count - reviewed >= 5
        if summary_due:
            await self._run_continuity_summary(
                parent_run_id,
                owner_id,
                concept_id,
                turn_count,
                connection,
                api_key,
                client_factory,
            )
        if review_due and not bool(status.get("has_pending_proposal")):
            await self._run_knowledge_review(
                parent_run_id,
                owner_id,
                concept_id,
                user_turn_count,
                connection,
                api_key,
                client_factory,
            )

    async def _run_continuity_summary(
        self,
        parent_run_id: str,
        owner_id: str,
        concept_id: str,
        turn_count: int,
        connection: ProviderConnection,
        api_key: str,
        client_factory: ProviderClientFactory,
    ) -> None:
        run, _created = await self._create_maintenance_run(
            owner_id=owner_id,
            concept_id=concept_id,
            parent_run_id=parent_run_id,
            kind="continuitySummary",
            idempotency_key=f"summary:{concept_id}:{turn_count}",
            agent_spec=CONTINUITY_AGENT_SPEC,
            connection=connection,
        )
        if run["status"] == "succeeded":
            return
        worker_id: str | None = None
        heartbeat: asyncio.Task[None] | None = None
        try:
            claimed, did_claim, worker_id = await self._claim_execution(
                str(run["id"]),
                owner_id,
            )
            if not did_claim or claimed is None:
                return
            heartbeat = self._start_lease_heartbeat(str(run["id"]), owner_id, worker_id)
            maintenance_connection = await self._provider_connection_for_run(
                run=claimed,
                owner_id=owner_id,
                worker_id=worker_id,
                fallback=connection,
            )
            execution = self._agent_execution(
                run_id=str(run["id"]),
                owner_id=owner_id,
                worker_id=worker_id,
                kind="continuitySummary",
                run=claimed,
                event_sink=None,
            )
            checkpoint_name, checkpoint_data = self._checkpoint_data(claimed)
            if checkpoint_name is None:
                await execution.start_step("context", "Preparing continuity context")
            concept = await self.store.get_concept(concept_id, owner_id)
            turns = await self.store.list_concept_turns(concept_id, owner_id)
            if concept is None or turns is None:
                raise PublicError("owner_scope_not_found", "Resource not found.", 404)
            source_turns = turns[:-6]
            source_hash = hashlib.sha256(
                "\n".join(
                    f"{row['role']}:{row['content']}" for row in source_turns
                ).encode()
            ).hexdigest()
            if checkpoint_name is None:
                checkpoint_data = {"sourceHash": source_hash}
                await self._checkpoint(
                    run_id=str(run["id"]),
                    owner_id=owner_id,
                    worker_id=worker_id,
                    name="contextCompleted",
                    data=checkpoint_data,
                )
                checkpoint_name = "contextCompleted"
            client = client_factory(maintenance_connection, api_key)
            _bind_model_call_observer(
                client,
                execution.model_call_started,
                execution.model_call_completed,
            )
            if checkpoint_name == "modelCompleted":
                result = ContinuitySummaryResult.model_validate(
                    checkpoint_data["modelResult"]
                )
            else:
                await execution.start_step("summarize", "Updating continuity memory")
                result = await client.summarize_continuity(
                    concept,
                    [
                        {"role": str(row["role"]), "content": str(row["content"])}
                        for row in source_turns
                    ],
                )
                checkpoint_data = {
                    "sourceHash": source_hash,
                    "modelResult": result.model_dump(mode="json", by_alias=True),
                }
                await self._checkpoint(
                    run_id=str(run["id"]),
                    owner_id=owner_id,
                    worker_id=worker_id,
                    name="modelCompleted",
                    data=checkpoint_data,
                )
            result_json = json.dumps(
                {"summary": result.summary},
                ensure_ascii=False,
                separators=(",", ":"),
            )
            await execution.start_step("commit", "Saving continuity memory")
            await self.store.complete_continuity_summary_run(
                run_id=str(run["id"]),
                owner_id=owner_id,
                worker_id=worker_id,
                concept_id=concept_id,
                summary=result.summary,
                through_turn_count=turn_count,
                source_turns_hash=source_hash,
                provider_snapshot_json=_provider_snapshot_json(maintenance_connection),
                result_json=result_json,
                now=_utc_isoformat(self.clock()),
            )
        except asyncio.CancelledError:
            return
        except Exception as error:
            if worker_id is not None:
                await self._fail_maintenance_run(
                    str(run["id"]), owner_id, worker_id, error
                )
        finally:
            if heartbeat is not None:
                await self._stop_lease_heartbeat(heartbeat)

    async def _run_knowledge_review(
        self,
        parent_run_id: str,
        owner_id: str,
        concept_id: str,
        user_turn_count: int,
        connection: ProviderConnection,
        api_key: str,
        client_factory: ProviderClientFactory,
    ) -> None:
        run, _created = await self._create_maintenance_run(
            owner_id=owner_id,
            concept_id=concept_id,
            parent_run_id=parent_run_id,
            kind="knowledgeReview",
            idempotency_key=f"review:{concept_id}:{user_turn_count}",
            agent_spec=KNOWLEDGE_REVIEW_AGENT_SPEC,
            connection=connection,
        )
        if run["status"] == "succeeded":
            return
        worker_id: str | None = None
        heartbeat: asyncio.Task[None] | None = None
        try:
            claimed, did_claim, worker_id = await self._claim_execution(
                str(run["id"]),
                owner_id,
            )
            if not did_claim or claimed is None:
                return
            heartbeat = self._start_lease_heartbeat(str(run["id"]), owner_id, worker_id)
            maintenance_connection = await self._provider_connection_for_run(
                run=claimed,
                owner_id=owner_id,
                worker_id=worker_id,
                fallback=connection,
            )
            execution = self._agent_execution(
                run_id=str(run["id"]),
                owner_id=owner_id,
                worker_id=worker_id,
                kind="knowledgeReview",
                run=claimed,
                event_sink=None,
            )
            checkpoint_name, checkpoint_data = self._checkpoint_data(claimed)
            if checkpoint_name is None:
                await execution.start_step("context", "Preparing knowledge review")
            concept_row = await self.store.get_concept(concept_id, owner_id)
            turns = await self.store.list_concept_turns(concept_id, owner_id)
            continuity = await self.store.get_continuity_summary(concept_id, owner_id)
            if concept_row is None or turns is None:
                raise PublicError("owner_scope_not_found", "Resource not found.", 404)
            if checkpoint_name is None:
                await self._checkpoint(
                    run_id=str(run["id"]),
                    owner_id=owner_id,
                    worker_id=worker_id,
                    name="contextCompleted",
                    data={},
                )
                checkpoint_name = "contextCompleted"
            client = client_factory(maintenance_connection, api_key)
            _bind_model_call_observer(
                client,
                execution.model_call_started,
                execution.model_call_completed,
            )
            if checkpoint_name == "modelCompleted":
                result = KnowledgeReviewResult.model_validate(
                    checkpoint_data["modelResult"]
                )
            else:
                await execution.start_step("review", "Reviewing durable knowledge")
                result = await client.review_knowledge(
                    concept_row,
                    [
                        {"role": str(row["role"]), "content": str(row["content"])}
                        for row in turns[-10:]
                    ],
                    str(continuity["summary"]) if continuity is not None else "",
                )
                checkpoint_data = {
                    "modelResult": result.model_dump(mode="json", by_alias=True)
                }
                await self._checkpoint(
                    run_id=str(run["id"]),
                    owner_id=owner_id,
                    worker_id=worker_id,
                    name="modelCompleted",
                    data=checkpoint_data,
                )
            proposal_record, proposal_response = await self._follow_up_proposal(
                str(run["id"]),
                owner_id,
                ConceptResponse.model_validate(concept_row),
                result.proposal,
            )
            if proposal_record is not None:
                proposal_record["origin"] = "periodicReview"
            now = _utc_isoformat(self.clock())
            allowed_source_ids = {
                str(source.get("id"))
                for source in concept_row.get("sources", [])
                if isinstance(source, dict) and source.get("id")
            }
            claims = []
            for claim in result.claims:
                source_ids = [
                    source_id
                    for source_id in claim.source_ids
                    if source_id in allowed_source_ids
                ]
                evidence_status = (
                    "sourceBacked"
                    if claim.evidence_status == "sourceBacked" and source_ids
                    else "modelExplanation"
                )
                claims.append(
                    {
                        "id": str(uuid4()),
                        "statement": claim.statement.strip(),
                        "claim_type": claim.type,
                        "evidence_status": evidence_status,
                        "time_sensitivity": claim.time_sensitivity,
                        "source_ids_json": json.dumps(
                            source_ids,
                            separators=(",", ":"),
                        ),
                        "verified_at": now if evidence_status == "sourceBacked" else None,
                        "created_at": now,
                    }
                )
            learning_updates = [
                {
                    "id": str(uuid4()),
                    "field": update.field,
                    "content": update.content.strip(),
                    "origin": update.origin,
                    "created_at": now,
                }
                for update in result.learning_state_updates
            ]
            result_json = json.dumps(
                {
                    "proposal": (
                        proposal_response.model_copy(
                            update={"origin": "periodicReview"}
                        ).model_dump(mode="json", by_alias=True)
                        if proposal_response is not None
                        else None
                    ),
                    "claims": claims,
                    "learningStateUpdates": learning_updates,
                    "reviewedThroughUserTurnCount": user_turn_count,
                },
                ensure_ascii=False,
                separators=(",", ":"),
            )
            await execution.start_step("commit", "Saving knowledge review")
            await self.store.complete_knowledge_review_run(
                run_id=str(run["id"]),
                owner_id=owner_id,
                worker_id=worker_id,
                concept_id=concept_id,
                reviewed_user_turn_count=user_turn_count,
                proposal=proposal_record,
                claims=claims,
                learning_state_updates=learning_updates,
                provider_snapshot_json=_provider_snapshot_json(maintenance_connection),
                result_json=result_json,
                now=now,
            )
        except asyncio.CancelledError:
            return
        except Exception as error:
            if worker_id is not None:
                await self._fail_maintenance_run(
                    str(run["id"]), owner_id, worker_id, error
                )
        finally:
            if heartbeat is not None:
                await self._stop_lease_heartbeat(heartbeat)

    async def _create_maintenance_run(
        self,
        *,
        owner_id: str,
        concept_id: str,
        parent_run_id: str,
        kind: str,
        idempotency_key: str,
        agent_spec: AgentSpec,
        connection: ProviderConnection,
    ) -> tuple[dict[str, Any], bool]:
        now = _utc_isoformat(self.clock())
        payload = json.dumps(
            {"conceptId": concept_id, "parentRunId": parent_run_id},
            separators=(",", ":"),
        )
        run_id = str(uuid4())
        return await self.store.create_model_run(
            run={
                "id": run_id,
                "owner_id": owner_id,
                "kind": kind,
                "status": "queued",
                "concept_id": concept_id,
                "client_draft_id": None,
                "idempotency_key": idempotency_key,
                "payload_hash": hashlib.sha256(payload.encode()).hexdigest(),
                "payload_json": payload,
                "provider_snapshot_json": _provider_snapshot_json(connection),
                "agent_spec": agent_spec.name,
                "agent_spec_version": agent_spec.version,
                "prompt_version": agent_spec.prompt_version,
                "budget_json": json.dumps(agent_spec.budget(), separators=(",", ":")),
                "tool_contract_hash": agent_spec.tool_contract_hash,
                "current_step": None,
                "model_call_count": 0,
                "tool_call_count": 0,
                "termination_reason": None,
                "dependency_run_id": parent_run_id,
                "checkpoint": None,
                "checkpoint_json": None,
                "result_json": None,
                "result_ref": None,
                "error_code": None,
                "error_message": None,
                "created_at": now,
                "updated_at": now,
            },
            event={
                "run_id": run_id,
                "sequence": 1,
                "event_type": "checkpoint",
                "data_json": '{"status":"queued"}',
                "created_at": now,
            },
        )

    async def _fail_maintenance_run(
        self,
        run_id: str,
        owner_id: str,
        worker_id: str,
        error: Exception,
    ) -> None:
        safe = (
            error
            if isinstance(error, PublicError)
            else PublicError("backend_unavailable", "Sift is temporarily unavailable.", 503)
        )
        await self.store.fail_model_run(
            run_id,
            owner_id,
            worker_id=worker_id,
            code=safe.code,
            message=safe.message,
            now=_utc_isoformat(self.clock()),
        )

    async def _follow_up_proposal(
        self,
        run_id: str,
        owner_id: str,
        concept: ConceptResponse,
        model_proposal: Any,
    ) -> tuple[dict[str, Any] | None, UpdateProposalResponse | None]:
        if model_proposal is None:
            return None, None
        pending = await self.store.list_update_proposals(
            concept.id,
            owner_id,
            "proposed",
        )
        if pending:
            return None, None
        blocks = {block.id: block for block in concept.blocks}
        operations = []
        for operation in model_proposal.patch_operations:
            if not isinstance(operation, (AppendPatchOutput, ReplacePatchOutput)):
                continue
            block = blocks.get(operation.target_block_id)
            if block is None or block.is_user_locked:
                continue
            if isinstance(operation, ReplacePatchOutput) and (
                operation.old_value_hash != _content_hash(block.content)
            ):
                continue
            operations.append(operation)
        if not operations:
            return None, None
        proposal_id = str(uuid4())
        now = _utc_isoformat(self.clock())
        operation_payload = [
            operation.model_dump(mode="json", by_alias=True)
            for operation in operations
        ]
        response = UpdateProposalResponse(
            id=proposal_id,
            baseNoteRevision=concept.note_revision,
            patchOperations=operation_payload,
            rationale=model_proposal.rationale.strip(),
            confidence=0.7,
            status="proposed",
            origin="followUp",
            sourceRunId=run_id,
        )
        return (
            {
                "id": proposal_id,
                "base_note_revision": concept.note_revision,
                "patch_operations_json": json.dumps(
                    operation_payload,
                    ensure_ascii=False,
                    separators=(",", ":"),
                ),
                "rationale": response.rationale,
                "confidence": response.confidence,
                "status": response.status,
                "origin": response.origin,
                "created_at": now,
            },
            response,
        )

    async def _emit(
        self,
        run_id: str,
        owner_id: str,
        event_type: str,
        data: dict[str, Any],
        event_sink: ModelRunEventSink | None,
        worker_id: str | None = None,
    ) -> None:
        now = _utc_isoformat(self.clock())
        sequence = await self.store.append_model_run_event(
            run_id,
            owner_id,
            event_type=event_type,
            data_json=json.dumps(data, ensure_ascii=False, separators=(",", ":")),
            now=now,
            worker_id=worker_id,
        )
        if sequence is None:
            raise PublicError("owner_scope_not_found", "Resource not found.", 404)
        if event_sink is not None:
            await event_sink(
                ModelRunEventResponse(
                    sequence=sequence,
                    type=event_type,
                    data=data,
                    createdAt=now,
                )
            )

    async def _run_web_tool_loop(
        self,
        *,
        run_id: str,
        owner_id: str,
        worker_id: str,
        request: str,
        provider_id: str,
        planner: ToolPlanner,
        checkpoint_data: dict[str, Any],
        web_settings: dict[str, Any],
        web_provider_key: str,
        event_sink: ModelRunEventSink | None,
        execution: AgentExecution,
    ) -> tuple[list[dict[str, str]], dict[str, Any]]:
        evidence = _checkpoint_evidence(checkpoint_data)
        observations = _checkpoint_tool_observations(checkpoint_data)
        planner_rounds = int(checkpoint_data.get("toolPlannerRounds") or 0)
        explicit = explicit_retrieval_required(request)
        if not bool(web_settings.get("web_search_enabled", 1)):
            if explicit:
                raise PublicError(
                    "retrieval_required",
                    "This request requires web research, but Research is disabled.",
                    409,
                )
            completed_data = {"evidence": evidence}
            await self._checkpoint(
                run_id=run_id,
                owner_id=owner_id,
                worker_id=worker_id,
                name="retrievalCompleted",
                data=completed_data,
            )
            return evidence, completed_data
        if explicit and not provider_supports_tools(provider_id):
            raise PublicError(
                "provider_capability_missing",
                "The selected model provider cannot call Sift tools.",
                409,
            )

        web_search_client = self.web_search_client or WorkerWebSearchClient(
            provider_id=str(web_settings.get("provider_type", "ddgs")),
            api_key=web_provider_key,
        )
        registry = web_tool_registry(
            web_search_client,
            search_timeout_seconds=WEB_SEARCH_TIMEOUT_SECONDS,
        )
        seen = {
            str(observation["signature"])
            for observation in observations
            if observation.get("signature")
        }
        reason = "roundBudgetExhausted"
        while planner_rounds < MAX_TOOL_PLANNER_ROUNDS:
            tool_calls = await planner(observations)
            planner_rounds += 1
            if not tool_calls:
                reason = "modelFinished"
                break
            new_call_count = 0
            for tool_call in tool_calls:
                definition = registry.resolve(tool_call.name)
                signature = _tool_call_signature(definition.name, tool_call.arguments)
                if signature in seen:
                    continue
                seen.add(signature)
                new_call_count += 1
                canonical = await execution.tool_call_started(
                    definition.name, tool_call.id
                )
                try:
                    _, raw_result = await registry.execute(canonical, tool_call.arguments)
                except Exception as error:
                    error_code = str(
                        getattr(error, "code", "tool_execution_failed")
                    )
                    await execution.tool_call_failed(
                        canonical,
                        call_id=tool_call.id,
                        code=error_code,
                    )
                    if error_code != "retrieval_required":
                        raise
                    observation = {
                        "signature": signature,
                        "callId": tool_call.id,
                        "tool": canonical,
                        "arguments": tool_call.arguments,
                        "result": [
                            {
                                "errorCode": error_code,
                                "errorMessage": str(
                                    getattr(
                                        error,
                                        "message",
                                        "The requested source could not be retrieved.",
                                    )
                                )[:300],
                            }
                        ],
                    }
                    if tool_call.provider_context is not None:
                        observation["providerContext"] = tool_call.provider_context
                    observations.append(observation)
                    checkpoint_data = {
                        "evidence": evidence,
                        "toolObservations": observations,
                        "toolPlannerRounds": planner_rounds,
                    }
                    await self._checkpoint(
                        run_id=run_id,
                        owner_id=owner_id,
                        worker_id=worker_id,
                        name="retrievalInProgress",
                        data=checkpoint_data,
                    )
                    continue
                results = _tool_evidence(raw_result)
                remaining = MAX_RETRIEVAL_EVIDENCE_ITEMS - len(evidence)
                results = results[:max(remaining, 0)]
                evidence.extend(results)
                observation = {
                    "signature": signature,
                    "callId": tool_call.id,
                    "tool": canonical,
                    "arguments": tool_call.arguments,
                    "result": results,
                }
                if tool_call.provider_context is not None:
                    observation["providerContext"] = tool_call.provider_context
                observations.append(observation)
                await execution.tool_call_completed(
                    canonical,
                    call_id=tool_call.id,
                    result_count=len(results),
                )
                checkpoint_data = {
                    "evidence": evidence,
                    "toolObservations": observations,
                    "toolPlannerRounds": planner_rounds,
                }
                await self._checkpoint(
                    run_id=run_id,
                    owner_id=owner_id,
                    worker_id=worker_id,
                    name="retrievalInProgress",
                    data=checkpoint_data,
                )
            if new_call_count == 0:
                reason = "duplicateToolCall"
                break

        if explicit and not evidence:
            raise PublicError(
                "retrieval_required",
                "This request requires web research, but the model did not call it.",
                502,
            )
        await execution.tool_loop_completed(
            reason=reason,
            rounds=planner_rounds,
            evidence_count=len(evidence),
        )
        completed_data = {"evidence": evidence}
        await self._checkpoint(
            run_id=run_id,
            owner_id=owner_id,
            worker_id=worker_id,
            name="retrievalCompleted",
            data=completed_data,
        )
        return evidence, completed_data

    async def _stream_answer(
        self,
        run_id: str,
        owner_id: str,
        stream: AnswerStream,
        event_sink: ModelRunEventSink | None,
        live_delta_sink: LiveDeltaSink | None,
        *,
        worker_id: str | None = None,
        execution: AgentExecution | None = None,
    ) -> str:
        recovery_deltas: list[str] = []
        recovery_chars = 0
        received_delta = False

        async def on_delta(delta: str) -> None:
            nonlocal received_delta, recovery_chars
            received_delta = True
            if live_delta_sink is not None:
                await live_delta_sink(delta)
            recovery_deltas.append(delta)
            recovery_chars += len(delta)
            if recovery_chars >= RECOVERY_DELTA_CHARS:
                await flush_recovery_delta()

        async def flush_recovery_delta() -> None:
            nonlocal recovery_chars
            if not recovery_deltas:
                return
            if execution is not None:
                await execution.check_cancelled()
            content = "".join(recovery_deltas)
            recovery_deltas.clear()
            recovery_chars = 0
            await self._emit(
                run_id,
                owner_id,
                "delta",
                {"content": content},
                event_sink,
                worker_id,
            )

        try:
            answer = await stream(on_delta)
        except PublicError as error:
            if received_delta or error.code not in TRANSIENT_STREAM_RETRY_CODES:
                raise
            answer = await stream(on_delta)
        await flush_recovery_delta()
        return answer

    async def get(self, run_id: str, owner_id: str) -> ModelRunResponse:
        run = await self.store.get_model_run(run_id, owner_id)
        if run is None:
            raise PublicError("owner_scope_not_found", "Resource not found.", 404)
        return _model_run_response(run)

    async def list(self, owner_id: str, *, active: bool) -> list[ModelRunResponse]:
        return [
            _model_run_response(run)
            for run in await self.store.list_model_runs(owner_id, active=active)
        ]

    async def cancel(self, run_id: str, owner_id: str) -> ModelRunResponse:
        cancelled = await self.store.cancel_model_run(
            run_id,
            owner_id,
            now=_utc_isoformat(self.clock()),
        )
        if cancelled is None:
            raise PublicError("owner_scope_not_found", "Resource not found.", 404)
        return _model_run_response(cancelled)

    async def events(
        self,
        run_id: str,
        owner_id: str,
        after_sequence: int,
    ) -> list[ModelRunEventResponse]:
        rows = await self.store.list_model_run_events(
            run_id,
            owner_id,
            after_sequence,
        )
        if rows is None:
            raise PublicError("owner_scope_not_found", "Resource not found.", 404)
        return [
            ModelRunEventResponse(
                sequence=int(row["sequence"]),
                type=str(row["event_type"]),
                data=_json_object(row.get("data_json")),
                createdAt=str(row["created_at"]),
            )
            for row in rows
        ]

    async def list_concepts(self, owner_id: str) -> list[ConceptResponse]:
        return [
            ConceptResponse.model_validate(row)
            for row in await self.store.list_concepts(owner_id)
        ]

    async def get_concept(self, concept_id: str, owner_id: str) -> ConceptResponse:
        row = await self.store.get_concept(concept_id, owner_id)
        if row is None:
            raise PublicError("owner_scope_not_found", "Resource not found.", 404)
        return ConceptResponse.model_validate(row)

    async def list_turns(
        self,
        concept_id: str,
        owner_id: str,
    ) -> list[ConceptHistoryTurnResponse]:
        rows = await self.store.list_concept_turns(concept_id, owner_id)
        if rows is None:
            raise PublicError("owner_scope_not_found", "Resource not found.", 404)
        return [
            ConceptHistoryTurnResponse(
                role=str(row["role"]),
                content=str(row["content"]),
                answerSource=_json_object_or_none(row.get("answer_source_json")),
            )
            for row in rows
        ]

    async def list_revisions(
        self,
        concept_id: str,
        owner_id: str,
    ) -> list[NoteRevisionSummaryResponse]:
        rows = await self.store.list_note_revisions(concept_id, owner_id)
        if rows is None:
            raise PublicError("owner_scope_not_found", "Resource not found.", 404)
        return [_revision_summary_response(row) for row in rows]

    async def get_revision(
        self,
        concept_id: str,
        revision: int,
        owner_id: str,
    ) -> NoteRevisionResponse:
        row = await self.store.get_note_revision(concept_id, revision, owner_id)
        if row is None:
            raise PublicError("owner_scope_not_found", "Resource not found.", 404)
        snapshot = _json_object(row.get("snapshot_json"))
        summary = _revision_summary_response(row)
        return NoteRevisionResponse(
            **summary.model_dump(),
            snapshotSchemaVersion=int(row.get("snapshot_schema_version") or 1),
            displayTitle=str(snapshot.get("displayTitle") or ""),
            canonicalTitle=str(
                snapshot.get("canonicalTitle") or snapshot.get("displayTitle") or ""
            ),
            oneLineExplanation=str(snapshot.get("oneLineExplanation") or ""),
            blocks=[
                NoteBlockResponse.model_validate(block)
                for block in snapshot.get("blocks", [])
                if isinstance(block, dict)
            ],
        )

    async def list_proposals(
        self,
        concept_id: str,
        owner_id: str,
        status: str | None,
    ) -> list[UpdateProposalResponse]:
        if status is not None and status not in {
            "proposed",
            "accepted",
            "dismissed",
            "stale",
        }:
            raise PublicError("invalid_request", "The proposal status is invalid.", 422)
        rows = await self.store.list_update_proposals(concept_id, owner_id, status)
        if rows is None:
            raise PublicError("owner_scope_not_found", "Resource not found.", 404)
        return [_proposal_response(row) for row in rows]

    async def dismiss_proposal(
        self,
        proposal_id: str,
        owner_id: str,
    ) -> None:
        proposal = await self.store.get_update_proposal(proposal_id, owner_id)
        if proposal is None:
            raise PublicError("owner_scope_not_found", "Resource not found.", 404)
        if proposal["status"] != "proposed":
            raise PublicError(
                "request_conflict",
                "Update proposal is not dismissible.",
                409,
            )
        resolved = await self.store.resolve_update_proposal(
            proposal_id,
            owner_id,
            status="dismissed",
            now=_utc_isoformat(self.clock()),
        )
        if not resolved:
            raise PublicError(
                "request_conflict",
                "Update proposal is not dismissible.",
                409,
            )


class ConceptMutationService:
    def __init__(
        self,
        store: WorkerStore,
        *,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self.store = store
        self.clock = clock or (lambda: datetime.now(UTC))

    async def update_summary(
        self,
        concept_id: str,
        owner_id: str,
        payload: UpdateConceptSummaryRequest,
    ) -> ConceptResponse:
        concept = await self._get(concept_id, owner_id)
        title = payload.display_title.strip()
        if not title:
            raise PublicError("invalid_request", "Concept title cannot be empty.", 422)
        updated = concept.model_copy(
            update={
                "canonical_title": title,
                "display_title": title,
                "one_line_explanation": payload.one_line_explanation.strip(),
                "note_revision": concept.note_revision + 1,
            }
        )
        return await self._save(concept, updated, owner_id, event_type="manualEdit")

    async def set_archived(
        self,
        concept_ids: list[str],
        owner_id: str,
        *,
        archived: bool,
    ) -> list[ConceptResponse]:
        unique_ids = list(dict.fromkeys(concept_ids))
        for concept_id in unique_ids:
            await self._get(concept_id, owner_id)
        rows = await self.store.set_concepts_archived(
            unique_ids,
            owner_id,
            archived=archived,
            now=_utc_isoformat(self.clock()),
        )
        if rows is None:
            raise PublicError(
                "revision_conflict",
                "A concept changed while it was being updated.",
                409,
            )
        return [ConceptResponse.model_validate(row) for row in rows]

    async def add_relation(
        self,
        concept_id: str,
        owner_id: str,
        payload: CreateConceptRelationRequest,
    ) -> ConceptResponse:
        relation_type = payload.relation_type.strip()
        if not relation_type:
            raise PublicError("invalid_request", "Relation type cannot be empty.", 422)
        if concept_id == payload.target_concept_id:
            raise PublicError(
                "invalid_request",
                "A concept cannot relate to itself.",
                422,
            )
        await self._get(concept_id, owner_id)
        await self._get(payload.target_concept_id, owner_id)
        row = await self.store.add_concept_relation(
            relation={
                "id": str(uuid4()),
                "source_concept_id": concept_id,
                "target_concept_id": payload.target_concept_id,
                "relation_type": relation_type,
                "status": "accepted",
                "confidence": 1,
                "source": "user",
                "created_at": _utc_isoformat(self.clock()),
            },
            owner_id=owner_id,
        )
        if row is None:
            raise PublicError("owner_scope_not_found", "Resource not found.", 404)
        return ConceptResponse.model_validate(row)

    async def remove_relation(
        self,
        concept_id: str,
        relation_id: str,
        owner_id: str,
    ) -> ConceptResponse:
        await self._get(concept_id, owner_id)
        row = await self.store.remove_concept_relation(
            concept_id=concept_id,
            relation_id=relation_id,
            owner_id=owner_id,
        )
        if row is None:
            raise PublicError(
                "owner_scope_not_found",
                "Concept relation not found.",
                404,
            )
        return ConceptResponse.model_validate(row)

    async def update_block(
        self,
        concept_id: str,
        block_id: str,
        owner_id: str,
        payload: UpdateNoteBlockRequest,
    ) -> ConceptResponse:
        concept = await self._get(concept_id, owner_id)
        content = payload.content.strip()
        if not content:
            raise PublicError("invalid_request", "Note block content cannot be empty.", 422)
        found = False
        blocks: list[NoteBlockResponse] = []
        for block in concept.blocks:
            if block.id == block_id:
                found = True
                blocks.append(
                    block.model_copy(
                        update={
                            "content": content,
                            "source": "user",
                            "is_user_locked": True,
                        }
                    )
                )
            else:
                blocks.append(block)
        if not found:
            raise PublicError("owner_scope_not_found", "Note block not found.", 404)
        updated = concept.model_copy(
            update={
                "maturity": "growing",
                "note_revision": concept.note_revision + 1,
                "blocks": blocks,
            }
        )
        return await self._save(concept, updated, owner_id, event_type="manualEdit")

    async def update_note(
        self,
        concept_id: str,
        owner_id: str,
        payload: UpdateConceptNoteRequest,
    ) -> ConceptResponse:
        concept = await self._get(concept_id, owner_id)
        title = payload.display_title.strip()
        if not title:
            raise PublicError("invalid_request", "Concept title cannot be empty.", 422)

        existing_by_id = {block.id: block for block in concept.blocks}
        blocks: list[NoteBlockResponse] = []
        for position, request_block in enumerate(payload.blocks):
            content = request_block.content.strip()
            if not content:
                continue
            if request_block.id is None:
                blocks.append(
                    NoteBlockResponse(
                        id=str(uuid4()),
                        blockType=request_block.block_type,
                        content=content,
                        source="user",
                        isUserLocked=True,
                        revision=1,
                        supportedClaimIds=[],
                        position=position,
                    )
                )
                continue
            existing = existing_by_id.get(request_block.id)
            if existing is None:
                raise PublicError(
                    "invalid_request",
                    "Note block does not belong to this concept.",
                    422,
                )
            changed = (
                existing.content != content
                or existing.block_type != request_block.block_type
            )
            blocks.append(
                existing.model_copy(
                    update={
                        "block_type": request_block.block_type,
                        "content": content,
                        "source": "user" if changed else existing.source,
                        "is_user_locked": True if changed else existing.is_user_locked,
                        "revision": existing.revision + 1 if changed else existing.revision,
                        "position": position,
                    }
                )
            )

        updated = concept.model_copy(
            update={
                "canonical_title": title,
                "display_title": title,
                "one_line_explanation": payload.one_line_explanation.strip(),
                "maturity": "growing",
                "note_revision": concept.note_revision + 1,
                "blocks": blocks,
                "tags": _normalized_names(payload.tags),
                "topics": _normalized_names(payload.topics),
            }
        )
        return await self._save(concept, updated, owner_id, event_type="manualEdit")

    async def update_organization(
        self,
        concept_id: str,
        owner_id: str,
        payload: UpdateConceptOrganizationRequest,
    ) -> ConceptResponse:
        concept = await self._get(concept_id, owner_id)
        updated = concept.model_copy(
            update={
                "tags": _normalized_names(payload.tags),
                "topics": _normalized_names(payload.topics),
                "note_revision": concept.note_revision + 1,
            }
        )
        return await self._save(concept, updated, owner_id, event_type="manualEdit")

    async def merge_proposal(
        self,
        proposal_id: str,
        owner_id: str,
        *,
        idempotency_key: str | None,
    ) -> ConceptResponse:
        scope = f"proposal-merge:{proposal_id}"
        payload_hash = hashlib.sha256(proposal_id.encode()).hexdigest()
        key = idempotency_key.strip() if idempotency_key else str(uuid4())
        existing = await self.store.get_mutation_idempotency(owner_id, scope, key)
        if existing is not None:
            if existing["payload_hash"] != payload_hash:
                raise PublicError(
                    "idempotency_payload_conflict",
                    "Idempotency key was already used with a different payload.",
                    409,
                )
            return ConceptResponse.model_validate(
                json.loads(str(existing["response_json"]))
            )

        proposal = await self.store.get_update_proposal(proposal_id, owner_id)
        if proposal is None:
            raise PublicError("owner_scope_not_found", "Resource not found.", 404)
        if proposal["status"] != "proposed":
            raise PublicError(
                "request_conflict",
                "Update proposal is not mergeable.",
                409,
            )
        concept = await self._get(str(proposal["concept_id"]), owner_id)
        if int(proposal["base_note_revision"]) != concept.note_revision:
            await self._mark_proposal_stale(proposal_id, owner_id)
            raise PublicError(
                "staleRevision",
                "Patch was generated against an older note revision.",
                409,
            )

        blocks_by_id = {block.id: block for block in concept.blocks}
        try:
            operations = json.loads(str(proposal["patch_operations_json"]))
            for raw_operation in operations:
                operation = str(raw_operation.get("operation"))
                if operation not in {"append", "replace"}:
                    raise PublicError(
                        "unsupportedOperation",
                        "The proposal contains an unsupported operation.",
                        409,
                    )
                block_id = str(raw_operation.get("targetBlockId") or "")
                block = blocks_by_id.get(block_id)
                if block is None:
                    raise PublicError(
                        "missingBlock",
                        "Patch target block does not exist.",
                        409,
                    )
                if block.is_user_locked:
                    raise PublicError(
                        "lockedBlock",
                        "Patch target block is user locked.",
                        409,
                    )
                if operation == "append":
                    addition = str(raw_operation.get("content") or "").strip()
                    if not addition:
                        raise PublicError(
                            "invalid_request",
                            "The proposal contains empty content.",
                            422,
                        )
                    content = f"{block.content}\n\n{addition}" if block.content else addition
                else:
                    if str(raw_operation.get("oldValueHash")) != _content_hash(
                        block.content
                    ):
                        raise PublicError(
                            "hashMismatch",
                            "Patch content no longer matches the proposal.",
                            409,
                        )
                    content = str(raw_operation.get("newContent") or "").strip()
                    if not content:
                        raise PublicError(
                            "invalid_request",
                            "The proposal contains empty content.",
                            422,
                        )
                blocks_by_id[block_id] = block.model_copy(
                    update={
                        "content": content,
                        "source": "merged",
                        "revision": block.revision + 1,
                    }
                )
        except PublicError:
            await self._mark_proposal_stale(proposal_id, owner_id)
            raise

        updated = concept.model_copy(
            update={
                "blocks": [
                    blocks_by_id[block.id] for block in concept.blocks
                ],
                "note_revision": concept.note_revision + 1,
                "maturity": "growing",
            }
        )
        return await self._save(
            concept,
            updated,
            owner_id,
            event_type="confirmedMerge",
            proposal_id=proposal_id,
            idempotency={
                "scope": scope,
                "idempotency_key": key,
                "payload_hash": payload_hash,
            },
        )

    async def restore_revision(
        self,
        concept_id: str,
        revision: int,
        owner_id: str,
    ) -> ConceptResponse:
        concept = await self._get(concept_id, owner_id)
        source = await self.store.get_note_revision(concept_id, revision, owner_id)
        if source is None:
            raise PublicError("owner_scope_not_found", "Note revision not found.", 404)
        snapshot = ConceptResponse.model_validate(_json_object(source["snapshot_json"]))
        updated = concept.model_copy(
            update={
                "canonical_title": snapshot.canonical_title,
                "display_title": snapshot.display_title,
                "one_line_explanation": snapshot.one_line_explanation,
                "blocks": snapshot.blocks,
                "note_revision": concept.note_revision + 1,
            }
        )
        return await self._save(
            concept,
            updated,
            owner_id,
            event_type="revisionRestore",
            restored_from_revision=revision,
        )

    async def _get(self, concept_id: str, owner_id: str) -> ConceptResponse:
        row = await self.store.get_concept(concept_id, owner_id)
        if row is None:
            raise PublicError("owner_scope_not_found", "Resource not found.", 404)
        return ConceptResponse.model_validate(row)

    async def _save(
        self,
        current: ConceptResponse,
        updated: ConceptResponse,
        owner_id: str,
        *,
        event_type: str,
        restored_from_revision: int | None = None,
        proposal_id: str | None = None,
        idempotency: dict[str, Any] | None = None,
    ) -> ConceptResponse:
        now = _utc_isoformat(self.clock())
        updated = updated.model_copy(update={"updated_at": now})
        document = updated.model_dump(mode="json", by_alias=True)
        document_json = json.dumps(document, ensure_ascii=False, separators=(",", ":"))
        blocks = [
            {
                "id": block.id,
                "block_type": block.block_type,
                "content": block.content,
                "source": block.source,
                "is_user_locked": int(block.is_user_locked),
                "revision": block.revision,
                "supported_claim_ids_json": json.dumps(
                    block.supported_claim_ids,
                    separators=(",", ":"),
                ),
                "position": position,
                "created_at": now,
                "updated_at": now,
            }
            for position, block in enumerate(updated.blocks)
        ]
        stored = await self.store.save_concept_revision(
            concept_id=current.id,
            owner_id=owner_id,
            expected_revision=current.note_revision,
            concept={
                "canonical_title": updated.canonical_title,
                "display_title": updated.display_title,
                "one_line_explanation": updated.one_line_explanation,
                "maturity": updated.maturity,
                "note_revision": updated.note_revision,
                "document_json": document_json,
                "updated_at": now,
            },
            blocks=blocks,
            tags=updated.tags,
            topics=updated.topics,
            revision={
                "revision": updated.note_revision,
                "snapshot_json": document_json,
                "actor": "user",
                "event_type": event_type,
                "created_at": now,
                "snapshot_schema_version": 2,
                "restored_from_revision": restored_from_revision,
            },
            proposal_id=proposal_id,
            idempotency=(
                {
                    **idempotency,
                    "response_json": document_json,
                    "created_at": now,
                }
                if idempotency is not None
                else None
            ),
        )
        if stored is None:
            raise PublicError(
                "revision_conflict",
                "The concept changed while it was being edited.",
                409,
            )
        return ConceptResponse.model_validate(stored)

    async def _mark_proposal_stale(self, proposal_id: str, owner_id: str) -> None:
        await self.store.resolve_update_proposal(
            proposal_id,
            owner_id,
            status="stale",
            now=_utc_isoformat(self.clock()),
        )


def _model_run_response(row: dict[str, Any]) -> ModelRunResponse:
    return ModelRunResponse(
        id=str(row["id"]),
        kind=str(row["kind"]),
        status=str(row["status"]),
        conceptId=_optional_str(row.get("concept_id")),
        clientDraftId=_optional_str(row.get("client_draft_id")),
        idempotencyKey=str(row["idempotency_key"]),
        providerSnapshot=_json_object(row.get("provider_snapshot_json")),
        agentSpec=str(row["agent_spec"]),
        agentSpecVersion=str(row["agent_spec_version"]),
        promptVersion=str(row["prompt_version"]),
        toolContractHash=str(row.get("tool_contract_hash") or ""),
        budget=_json_object(row.get("budget_json")),
        currentStep=_optional_str(row.get("current_step")),
        modelCallCount=int(row.get("model_call_count") or 0),
        toolCallCount=int(row.get("tool_call_count") or 0),
        modelLatencyMs=int(row.get("model_latency_ms") or 0),
        inputTokenCount=int(row.get("input_token_count") or 0),
        outputTokenCount=int(row.get("output_token_count") or 0),
        terminationReason=_optional_str(row.get("termination_reason")),
        dependencyRunId=_optional_str(row.get("dependency_run_id")),
        checkpoint=_optional_str(row.get("checkpoint")),
        result=_json_object_or_none(row.get("result_json")),
        resultRef=_optional_str(row.get("result_ref")),
        errorCode=_optional_str(row.get("error_code")),
        errorMessage=_optional_str(row.get("error_message")),
        childRunIds=[
            str(value) for value in row.get("child_run_ids", []) if value is not None
        ],
        createdAt=str(row["created_at"]),
        updatedAt=str(row["updated_at"]),
    )


def _revision_summary_response(row: dict[str, Any]) -> NoteRevisionSummaryResponse:
    revision = int(row["revision"])
    return NoteRevisionSummaryResponse(
        revision=revision,
        source=str(row["event_type"]),
        createdAt=str(row["created_at"]),
        isCurrent=revision == int(row["current_revision"]),
        restoredFromRevision=(
            int(row["restored_from_revision"])
            if row.get("restored_from_revision") is not None
            else None
        ),
    )


def _proposal_response(row: dict[str, Any]) -> UpdateProposalResponse:
    operations = json.loads(str(row["patch_operations_json"]))
    return UpdateProposalResponse(
        id=str(row["id"]),
        baseNoteRevision=int(row["base_note_revision"]),
        patchOperations=operations,
        rationale=str(row["rationale"]),
        confidence=float(row["confidence"]),
        status=str(row["status"]),
        origin=str(row["origin"]),
        sourceRunId=_optional_str(row.get("source_run_id")),
    )


def _provider_connection(row: dict[str, Any]) -> ProviderConnection:
    return ProviderConnection(
        owner_id=str(row["owner_id"]),
        provider_id=str(row["provider_id"]),
        base_url=str(row["base_url"]),
        model=str(row["model"]),
    )


def _provider_connection_from_snapshot(
    owner_id: str,
    raw_snapshot: Any,
) -> ProviderConnection | None:
    snapshot = _json_object(raw_snapshot)
    if not snapshot:
        return None
    provider_id = snapshot.get("provider")
    base_url = snapshot.get("baseURL")
    model = snapshot.get("model")
    if not all(isinstance(value, str) and value.strip() for value in (
        provider_id,
        base_url,
        model,
    )):
        raise PublicError(
            "provider_snapshot_invalid",
            "The agent run has an invalid provider snapshot.",
            409,
        )
    return validate_provider_connection(
        owner_id,
        provider_id,
        base_url,
        model,
    )


def _source_records(
    evidence: list[dict[str, str]],
    citations: list[Any],
    *,
    now: str,
) -> list[dict[str, Any]]:
    cited_ids = {
        citation.source_id for citation in citations if citation.source_id is not None
    }
    return [
        {
            "id": item["id"],
            "title": item["title"],
            "url": item["url"],
            "source_type": (
                "sourceRead"
                if item.get("provenance") == "extracted"
                else "searchDiscovered"
            ),
            "retrieved_at": now,
            "published_at": item.get("publishedAt") or None,
            "content_hash": _content_hash(item.get("snippet", "")),
        }
        for item in evidence
        if item["id"] in cited_ids
    ]


def _pending_concept_record(
    *,
    concept_id: str,
    raw_capture: str,
    now: str,
) -> dict[str, Any]:
    title = raw_capture.strip()
    document_model = ConceptResponse(
        id=concept_id,
        canonicalTitle=title,
        displayTitle=title,
        oneLineExplanation="",
        initialAnswer=None,
        maturity="initial",
        captureStatus="pendingGeneration",
        noteRevision=0,
        blocks=[],
        tags=[],
        topics=[],
        answerSource=None,
        relations=[],
        sources=[],
        claims=[],
        learningState=None,
        createdAt=now,
        updatedAt=now,
    )
    document_json = json.dumps(
        document_model.model_dump(mode="json", by_alias=True),
        ensure_ascii=False,
        separators=(",", ":"),
    )
    return {
        "id": concept_id,
        "canonical_title": title,
        "display_title": title,
        "one_line_explanation": "",
        "initial_answer": None,
        "maturity": "initial",
        "capture_status": "pendingGeneration",
        "note_revision": 0,
        "answer_source_json": None,
        "document_json": document_json,
        "created_at": now,
        "updated_at": now,
    }


def _input_turn_record(
    *,
    run_id: str,
    concept_id: str,
    operation_key: str,
    content: str,
    now: str,
) -> dict[str, Any]:
    return {
        "id": str(uuid5(NAMESPACE_URL, f"sift:{run_id}:turn:user")),
        "concept_id": concept_id,
        "operation_key": operation_key,
        "role": "user",
        "content": content.strip(),
        "answer_source_json": None,
        "created_at": now,
    }


def _initial_concept_records(
    *,
    run: dict[str, Any],
    payload: CreateConceptRunRequest,
    result: Any,
    now: str,
    evidence: list[dict[str, str]] | None = None,
) -> tuple[
    dict[str, Any],
    list[dict[str, Any]],
    list[str],
    list[str],
    dict[str, Any],
    list[dict[str, Any]],
]:
    run_id = str(run["id"])
    concept_id = run_id
    blocks: list[dict[str, Any]] = []
    block_responses: list[NoteBlockResponse] = []
    for position, output in enumerate(result.blocks):
        content = output.content.strip()
        if not content:
            continue
        block_id = str(uuid5(NAMESPACE_URL, f"sift:{run_id}:block:{position}"))
        blocks.append(
            {
                "id": block_id,
                "block_type": output.block_type,
                "content": content,
                "source": "ai",
                "is_user_locked": 0,
                "revision": 1,
                "supported_claim_ids_json": "[]",
                "position": position,
                "created_at": now,
                "updated_at": now,
            }
        )
        block_responses.append(
            NoteBlockResponse(
                id=block_id,
                blockType=output.block_type,
                content=content,
                source="ai",
                isUserLocked=False,
                revision=1,
                supportedClaimIds=[],
                position=position,
            )
        )

    tags = _normalized_names([suggestion.name for suggestion in result.suggested_tags])
    topics = _normalized_names([suggestion.name for suggestion in result.suggested_topics])
    answer_source = result.answer_source.model_dump(mode="json", by_alias=True)
    source_records = _source_records(
        evidence or [],
        result.answer_source.citations,
        now=now,
    )
    source_documents = [
        {
            "id": source["id"],
            "conceptId": run_id,
            "title": source["title"],
            "url": source["url"],
            "sourceType": source["source_type"],
            "retrievedAt": source["retrieved_at"],
            "publishedAt": source["published_at"],
            "contentHash": source["content_hash"],
        }
        for source in source_records
    ]
    document_model = ConceptResponse(
        id=concept_id,
        canonicalTitle=result.canonical_title.strip(),
        displayTitle=result.display_title.strip(),
        oneLineExplanation=result.one_line_explanation.strip(),
        initialAnswer=result.answer.strip(),
        maturity="initial",
        captureStatus="ready",
        noteRevision=1,
        blocks=block_responses,
        tags=tags,
        topics=topics,
        answerSource=answer_source,
        relations=[],
        sources=source_documents,
        claims=[],
        learningState=None,
        createdAt=now,
        updatedAt=now,
    )
    document = document_model.model_dump(mode="json", by_alias=True)
    document_json = json.dumps(document, ensure_ascii=False, separators=(",", ":"))
    concept = {
        "id": concept_id,
        "canonical_title": document_model.canonical_title,
        "display_title": document_model.display_title,
        "one_line_explanation": document_model.one_line_explanation,
        "initial_answer": document_model.initial_answer,
        "maturity": document_model.maturity,
        "capture_status": document_model.capture_status,
        "note_revision": document_model.note_revision,
        "answer_source_json": json.dumps(
            answer_source,
            ensure_ascii=False,
            separators=(",", ":"),
        ),
        "document_json": document_json,
        "created_at": now,
        "updated_at": now,
    }
    revision = {
        "revision": 1,
        "snapshot_json": document_json,
        "actor": "ai",
        "event_type": "initialGeneration",
        "created_at": now,
    }
    operation_key = str(run["idempotency_key"])
    turns = [
        {
            "id": str(uuid5(NAMESPACE_URL, f"sift:{run_id}:turn:user")),
            "operation_key": operation_key,
            "role": "user",
            "content": payload.capture.raw_capture.strip(),
            "answer_source_json": None,
            "created_at": now,
        },
        {
            "id": str(uuid5(NAMESPACE_URL, f"sift:{run_id}:turn:assistant")),
            "operation_key": operation_key,
            "role": "assistant",
            "content": result.answer.strip(),
            "answer_source_json": concept["answer_source_json"],
            "created_at": now,
        },
    ]
    return concept, blocks, tags, topics, revision, turns


def _regenerated_concept_records(
    *,
    current: ConceptResponse,
    result: Any,
    operation_key: str,
    question: str,
    now: str,
) -> tuple[
    dict[str, Any],
    list[dict[str, Any]],
    list[str],
    list[str],
    dict[str, Any],
    list[dict[str, Any]],
    ConceptResponse,
]:
    blocks: list[dict[str, Any]] = []
    block_responses: list[NoteBlockResponse] = []
    for position, output in enumerate(result.blocks):
        content = output.content.strip()
        if not content:
            continue
        block_id = str(uuid4())
        block_responses.append(
            NoteBlockResponse(
                id=block_id,
                blockType=output.block_type,
                content=content,
                source="ai",
                isUserLocked=False,
                revision=1,
                supportedClaimIds=[],
                position=position,
            )
        )
        blocks.append(
            {
                "id": block_id,
                "block_type": output.block_type,
                "content": content,
                "source": "ai",
                "is_user_locked": 0,
                "revision": 1,
                "supported_claim_ids_json": "[]",
                "position": position,
                "created_at": now,
                "updated_at": now,
            }
        )
    tags = _normalized_names([suggestion.name for suggestion in result.suggested_tags])
    topics = _normalized_names([suggestion.name for suggestion in result.suggested_topics])
    answer_source = result.answer_source.model_dump(mode="json", by_alias=True)
    concept_model = current.model_copy(
        update={
            "canonical_title": result.canonical_title.strip(),
            "display_title": result.display_title.strip(),
            "one_line_explanation": result.one_line_explanation.strip(),
            "initial_answer": result.answer.strip(),
            "maturity": "initial",
            "capture_status": "ready",
            "note_revision": current.note_revision + 1,
            "blocks": block_responses,
            "tags": tags,
            "topics": topics,
            "answer_source": result.answer_source,
            "updated_at": now,
        }
    )
    document = concept_model.model_dump(mode="json", by_alias=True)
    document_json = json.dumps(document, ensure_ascii=False, separators=(",", ":"))
    concept = {
        "id": current.id,
        "canonical_title": concept_model.canonical_title,
        "display_title": concept_model.display_title,
        "one_line_explanation": concept_model.one_line_explanation,
        "initial_answer": concept_model.initial_answer,
        "maturity": concept_model.maturity,
        "capture_status": concept_model.capture_status,
        "note_revision": concept_model.note_revision,
        "answer_source_json": json.dumps(
            answer_source,
            ensure_ascii=False,
            separators=(",", ":"),
        ),
        "document_json": document_json,
        "updated_at": now,
    }
    revision = {
        "revision": concept_model.note_revision,
        "snapshot_json": document_json,
        "actor": "ai",
        "event_type": "retryGeneration",
        "created_at": now,
        "snapshot_schema_version": 2,
    }
    turns = [
        {
            "id": str(uuid4()),
            "operation_key": operation_key,
            "role": "user",
            "content": question,
            "answer_source_json": None,
            "created_at": now,
        },
        {
            "id": str(uuid4()),
            "operation_key": operation_key,
            "role": "assistant",
            "content": result.answer.strip(),
            "answer_source_json": concept["answer_source_json"],
            "created_at": now,
        },
    ]
    return concept, blocks, tags, topics, revision, turns, concept_model


def _provider_snapshot_json(connection: ProviderConnection) -> str:
    return json.dumps(
        {
            "provider": connection.provider_id,
            "model": connection.model,
            "baseURL": connection.base_url,
        },
        ensure_ascii=False,
        separators=(",", ":"),
    )


def _bind_model_call_observer(
    client: Any,
    observer: Callable[[], Awaitable[int]],
    completion_observer: Callable[
        [int, int, int | None, int | None, bool], Awaitable[None]
    ],
) -> None:
    bind = getattr(client, "bind_model_call_observer", None)
    if callable(bind):
        bind(observer)
    bind_completion = getattr(client, "bind_model_call_completion_observer", None)
    if callable(bind_completion):
        bind_completion(completion_observer)


def _model_call_count(client: Any) -> int:
    count = getattr(client, "model_call_count", None)
    return count if isinstance(count, int) and 0 < count <= 3 else 2


def _normalized_names(names: list[str]) -> list[str]:
    seen: set[str] = set()
    normalized: list[str] = []
    for raw_name in names:
        name = raw_name.strip()
        key = name.casefold()
        if not name or key in seen:
            continue
        seen.add(key)
        normalized.append(name[:80])
    return normalized


def _hash_secret(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def _content_hash(value: str) -> str:
    return f"sha256:{hashlib.sha256(value.encode()).hexdigest()}"


def _utc_isoformat(value: datetime) -> str:
    return _as_utc(value).isoformat().replace("+00:00", "Z")


def _parse_utc(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(UTC)


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _optional_str(value: Any) -> str | None:
    return None if value is None else str(value)


def _json_object(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if not value:
        return {}
    parsed = json.loads(str(value))
    return parsed if isinstance(parsed, dict) else {}


def _json_object_or_none(value: Any) -> dict[str, Any] | None:
    if value is None:
        return None
    return _json_object(value)


def _checkpoint_evidence(data: dict[str, Any]) -> list[dict[str, str]]:
    raw = data.get("evidence")
    if not isinstance(raw, list):
        return []
    return [
        {str(key): str(value) for key, value in item.items() if value is not None}
        for item in raw
        if isinstance(item, dict)
    ]


def _evidence_citations(evidence: list[dict[str, str]]) -> list[dict[str, str]]:
    return [
        {
            "sourceId": item["id"],
            "title": item["title"],
            "url": item["url"],
        }
        for item in evidence
    ]


def _checkpoint_tool_observations(data: dict[str, Any]) -> list[dict[str, Any]]:
    raw = data.get("toolObservations")
    if not isinstance(raw, list):
        return []
    return [dict(item) for item in raw if isinstance(item, dict)]


def _tool_call_signature(name: str, arguments: dict[str, Any]) -> str:
    return json.dumps(
        {"tool": name, "arguments": arguments},
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _tool_evidence(raw_result: Any) -> list[dict[str, str]]:
    raw_items = raw_result if isinstance(raw_result, list) else [raw_result]
    if len(raw_items) > MAX_TOOL_RESULT_ITEMS:
        raise AgentControlError(
            "tool_invalid_result",
            "A runtime tool returned too many results.",
        )
    evidence: list[dict[str, str]] = []
    for item in raw_items:
        if not isinstance(item, dict):
            raise AgentControlError(
                "tool_invalid_result",
                "A runtime tool returned an invalid result.",
            )
        normalized: dict[str, str] = {}
        limits = {
            "id": 200,
            "title": MAX_TOOL_TITLE_CHARS,
            "url": MAX_TOOL_URL_CHARS,
            "snippet": MAX_TOOL_SNIPPET_CHARS,
            "publishedAt": 128,
            "provenance": 64,
        }
        for key, limit in limits.items():
            value = item.get(key)
            if value is None:
                continue
            if not isinstance(value, str):
                raise AgentControlError(
                    "tool_invalid_result",
                    "A runtime tool returned an invalid result.",
                )
            stripped = value.strip()
            if key == "url" and len(stripped) > limit:
                raise AgentControlError(
                    "tool_invalid_result",
                    "A runtime tool returned an invalid result.",
                )
            normalized[key] = stripped[:limit]
        if not all(normalized.get(key, "").strip() for key in ("id", "title", "url")):
            raise AgentControlError(
                "tool_invalid_result",
                "A runtime tool returned an invalid result.",
            )
        parsed_url = urlparse(normalized["url"])
        if parsed_url.scheme != "https" or not parsed_url.hostname:
            raise AgentControlError(
                "tool_invalid_result",
                "A runtime tool returned an invalid result.",
            )
        evidence.append(normalized)
    return evidence
