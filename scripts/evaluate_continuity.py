#!/usr/bin/env python3
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BACKEND_SRC = ROOT / "backend" / "src"
if str(BACKEND_SRC) not in sys.path:
    sys.path.insert(0, str(BACKEND_SRC))

from sift_backend.ai.context_pack import RecentTurn  # noqa: E402
from sift_backend.api.concepts import build_concept_service  # noqa: E402
from sift_backend.concepts.service import (  # noqa: E402
    InMemoryConceptStore,
    MockConceptModelService,
)
from sift_backend.config import load_settings  # noqa: E402
from sift_backend.schemas.model_outputs import ContinuitySummaryResult  # noqa: E402


def synthetic_turns(rounds: int) -> list[tuple[int, RecentTurn]]:
    turns: list[tuple[int, RecentTurn]] = []
    for index in range(rounds):
        if index == 0:
            question = "我的背景是产品经理；解释时请优先使用具体例子，而不是只给抽象定义。"
        elif index == 2:
            question = "我已经确认理解：幂等键用于识别同一个操作，不等于把所有请求串行化。"
        elif index in {5, 9}:
            question = "我仍然容易混淆 lease 到期和任务真正失败，两者的区别是什么？"
        elif index == rounds - 1:
            question = "还没解决的问题：多个进程同时恢复同一任务时，怎样避免重复领域写入？"
        else:
            question = f"第 {index + 1} 轮：请继续用一个具体场景解释可恢复任务的边界。"
        answer = (
            f"第 {index + 1} 轮回答：用任务 {index + 1} 的生命周期说明持久状态、"
            "lease 与幂等提交的职责不同。"
        )
        turns.append((index * 2 + 1, RecentTurn(role="user", content=question)))
        turns.append((index * 2 + 2, RecentTurn(role="assistant", content=answer)))
    return turns


def evaluate(result: ContinuitySummaryResult, turns: list[tuple[int, RecentTurn]]) -> list[str]:
    failures: list[str] = []
    categories = {
        "priorAnswers": result.prior_answers,
        "confirmedUnderstanding": result.confirmed_understanding,
        "userContext": result.user_context,
        "recurringConfusions": result.recurring_confusions,
        "openQuestions": result.open_questions,
    }
    for name, entries in categories.items():
        if not entries:
            failures.append(f"missing category: {name}")

    allowed_ids = {turn_id for turn_id, _ in turns}
    if any(not set(entry.source_turn_ids).issubset(allowed_ids) for entry in result.entries):
        failures.append("summary contains an unknown source turn")

    source_size = sum(len(turn.content) for _, turn in turns)
    summary_size = len(json.dumps(result.model_dump(mode="json", by_alias=True), ensure_ascii=False))
    ratio = summary_size / max(source_size, 1)
    if ratio >= 0.75:
        failures.append(f"summary is not compact enough: ratio={ratio:.2f}")
    return failures


async def run(rounds: int) -> int:
    settings = load_settings()
    if settings.runtime_provider == "mock" or not settings.runtime_api_key:
        print("FAIL: configure a real Provider before running continuity evaluation")
        return 2

    service = build_concept_service(settings, store=InMemoryConceptStore())
    concept = await MockConceptModelService().create_initial_concept(
        "可恢复模型任务",
        "zh-Hans",
    )
    turns = synthetic_turns(rounds)
    result = await service.model_service.summarize_continuity(concept, turns)
    failures = evaluate(result, turns)
    print(
        "Continuity evaluation: "
        f"provider={settings.runtime_provider}, model={settings.runtime_model}, "
        f"rounds={rounds}, entries={len(result.entries)}"
    )
    if failures:
        for failure in failures:
            print(f"FAIL: {failure}")
        return 1
    print("PASS: all semantic categories are grounded and the summary is compact")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run a content-safe long-conversation continuity evaluation."
    )
    parser.add_argument("--rounds", type=int, default=20)
    args = parser.parse_args()
    if args.rounds < 10 or args.rounds > 50:
        parser.error("--rounds must be between 10 and 50")
    return asyncio.run(run(args.rounds))


if __name__ == "__main__":
    raise SystemExit(main())
