from __future__ import annotations

import asyncio
import hashlib
import json
import time
from collections.abc import Callable
from contextlib import AbstractContextManager, nullcontext
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

from fastapi import HTTPException, status
from sqlalchemy import delete, func, or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from sift_backend.ai.context_pack import RecentTurn
from sift_backend.concepts.service import (
    ConceptService,
    PreparedTurnResult,
)
from sift_backend.model_runtime.harness import (
    AgentBudgetExceeded,
    SiftAgentRunner,
    agent_spec_for_kind,
)
from sift_backend.persistence.models import (
    ConceptContinuitySummaryRecord,
    ConceptMaintenanceStateRecord,
    ModelRunEventRecord,
    ModelRunRecord,
    TurnRecord,
    UpdateProposalRecord,
)
from sift_backend.schemas.concepts import (
    ConceptDTO,
    ConceptTurnRequest,
    CreateConceptRequest,
    UpdateProposalDTO,
)
from sift_backend.schemas.model_outputs import ConceptTurnResult
from sift_backend.schemas.model_runs import (
    ModelRunDTO,
    ModelRunEventDTO,
    ModelRunKind,
    ModelRunStatus,
)
from sift_backend.schemas.patches import AppendPatchOperation, ReplacePatchOperation

ACTIVE_STATUSES = {
    ModelRunStatus.queued.value,
    ModelRunStatus.waiting_for_credential.value,
    ModelRunStatus.running.value,
}
LEASE_DURATION = timedelta(minutes=2)
LEASE_HEARTBEAT_SECONDS = 30


def _utc_isoformat(value: datetime) -> str:
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


class ModelRunLeaseLost(RuntimeError):
    pass


