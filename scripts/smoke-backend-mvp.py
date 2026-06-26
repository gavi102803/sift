#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any


BASE_URL = "http://127.0.0.1:8000"
REQUEST_TIMEOUT_SECONDS = 90


@dataclass(frozen=True)
class StepResult:
    name: str
    ok: bool
    detail: str


ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    global BASE_URL
    args = parse_args()
    BASE_URL = f"http://127.0.0.1:{args.port}"
    server = start_server(args.port) if args.start_server else None
    try:
        return run_smoke(
            capture=args.capture,
            check_web_search=args.check_web_search,
            require_provider=args.require_provider,
            require_web_search_used=args.require_web_search_used,
            require_initial_retrieval=args.require_initial_retrieval,
            allow_model_variance=args.allow_model_variance,
        )
    finally:
        if server is not None:
            server.terminate()
            try:
                server.wait(timeout=5)
            except subprocess.TimeoutExpired:
                server.kill()
                server.wait(timeout=5)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run Sift backend MVP smoke checks.")
    parser.add_argument(
        "--start-server",
        action="store_true",
        help="Start backend/.venv uvicorn for this smoke run and stop it afterwards.",
    )
    parser.add_argument(
        "--check-web-search",
        action="store_true",
        help="Also run /v1/web-search-diagnostic; requires web provider configuration.",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=8000,
        help="Backend port to use when starting or checking the server.",
    )
    parser.add_argument(
        "--capture",
        default="Backend smoke RAG",
        help=(
            "Raw concept capture to create. Use a freshness-sensitive phrase when "
            "checking initial web retrieval."
        ),
    )
    parser.add_argument(
        "--require-provider",
        choices=("mock", "openai", "deepseek", "openrouter", "nous", "kimi", "custom"),
        help="Fail unless /v1/app-status reports this model provider.",
    )
    parser.add_argument(
        "--require-web-search-used",
        action="store_true",
        help="Fail unless /v1/web-search-diagnostic reports webSearchUsed=true.",
    )
    parser.add_argument(
        "--require-initial-retrieval",
        action="store_true",
        help="Fail unless the created concept answerSource has retrievalUsed=true.",
    )
    parser.add_argument(
        "--allow-model-variance",
        action="store_true",
        help=(
            "Accept any valid model updateMode and skip deterministic proposal assertions. "
            "Use this for real provider E2E checks."
        ),
    )
    return parser.parse_args()


