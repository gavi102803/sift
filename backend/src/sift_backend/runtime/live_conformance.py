import argparse
import asyncio
import json
import os
from dataclasses import asdict, dataclass
from pathlib import Path

from sift_backend.runtime.conformance import run_model_driver_conformance
from sift_backend.runtime.providers import (
    build_model_provider_registry,
    build_runtime_model_provider,
    resolve_runtime_base_url,
    resolve_runtime_model,
)


@dataclass(frozen=True)
class LiveConformanceTarget:
    provider: str
    api_key_env: str
    base_url_env: str
    model_env: str


@dataclass(frozen=True)
class LiveConformanceSkip:
    provider: str
    reason: str


@dataclass(frozen=True)
class LiveConformanceRun:
    provider: str
    model: str
    ok: bool
    result: dict


PLANNED_STABLE_TARGETS: tuple[LiveConformanceTarget, ...] = (
    LiveConformanceTarget(
        provider="openai",
        api_key_env="SIFT_TEST_OPENAI_API_KEY",
        base_url_env="SIFT_TEST_OPENAI_BASE_URL",
        model_env="SIFT_TEST_OPENAI_MODEL",
    ),
    LiveConformanceTarget(
        provider="anthropic",
        api_key_env="SIFT_TEST_ANTHROPIC_API_KEY",
        base_url_env="SIFT_TEST_ANTHROPIC_BASE_URL",
        model_env="SIFT_TEST_ANTHROPIC_MODEL",
    ),
    LiveConformanceTarget(
        provider="gemini",
        api_key_env="SIFT_TEST_GEMINI_API_KEY",
        base_url_env="SIFT_TEST_GEMINI_BASE_URL",
        model_env="SIFT_TEST_GEMINI_MODEL",
    ),
    LiveConformanceTarget(
        provider="deepseek",
        api_key_env="SIFT_TEST_DEEPSEEK_API_KEY",
        base_url_env="SIFT_TEST_DEEPSEEK_BASE_URL",
        model_env="SIFT_TEST_DEEPSEEK_MODEL",
    ),
    LiveConformanceTarget(
        provider="openrouter",
        api_key_env="SIFT_TEST_OPENROUTER_API_KEY",
        base_url_env="SIFT_TEST_OPENROUTER_BASE_URL",
        model_env="SIFT_TEST_OPENROUTER_MODEL",
    ),
    LiveConformanceTarget(
        provider="kimi",
        api_key_env="SIFT_TEST_KIMI_API_KEY",
        base_url_env="SIFT_TEST_KIMI_BASE_URL",
        model_env="SIFT_TEST_KIMI_MODEL",
    ),
    LiveConformanceTarget(
        provider="nous",
        api_key_env="SIFT_TEST_NOUS_API_KEY",
        base_url_env="SIFT_TEST_NOUS_BASE_URL",
        model_env="SIFT_TEST_NOUS_MODEL",
    ),
    LiveConformanceTarget(
        provider="custom",
        api_key_env="SIFT_TEST_CUSTOM_API_KEY",
        base_url_env="SIFT_TEST_CUSTOM_BASE_URL",
        model_env="SIFT_TEST_CUSTOM_MODEL",
    ),
)


def selected_targets(provider_names: set[str] | None = None) -> list[LiveConformanceTarget]:
    registry = build_model_provider_registry()
    selected: list[LiveConformanceTarget] = []
    requested = {name.strip().lower() for name in provider_names or set()}
    for target in PLANNED_STABLE_TARGETS:
        if requested and target.provider not in requested:
            continue
        registry.profile(target.provider)
        selected.append(target)
    return selected


async def run_live_conformance(
    provider_names: set[str] | None = None,
) -> dict[str, list[dict]]:
    _ensure_isolated_probe_cache()
    runs: list[LiveConformanceRun] = []
    skips: list[LiveConformanceSkip] = []

    for target in selected_targets(provider_names):
        api_key = os.environ.get(target.api_key_env, "").strip()
        if not api_key:
            skips.append(
                LiveConformanceSkip(
                    provider=target.provider,
                    reason=f"missing {target.api_key_env}",
                )
            )
            continue
        base_url = os.environ.get(target.base_url_env, "").strip()
        model = os.environ.get(target.model_env, "").strip()
        provider = build_runtime_model_provider(
            target.provider,
            base_url=base_url or resolve_runtime_base_url(target.provider, ""),
            api_key=api_key,
            timeout=60,
        )
        resolved_model = resolve_runtime_model(target.provider, model)
        profile = build_model_provider_registry().profile(target.provider)
        result = await run_model_driver_conformance(
            provider,
            provider_name=target.provider,
            model=resolved_model,
            supports_model_listing=profile.supports_model_listing,
        )
        runs.append(
            LiveConformanceRun(
                provider=target.provider,
                model=resolved_model,
                ok=result.ok,
                result=asdict(result),
            )
        )

    return {
        "runs": [asdict(run) for run in runs],
        "skips": [asdict(skip) for skip in skips],
    }


def _ensure_isolated_probe_cache() -> None:
    if os.environ.get("SIFT_CAPABILITY_PROBE_CACHE_PATH"):
        return
    configured_path = os.environ.get("SIFT_TEST_CAPABILITY_PROBE_CACHE_PATH", "").strip()
    path = (
        Path(configured_path)
        if configured_path
        else Path("/tmp/sift-live-conformance-probes.json")
    )
    os.environ["SIFT_CAPABILITY_PROBE_CACHE_PATH"] = str(path)


def main() -> int:
    parser = argparse.ArgumentParser(description="Run Sift live provider conformance.")
    parser.add_argument(
        "--provider",
        action="append",
        dest="providers",
        help="Provider id to test. Can be repeated. Defaults to every planned stable provider.",
    )
    args = parser.parse_args()
    provider_names = set(args.providers or []) or None
    output = asyncio.run(run_live_conformance(provider_names))
    print(json.dumps(output, ensure_ascii=False, indent=2))
    failed = [run for run in output["runs"] if not run["ok"]]
    if not output["runs"]:
        return 2
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
