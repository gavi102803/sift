import asyncio
import json
from pathlib import Path

from sift_backend.config import load_settings
from sift_backend.runtime.conformance import (
    model_driver_conformance_artifact,
    run_model_driver_conformance,
)
from sift_backend.runtime.providers import build_runtime_model_provider, resolve_runtime_model


async def main() -> None:
    settings = load_settings()
    output_path = Path("backend/.data/live-conformance.json")
    output_path.parent.mkdir(parents=True, exist_ok=True)

    if not settings.runtime_api_key or settings.runtime_provider == "mock":
        artifact = {
            "kind": "sift.modelDriverConformance",
            "provider": settings.runtime_provider,
            "model": resolve_runtime_model(settings.runtime_provider, settings.runtime_model),
            "ok": False,
            "skipped": True,
            "reason": "Runtime provider credentials are not configured.",
        }
        output_path.write_text(json.dumps(artifact, indent=2), encoding="utf-8")
        print(json.dumps(artifact))
        return

    provider = build_runtime_model_provider(
        settings.runtime_provider,
        base_url=settings.runtime_base_url,
        api_key=settings.runtime_api_key,
        timeout=30,
    )
    model = resolve_runtime_model(settings.runtime_provider, settings.runtime_model)
    result = await run_model_driver_conformance(
        provider,
        provider_name=settings.runtime_provider,
        model=model,
    )
    artifact = model_driver_conformance_artifact(result)
    output_path.write_text(json.dumps(artifact, indent=2), encoding="utf-8")
    print(json.dumps(artifact))


if __name__ == "__main__":
    asyncio.run(main())
