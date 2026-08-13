from __future__ import annotations

import json
import re
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


class Handler(BaseHTTPRequestHandler):
    def do_POST(self) -> None:
        content_length = int(self.headers.get("Content-Length", "0"))
        payload = json.loads(self.rfile.read(content_length) or b"{}")
        structured = payload.get("response_format") == {"type": "json_object"}
        messages = payload.get("messages") or []
        prompt = "\n".join(
            str(message.get("content", ""))
            for message in messages
            if isinstance(message, dict)
        )
        if "compact continuity memory" in prompt:
            content = json.dumps({"summary": "Local continuity summary."})
        elif "Review recent learning" in prompt:
            content = json.dumps(
                {
                    "proposal": None,
                    "claims": [
                        {
                            "statement": "Maintenance preserves durable learning.",
                            "type": "fact",
                            "evidenceStatus": "modelExplanation",
                            "timeSensitivity": "stable",
                            "sourceIds": [],
                        }
                    ],
                    "learningStateUpdates": [
                        {
                            "field": "confirmedUnderstanding",
                            "content": "The user connected follow-ups to durable notes.",
                            "origin": "userConfirmed",
                        }
                    ],
                }
            )
        elif "Create a Sift concept card" in prompt:
            content = json.dumps(_initial_result(prompt))
        elif "Explain this captured concept for Sift" in prompt:
            content = (
                "**What it is**\n\nCloudflare Workers is a serverless edge runtime.\n\n"
                "**Why it matters**\n\nIt runs code near users without managing servers.\n\n"
                "**Example**\n\nAn API can validate and answer requests at the edge."
            )
        elif "retrievalEvidence" in prompt:
            content = (
                json.dumps(_follow_up_result(prompt))
                if structured
                else (
                    "The mock provider answered clearly.\n\n"
                    "- It used the current card context.\n"
                    "- It preserved the durable note until validation completed."
                )
            )
        else:
            content = json.dumps(_initial_result(prompt)) if structured else "ok"
        if payload.get("stream") is True:
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Cache-Control", "no-cache")
            self.end_headers()
            for delta in _provider_deltas(content):
                event = {
                    "model": payload.get("model", "mock-model"),
                    "choices": [{"delta": {"content": delta}}],
                }
                self.wfile.write(
                    f"data: {json.dumps(event, ensure_ascii=False)}\n\n".encode()
                )
                self.wfile.flush()
                time.sleep(0.08)
            self.wfile.write(b"data: [DONE]\n\n")
            self.wfile.flush()
            return
        response = json.dumps(
            {
                "model": payload.get("model", "mock-model"),
                "choices": [{"message": {"content": content}}],
                "usage": {"prompt_tokens": 12, "completion_tokens": 24},
            }
        ).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(response)))
        self.end_headers()
        self.wfile.write(response)

    def log_message(self, message: str, *args: object) -> None:
        print(message % args)


def _provider_deltas(content: str) -> list[str]:
    if len(content) < 3:
        return [content]
    first = max(1, len(content) // 3)
    second = max(first + 1, (len(content) * 2) // 3)
    return [content[:first], content[first:second], content[second:]]


def _initial_result(prompt: str = "") -> dict:
    evidence_match = _evidence_match(prompt)
    has_evidence = evidence_match is not None
    citations = []
    if evidence_match is not None:
        source_id, title, url = evidence_match.groups()
        citations = [{"sourceId": source_id, "title": title, "url": url}]
    return {
        "canonicalTitle": "Cloudflare Workers",
        "displayTitle": "Cloudflare Workers",
        "oneLineExplanation": "A serverless edge execution environment.",
        "answer": (
            "**What it is**\n\nA serverless edge execution environment.\n\n"
            "**Why it matters**\n\nIt removes server lifecycle management."
        ),
        "blocks": [
            {
                "blockType": "whatItIs",
                "content": "A serverless edge execution environment.",
            },
            {
                "blockType": "whyItMatters",
                "content": "It removes server lifecycle management.",
            },
        ],
        "suggestedTags": [{"name": "Cloudflare", "confidence": 0.9}],
        "suggestedTopics": [{"name": "Infrastructure", "confidence": 0.8}],
        "answerSource": {
            "sourceType": "webVerified" if has_evidence else "modelKnowledge",
            "confidence": 0.8,
            "uncertaintyNote": None,
            "retrievalUsed": has_evidence,
            "freshnessNote": "Validated in the local Worker." if has_evidence else None,
            "citations": citations,
        },
        "modelMeta": {
            "provider": "mock",
            "model": "mock-model",
            "latencyMs": None,
            "inputTokens": None,
            "outputTokens": None,
        },
    }


def _follow_up_result(prompt: str) -> dict:
    evidence_match = _evidence_match(prompt)
    has_evidence = evidence_match is not None
    citations = []
    if evidence_match is not None:
        source_id, title, url = evidence_match.groups()
        citations = [{"sourceId": source_id, "title": title, "url": url}]
    return {
        "answer": "The mock provider answered with validated retrieval evidence.",
        "proposal": None,
        "answerSource": {
            "sourceType": "webVerified" if has_evidence else "modelKnowledge",
            "confidence": 0.8,
            "uncertaintyNote": None,
            "retrievalUsed": has_evidence,
            "freshnessNote": "Validated in the local Worker." if has_evidence else None,
            "citations": citations,
        },
        "modelMeta": {
            "provider": "mock",
            "model": "mock-model",
            "latencyMs": None,
            "inputTokens": None,
            "outputTokens": None,
        },
    }


def _evidence_match(prompt: str) -> re.Match[str] | None:
    return re.search(
        r'retrievalEvidence(?:=|":)\s*\[\{"id":\s*"([^"]+)",\s*'
        r'"title":\s*"([^"]+)",\s*"url":\s*"([^"]+)"',
        prompt,
    )


if __name__ == "__main__":
    ThreadingHTTPServer(("127.0.0.1", 8791), Handler).serve_forever()
