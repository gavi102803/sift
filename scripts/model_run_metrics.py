#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import math
import sys
from collections import Counter
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.exc import SQLAlchemyError

ROOT = Path(__file__).resolve().parents[1]
BACKEND_SRC = ROOT / "backend" / "src"
if str(BACKEND_SRC) not in sys.path:
    sys.path.insert(0, str(BACKEND_SRC))

from sift_backend.config import load_settings  # noqa: E402
from sift_backend.persistence.database import create_session_factory  # noqa: E402
from sift_backend.persistence.models import (  # noqa: E402
    CaptureAttemptRecord,
    ConceptRecord,
    ConceptContinuitySummaryRecord,
    ConceptMaintenanceStateRecord,
    ModelRunEventRecord,
    ModelRunRecord,
    TurnRecord,
    UpdateEventRecord,
    UpdateProposalRecord,
)

ACTIVE_STATUSES = {"queued", "waitingForCredential", "running"}
TERMINAL_EVENT_TYPES = {"completed", "failed"}


def collect_model_run_metrics(session_factory, *, now: datetime | None = None) -> dict[str, Any]:
    with session_factory() as session:
        runs = session.execute(
            select(
                ModelRunRecord.id,
                ModelRunRecord.kind,
                ModelRunRecord.status,
                ModelRunRecord.started_at,
                ModelRunRecord.completed_at,
                ModelRunRecord.lease_expires_at,
                ModelRunRecord.result_json.is_not(None).label("has_result"),
            )
        ).all()
        events = session.execute(
            select(ModelRunEventRecord.run_id, ModelRunEventRecord.event_type)
        ).all()
        periodic_proposals = session.execute(
            select(UpdateProposalRecord.status).where(
                UpdateProposalRecord.origin == "periodicReview"
            )
        ).scalars().all()
        summary_count = session.scalar(select(func.count(ConceptContinuitySummaryRecord.concept_id)))
        review_due_count = session.scalar(
            select(func.count(ConceptMaintenanceStateRecord.concept_id)).where(
                ConceptMaintenanceStateRecord.review_due.is_(True)
            )
        )
        capture_statuses = session.execute(select(CaptureAttemptRecord.status)).scalars().all()
        concepts = session.execute(
            select(ConceptRecord.id, ConceptRecord.created_at)
        ).all()
        user_turns = session.execute(
            select(TurnRecord.concept_id, TurnRecord.created_at)
            .where(TurnRecord.role == "user")
            .order_by(TurnRecord.concept_id, TurnRecord.created_at, TurnRecord.id)
        ).all()
        revision_restore_count = session.scalar(
            select(func.count(UpdateEventRecord.id)).where(
                UpdateEventRecord.event_type == "revisionRestore"
            )
        )

    statuses = Counter(row.status for row in runs)
    kinds = Counter(row.kind for row in runs)
    terminal_count = statuses["succeeded"] + statuses["failed"]
    durations = sorted(
        (row.completed_at - row.started_at).total_seconds() * 1000
        for row in runs
        if row.started_at is not None
        and row.completed_at is not None
        and row.completed_at >= row.started_at
    )
    event_counts: Counter[tuple[str, str]] = Counter(
        (row.run_id, row.event_type) for row in events
    )
    current_time = now or datetime.now()
    capture_counts = Counter(capture_statuses)
    terminal_captures = capture_counts["succeeded"] + capture_counts["failed"]
    concept_created_at = {row.id: row.created_at for row in concepts}
    turns_by_concept: dict[str, list[datetime]] = {}
    for row in user_turns:
        turns_by_concept.setdefault(row.concept_id, []).append(row.created_at)
    follow_up_counts = sorted(
        max(len(turns_by_concept.get(concept_id, [])) - 1, 0)
        for concept_id in concept_created_at
    )
    periodic_proposal_counts = Counter(periodic_proposals)
    decided_proposals = (
        periodic_proposal_counts["accepted"] + periodic_proposal_counts["dismissed"]
    )

    return {
        "runs": {
            "total": len(runs),
            "byKind": dict(sorted(kinds.items())),
            "byStatus": dict(sorted(statuses.items())),
            "terminalSuccessRate": (
                round(statuses["succeeded"] / terminal_count, 4) if terminal_count else None
            ),
        },
        "latencyMs": {
            "sampleCount": len(durations),
            "p50": _percentile(durations, 0.50),
            "p95": _percentile(durations, 0.95),
        },
        "recovery": {
            "runsWithMultipleStarts": sum(
                1 for (run_id, event_type), count in event_counts.items()
                if event_type == "started" and count > 1
            ),
        },
        "integrity": {
            "expiredActiveLeases": sum(
                1
                for row in runs
                if row.status in ACTIVE_STATUSES
                and row.lease_expires_at is not None
                and _is_before(row.lease_expires_at, current_time)
            ),
            "succeededWithoutResult": sum(
                1 for row in runs if row.status == "succeeded" and not row.has_result
            ),
            "runsWithDuplicateTerminalEvents": len(
                {
                    run_id
                    for (run_id, event_type), count in event_counts.items()
                    if event_type in TERMINAL_EVENT_TYPES and count > 1
                }
            ),
        },
        "maintenance": {
            "continuitySummaries": int(summary_count or 0),
            "reviewsDue": int(review_due_count or 0),
            "periodicProposals": dict(sorted(periodic_proposal_counts.items())),
            "periodicProposalDecisionRate": (
                round(decided_proposals / len(periodic_proposals), 4)
                if periodic_proposals
                else None
            ),
            "periodicProposalAcceptanceRate": (
                round(periodic_proposal_counts["accepted"] / decided_proposals, 4)
                if decided_proposals
                else None
            ),
        },
        "productUsage": {
            "captures": {
                "total": len(capture_statuses),
                "byStatus": dict(sorted(capture_counts.items())),
                "terminalSuccessRate": (
                    round(capture_counts["succeeded"] / terminal_captures, 4)
                    if terminal_captures
                    else None
                ),
            },
            "concepts": {
                "total": len(concepts),
                "withFollowUps": sum(count > 0 for count in follow_up_counts),
                "withFollowUpAfter7Days": sum(
                    _has_follow_up_after(
                        turns_by_concept.get(concept_id, []),
                        created_at + timedelta(days=7),
                    )
                    for concept_id, created_at in concept_created_at.items()
                ),
            },
            "followUpsPerConcept": {
                "total": sum(follow_up_counts),
                "average": (
                    round(sum(follow_up_counts) / len(follow_up_counts), 2)
                    if follow_up_counts
                    else None
                ),
                "p50": _percentile(follow_up_counts, 0.50),
                "p95": _percentile(follow_up_counts, 0.95),
            },
            "revisionRestores": int(revision_restore_count or 0),
        },
    }


