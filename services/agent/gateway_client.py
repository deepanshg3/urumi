"""MCP client for the gateway's ``/mcp`` endpoint.

The agent is a normal MCP client. It authenticates with a short-lived,
per-user, delegated API key minted server-side, so the gateway can still
attribute every tool call to the real user and enforce that user's permissions.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

import httpx
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

from services.common.logging import get_logger

logger = get_logger("urumi.agent.gateway_client")


class GatewayClientError(Exception):
    """A safe, categorized gateway failure (no secrets in the message)."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass(frozen=True)
class GatewayTool:
    name: str
    description: str | None
    input_schema: dict[str, Any]


@dataclass(frozen=True)
class ToolResult:
    text: str
    structured: dict[str, Any] | None = None
    is_error: bool = False
    content_types: list[str] = field(default_factory=list)


def _content_text(result: Any) -> tuple[str, list[str]]:
    parts: list[str] = []
    types: list[str] = []
    for item in getattr(result, "content", None) or []:
        item_type = getattr(item, "type", "unknown")
        types.append(item_type)
        if item_type == "text":
            parts.append(getattr(item, "text", "") or "")
        else:
            dumped = item.model_dump(exclude_none=True) if hasattr(item, "model_dump") else {}
            parts.append(json.dumps(dumped, default=str))
    return "\n".join(part for part in parts if part), types


class GatewayMCPClient:
    """One MCP session against the gateway, reused across a chat turn."""

    def __init__(
        self,
        url: str,
        token: str,
        *,
        timeout_seconds: float = 20.0,
    ) -> None:
        self.url = url
        self.token = token
        self.timeout_seconds = timeout_seconds
        self._http: httpx.AsyncClient | None = None
        self._session: ClientSession | None = None
        self._cm: Any = None

    async def __aenter__(self) -> "GatewayMCPClient":
        headers = {"Authorization": f"Bearer {self.token}"}
        self._http = httpx.AsyncClient(
            headers=headers, timeout=httpx.Timeout(self.timeout_seconds)
        )
        try:
            self._cm = streamable_http_client(self.url, http_client=self._http)
            read, write, _ = await self._cm.__aenter__()
            self._session = ClientSession(read, write)
            await self._session.__aenter__()
            await self._session.initialize()
        except Exception as exc:
            await self.__aexit__(type(exc), exc, None)
            logger.warning("gateway MCP connect failed type=%s", type(exc).__name__)
            raise GatewayClientError(
                "gateway_unreachable", "could not connect to the gateway MCP endpoint"
            ) from exc
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        if self._session is not None:
            try:
                await self._session.__aexit__(exc_type, exc, tb)
            finally:
                self._session = None
        if self._cm is not None:
            try:
                await self._cm.__aexit__(exc_type, exc, tb)
            finally:
                self._cm = None
        if self._http is not None:
            await self._http.aclose()
            self._http = None

    async def list_tools(self) -> list[GatewayTool]:
        if self._session is None:
            raise GatewayClientError("not_connected", "gateway session is not open")
        try:
            result = await self._session.list_tools()
        except Exception as exc:
            logger.warning("gateway list_tools failed type=%s", type(exc).__name__)
            raise GatewayClientError("gateway_error", "tool discovery failed") from exc
        return [
            GatewayTool(
                name=tool.name,
                description=tool.description,
                input_schema=dict(tool.inputSchema or {"type": "object"}),
            )
            for tool in result.tools
        ]

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> ToolResult:
        if self._session is None:
            raise GatewayClientError("not_connected", "gateway session is not open")
        try:
            result = await self._session.call_tool(name, arguments)
        except Exception as exc:
            logger.warning("gateway call_tool failed tool=%s type=%s", name, type(exc).__name__)
            raise GatewayClientError("gateway_error", "tool call failed") from exc
        text, types = _content_text(result)
        return ToolResult(
            text=text,
            structured=result.structuredContent,
            is_error=bool(result.isError),
            content_types=types,
        )
