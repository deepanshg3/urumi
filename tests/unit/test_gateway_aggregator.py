"""Unit tests for tool discovery, aggregation, naming and routing."""

from __future__ import annotations

import asyncio

import pytest

from services.common.errors import NotFoundError
from services.gateway.aggregator import Aggregator, public_tool_name, sanitize_server_id
from services.gateway.db import Database, ensure_schema
from services.gateway.registry import ServerRegistry
from services.gateway.schemas import ServerCreate
from services.gateway.upstream import (
    UpstreamCallError,
    UpstreamResult,
    UpstreamTool,
)

from tests.conftest import gateway_settings


class FakeClient:
    def __init__(self, tools=None, *, call_result=None, call_error=None, delay=0.0):
        self._tools = tools or [
            UpstreamTool(name="echo", description="Echo", input_schema={"type": "object"})
        ]
        self._call_result = call_result or UpstreamResult(
            content=[{"type": "text", "text": "ok"}]
        )
        self._call_error = call_error
        self._delay = delay

    async def list_tools(self):
        return list(self._tools)

    async def call_tool(self, name, arguments):
        if self._delay:
            await asyncio.sleep(self._delay)
        if self._call_error:
            raise self._call_error
        return self._call_result


@pytest.fixture
async def setup(tmp_path):
    database = Database(f"sqlite+aiosqlite:///{tmp_path / 'agg.db'}")
    await ensure_schema(database)
    registry = ServerRegistry(database, gateway_settings())
    try:
        yield database, registry
    finally:
        await database.dispose()


async def _register(registry: ServerRegistry, server_id: str) -> None:
    await registry.create(
        ServerCreate(server_id=server_id, name=server_id, url=f"http://127.0.0.1:99/{server_id}")
    )


def test_sanitize_and_public_name() -> None:
    assert sanitize_server_id("My Server!") == "my_server"
    assert sanitize_server_id("!!!") == "server"
    assert public_tool_name("My Server", "list_products") == "my_server__list_products"


async def test_refresh_discovers_and_names_tools(setup) -> None:
    _, registry = setup
    await _register(registry, "woo")
    clients = {"woo": FakeClient()}
    aggregator = Aggregator(registry, gateway_settings(), client_factory=lambda s: clients[s.server_id])
    await aggregator.refresh()
    routes = aggregator.routes()
    assert [route.public_name for route in routes] == ["woo__echo"]
    assert aggregator.catalog("woo").healthy is True


async def test_duplicate_upstream_tools_deduped(setup) -> None:
    _, registry = setup
    await _register(registry, "woo")
    tools = [
        UpstreamTool(name="echo", description=None, input_schema={"type": "object"}),
        UpstreamTool(name="echo", description=None, input_schema={"type": "object"}),
    ]
    clients = {"woo": FakeClient(tools=tools)}
    aggregator = Aggregator(registry, gateway_settings(), client_factory=lambda s: clients[s.server_id])
    await aggregator.refresh()
    assert len(aggregator.routes()) == 1


async def test_failed_discovery_is_isolated(setup) -> None:
    _, registry = setup
    await _register(registry, "good")
    await _register(registry, "bad")

    class FailingClient(FakeClient):
        async def list_tools(self):
            raise UpstreamCallError("upstream_error", "boom")

    clients = {"good": FakeClient(), "bad": FailingClient()}
    aggregator = Aggregator(
        registry, gateway_settings(), client_factory=lambda s: clients[s.server_id]
    )
    await aggregator.refresh()
    assert [route.server_id for route in aggregator.routes()] == ["good"]
    assert aggregator.catalog("bad").healthy is False
    assert aggregator.catalog("bad").error == "upstream_error"


async def test_disabled_server_tools_dropped(setup) -> None:
    _, registry = setup
    await _register(registry, "woo")
    clients = {"woo": FakeClient()}
    aggregator = Aggregator(registry, gateway_settings(), client_factory=lambda s: clients[s.server_id])
    await aggregator.refresh()
    assert aggregator.routes()
    await registry.set_enabled("woo", False)
    await aggregator.refresh()
    assert aggregator.routes() == []
    with pytest.raises(NotFoundError):
        aggregator.resolve("woo__echo")


async def test_resolve_unknown_tool(setup) -> None:
    _, registry = setup
    aggregator = Aggregator(registry, gateway_settings(), client_factory=lambda s: FakeClient())
    with pytest.raises(NotFoundError):
        aggregator.resolve("nope__missing")


async def test_call_delegates_and_rejects_disabled(setup) -> None:
    _, registry = setup
    await _register(registry, "woo")
    clients = {"woo": FakeClient()}
    aggregator = Aggregator(registry, gateway_settings(), client_factory=lambda s: clients[s.server_id])
    await aggregator.refresh()
    route = aggregator.resolve("woo__echo")
    result = await aggregator.call(route, {"message": "hi"})
    assert result.is_error is False
    await registry.set_enabled("woo", False)
    with pytest.raises(UpstreamCallError) as excinfo:
        await aggregator.call(route, {})
    assert excinfo.value.code == "disabled"


async def test_call_timeout_categorized(setup) -> None:
    _, registry = setup
    await _register(registry, "slow")
    settings = gateway_settings(upstream_timeout_seconds=0.05)
    aggregator = Aggregator(
        registry, settings, client_factory=lambda s: FakeClient(delay=0.5)
    )
    await aggregator.refresh()
    route = aggregator.resolve("slow__echo")
    with pytest.raises(UpstreamCallError) as excinfo:
        await aggregator.call(route, {})
    assert excinfo.value.code == "timeout"


async def test_settle_discovery_recovers_late_upstream(setup) -> None:
    from services.gateway.app import settle_discovery

    _, registry = setup
    await _register(registry, "late")
    attempts = {"n": 0}

    class FlakyClient(FakeClient):
        async def list_tools(self):
            attempts["n"] += 1
            if attempts["n"] == 1:
                raise UpstreamCallError("upstream_error", "not ready")
            return await super().list_tools()

    aggregator = Aggregator(registry, gateway_settings(), client_factory=lambda s: FlakyClient())
    await aggregator.refresh()
    assert aggregator.unhealthy_servers() == ["late"]
    await settle_discovery(aggregator, attempts=3, delay=0)
    assert aggregator.unhealthy_servers() == []
    assert aggregator.resolve("late__echo").upstream_name == "echo"
