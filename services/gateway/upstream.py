"""MCP client connections to upstream servers (Streamable HTTP)."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any, Protocol

import httpx
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client
from mcp.types import CallToolResult, Tool

from services.common.logging import get_logger

logger = get_logger("urumi.gateway.upstream")


class UpstreamCallError(Exception):
    """A safe, categorized upstream failure (no credentials in the message)."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass(frozen=True)
class UpstreamTool:
    name: str
    description: str | None
    input_schema: dict[str, Any]
    output_schema: dict[str, Any] | None = None


@dataclass(frozen=True)
class UpstreamResult:
    content: list[Any] = field(default_factory=list)
    structured: dict[str, Any] | None = None
    is_error: bool = False

    @classmethod
    def from_call_result(cls, result: CallToolResult) -> "UpstreamResult":
        return cls(
            content=list(result.content),
            structured=result.structuredContent,
            is_error=bool(result.isError),
        )

    def to_call_result(self) -> CallToolResult:
        return CallToolResult(
            content=self.content,  # type: ignore[arg-type]
            structuredContent=self.structured,
            isError=self.is_error,
        )


class UpstreamClient(Protocol):
    server_id: str

    async def list_tools(self) -> list[UpstreamTool]: ...

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> UpstreamResult: ...


class StreamableHTTPUpstream:
    """One-shot MCP client connection to an upstream server.

    A fresh session is opened per operation. This is simple and avoids sharing
    state across users; the SDK's stateless Streamable HTTP mode makes it cheap.
    """

    def __init__(
        self,
        server_id: str,
        url: str,
        *,
        headers: dict[str, str] | None = None,
        timeout_seconds: float = 15.0,
        retries: int = 0,
    ) -> None:
        self.server_id = server_id
        self.url = url
        self.headers = headers or {}
        self.timeout_seconds = timeout_seconds
        self.retries = retries

    async def _with_session(self, operation):
        timeout = httpx.Timeout(self.timeout_seconds)
        async with httpx.AsyncClient(headers=self.headers, timeout=timeout) as http_client:
            async with streamable_http_client(self.url, http_client=http_client) as (
                read,
                write,
                _,
            ):
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    return await operation(session)

    async def list_tools(self) -> list[UpstreamTool]:
        async def operation(session: ClientSession):
            return await session.list_tools()

        try:
            result = await asyncio.wait_for(
                self._with_session(operation), timeout=self.timeout_seconds
            )
        except (TimeoutError, asyncio.TimeoutError) as exc:
            raise UpstreamCallError("timeout", "upstream tool discovery timed out") from exc
        except httpx.HTTPError as exc:
            raise UpstreamCallError("connection_error", "upstream is unreachable") from exc
        except Exception as exc:  # SDK/protocol failures are categorized, not leaked
            logger.warning("upstream discovery failed server=%s type=%s", self.server_id, type(exc).__name__)
            raise UpstreamCallError("upstream_error", "upstream tool discovery failed") from exc

        return [
            UpstreamTool(
                name=tool.name,
                description=tool.description,
                input_schema=dict(tool.inputSchema or {"type": "object"}),
                output_schema=dict(tool.outputSchema) if tool.outputSchema else None,
            )
            for tool in result.tools
        ]

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> UpstreamResult:
        async def operation(session: ClientSession):
            return await session.call_tool(name, arguments)

        try:
            result = await asyncio.wait_for(
                self._with_session(operation), timeout=self.timeout_seconds
            )
        except (TimeoutError, asyncio.TimeoutError) as exc:
            raise UpstreamCallError("timeout", "upstream tool call timed out") from exc
        except httpx.HTTPError as exc:
            raise UpstreamCallError("connection_error", "upstream is unreachable") from exc
        except Exception as exc:
            logger.warning(
                "upstream call failed server=%s tool=%s type=%s",
                self.server_id,
                name,
                type(exc).__name__,
            )
            raise UpstreamCallError("upstream_error", "upstream tool call failed") from exc
        return UpstreamResult.from_call_result(result)


def tool_to_mcp(name: str, tool: UpstreamTool) -> Tool:
    return Tool(
        name=name,
        description=tool.description,
        inputSchema=tool.input_schema,
        outputSchema=tool.output_schema,
    )
