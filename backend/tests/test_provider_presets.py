from sift_backend.runtime.provider_presets import HERMES_COMMIT_SHA, MODEL_PROVIDER_PRESETS
from sift_backend.runtime.providers import build_model_provider_registry


def test_provider_presets_are_pinned_and_exposed_through_registry() -> None:
    assert HERMES_COMMIT_SHA == "bb6a4d2a57f3f239a2a6d74cb2dec9534a20e607"

    preset_names = {preset["profile"]["name"] for preset in MODEL_PROVIDER_PRESETS}
    registry = build_model_provider_registry()
    registry_names = set(registry.names())

    assert preset_names == registry_names
    assert {"bedrock", "xai", "qwen-oauth", "copilot", "copilot-acp"}.isdisjoint(
        registry_names
    )


def test_provider_preset_exposure_and_aliases() -> None:
    registry = build_model_provider_registry()

    assert registry.normalize("sift_runtime") == "custom"
    assert registry.normalize("openai_responses") == "openai"
    assert registry.profile("alibaba").is_advanced is True
    assert registry.profile("gemini").exposure_tier == "plannedStable"
    assert registry.profile("gemini").protocol_driver == "GeminiDriver"
    assert registry.profile("deepseek").protocol_driver == "ChatCompletionsDriver"
    assert registry.profile("anthropic").protocol_driver == "AnthropicMessagesDriver"
