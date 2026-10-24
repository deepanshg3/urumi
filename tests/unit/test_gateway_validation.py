"""Unit tests for upstream URL validation / SSRF protection."""

from __future__ import annotations

import ipaddress

import pytest

from services.gateway import validation
from services.gateway.validation import UpstreamURLRejected, validate_upstream_url

from tests.conftest import gateway_settings


def _force_resolution(monkeypatch: pytest.MonkeyPatch, *addresses: str) -> None:
    async def fake_resolve(host: str, port: int):
        return [ipaddress.ip_address(address) for address in addresses]

    monkeypatch.setattr(validation, "_resolve", fake_resolve)


async def test_accepts_allowlisted_local_host(monkeypatch: pytest.MonkeyPatch) -> None:
    _force_resolution(monkeypatch, "127.0.0.1")
    url = await validate_upstream_url("http://127.0.0.1:8101/mcp/", gateway_settings())
    assert url == "http://127.0.0.1:8101/mcp"


@pytest.mark.parametrize(
    "url",
    [
        "",
        "ftp://example.com/mcp",
        "http://user:pass@example.com/mcp",
        "http:///mcp",
        "http://metadata.google.internal/mcp",
        "not a url",
    ],
)
async def test_rejects_malformed_or_unsafe_urls(
    monkeypatch: pytest.MonkeyPatch, url: str
) -> None:
    _force_resolution(monkeypatch, "127.0.0.1")
    with pytest.raises(UpstreamURLRejected):
        await validate_upstream_url(url, gateway_settings())


async def test_rejects_host_outside_allowlist(monkeypatch: pytest.MonkeyPatch) -> None:
    _force_resolution(monkeypatch, "93.184.216.34")
    with pytest.raises(UpstreamURLRejected):
        await validate_upstream_url("https://example.com/mcp", gateway_settings())


async def test_public_upstream_requires_opt_in(monkeypatch: pytest.MonkeyPatch) -> None:
    _force_resolution(monkeypatch, "93.184.216.34")
    settings = gateway_settings(allow_public_upstreams=True)
    url = await validate_upstream_url("https://example.com/mcp", settings)
    assert url == "https://example.com/mcp"


async def test_public_opt_in_still_rejects_private_ip(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _force_resolution(monkeypatch, "10.0.0.5")
    settings = gateway_settings(allow_public_upstreams=True)
    with pytest.raises(UpstreamURLRejected):
        await validate_upstream_url("https://example.com/mcp", settings)


async def test_metadata_ip_always_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    _force_resolution(monkeypatch, "169.254.169.254")
    settings = gateway_settings(
        allow_public_upstreams=True, allowed_upstream_hosts="example.com"
    )
    with pytest.raises(UpstreamURLRejected):
        await validate_upstream_url("https://example.com/mcp", settings)


async def test_wildcard_allowlist_entry(monkeypatch: pytest.MonkeyPatch) -> None:
    _force_resolution(monkeypatch, "127.0.0.1")
    settings = gateway_settings(allowed_upstream_hosts="*.internal")
    url = await validate_upstream_url("http://ship.internal:9000/mcp", settings)
    assert url == "http://ship.internal:9000/mcp"
