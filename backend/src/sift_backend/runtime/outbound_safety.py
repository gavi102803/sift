import ipaddress
import os
import socket
from collections.abc import Callable
from dataclasses import dataclass
from urllib.parse import urlparse

from sift_backend.runtime.types import SiftRuntimeError

AddressResolver = Callable[[str], list[str]]


@dataclass(frozen=True)
class OutboundTargetPolicy:
    kind: str
    allow_local: bool = False
    allowed_ports: frozenset[int] = frozenset({80, 443})


def validate_outbound_url(
    url: str,
    *,
    policy: OutboundTargetPolicy,
    resolver: AddressResolver | None = None,
) -> str:
    parsed = urlparse(url.strip())
    if parsed.scheme not in {"http", "https"}:
        raise SiftRuntimeError(
            f"{policy.kind}_url_blocked",
            "Only HTTP(S) outbound URLs are allowed.",
        )
    if not parsed.hostname:
        raise SiftRuntimeError(f"{policy.kind}_url_blocked", "Outbound URL must include a host.")
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    if port not in policy.allowed_ports and not policy.allow_local:
        raise SiftRuntimeError(
            f"{policy.kind}_url_blocked",
            "Outbound URL port is not allowed.",
        )
    resolver = resolver or resolve_host_addresses
    for address in resolver(parsed.hostname):
        if is_blocked_address(address) and not policy.allow_local:
            raise SiftRuntimeError(
                f"{policy.kind}_url_blocked",
                "Outbound URL resolves to a blocked network address.",
            )
    return parsed.geturl()


def model_endpoint_policy(provider_name: str) -> OutboundTargetPolicy:
    return OutboundTargetPolicy(
        kind="model_endpoint",
        allow_local=_allow_local_model_endpoint(provider_name),
    )


def extraction_policy() -> OutboundTargetPolicy:
    return OutboundTargetPolicy(kind="extract")


def resolve_host_addresses(host: str) -> list[str]:
    return sorted(
        {
            result[4][0]
            for result in socket.getaddrinfo(host, None, proto=socket.IPPROTO_TCP)
        }
    )


def is_blocked_address(address: str) -> bool:
    ip = ipaddress.ip_address(address)
    return any(
        (
            ip.is_loopback,
            ip.is_private,
            ip.is_link_local,
            ip.is_multicast,
            ip.is_unspecified,
            ip.is_reserved,
            address in {"169.254.169.254", "100.100.100.200"},
        )
    )


def _allow_local_model_endpoint(provider_name: str) -> bool:
    if provider_name.strip().lower() != "custom":
        return False
    if os.environ.get("SIFT_ENV", "development").strip().lower() not in {
        "development",
        "dev",
        "test",
    }:
        return False
    return os.environ.get("SIFT_ALLOW_LOCAL_MODEL_ENDPOINT", "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }
