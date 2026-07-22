#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
import urllib.error
import urllib.request
from collections import Counter
from pathlib import Path
from typing import Any, Callable
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
TERMINAL_STATUSES = {"succeeded", "failed"}
MARKER = "SIFT-CONTINUITY-ANCHOR-7F3A"
LEGACY_QUESTIONS_HASH = "0855f2272ec522dbc249e02e846713ef73c7ab6e2060f533a24e198d675e81c3"
QUESTIONS = [
    "请用一句话说明这张卡当前最重要的结论。",
    "这个结论最容易被误解的地方是什么？",
    "给我一个可以实际应用它的例子。",
    "刚才的例子在哪些条件下不成立？",
    "把目前的理解拆成三个层次。",
    "我已经确认理解了基础定义，请记住这一点。",
    "接下来还有哪个关键问题没有解决？",
    "比较两个可能相冲突的解释。",
    "用反例检查我们当前的理解。",
    "把目前讨论压缩成一个决策原则。",
    "如果以后继续研究，第一步应该做什么？",
    "不要查看外部资料：请在回答中明确写出首卡里约定的连续性标记。",
    "结合早期讨论，指出当前卡片最需要补充的一点。",
    "哪些内容来自我的上下文，哪些只是一般解释？",
    "列出一个仍然存在的不确定性。",
    "现在换一个角度解释，但不要推翻已确认的理解。",
    "检查最近几轮是否出现重复误区。",
    "提出一个能检验这张卡是否真正有用的问题。",
    "给出下一次回访这张卡时应该先看的内容。",
    "总结二十轮讨论后，哪些内容值得进入长期卡片，哪些不值得？",
]


class DogfoodError(RuntimeError):
    pass


