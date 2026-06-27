import os

import pytest

from sift_backend.runtime.live_conformance import (
    main,
    run_live_conformance,
    selected_targets,
)


def test_selected_targets_are_limited_to_requested_planned_stable_providers() -> None:
    targets = selected_targets({"deepseek", "gemini"})

    assert [target.provider for target in targets] == ["gemini", "deepseek"]
    assert targets[0].api_key_env == "SIFT_TEST_GEMINI_API_KEY"
    assert targets[1].api_key_env == "SIFT_TEST_DEEPSEEK_API_KEY"


@pytest.mark.asyncio
async def test_live_conformance_skips_without_explicit_test_credentials(
    tmp_path,
    monkeypatch,
) -> None:
    monkeypatch.delenv("SIFT_TEST_DEEPSEEK_API_KEY", raising=False)
    monkeypatch.delenv("SIFT_CAPABILITY_PROBE_CACHE_PATH", raising=False)
    monkeypatch.setenv(
        "SIFT_TEST_CAPABILITY_PROBE_CACHE_PATH",
        str(tmp_path / "live-probes.json"),
    )

    result = await run_live_conformance({"deepseek"})

    assert result["runs"] == []
    assert result["skips"] == [
        {
            "provider": "deepseek",
            "reason": "missing SIFT_TEST_DEEPSEEK_API_KEY",
        }
    ]
    assert os.environ["SIFT_CAPABILITY_PROBE_CACHE_PATH"] == str(tmp_path / "live-probes.json")


def test_live_conformance_main_fails_when_every_provider_is_skipped(
    tmp_path,
    monkeypatch,
    capsys,
) -> None:
    monkeypatch.delenv("SIFT_TEST_DEEPSEEK_API_KEY", raising=False)
    monkeypatch.delenv("SIFT_CAPABILITY_PROBE_CACHE_PATH", raising=False)
    monkeypatch.setenv(
        "SIFT_TEST_CAPABILITY_PROBE_CACHE_PATH",
        str(tmp_path / "live-probes.json"),
    )
    monkeypatch.setattr("sys.argv", ["live_conformance", "--provider", "deepseek"])

    assert main() == 2
    assert "missing SIFT_TEST_DEEPSEEK_API_KEY" in capsys.readouterr().out
