from datetime import UTC, datetime, timedelta

from scripts.model_run_metrics import collect_model_run_metrics
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from sift_backend.persistence.database import initialize_database
from sift_backend.persistence.models import (
    CaptureAttemptRecord,
    ConceptMaintenanceStateRecord,
    ConceptRecord,
    ModelRunEventRecord,
    ModelRunRecord,
    TurnRecord,
    UpdateEventRecord,
    UpdateProposalRecord,
)


def test_metrics_are_aggregate_and_do_not_expose_stored_content_or_secrets() -> None:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    initialize_database(engine)
    sessions = sessionmaker(bind=engine, expire_on_commit=False)
    now = datetime(2033, 1, 2, tzinfo=UTC)

    with sessions() as session:
        session.add_all(
            [
                _concept("concept-1", created_at=now - timedelta(days=10)),
                _concept("concept-2", created_at=now - timedelta(days=2)),
            ]
        )
        session.add_all(
            [
                _capture("capture-success", "succeeded", concept_id="concept-1"),
                _capture("capture-failed", "failed"),
                _capture("capture-active", "generating"),
                _turn("concept-1", now - timedelta(days=10), "initial"),
                _turn("concept-1", now - timedelta(days=8), "follow-up-1"),
                _turn("concept-1", now - timedelta(days=1), "follow-up-2"),
                _turn("concept-2", now - timedelta(days=2), "initial-2"),
            ]
        )
        session.add_all(
            [
                _run(
                    "run-success",
                    status="succeeded",
                    started_at=now - timedelta(seconds=2),
                    completed_at=now - timedelta(milliseconds=500),
                    result_json='{"answer":"SECRET-KNOWLEDGE"}',
                ),
                _run(
                    "run-failed",
                    status="failed",
                    started_at=now - timedelta(seconds=4),
                    completed_at=now - timedelta(seconds=1),
                    error_message="SECRET-PROVIDER-KEY",
                ),
                _run(
                    "run-expired",
                    status="running",
                    lease_expires_at=now - timedelta(seconds=1),
                ),
                _run("run-missing-result", status="succeeded", completed_at=now),
            ]
        )
        session.add_all(
            [
                _event("run-success", 1, "started"),
                _event("run-success", 2, "started"),
                _event("run-success", 3, "completed"),
                _event("run-success", 4, "completed"),
                _event("run-failed", 1, "failed"),
            ]
        )
        session.add(
            UpdateProposalRecord(
                id="proposal-periodic",
                concept_id="concept-1",
                base_note_revision=1,
                patch_operations_json='[{"content":"SECRET-PROPOSAL"}]',
                rationale="SECRET-RATIONALE",
                confidence=0.8,
                status="proposed",
                origin="periodicReview",
            )
        )
        session.add_all(
            [
                _periodic_proposal("proposal-accepted", "accepted", "concept-1"),
                _periodic_proposal("proposal-dismissed", "dismissed", "concept-2"),
            ]
        )
        session.add(
            ConceptMaintenanceStateRecord(
                concept_id="concept-1",
                owner_id="owner-1",
                review_due=True,
            )
        )
        session.add(
            UpdateEventRecord(
                id="restore-event",
                concept_id="concept-1",
                note_revision=2,
                event_type="revisionRestore",
                actor="user",
            )
        )
        session.commit()

    metrics = collect_model_run_metrics(sessions, now=now)
    rendered = str(metrics)

    assert metrics["runs"]["total"] == 4
    assert metrics["runs"]["terminalSuccessRate"] == 0.6667
    assert metrics["latencyMs"] == {"sampleCount": 2, "p50": 1500, "p95": 3000}
    assert metrics["recovery"]["runsWithMultipleStarts"] == 1
    assert metrics["integrity"] == {
        "expiredActiveLeases": 1,
        "succeededWithoutResult": 1,
        "runsWithDuplicateTerminalEvents": 1,
    }
    assert metrics["maintenance"]["reviewsDue"] == 1
    assert metrics["maintenance"]["periodicProposals"] == {
        "accepted": 1,
        "dismissed": 1,
        "proposed": 1,
    }
    assert metrics["maintenance"]["periodicProposalDecisionRate"] == 0.6667
    assert metrics["maintenance"]["periodicProposalAcceptanceRate"] == 0.5
    assert metrics["productUsage"] == {
        "captures": {
            "total": 3,
            "byStatus": {"failed": 1, "generating": 1, "succeeded": 1},
            "terminalSuccessRate": 0.5,
        },
        "concepts": {
            "total": 2,
            "withFollowUps": 1,
            "withFollowUpAfter7Days": 1,
        },
        "followUpsPerConcept": {
            "total": 2,
            "average": 1.0,
            "p50": 0,
            "p95": 2,
        },
        "revisionRestores": 1,
    }
    assert "SECRET" not in rendered


def _concept(concept_id: str, *, created_at: datetime) -> ConceptRecord:
    return ConceptRecord(
        id=concept_id,
        owner_id="owner-1",
        canonical_title="SECRET-TITLE",
        display_title="SECRET-TITLE",
        one_line_explanation="SECRET-EXPLANATION",
        maturity="seed",
        capture_status="ready",
        created_at=created_at,
    )


def _capture(
    attempt_id: str, status: str, *, concept_id: str | None = None
) -> CaptureAttemptRecord:
    return CaptureAttemptRecord(
        id=attempt_id,
        owner_id="owner-1",
        idempotency_key=attempt_id,
        payload_hash="1" * 64,
        raw_capture="SECRET-CAPTURE",
        locale="zh-CN",
        status=status,
        concept_id=concept_id,
        failure_message="SECRET-CAPTURE-FAILURE" if status == "failed" else None,
    )


def _turn(concept_id: str, created_at: datetime, operation_key: str) -> TurnRecord:
    return TurnRecord(
        concept_id=concept_id,
        role="user",
        content="SECRET-TURN",
        operation_key=operation_key,
        created_at=created_at,
    )


def _periodic_proposal(
    proposal_id: str, status: str, concept_id: str
) -> UpdateProposalRecord:
    return UpdateProposalRecord(
        id=proposal_id,
        concept_id=concept_id,
        base_note_revision=1,
        patch_operations_json='[{"content":"SECRET-PROPOSAL"}]',
        rationale="SECRET-RATIONALE",
        confidence=0.8,
        status=status,
        origin="periodicReview",
    )


def _run(
    run_id: str,
    *,
    status: str,
    started_at=None,
    completed_at=None,
    lease_expires_at=None,
    result_json=None,
    error_message=None,
) -> ModelRunRecord:
    return ModelRunRecord(
        id=run_id,
        owner_id="owner-1",
        kind="followUp",
        status=status,
        idempotency_key=run_id,
        payload_hash="0" * 64,
        payload_json='{"question":"SECRET-QUESTION"}',
        provider_snapshot_json="{}",
        started_at=started_at,
        completed_at=completed_at,
        lease_expires_at=lease_expires_at,
        result_json=result_json,
        error_message=error_message,
    )


def _event(run_id: str, sequence: int, event_type: str) -> ModelRunEventRecord:
    return ModelRunEventRecord(
        run_id=run_id,
        sequence=sequence,
        event_type=event_type,
        data_json='{"content":"SECRET-DELTA"}',
    )
