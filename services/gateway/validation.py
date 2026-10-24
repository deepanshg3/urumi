"""Upstream URL validation and SSRF protection.

Registration is an admin action but still untrusted input: without controls an
administrator (or a compromised admin session) could make the gateway probe
localhost, cloud metadata or arbitrary private networks. The policy is an
explicit host allowlist (defaults cover the local Compose stack). Public
upstreams require ``GATEWAY_ALLOW_PUBLIC_UPSTREAMS=true`` and may never resolve
to loopback/link-local/private/reserved addresses.
"""

from __future__ import annotations

import asyncio
import ipaddress
import socket
from urllib.parse import urlsplit

from services.common.config import GatewaySettings
from services.common.errors import ValidationError


class UpstreamURLRejected(ValidationError):
    code = "invalid_upstream_url"

    def __init__(self, message: str) -> None:
        super().__init__(message)


_METADATA_HOSTS = {"metadata.google.internal", "metadata", "instance-data"}
_METADATA_IPS = {
    ipaddress.ip_address("169.254.169.254"),
    ipaddress.ip_address("100.100.100.200"),
}


def _host_allowed(host: str, allowlist: list[str]) -> bool:
    host = host.lower().rstrip(".")
    if host in allowlist:
        return True
    return any(
        entry.startswith("*.") and host.endswith(entry[1:]) for entry in allowlist
    )


def _is_sensitive_ip(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    return (
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_multicast
        or ip.is_reserved
        or ip.is_unspecified
        or ip in _METADATA_IPS
    )


async def _resolve(host: str, port: int) -> list[ipaddress.IPv4Address | ipaddress.IPv6Address]:
    loop = asyncio.get_running_loop()
    infos = await loop.run_in_executor(
        None, lambda: socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    )
    addresses: list[ipaddress.IPv4Address | ipaddress.IPv6Address] = []
    for info in infos:
        raw = info[4][0]
        try:
            addresses.append(ipaddress.ip_address(raw))
        except ValueError:
            continue
    return addresses


async def validate_upstream_url(url: str, settings: GatewaySettings) -> str:
    """Return a normalized URL or raise :class:`UpstreamURLRejected`."""
    if not isinstance(url, str) or not url.strip():
        raise UpstreamURLRejected("upstream URL is required")
    value = url.strip()
    parsed = urlsplit(value)
    if parsed.scheme not in {"http", "https"}:
        raise UpstreamURLRejected("upstream URL must use http or https")
    if parsed.username or parsed.password:
        raise UpstreamURLRejected("upstream URL must not embed credentials")
    if not parsed.hostname:
        raise UpstreamURLRejected("upstream URL must include a hostname")
    try:
        port = parsed.port or (443 if parsed.scheme == "https" else 80)
    except ValueError as exc:
        raise UpstreamURLRejected("upstream URL has an invalid port") from exc

    host = parsed.hostname.lower().rstrip(".")
    if host in _METADATA_HOSTS:
        raise UpstreamURLRejected("cloud metadata endpoints are not permitted")

    allowlisted = _host_allowed(host, settings.allowed_upstream_host_list)
    if not allowlisted and not settings.allow_public_upstreams:
        raise UpstreamURLRejected(
            "upstream host is not in GATEWAY_ALLOWED_UPSTREAM_HOSTS"
        )

    try:
        addresses = await _resolve(host, port)
    except OSError as exc:
        raise UpstreamURLRejected("upstream hostname could not be resolved") from exc
    if not addresses:
        raise UpstreamURLRejected("upstream hostname did not resolve")
    sensitive = [ip for ip in addresses if _is_sensitive_ip(ip)]
    if sensitive and not allowlisted:
        raise UpstreamURLRejected(
            "upstream resolves to a private, loopback or link-local address"
        )
    if sensitive and any(ip in _METADATA_IPS for ip in sensitive):
        raise UpstreamURLRejected("cloud metadata endpoints are not permitted")

    # Keep only the origin + path; query/fragment on an MCP endpoint are noise.
    normalized = f"{parsed.scheme}://{parsed.netloc}{parsed.path}".rstrip("/")
    return normalized