def _percentile(values: list[float], percentile: float) -> int | None:
    if not values:
        return None
    index = max(0, math.ceil(len(values) * percentile) - 1)
    return round(values[index])


def _is_before(value: datetime, reference: datetime) -> bool:
    if value.tzinfo is None:
        reference = reference.replace(tzinfo=None)
    elif reference.tzinfo is None:
        reference = reference.replace(tzinfo=value.tzinfo)
    return value < reference


def _has_follow_up_after(user_turns: list[datetime], threshold: datetime) -> bool:
    return any(not _is_before(turn, threshold) for turn in user_turns[1:])


def _resolved_database_url(value: str) -> str:
    prefix = "sqlite:///"
    if not value.startswith(prefix):
        return value
    raw_path = value.removeprefix(prefix)
    if raw_path in {"", ":memory:"} or Path(raw_path).is_absolute():
        return value
    return prefix + str((ROOT / "backend" / raw_path).resolve())


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Print privacy-safe aggregate reliability and product-usage metrics for Sift."
    )
    parser.add_argument("--database-url", help="Override the configured Sift database URL.")
    args = parser.parse_args()
    database_url = _resolved_database_url(args.database_url or load_settings().database_url)
    try:
        metrics = collect_model_run_metrics(
            create_session_factory(database_url, initialize_schema=False)
        )
    except SQLAlchemyError:
        print("ModelRun metrics unavailable: database query failed.", file=sys.stderr)
        return 1
    print(json.dumps(metrics, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