class ModelRunRepository:
    def __init__(self, sessions: sessionmaker[Session]) -> None:
        self.sessions = sessions

    def create(
        self,
        *,
        owner_id: str,
        kind: ModelRunKind,
        idempotency_key: str,
        payload: dict[str, Any],
        concept_id: UUID | None = None,
        client_draft_id: str | None = None,
        provider_snapshot: dict[str, Any] | None = None,
        dependency_run_id: UUID | None = None,
        waiting_for_credential: bool = False,
    ) -> tuple[ModelRunDTO, bool]:
        canonical_payload = json.dumps(
            payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        )
        payload_hash = hashlib.sha256(canonical_payload.encode()).hexdigest()
        agent_spec = agent_spec_for_kind(kind)
        with self.sessions() as session:
            existing = session.scalar(
                select(ModelRunRecord).where(
                    ModelRunRecord.owner_id == owner_id,
                    ModelRunRecord.kind == kind.value,
                    ModelRunRecord.idempotency_key == idempotency_key,
                )
            )
            if existing is not None:
                if existing.payload_hash != payload_hash:
                    raise HTTPException(
                        status_code=status.HTTP_409_CONFLICT,
                        detail={
                            "code": "idempotency_payload_conflict",
                            "message": "Idempotency key was already used with a different payload.",
                        },
                    )
                return self._to_dto(session, existing), False
            record = ModelRunRecord(
                id=str(uuid4()),
                owner_id=owner_id,
                kind=kind.value,
                status=(
                    ModelRunStatus.waiting_for_credential.value
                    if waiting_for_credential
                    else ModelRunStatus.queued.value
                ),
                concept_id=str(concept_id) if concept_id else None,
                client_draft_id=client_draft_id,
                idempotency_key=idempotency_key,
                payload_hash=payload_hash,
                payload_json=canonical_payload,
                provider_snapshot_json=json.dumps(provider_snapshot or {}, ensure_ascii=False),
                agent_spec=agent_spec.name,
                agent_spec_version=agent_spec.version,
                prompt_version=agent_spec.prompt_version,
                budget_json=json.dumps(agent_spec.budget()),
                dependency_run_id=str(dependency_run_id) if dependency_run_id else None,
            )
            session.add(record)
            try:
                session.flush()
            except IntegrityError:
                session.rollback()
                return self.create(
                    owner_id=owner_id,
                    kind=kind,
                    idempotency_key=idempotency_key,
                    payload=payload,
                    concept_id=concept_id,
                    client_draft_id=client_draft_id,
                    provider_snapshot=provider_snapshot,
                    dependency_run_id=dependency_run_id,
                    waiting_for_credential=waiting_for_credential,
                )
            self._append_event(
                session,
                record.id,
                "waitingForCredential" if waiting_for_credential else "checkpoint",
                {"status": record.status},
            )
            session.commit()
            session.refresh(record)
            return self._to_dto(session, record), True

    def get(self, run_id: UUID, owner_id: str) -> ModelRunDTO:
        with self.sessions() as session:
            record = session.get(ModelRunRecord, str(run_id))
            if record is None or record.owner_id != owner_id:
                raise HTTPException(status_code=404, detail="Model run not found.")
            return self._to_dto(session, record)

    def list(self, owner_id: str, *, active: bool) -> list[ModelRunDTO]:
        with self.sessions() as session:
            query = select(ModelRunRecord).where(ModelRunRecord.owner_id == owner_id)
            if active:
                query = query.where(ModelRunRecord.status.in_(ACTIVE_STATUSES))
            records = session.scalars(query.order_by(ModelRunRecord.created_at)).all()
            return [self._to_dto(session, record) for record in records]

    def events(self, run_id: UUID, owner_id: str, after_sequence: int) -> list[ModelRunEventDTO]:
        self.get(run_id, owner_id)
        with self.sessions() as session:
            rows = session.scalars(
                select(ModelRunEventRecord)
                .where(
                    ModelRunEventRecord.run_id == str(run_id),
                    ModelRunEventRecord.sequence > after_sequence,
                )
                .order_by(ModelRunEventRecord.sequence)
            ).all()
            return [
                ModelRunEventDTO(
                    sequence=row.sequence,
                    type=row.event_type,
                    data=json.loads(row.data_json) if row.data_json else None,
                    createdAt=_utc_isoformat(row.created_at),
                )
                for row in rows
            ]

    def payload(self, run_id: UUID) -> dict[str, Any]:
        with self.sessions() as session:
            record = session.get(ModelRunRecord, str(run_id))
            if record is None:
                raise LookupError(run_id)
            return json.loads(record.payload_json)

    def checkpoint_data(self, run_id: UUID) -> tuple[str | None, dict[str, Any] | None]:
        with self.sessions() as session:
            record = session.get(ModelRunRecord, str(run_id))
            if record is None:
                raise LookupError(run_id)
            return (
                record.checkpoint,
                json.loads(record.checkpoint_json) if record.checkpoint_json else None,
            )

    def mark_queued(self, run_id: UUID, owner_id: str) -> ModelRunDTO:
        with self.sessions() as session:
            record = session.get(ModelRunRecord, str(run_id))
            if record is None or record.owner_id != owner_id:
                raise HTTPException(status_code=404, detail="Model run not found.")
            if record.status not in {
                ModelRunStatus.waiting_for_credential.value,
                ModelRunStatus.failed.value,
            }:
                return self._to_dto(session, record)
            record.status = ModelRunStatus.queued.value
            record.error_code = record.error_message = None
            self._append_event(session, record.id, "checkpoint", {"status": record.status})
            session.commit()
            session.refresh(record)
            return self._to_dto(session, record)

    def set_provider_snapshot(
        self, run_id: UUID, owner_id: str, snapshot: dict[str, str]
    ) -> ModelRunDTO:
        with self.sessions() as session:
            record = session.get(ModelRunRecord, str(run_id))
            if record is None or record.owner_id != owner_id:
                raise HTTPException(status_code=404, detail="Model run not found.")
            record.provider_snapshot_json = json.dumps(snapshot, ensure_ascii=False)
            session.commit()
            session.refresh(record)
            return self._to_dto(session, record)

    def begin(self, run_id: UUID, worker_id: str) -> bool:
        now = datetime.now(UTC)
        with self.sessions() as session:
            record = session.get(ModelRunRecord, str(run_id))
            if record is None or record.status not in {
                ModelRunStatus.queued.value,
                ModelRunStatus.running.value,
            }:
                return False
            if record.dependency_run_id:
                dependency = session.get(ModelRunRecord, record.dependency_run_id)
                if dependency is None or dependency.status not in {
                    ModelRunStatus.succeeded.value,
                    ModelRunStatus.failed.value,
                }:
                    return False
            if record.concept_id is not None:
                session.execute(
                    update(ModelRunRecord)
                    .where(
                        ModelRunRecord.id != str(run_id),
                        ModelRunRecord.concept_id == record.concept_id,
                        ModelRunRecord.status == ModelRunStatus.running.value,
                        ModelRunRecord.lease_expires_at <= now,
                    )
                    .values(
                        status=ModelRunStatus.queued.value,
                        lease_owner=None,
                        lease_expires_at=None,
                    )
                    .execution_options(synchronize_session=False)
                )
            try:
                claimed = session.execute(
                    update(ModelRunRecord)
                    .where(
                        ModelRunRecord.id == str(run_id),
                        ModelRunRecord.status.in_(
                            [ModelRunStatus.queued.value, ModelRunStatus.running.value]
                        ),
                        or_(
                            ModelRunRecord.lease_expires_at.is_(None),
                            ModelRunRecord.lease_expires_at <= now,
                            ModelRunRecord.lease_owner == worker_id,
                        ),
                    )
                    .values(
                        status=ModelRunStatus.running.value,
                        lease_owner=worker_id,
                        lease_expires_at=now + LEASE_DURATION,
                        started_at=func.coalesce(ModelRunRecord.started_at, now),
                    )
                    .execution_options(synchronize_session=False)
                )
                session.flush()
            except IntegrityError:
                session.rollback()
                return False
            if claimed.rowcount != 1:
                session.rollback()
                return False
            self._append_event(session, str(run_id), "started", None)
            session.commit()
            return True

    def renew_lease(self, run_id: UUID, worker_id: str) -> bool:
        now = datetime.now(UTC)
        with self.sessions() as session:
            renewed = session.execute(
                update(ModelRunRecord)
                .where(
                    ModelRunRecord.id == str(run_id),
                    ModelRunRecord.status == ModelRunStatus.running.value,
                    ModelRunRecord.lease_owner == worker_id,
                )
                .values(lease_expires_at=now + LEASE_DURATION)
                .execution_options(synchronize_session=False)
            )
            session.commit()
            return renewed.rowcount == 1

    def owns_lease(self, run_id: UUID, worker_id: str) -> bool:
        with self.sessions() as session:
            record = session.get(ModelRunRecord, str(run_id))
            return bool(
                record is not None
                and record.status == ModelRunStatus.running.value
                and record.lease_owner == worker_id
            )

    def require_lease(self, run_id: UUID, worker_id: str) -> None:
        if not self.owns_lease(run_id, worker_id):
            raise ModelRunLeaseLost(f"Worker no longer owns model run {run_id}.")

    def checkpoint(
        self,
        run_id: UUID,
        name: str,
        data: dict[str, Any],
        *,
        worker_id: str | None = None,
    ) -> None:
        with self.sessions() as session:
            record = session.get(ModelRunRecord, str(run_id))
            assert record is not None
            self._require_record_lease(record, worker_id)
            record.checkpoint = name
            record.checkpoint_json = json.dumps(data, ensure_ascii=False)
            self._append_event(session, record.id, "checkpoint", {"name": name})
            session.commit()

    def delta(self, run_id: UUID, content: str, *, worker_id: str | None = None) -> None:
        with self.sessions() as session:
            record = session.get(ModelRunRecord, str(run_id))
            assert record is not None
            self._require_record_lease(record, worker_id)
            self._append_event(session, record.id, "delta", {"content": content})
            session.commit()

    def harness_step(
        self,
        run_id: UUID,
        step: str,
        *,
        started: bool,
        label: str | None = None,
        worker_id: str | None = None,
    ) -> None:
        with self.sessions() as session:
            record = session.get(ModelRunRecord, str(run_id))
            assert record is not None
            self._require_record_lease(record, worker_id)
            record.current_step = step
            data: dict[str, Any] = {"step": step}
            if label is not None:
                data["label"] = label
            self._append_event(
                session,
                record.id,
                "stepStarted" if started else "stepCompleted",
                data,
            )
            session.commit()

    def update_usage(
        self,
        run_id: UUID,
        model_calls: int,
        tool_calls: int,
        *,
        worker_id: str | None = None,
    ) -> None:
        with self.sessions() as session:
            record = session.get(ModelRunRecord, str(run_id))
            assert record is not None
            self._require_record_lease(record, worker_id)
            record.model_call_count = model_calls
            record.tool_call_count = tool_calls
            self._append_event(
                session,
                record.id,
                "budgetUpdated",
                {"modelCalls": model_calls, "toolCalls": tool_calls},
            )
            session.commit()

    def succeed(
        self,
        run_id: UUID,
        result: dict[str, Any],
        result_ref: str | None = None,
        *,
        worker_id: str | None = None,
    ) -> None:
        with self.sessions() as session:
            record = session.get(ModelRunRecord, str(run_id))
            assert record is not None
            self._require_record_lease(record, worker_id)
            record.status = ModelRunStatus.succeeded.value
            record.result_json = json.dumps(result, ensure_ascii=False)
            record.result_ref = result_ref
            record.termination_reason = "completed"
            record.completed_at = datetime.now(UTC)
            record.lease_owner = None
            record.lease_expires_at = None
            self._compact_deltas(session, record.id)
            self._append_event(session, record.id, "completed", {"result": result})
            session.commit()

    def commit_domain_and_succeed(
        self,
        run_id: UUID,
        *,
        worker_id: str,
        action: Callable[[Session], tuple[Any, dict[str, Any], str | None]],
        transaction: Callable[[Session], AbstractContextManager[None]] | None = None,
    ) -> Any:
        """Commit domain writes and the terminal run event in one transaction."""
        with self.sessions() as session:
            record = session.scalar(
                select(ModelRunRecord)
                .where(ModelRunRecord.id == str(run_id))
                .with_for_update()
            )
            assert record is not None
            self._require_record_lease(record, worker_id)
            transaction_scope = transaction(session) if transaction is not None else nullcontext()
            with transaction_scope:
                domain_result, result, result_ref = action(session)
                record.status = ModelRunStatus.succeeded.value
                record.result_json = json.dumps(result, ensure_ascii=False)
                record.result_ref = result_ref
                record.termination_reason = "completed"
                record.completed_at = datetime.now(UTC)
                record.lease_owner = None
                record.lease_expires_at = None
                self._compact_deltas(session, record.id)
                self._append_event(session, record.id, "completed", {"result": result})
            session.commit()
            return domain_result

    def fail(
        self,
        run_id: UUID,
        code: str,
        message: str,
        *,
        waiting: bool = False,
        worker_id: str | None = None,
    ) -> None:
        with self.sessions() as session:
            record = session.get(ModelRunRecord, str(run_id))
            assert record is not None
            self._require_record_lease(record, worker_id)
            record.status = (
                ModelRunStatus.waiting_for_credential.value
                if waiting
                else ModelRunStatus.failed.value
            )
            record.error_code = code
            record.error_message = message
            record.termination_reason = "waitingForCredential" if waiting else code
            record.completed_at = None if waiting else datetime.now(UTC)
            record.lease_owner = None
            record.lease_expires_at = None
            if not waiting:
                self._compact_deltas(session, record.id)
            self._append_event(
                session,
                record.id,
                "waitingForCredential" if waiting else "failed",
                {"code": code, "message": message},
            )
            session.commit()

    def _require_record_lease(
        self,
        record: ModelRunRecord,
        worker_id: str | None,
    ) -> None:
        if worker_id is None:
            return
        if (
            record.status != ModelRunStatus.running.value
            or record.lease_owner != worker_id
        ):
            raise ModelRunLeaseLost(f"Worker no longer owns model run {record.id}.")

    def _compact_deltas(self, session: Session, run_id: str) -> None:
        session.execute(
            delete(ModelRunEventRecord).where(
                ModelRunEventRecord.run_id == run_id,
                ModelRunEventRecord.event_type == "delta",
            )
        )

    def recoverable(self) -> list[tuple[UUID, str]]:
        now = datetime.now(UTC)
        with self.sessions() as session:
            rows = session.scalars(
                select(ModelRunRecord).where(
                    or_(
                        ModelRunRecord.status == ModelRunStatus.queued.value,
                        (ModelRunRecord.status == ModelRunStatus.running.value)
                        & (ModelRunRecord.lease_expires_at < now),
                    )
                )
            ).all()
            return [(UUID(row.id), row.owner_id) for row in rows]

    def _append_event(
        self, session: Session, run_id: str, event_type: str, data: dict[str, Any] | None
    ) -> None:
        sequence = (
            session.scalar(
                select(func.max(ModelRunEventRecord.sequence)).where(
                    ModelRunEventRecord.run_id == run_id
                )
            )
            or 0
        ) + 1
        session.add(
            ModelRunEventRecord(
                run_id=run_id,
                sequence=sequence,
                event_type=event_type,
                data_json=json.dumps(data, ensure_ascii=False) if data is not None else None,
            )
        )

    def _to_dto(self, session: Session, record: ModelRunRecord) -> ModelRunDTO:
        candidates = session.scalars(
            select(ModelRunRecord).where(ModelRunRecord.owner_id == record.owner_id)
        ).all()
        children = [
            row.id
            for row in candidates
            if row.dependency_run_id == record.id
            or json.loads(row.payload_json).get("parentRunId") == record.id
        ]
        return ModelRunDTO(
            id=UUID(record.id),
            kind=record.kind,
            status=record.status,
            conceptId=UUID(record.concept_id) if record.concept_id else None,
            clientDraftId=record.client_draft_id,
            idempotencyKey=record.idempotency_key,
            providerSnapshot=json.loads(record.provider_snapshot_json),
            agentSpec=record.agent_spec,
            agentSpecVersion=record.agent_spec_version,
            promptVersion=record.prompt_version,
            budget=json.loads(record.budget_json),
            currentStep=record.current_step,
            modelCallCount=record.model_call_count,
            toolCallCount=record.tool_call_count,
            terminationReason=record.termination_reason,
            dependencyRunId=UUID(record.dependency_run_id) if record.dependency_run_id else None,
            checkpoint=record.checkpoint,
            result=json.loads(record.result_json) if record.result_json else None,
            resultRef=record.result_ref,
            errorCode=record.error_code,
            errorMessage=record.error_message,
            childRunIds=[UUID(value) for value in children],
            createdAt=_utc_isoformat(record.created_at),
            updatedAt=_utc_isoformat(record.updated_at),
        )


