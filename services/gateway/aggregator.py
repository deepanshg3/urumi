"""Tool discovery, aggregation, naming and routing across upstreams."""

from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from services.common.config import GatewaySettings
from services.common.errors import NotFoundError
from services.common.logging import get_logger
from services.gateway.db import ServerRegistration
from services.gateway.registry import ServerRegistry
from services.gateway.upstream import (
    StreamableHTTPUpstream,
    UpstreamCallError,
    UpstreamClient,
    UpstreamResult,
    UpstreamTool,
    tool_to_mcp,
)

logger = get_logger("urumi.gateway.aggregator")

PUBLIC_SEPARATOR = "__"


def sanitize_server_id(server_id: str) -> str:
    value = re.sub(r"[^a-z0-9]+", "_", server_id.lower()).strip("_")
    return value or "server"


def public_tool_name(server_id: str, upstream_tool: str) -> str:
    return f"{sanitize_server_id(server_id)}{PUBLIC_SEPARATOR}{upstream_tool}"


@dataclass(frozen=True)
class ToolRoute:
    public_name: str
    server_id: str
    upstream_name: str
    description: str | None
    input_schema: dict[str, Any]
    output_schema: dict[str, Any] | None = None

    def to_mcp_tool(self):
        return tool_to_mcp(
            self.public_name,
            UpstreamTool(
                name=self.upstream_name,
                description=self.description,
                input_schema=self.input_schema,
                output_schema=self.output_schema,
            ),
        )


@dataclass
class ServerCatalog:
    server_id: str
    healthy: bool = False
    error: str | None = None
    refreshed_at: datetime | None = None
    tools: list[ToolRoute] = field(default_factory=list)


class Aggregator:
    def __init__(
        self,
        registry: ServerRegistry,
        settings: GatewaySettings,
        *,
        client_factory=None,
    ) -> None:
        self.registry = registry
        self.settings = settings
        self._client_factory = client_factory or self._default_client
        self._catalogs: dict[str, ServerCatalog] = {}
        self._lock = asyncio.Lock()

    def _default_client(self, server: ServerRegistration) -> UpstreamClient:
        return StreamableHTTPUpstream(
            server.server_id,
            server.endpoint or "",
            headers=self.registry.auth_headers(server),
            timeout_seconds=self.settings.upstream_timeout_seconds,
            retries=self.settings.upstream_retries,
        )

    def client_for(self, server: ServerRegistration) -> UpstreamClient:
        return self._client_factory(server)

    async def refresh(self, server_id: str | None = None) -> dict[str, ServerCatalog]:
        async with self._lock:
            if server_id is None:
                servers = await self.registry.enabled()
            else:
                try:
                    server = await self.registry.get(server_id)
                except NotFoundError:
                    self._catalogs.pop(server_id, None)
                    return dict(self._catalogs)
                servers = [server] if server.enabled else [server]

            for server in servers:
                if not server.enabled:
                    self._catalogs.pop(server.server_id, None)
                    await self.registry.mark_health(server.server_id, status="disabled", tool_count=0)
                    continue
                await self._refresh_one(server)
            if server_id is None:
                known_enabled = {server.server_id for server in servers}
                for stale in set(self._catalogs) - known_enabled:
                    self._catalogs.pop(stale, None)
            return dict(self._catalogs)

    async def _refresh_one(self, server: ServerRegistration) -> None:
        try:
            client = self.client_for(server)
            tools = await asyncio.wait_for(
                client.list_tools(), timeout=self.settings.discovery_timeout_seconds
            )
        except (asyncio.TimeoutError, TimeoutError):
            await self._mark_failed(server.server_id, "timeout", "tool discovery timed out")
            return
        except UpstreamCallError as exc:
            await self._mark_failed(server.server_id, exc.code, exc.message)
            return
        except Exception as exc:  # defensive: never let one upstream break the rest
            logger.warning(
                "unexpected discovery error server=%s type=%s",
                server.server_id,
                type(exc).__name__,
            )
            await self._mark_failed(server.server_id, "upstream_error", "tool discovery failed")
            return

        routes: list[ToolRoute] = []
        seen: set[str] = set()
        for tool in tools:
            public = public_tool_name(server.server_id, tool.name)
            if public in seen:
                logger.warning(
                    "duplicate upstream tool skipped server=%s tool=%s",
                    server.server_id,
                    tool.name,
                )
                continue
            seen.add(public)
            routes.append(
                ToolRoute(
                    public_name=public,
                    server_id=server.server_id,
                    upstream_name=tool.name,
                    description=tool.description,
                    input_schema=tool.input_schema,
                    output_schema=tool.output_schema,
                )
            )
        self._catalogs[server.server_id] = ServerCatalog(
            server_id=server.server_id,
            healthy=True,
            refreshed_at=datetime.now(timezone.utc),
            tools=routes,
        )
        await self.registry.mark_health(
            server.server_id, status="healthy", tool_count=len(routes), error=None
        )

    async def _mark_failed(self, server_id: str, code: str, message: str) -> None:
        logger.warning("upstream unhealthy server=%s code=%s", server_id, code)
        # Drop its tools so unavailable upstreams do not poison discovery.
        self._catalogs[server_id] = ServerCatalog(server_id=server_id, healthy=False, error=code)
        await self.registry.mark_health(
            server_id, status="unhealthy", tool_count=0, error=code
        )

    # -- reads -------------------------------------------------------------
    def routes(self, *, healthy_only: bool = True) -> list[ToolRoute]:
        routes: list[ToolRoute] = []
        for catalog in self._catalogs.values():
            if healthy_only and not catalog.healthy:
                continue
            routes.extend(catalog.tools)
        return sorted(routes, key=lambda route: route.public_name)

    def catalog(self, server_id: str) -> ServerCatalog | None:
        return self._catalogs.get(server_id)

    def unhealthy_servers(self) -> list[str]:
        return sorted(sid for sid, catalog in self._catalogs.items() if not catalog.healthy)

    def resolve(self, public_name: str) -> ToolRoute:
        for catalog in self._catalogs.values():
            if not catalog.healthy:
                continue
            for route in catalog.tools:
                if route.public_name == public_name:
                    return route
        raise NotFoundError("tool", public_name)

    # -- calls -------------------------------------------------------------
    async def call(
        self, route: ToolRoute, arguments: dict[str, Any]
    ) -> UpstreamResult:
        server = await self.registry.get(route.server_id)
        if not server.enabled:
            raise UpstreamCallError("disabled", "upstream server is disabled")
        client = self.client_for(server)
        try:
            return await asyncio.wait_for(
                client.call_tool(route.upstream_name, arguments),
                timeout=self.settings.upstream_timeout_seconds,
            )
        except (asyncio.TimeoutError, TimeoutError) as exc:
            raise UpstreamCallError("timeout", "upstream tool call timed out") from exc
        except UpstreamCallError:
            raise
        except Exception as exc:  # defensive categorization
            logger.warning(
                "unexpected call error server=%s tool=%s type=%s",
                route.server_id,
                route.upstream_name,
                type(exc).__name__,
            )
            raise UpstreamCallError("upstream_error", "upstream tool call failed") from exc
