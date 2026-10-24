"""Gateway MCP server: aggregated tools over one Streamable HTTP endpoint.

Authentication is enforced by the ASGI middleware in `app.py` before the MCP
transport runs. This module re-reads the authenticated context from the request
state, filters discovery by permission and authorizes every call again.
"""

from __future__ import annotations

import time
from typing import Any

from mcp import types
from mcp.server.lowlevel import Server
from mcp.server.lowlevel.server import request_ctx
from mcp.server.transport_security import TransportSecuritySettings

from services.common.config import GatewaySettings
from services.common.errors import NotFoundError
from services.common.logging import get_logger
from services.gateway import audit
from services.gateway.aggregator import Aggregator, ToolRoute
from services.gateway.auth import AuthContext
from services.gateway.db import Database
from services.gateway.policy import PermissionPolicy
from services.gateway.upstream import UpstreamCallError

logger = get_logger("urumi.gateway.mcp")


def transport_security(settings: GatewaySettings, host: str) -> TransportSecuritySettings:
    hosts = settings.allowed_host_list if hasattr(settings, "allowed_host_list") else []
    origins = settings.allowed_origin_list if hasattr(settings, "allowed_origin_list") else []
    if not hosts and host in {"127.0.0.1", "localhost", "::1"}:
        hosts = ["127.0.0.1:*", "localhost:*", "[::1]:*"]
    if not origins and host in {"127.0.0.1", "localhost", "::1"}:
        origins = ["http://127.0.0.1:*", "http://localhost:*", "http://[::1]:*"]
    return TransportSecuritySettings(
        enable_dns_rebinding_protection=settings.enable_dns_rebinding_protection,
        allowed_hosts=hosts,
        allowed_origins=origins,
    )


def current_context() -> AuthContext | None:
    context = request_ctx.get(None)
    request = getattr(context, "request", None) if context else None
    return getattr(getattr(request, "state", None), "auth", None)


def unknown_arguments(route: ToolRoute, arguments: dict[str, Any]) -> list[str]:
    """Return argument names that the upstream tool does not declare.

    Upstream MCP servers bind arguments to typed models, so anything they do not
    know is dropped silently. Rejecting unknown names here turns a typo (or a
    hallucinated argument) into an explicit error instead of a call that quietly
    ran with default values.
    """
    schema = route.input_schema or {}
    properties = schema.get("properties")
    if not isinstance(properties, dict) or schema.get("additionalProperties") is True:
        return []
    return sorted(set(arguments) - set(properties))


def build_server(
    aggregator: Aggregator,
    database: Database,
    settings: GatewaySettings,
    policy: PermissionPolicy,
) -> Server:
    server = Server(
        "urumi-gateway",
        version="0.1.0",
        instructions=(
            "Aggregated Urumi MCP tools. Tool names are prefixed with the upstream "
            "server identifier, for example woocommerce__list_products. Access is "
            "authorized per user; unavailable upstreams are reported as tool errors."
        ),
    )

    def _visible_routes(context: AuthContext | None) -> list[ToolRoute]:
        if context is None:
            return []
        hidden = set(settings.model_hidden_tools)
        return [
            route
            for route in aggregator.routes(healthy_only=True)
            if route.public_name not in hidden
            and policy.can_call_tool(context.permissions, route.server_id, route.upstream_name)
        ]

    @server.list_tools()
    async def list_tools() -> list[types.Tool]:
        return [route.to_mcp_tool() for route in _visible_routes(current_context())]

    @server.call_tool(validate_input=False)
    async def call_tool(name: str, arguments: dict[str, Any]) -> types.CallToolResult:
        context = current_context()
        started = time.perf_counter()
        if context is None:
            return types.CallToolResult(
                content=[types.TextContent(type="text", text="authentication_error: missing credentials")],
                isError=True,
            )

        try:
            route = aggregator.resolve(name)
        except NotFoundError:
            await audit.record(
                database,
                settings,
                context,
                server_id="unknown",
                public_tool=name,
                upstream_tool=None,
                status="error",
                error_code="unknown_tool",
            )
            return types.CallToolResult(
                content=[
                    types.TextContent(
                        type="text",
                        text=f"unknown_tool: {name!r} is not an available upstream tool",
                    )
                ],
                isError=True,
            )

        if not policy.can_call_tool(context.permissions, route.server_id, route.upstream_name):
            await audit.record(
                database,
                settings,
                context,
                server_id=route.server_id,
                public_tool=route.public_name,
                upstream_tool=route.upstream_name,
                status="denied",
                latency_ms=(time.perf_counter() - started) * 1000,
                error_code="permission_denied",
            )
            return types.CallToolResult(
                content=[
                    types.TextContent(
                        type="text",
                        text=f"permission_denied: access to {route.public_name!r} is not allowed",
                    )
                ],
                isError=True,
            )

        unexpected = unknown_arguments(route, arguments)
        if unexpected:
            await audit.record(
                database,
                settings,
                context,
                server_id=route.server_id,
                public_tool=route.public_name,
                upstream_tool=route.upstream_name,
                status="error",
                latency_ms=(time.perf_counter() - started),
                error_code="invalid_arguments",
            )
            return types.CallToolResult(
                content=[
                    types.TextContent(
                        type="text",
                        text=(
                            f"invalid_arguments: unknown argument(s) "
                            f"{', '.join(repr(name) for name in unexpected)} for tool "
                            f"{route.public_name!r}"
                        ),
                    )
                ],
                isError=True,
            )

        try:
            result = await aggregator.call(route, arguments)
        except UpstreamCallError as exc:
            await audit.record(
                database,
                settings,
                context,
                server_id=route.server_id,
                public_tool=route.public_name,
                upstream_tool=route.upstream_name,
                status="timeout" if exc.code == "timeout" else "error",
                latency_ms=(time.perf_counter() - started) * 1000,
                error_code=exc.code,
            )
            return types.CallToolResult(
                content=[
                    types.TextContent(
                        type="text",
                        text=f"{exc.code}: {exc.message}",
                    )
                ],
                isError=True,
            )

        status = "error" if result.is_error else "success"
        try:
            await audit.record(
                database,
                settings,
                context,
                server_id=route.server_id,
                public_tool=route.public_name,
                upstream_tool=route.upstream_name,
                status=status,
                latency_ms=(time.perf_counter() - started) * 1000,
                error_code="upstream_tool_error" if result.is_error else None,
            )
        except audit.AuditWriteError:
            return types.CallToolResult(
                content=[
                    types.TextContent(
                        type="text",
                        text="audit_error: the call ran but the audit entry could not be written",
                    )
                ],
                isError=True,
            )
        return result.to_call_result()

    return server