class _RepositoryAgentRunSink:
    def __init__(
        self,
        repository: ModelRunRepository,
        run_id: UUID,
        worker_id: str,
    ) -> None:
        self.repository = repository
        self.run_id = run_id
        self.worker_id = worker_id

    def step_started(self, step: str, label: str) -> None:
        self.repository.harness_step(
            self.run_id,
            step,
            started=True,
            label=label,
            worker_id=self.worker_id,
        )

    def step_completed(self, step: str) -> None:
        self.repository.harness_step(
            self.run_id,
            step,
            started=False,
            worker_id=self.worker_id,
        )

    def usage_updated(self, model_calls: int, tool_calls: int) -> None:
        self.repository.update_usage(
            self.run_id,
            model_calls,
            tool_calls,
            worker_id=self.worker_id,
        )


class ModelRunCoordinator:
    def __init__(
        self, repository: ModelRunRepository, default_service: ConceptService, *, managed: bool
    ) -> None:
        self.repository = repository
        self.default_service = default_service
        self.managed = managed
        self._services: dict[UUID, ConceptService] = {}
        self._tasks: dict[UUID, asyncio.Task[None]] = {}
        self._concept_locks: dict[str, asyncio.Lock] = {}
        self._workers = asyncio.Semaphore(2)
        self._worker_id = str(uuid4())
        self._recovery_task: asyncio.Task[None] | None = None

    def start(self) -> None:
        self.recover()
        if self._recovery_task is None:
            self._recovery_task = asyncio.create_task(self._recovery_loop())

    async def stop(self) -> None:
        if self._recovery_task is None:
            return
        self._recovery_task.cancel()
        try:
            await self._recovery_task
        except asyncio.CancelledError:
            pass
        self._recovery_task = None

    async def _recovery_loop(self) -> None:
        while True:
            await asyncio.sleep(1)
            self.recover()

    def enqueue(self, run: ModelRunDTO, service: ConceptService | None) -> None:
        if service is not None:
            self._services[run.id] = service
        if run.status == ModelRunStatus.waiting_for_credential or run.id in self._tasks:
            return
        self._tasks[run.id] = asyncio.create_task(self._execute(run.id))

    def recover(self) -> None:
        for run_id, owner_id in self.repository.recoverable():
            if run_id in self._tasks:
                continue
            run = self.repository.get(run_id, owner_id)
            if self.managed and run.kind in {ModelRunKind.initial_concept, ModelRunKind.follow_up}:
                self.repository.fail(
                    run_id,
                    "credential_required",
                    "Reconnect to resume this model run.",
                    waiting=True,
                )
            else:
                self.enqueue(run, self.default_service)

    async def _execute(self, run_id: UUID) -> None:
        heartbeat: asyncio.Task[None] | None = None
        try:
            run = self.repository.get(
                run_id, self._services.get(run_id, self.default_service).owner_id
            )
            lock_key = str(run.concept_id or run.id)
            async with self._workers, self._concept_locks.setdefault(lock_key, asyncio.Lock()):
                if not self.repository.begin(run_id, self._worker_id):
                    return
                owner_task = asyncio.current_task()
                assert owner_task is not None
                heartbeat = asyncio.create_task(self._heartbeat(run_id, owner_task))
                service = self._services.get(run_id, self.default_service)
                payload = self.repository.payload(run_id)
                runner = SiftAgentRunner(
                    agent_spec_for_kind(run.kind),
                    _RepositoryAgentRunSink(self.repository, run_id, self._worker_id),
                )
                if run.kind == ModelRunKind.initial_concept:
                    request = CreateConceptRequest.model_validate(payload["capture"])
                    checkpoint, data = self.repository.checkpoint_data(run_id)
                    if checkpoint == "modelCompleted" and data is not None:
                        concept = ConceptDTO.model_validate(data["concept"])
                    else:
                        deltas = _DeltaBuffer(self.repository, run_id, self._worker_id)
                        concept = await runner.prepare_initial(service, request, deltas.add)
                        deltas.flush()
                        data = {"concept": concept.model_dump(mode="json", by_alias=True)}
                        self.repository.checkpoint(
                            run_id,
                            "modelCompleted",
                            data,
                            worker_id=self._worker_id,
                        )
                    self.repository.require_lease(run_id, self._worker_id)
                    store_transaction = getattr(service.store, "transaction", None)
                    if store_transaction is None:
                        result = service.commit_prepared_initial_concept(
                            request, concept, run.idempotency_key
                        )
                        final_data = {
                            "concept": result.model_dump(mode="json", by_alias=True)
                        }
                        self.repository.succeed(
                            run_id,
                            final_data,
                            str(result.id),
                            worker_id=self._worker_id,
                        )
                    else:

                        def commit_initial(_session: Session) -> tuple[Any, dict[str, Any], str]:
                            result = service.commit_prepared_initial_concept(
                                request, concept, run.idempotency_key
                            )
                            final_data = {
                                "concept": result.model_dump(mode="json", by_alias=True)
                            }
                            return result, final_data, str(result.id)

                        self.repository.commit_domain_and_succeed(
                            run_id,
                            worker_id=self._worker_id,
                            transaction=store_transaction,
                            action=commit_initial,
                        )
                elif run.kind == ModelRunKind.follow_up:
                    assert run.concept_id is not None
                    request = ConceptTurnRequest.model_validate(payload["turn"])
                    checkpoint, data = self.repository.checkpoint_data(run_id)
                    if checkpoint == "modelCompleted" and data is not None:
                        prepared = _prepared_turn_from_checkpoint(data)
                    else:
                        deltas = _DeltaBuffer(self.repository, run_id, self._worker_id)
                        prepared = await runner.prepare_follow_up(
                            service,
                            run.concept_id,
                            request,
                            deltas.add,
                        )
                        deltas.flush()
                        data = _prepared_turn_checkpoint(prepared)
                        self.repository.checkpoint(
                            run_id,
                            "modelCompleted",
                            data,
                            worker_id=self._worker_id,
                        )
                    self.repository.require_lease(run_id, self._worker_id)
                    store_transaction = getattr(service.store, "transaction", None)
                    if store_transaction is None:
                        response = service.commit_prepared_turn(
                            run.concept_id, request, prepared, run.idempotency_key
                        )
                        final_data = {
                            "response": response.model_dump(mode="json", by_alias=True)
                        }
                        self.repository.succeed(
                            run_id,
                            final_data,
                            str(run.concept_id),
                            worker_id=self._worker_id,
                        )
                    else:

                        def commit_follow_up(
                            _session: Session,
                        ) -> tuple[Any, dict[str, Any], str]:
                            response = service.commit_prepared_turn(
                                run.concept_id,
                                request,
                                prepared,
                                run.idempotency_key,
                            )
                            final_data = {
                                "response": response.model_dump(mode="json", by_alias=True)
                            }
                            return response, final_data, str(run.concept_id)

                        self.repository.commit_domain_and_succeed(
                            run_id,
                            worker_id=self._worker_id,
                            transaction=store_transaction,
                            action=commit_follow_up,
                        )
                    self._schedule_maintenance(run, service)
                elif run.kind == ModelRunKind.continuity_summary:
                    await self._run_summary(run_id, run, service, runner)
                else:
                    await self._run_review(run_id, run, service, runner)
        except ModelRunLeaseLost:
            return
        except AgentBudgetExceeded:
            if self.repository.owns_lease(run_id, self._worker_id):
                self.repository.fail(
                    run_id,
                    "agent_budget_exceeded",
                    "The agent stopped at its configured execution limit.",
                    worker_id=self._worker_id,
                )
        except HTTPException as error:
            detail = (
                error.detail if isinstance(error.detail, dict) else {"message": str(error.detail)}
            )
            if self.repository.owns_lease(run_id, self._worker_id):
                self.repository.fail(
                    run_id,
                    str(detail.get("code", "model_run_failed")),
                    str(detail.get("message", detail)),
                    worker_id=self._worker_id,
                )
        except Exception:
            if self.repository.owns_lease(run_id, self._worker_id):
                self.repository.fail(
                    run_id,
                    "model_run_failed",
                    "The model run could not be completed.",
                    worker_id=self._worker_id,
                )
        finally:
            if heartbeat is not None:
                heartbeat.cancel()
                try:
                    await heartbeat
                except asyncio.CancelledError:
                    pass
            self._enqueue_dependents(run_id)
            self._services.pop(run_id, None)
            self._tasks.pop(run_id, None)

    async def _heartbeat(self, run_id: UUID, owner_task: asyncio.Task[None]) -> None:
        while True:
            await asyncio.sleep(LEASE_HEARTBEAT_SECONDS)
            if not self.repository.renew_lease(run_id, self._worker_id):
                owner_task.cancel()
                return

    def _enqueue_dependents(self, run_id: UUID) -> None:
        service = self._services.get(run_id, self.default_service)
        run = self.repository.get(run_id, service.owner_id)
        if run.status not in {ModelRunStatus.succeeded, ModelRunStatus.failed}:
            return
        for child_id in run.child_run_ids:
            child = self.repository.get(child_id, service.owner_id)
            if child.dependency_run_id == run_id:
                self.enqueue(child, self._services.get(child_id, service))

    def _schedule_maintenance(self, parent: ModelRunDTO, service: ConceptService) -> None:
        if parent.concept_id is None:
            return
        with self.repository.sessions() as session:
            turns = session.scalars(
                select(TurnRecord)
                .where(TurnRecord.concept_id == str(parent.concept_id))
                .order_by(TurnRecord.id)
            ).all()
            user_turns = [row for row in turns if row.role == "user"]
            summary = session.get(ConceptContinuitySummaryRecord, str(parent.concept_id))
            new_summary_turns = (
                len(turns)
                if summary is None
                else sum(row.id > summary.through_turn_id for row in turns)
            )
            summary_due = len(turns) >= 12 and (
                summary is None or new_summary_turns >= 6
            )
            state = session.get(ConceptMaintenanceStateRecord, str(parent.concept_id))
            reviewed_id = state.last_reviewed_turn_id if state else None
            followups = [
                row for row in user_turns[1:] if reviewed_id is None or row.id > reviewed_id
            ]
            review_due = len(followups) >= 5
            pending_proposal = session.scalar(
                select(UpdateProposalRecord.id).where(
                    UpdateProposalRecord.concept_id == str(parent.concept_id),
                    UpdateProposalRecord.status == "proposed",
                )
            )
            active_review = session.scalar(
                select(ModelRunRecord.id).where(
                    ModelRunRecord.concept_id == str(parent.concept_id),
                    ModelRunRecord.kind == ModelRunKind.knowledge_review.value,
                    ModelRunRecord.status.in_(ACTIVE_STATUSES),
                )
            )
            if review_due and (pending_proposal is not None or active_review is not None):
                if state is None:
                    state = ConceptMaintenanceStateRecord(
                        concept_id=str(parent.concept_id),
                        owner_id=service.owner_id,
                    )
                    session.add(state)
                state.review_due = True
                session.commit()
                review_due = False
        dependency = None
        if summary_due:
            child, created = self.repository.create(
                owner_id=service.owner_id,
                kind=ModelRunKind.continuity_summary,
                idempotency_key=f"summary:{parent.concept_id}:{turns[-1].id}",
                payload={"conceptId": str(parent.concept_id), "parentRunId": str(parent.id)},
                concept_id=parent.concept_id,
            )
            dependency = child.id
            if created:
                self.enqueue(child, service)
        if review_due:
            child, created = self.repository.create(
                owner_id=service.owner_id,
                kind=ModelRunKind.knowledge_review,
                idempotency_key=f"review:{parent.concept_id}:{followups[-1].id}",
                payload={"conceptId": str(parent.concept_id), "parentRunId": str(parent.id)},
                concept_id=parent.concept_id,
                dependency_run_id=dependency,
            )
            if created:
                if dependency is None:
                    self.enqueue(child, service)
                else:
                    self._services[child.id] = service

    async def _run_summary(
        self,
        run_id: UUID,
        run: ModelRunDTO,
        service: ConceptService,
        runner: SiftAgentRunner,
    ) -> None:
        assert run.concept_id is not None
        with self.repository.sessions() as session:
            turns = session.scalars(
                select(TurnRecord)
                .where(TurnRecord.concept_id == str(run.concept_id))
                .order_by(TurnRecord.id)
            ).all()
            source = turns[:-6]
            digest = hashlib.sha256(
                "\n".join(f"{row.id}:{row.role}:{row.content}" for row in source).encode()
            ).hexdigest()
        source_turns = [
            (
                row.id,
                RecentTurn(
                    role=row.role,
                    content=row.content,
                    answer_source_json=row.answer_source_json,
                ),
            )
            for row in source
        ]
        result = await runner.summarize(
            service,
            service.get_concept(run.concept_id),
            source_turns,
        )
        summary = result.model_dump(mode="json", by_alias=True)
        def commit_summary(session: Session) -> tuple[dict[str, Any], dict[str, Any], None]:
            record = session.get(ConceptContinuitySummaryRecord, str(run.concept_id))
            if record is None:
                record = ConceptContinuitySummaryRecord(
                    concept_id=str(run.concept_id),
                    owner_id=service.owner_id,
                    summary_json="{}",
                    through_turn_id=0,
                    source_turns_hash="",
                )
                session.add(record)
            record.owner_id = service.owner_id
            record.summary_json = json.dumps(summary, ensure_ascii=False)
            record.through_turn_id = turns[-1].id if turns else 0
            record.source_turns_hash = digest
            record.version = (record.version or 0) + 1
            record.generated_at = datetime.now(UTC)
            result_data = {"summary": summary}
            return summary, result_data, None

        self.repository.commit_domain_and_succeed(
            run_id,
            worker_id=self._worker_id,
            action=commit_summary,
        )

    async def _run_review(
        self,
        run_id: UUID,
        run: ModelRunDTO,
        service: ConceptService,
        runner: SiftAgentRunner,
    ) -> None:
        assert run.concept_id is not None
        self.repository.require_lease(run_id, self._worker_id)
        with self.repository.sessions() as session:
            latest_user = session.scalar(
                select(func.max(TurnRecord.id)).where(
                    TurnRecord.concept_id == str(run.concept_id), TurnRecord.role == "user"
                )
            )
            pending = session.scalar(
                select(UpdateProposalRecord.id).where(
                    UpdateProposalRecord.concept_id == str(run.concept_id),
                    UpdateProposalRecord.status == "proposed",
                )
            )
            state = session.get(ConceptMaintenanceStateRecord, str(run.concept_id))
            if pending:
                def commit_deferred_review(
                    terminal_session: Session,
                ) -> tuple[None, dict[str, Any], None]:
                    terminal_state = terminal_session.get(
                        ConceptMaintenanceStateRecord,
                        str(run.concept_id),
                    )
                    if terminal_state is None:
                        terminal_state = ConceptMaintenanceStateRecord(
                            concept_id=str(run.concept_id),
                            owner_id=service.owner_id,
                        )
                        terminal_session.add(terminal_state)
                    terminal_state.review_due = True
                    return None, {"proposal": None, "deferred": True}, None

                self.repository.commit_domain_and_succeed(
                    run_id,
                    worker_id=self._worker_id,
                    action=commit_deferred_review,
                )
                return
            reviewed_id = state.last_reviewed_turn_id if state is not None else 0
            rows = session.scalars(
                select(TurnRecord)
                .where(
                    TurnRecord.concept_id == str(run.concept_id),
                    TurnRecord.id > reviewed_id,
                )
                .order_by(TurnRecord.id)
            ).all()
            summary = session.get(ConceptContinuitySummaryRecord, str(run.concept_id))
            card_memory = summary.summary_json if summary is not None else ""

        concept = service.get_concept(run.concept_id)
        recent_turns = [
            RecentTurn(
                role=row.role,
                content=row.content,
                answer_source_json=row.answer_source_json,
            )
            for row in rows[-10:]
        ]
        result = await runner.review(
            service,
            concept,
            recent_turns,
            card_memory,
        )
        self.repository.require_lease(run_id, self._worker_id)
        proposal = None
        if result.proposal is not None:
            unlocked_ids = {block.id for block in concept.blocks if not block.is_user_locked}
            operations = [
                operation
                for operation in result.proposal.patch_operations
                if isinstance(operation, (AppendPatchOperation, ReplacePatchOperation))
                and operation.target_block_id in unlocked_ids
            ]
            if operations:
                proposal = UpdateProposalDTO(
                    id=uuid4(),
                    baseNoteRevision=concept.note_revision,
                    patchOperations=operations,
                    rationale=result.proposal.rationale,
                    confidence=0.7,
                    status="proposed",
                    origin="periodicReview",
                    sourceRunId=run_id,
                )

        def commit_review(
            session: Session,
        ) -> tuple[UpdateProposalDTO | None, dict[str, Any], None]:
            if proposal is not None:
                service.store.save_proposal(proposal, concept_id=concept.id)
            state = session.get(ConceptMaintenanceStateRecord, str(run.concept_id))
            if state is None:
                state = ConceptMaintenanceStateRecord(
                    concept_id=str(run.concept_id),
                    owner_id=service.owner_id,
                )
                session.add(state)
            state.last_reviewed_turn_id = latest_user
            state.review_due = False
            result_data = {
                "proposal": (
                    proposal.model_dump(mode="json", by_alias=True)
                    if proposal is not None
                    else None
                ),
                "reviewedThroughTurnId": latest_user,
            }
            return proposal, result_data, None

        store_transaction = getattr(service.store, "transaction", None)
        self.repository.commit_domain_and_succeed(
            run_id,
            worker_id=self._worker_id,
            transaction=store_transaction,
            action=commit_review,
        )

    def reconsider_review(self, concept_id: UUID, service: ConceptService) -> None:
        with self.repository.sessions() as session:
            state = session.get(ConceptMaintenanceStateRecord, str(concept_id))
            if state is None or not state.review_due:
                return
            latest_user = session.scalar(
                select(func.max(TurnRecord.id)).where(
                    TurnRecord.concept_id == str(concept_id), TurnRecord.role == "user"
                )
            )
        if latest_user is None:
            return
        run, created = self.repository.create(
            owner_id=service.owner_id,
            kind=ModelRunKind.knowledge_review,
            idempotency_key=f"review:{concept_id}:{latest_user}:retry:{uuid4()}",
            payload={"conceptId": str(concept_id)},
            concept_id=concept_id,
        )
        if created:
            self.enqueue(run, service)


