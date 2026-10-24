"""Chat orchestration: authenticate, delegate, discover, run, persist."""

from __future__ import annotations

import time
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import Any

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage

from services.agent import persistence
from services.agent.executor import AgentExecutor, AgentRunResult, ToolInvocation, build_tool_specs
from services.agent.gateway_client import GatewayMCPClient, GatewayTool
from services.agent.model import build_chat_model, configure_tracing, require_api_key
from services.agent.prompt import render_system_prompt
from services.common.config import AppSettings
from services.common.logging import get_logger
from services.gateway.auth import create_ephemeral_api_key, revoke_api_key
from services.gateway.db import Database, User

logger = get_logger("urumi.agent.service")

ModelFactory = Callable[[Any, list[Any]], Any]
ClientFactory = Callable[[str], "GatewayMCPClient"]


@dataclass
class ChatOutcome:
    conversation_id: int
    reply: str
    invocations: list[ToolInvocation] = field(default_factory=list)
    iterations: int = 0
    truncated: bool = False
    truncated_reason: str | None = None
    model_error: str | None = None

    @property
    def tool_calls(self) -> list[dict[str, Any]]:
        return [inv.summary() for inv in self.invocations]


def _default_client_factory(url: str, timeout: float) -> ClientFactory:
    return lambda token: GatewayMCPClient(url, token, timeout_seconds=timeout)


class AgentService:
    def __init__(
        self,
        database: Database,
        settings: AppSettings,
        *,
        model_factory: ModelFactory | None = None,
        client_factory: ClientFactory | None = None,
    ) -> None:
        self.database = database
        self.settings = settings
        self.llm = settings.llm
        self.langsmith = settings.langsmith
        self.agent = settings.chat_agent
        self._model_factory = model_factory or (
            lambda llm, tools: build_chat_model(llm, tools=tools)
        )
        self._client_factory = client_factory or _default_client_factory(
            self.agent.gateway_mcp_url, self.agent.gateway_timeout_seconds
        )
        self._tool_cache: dict[int, tuple[float, list[GatewayTool]]] = {}

    @asynccontextmanager
    async def _delegated_token(self, user_id: int) -> AsyncIterator[str]:
        record, plaintext = await create_ephemeral_api_key(
            self.database,
            user_id,
            ttl_seconds=self.agent.ephemeral_key_ttl_seconds,
        )
        try:
            yield plaintext
        finally:
            await revoke_api_key(self.database, record.id, user_id)

    async def discover_tools(self, user_id: int, *, force: bool = False) -> list[GatewayTool]:
        """Tools the gateway exposes to this user (already permission-filtered)."""
        refresh = self.agent.tool_discovery_refresh_seconds
        cached = self._tool_cache.get(user_id)
        if (
            not force
            and refresh > 0
            and cached is not None
            and (time.monotonic() - cached[0]) < refresh
        ):
            return cached[1]
        async with self._delegated_token(user_id) as token:
            async with self._client_factory(token) as client:
                tools = await client.list_tools()
        self._tool_cache[user_id] = (time.monotonic(), tools)
        return tools

    def invalidate_tool_cache(self, user_id: int | None = None) -> None:
        if user_id is None:
            self._tool_cache.clear()
        else:
            self._tool_cache.pop(user_id, None)

    @staticmethod
    def _history_messages(records: list[persistence.ChatMessage]) -> list[BaseMessage]:
        messages: list[BaseMessage] = []
        for record in records:
            if record.role == "user":
                messages.append(HumanMessage(content=record.content))
            elif record.role == "assistant":
                messages.append(AIMessage(content=record.content))
        return messages

    async def handle_chat(
        self,
        user: User,
        message: str,
        *,
        conversation_id: int | None = None,
    ) -> ChatOutcome:
        message = message.strip()
        if conversation_id is not None:
            conversation = await persistence.get_conversation(
                self.database, conversation_id, user.id
            )
            if conversation is None:
                from services.common.errors import NotFoundError

                raise NotFoundError("conversation", conversation_id)
        else:
            conversation = await persistence.create_conversation(
                self.database, user.id, title=message[:80]
            )

        history_records = await persistence.list_messages(
            self.database, conversation.id, limit=self.agent.max_history_messages
        )
        history = self._history_messages(history_records)

        await persistence.append_message(
            self.database, conversation.id, "user", message
        )

        try:
            # Fail fast with an actionable error when the model is misconfigured,
            # independent of gateway availability.
            require_api_key(self.llm)
            tools = await self.discover_tools(user.id)
            specs = build_tool_specs(tools)
            configure_tracing(self.langsmith)
            model = self._model_factory(self.llm, [spec.lc_tool for spec in specs])
            executor = AgentExecutor(
                model,
                specs,
                max_iterations=self.agent.max_iterations,
                max_tool_calls=self.agent.max_tool_calls,
                model_timeout_seconds=self.llm.request_timeout_seconds + 5.0,
                tool_timeout_seconds=self.agent.gateway_timeout_seconds,
                max_content_chars=self.agent.max_message_chars,
            )
            system_prompt = render_system_prompt(
                self.agent, tools, user_email=user.email
            )
            async with self._delegated_token(user.id) as token:
                async with self._client_factory(token) as client:
                    result = await executor.run(
                        system_prompt=system_prompt,
                        history=history,
                        user_text=message,
                        caller=client.call_tool,
                    )
        except Exception as exc:  # never leak internals; keep audit-friendly
            logger.warning("chat turn failed type=%s", type(exc).__name__)
            code = getattr(exc, "code", "agent_error")
            from services.common.errors import ConfigurationError

            if isinstance(exc, ConfigurationError):
                # Actionable configuration guidance, safe to show (no secrets).
                reply = getattr(exc, "message", str(exc))
            else:
                reply = (
                    "I could not complete that request. "
                    f"({code}) Please try again or contact an administrator."
                )
            outcome = ChatOutcome(
                conversation_id=conversation.id,
                reply=reply,
                truncated=True,
                truncated_reason=code,
                model_error=type(exc).__name__,
            )
        else:
            outcome = ChatOutcome(
                conversation_id=conversation.id,
                reply=result.reply,
                invocations=result.invocations,
                iterations=result.iterations,
                truncated=result.truncated,
                truncated_reason=result.truncated_reason,
                model_error=result.model_error,
            )

        await persistence.append_message(
            self.database,
            conversation.id,
            "assistant",
            outcome.reply,
            tool_summary=outcome.tool_calls or None,
        )
        await persistence.trim_conversation(
            self.database, conversation.id, max_messages=self.agent.conversation_max_messages
        )
        return outcome