class DogfoodSession:
    def __init__(
        self,
        *,
        backend_url: str,
        state_path: Path,
        request_timeout: float,
        recovery_timeout: float,
    ) -> None:
        self.backend_url = backend_url.rstrip("/")
        self.state_path = state_path
        self.request_timeout = request_timeout
        self.recovery_timeout = recovery_timeout
        self.state = self._load_or_create_state()

    def run(
        self,
        *,
        confirm_live_cost: bool,
        retry_failed_runs: bool = False,
    ) -> dict[str, Any]:
        app_status = self.request("GET", "/v1/app-status")
        provider = str(app_status["modelProvider"])
        if provider != "mock" and not confirm_live_cost:
            raise DogfoodError(
                f"Backend provider is {provider}; rerun with --confirm-live-cost to authorize "
                "20+ external model calls."
            )

        concept_run = self._ensure_initial_run()
        concept_id = str(concept_run.get("resultRef") or concept_run.get("conceptId") or "")
        if not concept_id:
            raise DogfoodError("Initial ModelRun succeeded without a concept reference.")
        self.state["conceptId"] = concept_id
        self._save_state()

        parent_runs = [concept_run]
        parent_runs.extend(
            self._wait_for_run(str(run_id))
            for run_id in self.state["turnRunIds"][: int(self.state["completedFollowUps"])]
        )
        start = int(self.state["completedFollowUps"])
        for index in range(start, len(QUESTIONS)):
            run = self._ensure_follow_up(
                index,
                concept_id,
                retry_failed_runs=retry_failed_runs,
            )
            parent_runs.append(run)
            if index == 11 and provider != "mock":
                answer = str(((run.get("result") or {}).get("response") or {}).get("answer", ""))
                self.state["earlyContextRecallPassed"] = MARKER in answer
            self.state["completedFollowUps"] = index + 1
            self.state["pendingTurnIndex"] = None
            self.state["pendingRunId"] = None
            self._save_state()
            print(f"follow-up {index + 1}/{len(QUESTIONS)} succeeded", file=sys.stderr)

        replay = self._post_follow_up(len(QUESTIONS) - 1, concept_id)
        if str(replay["id"]) != str(parent_runs[-1]["id"]):
            raise DogfoodError("Idempotent replay returned a different ModelRun.")

        maintenance = self._wait_for_children(parent_runs)
        turns = self.request("GET", f"/v1/concepts/{concept_id}/turns")
        expected_turns = 2 + 2 * len(QUESTIONS)
        event_integrity = self._event_integrity(parent_runs + maintenance)
        maintenance_by_kind = {
            kind: dict(
                sorted(Counter(run["status"] for run in maintenance if run["kind"] == kind).items())
            )
            for kind in sorted({str(run["kind"]) for run in maintenance})
        }
        maintenance_passed = bool(maintenance) and all(
            run["status"] == "succeeded" for run in maintenance
        ) and any(
            run["kind"] == "continuitySummary" and run["status"] == "succeeded"
            for run in maintenance
        )
        summary = {
            "provider": provider,
            "conceptId": concept_id,
            "followUpsRequested": len(QUESTIONS),
            "followUpsSucceeded": int(self.state["completedFollowUps"]),
            "persistedTurns": len(turns),
            "expectedTurns": expected_turns,
            "idempotentReplayPassed": True,
            "earlyContextRecallPassed": self.state.get("earlyContextRecallPassed"),
            "transientNetworkFailures": int(self.state["transientNetworkFailures"]),
            "maintenanceRuns": maintenance_by_kind,
            "maintenancePassed": maintenance_passed,
            "eventIntegrityPassed": event_integrity,
        }
        summary["passed"] = bool(
            summary["followUpsSucceeded"] == len(QUESTIONS)
            and summary["persistedTurns"] == expected_turns
            and event_integrity
            and maintenance_passed
            and (provider == "mock" or summary["earlyContextRecallPassed"] is True)
        )
        return summary

    def request(
        self,
        method: str,
        path: str,
        *,
        body: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
    ) -> Any:
        deadline = time.monotonic() + self.recovery_timeout
        while True:
            request = urllib.request.Request(
                self.backend_url + path,
                data=json.dumps(body).encode() if body is not None else None,
                headers={"Content-Type": "application/json", **(headers or {})},
                method=method,
            )
            try:
                with urllib.request.urlopen(request, timeout=self.request_timeout) as response:
                    return json.loads(response.read())
            except urllib.error.HTTPError as error:
                if error.code not in {502, 503, 504}:
                    raise DogfoodError(f"HTTP {error.code} for {method} {path}.") from error
                self._wait_after_transient_failure(error, deadline)
            except (TimeoutError, OSError, urllib.error.URLError) as error:
                self._wait_after_transient_failure(error, deadline)

    def _wait_after_transient_failure(self, error: Exception, deadline: float) -> None:
        self.state["transientNetworkFailures"] += 1
        self._save_state()
        if time.monotonic() >= deadline:
            raise DogfoodError(
                f"Backend did not recover within {self.recovery_timeout:g} seconds."
            ) from error
        time.sleep(0.5)

    def _ensure_initial_run(self) -> dict[str, Any]:
        run_id = self.state.get("conceptRunId")
        if run_id:
            return self._wait_for_run(str(run_id))
        created = self.request(
            "POST",
            "/v1/concept-runs",
            headers={"Idempotency-Key": f"{self.state['sessionId']}-initial"},
            body={
                "capture": {
                    "rawCapture": (
                        "这是 Sift 长期上下文恢复 dogfood。请在后续对话中保留标记 " + MARKER
                    ),
                    "locale": "zh-CN",
                },
                "clientDraftId": f"dogfood-{self.state['sessionId']}",
            },
        )
        self.state["conceptRunId"] = str(created["id"])
        self._save_state()
        return self._wait_for_run(str(created["id"]))

    def _ensure_follow_up(
        self,
        index: int,
        concept_id: str,
        *,
        retry_failed_runs: bool,
    ) -> dict[str, Any]:
        existing_id = None
        if self.state.get("pendingTurnIndex") == index and self.state.get("pendingRunId"):
            existing_id = str(self.state["pendingRunId"])
        elif index < len(self.state["turnRunIds"]):
            existing_id = str(self.state["turnRunIds"][index])
        if existing_id is not None:
            existing = self.request("GET", f"/v1/model-runs/{existing_id}")
            if existing["status"] != "failed" or not retry_failed_runs:
                return self._wait_for_run(existing_id)
            attempts = self.state["turnAttemptCounts"]
            attempts[str(index)] = int(attempts.get(str(index), 0)) + 1
        created = self._post_follow_up(index, concept_id)
        self.state["pendingTurnIndex"] = index
        self.state["pendingRunId"] = str(created["id"])
        if index == len(self.state["turnRunIds"]):
            self.state["turnRunIds"].append(str(created["id"]))
        elif index < len(self.state["turnRunIds"]):
            self.state["turnRunIds"][index] = str(created["id"])
        else:
            raise DogfoodError("State file has a non-contiguous turn run sequence.")
        self._save_state()
        return self._wait_for_run(str(created["id"]))

    def _post_follow_up(self, index: int, concept_id: str) -> dict[str, Any]:
        return self.request(
            "POST",
            f"/v1/concepts/{concept_id}/turn-runs",
            headers={"Idempotency-Key": self._turn_idempotency_key(index)},
            body={"turn": {"question": QUESTIONS[index]}},
        )

    def _turn_idempotency_key(self, index: int) -> str:
        attempt = int(self.state["turnAttemptCounts"].get(str(index), 0))
        suffix = f"-retry-{attempt}" if attempt else ""
        return f"{self.state['sessionId']}-turn-{index}{suffix}"

    def _wait_for_run(self, run_id: str) -> dict[str, Any]:
        deadline = time.monotonic() + self.recovery_timeout
        while True:
            run = self.request("GET", f"/v1/model-runs/{run_id}")
            if run["status"] in TERMINAL_STATUSES:
                if run["status"] == "failed":
                    raise DogfoodError(
                        f"ModelRun {run_id} failed with code {run.get('errorCode', 'unknown')}."
                    )
                return run
            if time.monotonic() >= deadline:
                raise DogfoodError(f"ModelRun {run_id} did not finish before timeout.")
            time.sleep(0.2)

    def _wait_for_children(self, parents: list[dict[str, Any]]) -> list[dict[str, Any]]:
        child_ids: set[str] = set()
        stable_polls = 0
        deadline = time.monotonic() + self.recovery_timeout
        concept_id = str(self.state["conceptId"])
        while stable_polls < 3:
            previous = set(child_ids)
            for parent in parents:
                refreshed = self.request("GET", f"/v1/model-runs/{parent['id']}")
                child_ids.update(str(value) for value in refreshed.get("childRunIds", []))
            active = self.request("GET", "/v1/model-runs?active=true")
            relevant_active = any(str(run.get("conceptId")) == concept_id for run in active)
            stable_polls = stable_polls + 1 if child_ids == previous and not relevant_active else 0
            if time.monotonic() >= deadline:
                raise DogfoodError("Maintenance ModelRuns did not settle before timeout.")
            time.sleep(0.2)
        return [self._wait_for_run(run_id) for run_id in sorted(child_ids)]

    def _event_integrity(self, parents: list[dict[str, Any]]) -> bool:
        for parent in parents:
            events = self.request(
                "GET", f"/v1/model-runs/{parent['id']}/events?afterSequence=0"
            )
            types = Counter(event["type"] for event in events)
            if types["completed"] != 1 or types["failed"] != 0:
                return False
        return True

    def _load_or_create_state(self) -> dict[str, Any]:
        if self.state_path.exists():
            state = json.loads(self.state_path.read_text())
            if state.get("backendUrl") != self.backend_url:
                raise DogfoodError("State file belongs to a different backend URL.")
            if state.get("questionsHash") != _questions_hash():
                if (
                    state.get("questionsHash") != LEGACY_QUESTIONS_HASH
                    or int(state.get("completedFollowUps", 0)) > 11
                ):
                    raise DogfoodError(
                        "State file belongs to a different dogfood protocol version."
                    )
                state["questionsHash"] = _questions_hash()
                state["version"] = 2
            state.setdefault("turnAttemptCounts", {})
            return state
        state = {
            "version": 2,
            "backendUrl": self.backend_url,
            "questionsHash": _questions_hash(),
            "sessionId": str(uuid4()),
            "conceptRunId": None,
            "conceptId": None,
            "completedFollowUps": 0,
            "turnRunIds": [],
            "turnAttemptCounts": {},
            "pendingTurnIndex": None,
            "pendingRunId": None,
            "earlyContextRecallPassed": None,
            "transientNetworkFailures": 0,
        }
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        self.state = state
        self._save_state()
        return state

    def _save_state(self) -> None:
        temporary = self.state_path.with_suffix(self.state_path.suffix + ".tmp")
        temporary.write_text(json.dumps(self.state, ensure_ascii=False, indent=2, sort_keys=True))
        temporary.replace(self.state_path)