class _DeltaBuffer:
    def __init__(
        self,
        repository: ModelRunRepository,
        run_id: UUID,
        worker_id: str,
    ) -> None:
        self.repository = repository
        self.run_id = run_id
        self.worker_id = worker_id
        self.parts: list[str] = []
        self.size = 0
        self.last_flush = time.monotonic()

    def add(self, content: str) -> None:
        self.parts.append(content)
        self.size += len(content)
        if self.size >= 512 or time.monotonic() - self.last_flush >= 0.25:
            self.flush()

    def flush(self) -> None:
        if not self.parts:
            return
        self.repository.delta(
            self.run_id,
            "".join(self.parts),
            worker_id=self.worker_id,
        )
        self.parts.clear()
        self.size = 0
        self.last_flush = time.monotonic()


def _prepared_turn_checkpoint(prepared: PreparedTurnResult) -> dict[str, Any]:
    if prepared.regenerated_concept is not None:
        return {
            "mode": "regenerate",
            "baseNoteRevision": prepared.base_note_revision,
            "concept": prepared.regenerated_concept.model_dump(mode="json", by_alias=True),
        }
    if prepared.turn_result is None:
        raise ValueError("Prepared turn has no model result.")
    return {
        "mode": "turn",
        "baseNoteRevision": prepared.base_note_revision,
        "result": prepared.turn_result.model_dump(mode="json", by_alias=True),
    }


def _prepared_turn_from_checkpoint(data: dict[str, Any]) -> PreparedTurnResult:
    if data.get("mode") == "regenerate":
        return PreparedTurnResult(
            base_note_revision=int(data["baseNoteRevision"]),
            regenerated_concept=ConceptDTO.model_validate(data["concept"]),
        )
    return PreparedTurnResult(
        base_note_revision=int(data["baseNoteRevision"]),
        turn_result=ConceptTurnResult.model_validate(data["result"]),
    )