def start_server(port: int) -> subprocess.Popen:
    python = ROOT / "backend" / ".venv" / "bin" / "python"
    if not python.exists():
        raise RuntimeError("backend/.venv is missing; create it and install backend dependencies.")

    server = subprocess.Popen(
        [
            str(python),
            "-m",
            "uvicorn",
            "sift_backend.main:app",
            "--host",
            "127.0.0.1",
            "--port",
            str(port),
        ],
        cwd=ROOT / "backend",
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    wait_for_server(server)
    return server


def wait_for_server(server: subprocess.Popen) -> None:
    deadline = time.monotonic() + 20
    last_error = ""
    while time.monotonic() < deadline:
        if server.poll() is not None:
            raise RuntimeError(f"backend server exited early with code {server.returncode}")
        try:
            health = get_json("/health")
            if isinstance(health, dict) and health.get("status") == "ok":
                return
        except Exception as error:
            last_error = str(error)
            time.sleep(0.25)
    raise RuntimeError(f"backend server did not become ready: {last_error}")


def run_smoke(
    capture: str,
    check_web_search: bool,
    require_provider: str | None,
    require_web_search_used: bool,
    require_initial_retrieval: bool,
    allow_model_variance: bool,
) -> int:
    results: list[StepResult] = []
    try:
        health = get_json("/health")
        results.append(assert_equal("health", health.get("status"), "ok"))

        app_status = get_json("/v1/app-status")
        provider = app_status.get("modelProvider", "unknown")
        results.append(StepResult("app-status", True, f"provider={provider}"))
        if require_provider is not None:
            results.append(assert_equal("required-provider", provider, require_provider))

        diagnostic = post_json("/v1/model-diagnostic", {})
        results.append(
            StepResult(
                "model-diagnostic",
                bool(diagnostic.get("ok")),
                diagnostic_detail(diagnostic),
            )
        )

        if check_web_search or require_web_search_used:
            web_search_diagnostic = post_json("/v1/web-search-diagnostic", {})
            results.append(
                StepResult(
                    "web-search-diagnostic",
                    bool(web_search_diagnostic.get("ok")),
                    diagnostic_detail(web_search_diagnostic),
                )
            )
            if require_web_search_used:
                results.append(
                    assert_equal(
                        "required-web-search-used",
                        web_search_diagnostic.get("webSearchUsed"),
                        True,
                    )
                )

        concept = post_json(
            "/v1/concepts",
            {"rawCapture": capture, "locale": "en"},
        )
        concept_id = concept["id"]
        results.append(assert_equal("create-concept", concept["captureStatus"], "ready"))
        results.append(
            StepResult(
                "initial-answer-source",
                bool(concept.get("answerSource", {}).get("sourceType")),
                json.dumps(concept.get("answerSource"), ensure_ascii=False),
            )
        )
        if require_initial_retrieval:
            results.append(
                assert_equal(
                    "required-initial-retrieval",
                    concept.get("answerSource", {}).get("retrievalUsed"),
                    True,
                )
            )

        edited = patch_json(
            f"/v1/concepts/{concept_id}",
            {
                "displayTitle": "Backend Smoke RAG",
                "oneLineExplanation": "Smoke test concept edited by the user.",
            },
        )
        results.append(assert_equal("edit-concept-summary", edited["noteRevision"], 2))

        organized = patch_json(
            f"/v1/concepts/{concept_id}/organization",
            {"tags": ["AI", "Retrieval"], "topics": ["Machine Learning"]},
        )
        results.append(assert_equal("edit-organization-tags", organized["tags"], ["AI", "Retrieval"]))
        results.append(
            assert_equal("edit-organization-topics", organized["topics"], ["Machine Learning"])
        )

        related_concept = post_json(
            "/v1/concepts",
            {"rawCapture": "Backend Smoke Embedding", "locale": "en"},
        )
        relation_result = post_json(
            f"/v1/concepts/{concept_id}/relations",
            {"targetConceptId": related_concept["id"], "relationType": "related"},
        )
        relation = relation_result.get("relations", [{}])[0]
        results.append(
            assert_equal("add-relation-target", relation.get("targetConceptId"), related_concept["id"])
        )
        relation_id = relation.get("id")
        if relation_id:
            removed_relation = delete_json(f"/v1/concepts/{concept_id}/relations/{relation_id}")
            results.append(assert_equal("remove-relation", removed_relation.get("relations"), []))
        else:
            results.append(StepResult("remove-relation", False, "missing relation id"))

        turn = post_json(
            f"/v1/concepts/{concept_id}/turns",
            {"question": "Define this more precisely"},
        )
        update_mode = turn.get("updateMode")
        if allow_model_variance:
            results.append(
                StepResult(
                    "submit-turn",
                    update_mode in {"none", "autoMerge", "needsConfirmation"},
                    f"updateMode={update_mode}",
                )
            )
        else:
            results.append(assert_equal("submit-turn", update_mode, "needsConfirmation"))

        history = get_json(f"/v1/concepts/{concept_id}/turns")
        assistant_turns = [item for item in history if item.get("role") == "assistant"]
        answer_source = assistant_turns[-1].get("answerSource") if assistant_turns else None
        results.append(
            StepResult(
                "turn-history-answer-source",
                bool(answer_source and answer_source.get("sourceType")),
                json.dumps(answer_source, ensure_ascii=False),
            )
        )

        proposal = turn.get("proposal")
        if proposal is not None:
            try:
                merged = post_json(f"/v1/update-proposals/{proposal['id']}/merge", {})
            except HttpRequestError as error:
                if allow_model_variance and error.status_code == 409:
                    results.append(
                        StepResult(
                            "merge-proposal",
                            _is_safe_merge_rejection(error.body),
                            f"safe rejection: {error.body}",
                        )
                    )
                    merged = None
                else:
                    raise

            if allow_model_variance and merged is not None:
                results.append(
                    StepResult(
                        "merge-proposal",
                        merged.get("noteRevision", 0) >= 4,
                        f"noteRevision={merged.get('noteRevision')}",
                    )
                )
            elif merged is not None:
                results.append(assert_equal("merge-proposal", merged["noteRevision"], 4))

            if merged is not None:
                block_id = merged["blocks"][0]["id"]
                edited_block = patch_json(
                    f"/v1/concepts/{concept_id}/blocks/{block_id}",
                    {"content": "User-edited smoke note block."},
                )
                results.append(
                    assert_equal(
                        "edit-note-block-locks-content",
                        edited_block["blocks"][0]["isUserLocked"],
                        True,
                    )
                )
            elif allow_model_variance:
                results.append(
                    StepResult(
                        "edit-note-block-locks-content",
                        True,
                        "skipped; proposal merge was safely rejected",
                    )
                )
        elif allow_model_variance:
            results.append(StepResult("merge-proposal", True, "skipped; no proposal returned"))
        else:
            results.append(StepResult("merge-proposal", False, "missing proposal"))
    except Exception as error:
        results.append(StepResult("smoke-run", False, str(error)))

    for result in results:
        status = "ok" if result.ok else "fail"
        print(f"[{status}] {result.name}: {result.detail}")

    return 0 if all(result.ok for result in results) else 1


def get_json(path: str) -> dict[str, Any] | list[Any]:
    request = urllib.request.Request(f"{BASE_URL}{path}")
    return _json_response(request)


def post_json(path: str, payload: dict[str, Any]) -> dict[str, Any]:
    return request_json(path, payload, method="POST")


def patch_json(path: str, payload: dict[str, Any]) -> dict[str, Any]:
    return request_json(path, payload, method="PATCH")


def delete_json(path: str) -> dict[str, Any]:
    request = urllib.request.Request(f"{BASE_URL}{path}", method="DELETE")
    response = _json_response(request)
    if not isinstance(response, dict):
        raise ValueError(f"{path} returned non-object JSON")
    return response


def request_json(path: str, payload: dict[str, Any], method: str) -> dict[str, Any]:
    data = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        f"{BASE_URL}{path}",
        data=data,
        headers={"Content-Type": "application/json"},
        method=method,
    )
    response = _json_response(request)
    if not isinstance(response, dict):
        raise ValueError(f"{path} returned non-object JSON")
    return response


