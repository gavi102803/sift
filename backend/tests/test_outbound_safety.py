import pytest

from sift_backend.runtime.outbound_safety import (
    OutboundTargetPolicy,
    extraction_policy,
    model_endpoint_policy,
    validate_outbound_url,
)
from sift_backend.runtime.providers import ChatCompletionsDriver
from sift_backend.runtime.types import RuntimeMessage, RuntimeModelRequest, SiftRuntimeError


def test_outbound_safety_blocks_localhost_and_loopback() -> None:
    with pytest.raises(SiftRuntimeError, match="blocked"):
        validate_outbound_url(
            "http://localhost/page",
            policy=extraction_policy(),
            resolver=lambda host: ["127.0.0.1"],
        )
    with pytest.raises(SiftRuntimeError, match="blocked"):
        validate_outbound_url(
            "http://[::1]/page",
            policy=extraction_policy(),
            resolver=lambda host: ["::1"],
        )


def test_outbound_safety_blocks_private_link_local_and_metadata_addresses() -> None:
    for address in ("10.0.0.2", "192.168.1.10", "169.254.10.20", "169.254.169.254"):
        with pytest.raises(SiftRuntimeError, match="blocked"):
            validate_outbound_url(
                f"http://{address}/page",
                policy=extraction_policy(),
                resolver=lambda host, address=address: [address],
            )


def test_outbound_safety_blocks_dns_resolution_to_private_ip() -> None:
    with pytest.raises(SiftRuntimeError, match="blocked"):
        validate_outbound_url(
            "https://example.com/page",
            policy=extraction_policy(),
            resolver=lambda host: ["10.0.0.5"],
        )


def test_outbound_safety_blocks_non_http_and_unapproved_ports() -> None:
    with pytest.raises(SiftRuntimeError, match="HTTP"):
        validate_outbound_url(
            "file:///etc/passwd",
            policy=extraction_policy(),
            resolver=lambda host: ["93.184.216.34"],
        )
    with pytest.raises(SiftRuntimeError, match="port"):
        validate_outbound_url(
            "https://example.com:8443/page",
            policy=extraction_policy(),
            resolver=lambda host: ["93.184.216.34"],
        )


@pytest.mark.asyncio
async def test_custom_provider_blocks_localhost_without_dev_allowlist(monkeypatch) -> None:
    monkeypatch.setenv("SIFT_ENV", "production")
    monkeypatch.delenv("SIFT_ALLOW_LOCAL_MODEL_ENDPOINT", raising=False)
    provider = ChatCompletionsDriver(
        base_url="http://localhost/v1",
        api_key="local-key",
        provider_name="custom",
    )

    with pytest.raises(SiftRuntimeError, match="blocked"):
        await provider.complete(
            RuntimeModelRequest(
                model="local-model",
                messages=(RuntimeMessage(role="user", content="ok"),),
            )
        )


def test_development_custom_endpoint_can_explicitly_allow_localhost(monkeypatch) -> None:
    monkeypatch.setenv("SIFT_ENV", "development")
    monkeypatch.setenv("SIFT_ALLOW_LOCAL_MODEL_ENDPOINT", "true")

    assert validate_outbound_url(
        "http://localhost:11434/v1",
        policy=model_endpoint_policy("custom"),
        resolver=lambda host: ["127.0.0.1"],
    ) == "http://localhost:11434/v1"


def test_non_custom_model_endpoint_never_uses_localhost_development_escape(
    monkeypatch,
) -> None:
    monkeypatch.setenv("SIFT_ENV", "development")
    monkeypatch.setenv("SIFT_ALLOW_LOCAL_MODEL_ENDPOINT", "true")

    with pytest.raises(SiftRuntimeError, match="blocked"):
        validate_outbound_url(
            "http://localhost/v1",
            policy=model_endpoint_policy("deepseek"),
            resolver=lambda host: ["127.0.0.1"],
        )


def test_outbound_safety_allows_public_default_https_port() -> None:
    assert validate_outbound_url(
        "https://example.com/page",
        policy=OutboundTargetPolicy(kind="test"),
        resolver=lambda host: ["93.184.216.34"],
    ) == "https://example.com/page"