def _questions_hash() -> str:
    encoded = json.dumps(QUESTIONS, ensure_ascii=False, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run Sift's resumable 20-turn continuity and integrity dogfood protocol."
    )
    parser.add_argument("--backend-url", default="http://127.0.0.1:8000")
    parser.add_argument(
        "--state-file",
        type=Path,
        default=ROOT / ".data" / "recovery-dogfood-state.json",
    )
    parser.add_argument("--request-timeout-seconds", type=float, default=10)
    parser.add_argument("--recovery-timeout-seconds", type=float, default=300)
    parser.add_argument(
        "--confirm-live-cost",
        action="store_true",
        help="Explicitly authorize external model calls when the backend is not using mock.",
    )
    parser.add_argument(
        "--retry-failed-runs",
        action="store_true",
        help="Create a new idempotent attempt for a failed turn while preserving prior progress.",
    )
    return parser


def main(factory: Callable[..., DogfoodSession] = DogfoodSession) -> int:
    args = _parser().parse_args()
    try:
        session = factory(
            backend_url=args.backend_url,
            state_path=args.state_file,
            request_timeout=args.request_timeout_seconds,
            recovery_timeout=args.recovery_timeout_seconds,
        )
        summary = session.run(
            confirm_live_cost=args.confirm_live_cost,
            retry_failed_runs=args.retry_failed_runs,
        )
    except (DogfoodError, ValueError, json.JSONDecodeError) as error:
        print(f"Dogfood failed: {error}", file=sys.stderr)
        return 1
    print(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if summary["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