def _json_response(request: urllib.request.Request) -> dict[str, Any] | list[Any]:
    try:
        with urllib.request.urlopen(request, timeout=REQUEST_TIMEOUT_SECONDS) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as error:
        body = error.read().decode("utf-8")
        raise HttpRequestError(request.full_url, error.code, body) from error
    except urllib.error.URLError as error:
        raise RuntimeError(f"{request.full_url} is not reachable: {error.reason}") from error


def assert_equal(name: str, actual: Any, expected: Any) -> StepResult:
    return StepResult(
        name=name,
        ok=actual == expected,
        detail=f"expected={expected!r} actual={actual!r}",
    )


def diagnostic_detail(diagnostic: dict[str, Any]) -> str:
    parts = [
        f"provider={diagnostic.get('provider', 'unknown')}",
        f"model={diagnostic.get('model', 'unknown')}",
        diagnostic.get("message", "missing message"),
    ]
    if "webSearchUsed" in diagnostic:
        parts.append(f"webSearchUsed={diagnostic['webSearchUsed']}")
    if "citationCount" in diagnostic:
        parts.append(f"citationCount={diagnostic['citationCount']}")
    return "; ".join(parts)


class HttpRequestError(RuntimeError):
    def __init__(self, url: str, status_code: int, body: str) -> None:
        super().__init__(f"{url} returned HTTP {status_code}: {body}")
        self.url = url
        self.status_code = status_code
        self.body = body


def _is_safe_merge_rejection(body: str) -> bool:
    try:
        payload = json.loads(body)
    except ValueError:
        return False
    detail = payload.get("detail") if isinstance(payload, dict) else None
    code = detail.get("code") if isinstance(detail, dict) else None
    return code in {"hashMismatch", "lockedBlock", "staleRevision", "missingConcept"}


if __name__ == "__main__":
    sys.exit(main())
