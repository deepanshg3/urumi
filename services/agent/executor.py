"""The LangChain tool-calling loop.

A deliberately small, dependency-light loop built on LangChain message types
and Gemini function calling (``ChatGoogleGenerativeAI.bind_tools``). It gives
explicit, testable control over iteration and tool-call limits, per-call
timeouts and error handling -- and it never executes a tool the user is not
authorized to see, because the tool list comes from the gateway itself.
"""

from __future__ import annotations

import asyncio
import json
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

from langchain_core.messages import (
    AIMessage,
    BaseMessage,
    HumanMessage,
    SystemMessage,
    ToolMessage,
)
from langchain_core.tools import StructuredTool
from pydantic import BaseModel, ValidationError

from services.agent.gateway_client import GatewayTool, ToolResult
from services.agent.schema import json_schema_to_model
from services.common.logging import get_logger

logger = get_logger("urumi.agent.executor")

ToolCaller = Callable[[str, dict[str, Any]], Awaitable[ToolResult]]

MAX_TOOL_RESULT_CHARS = 8000


@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str
    input_schema: dict[str, Any]
    args_model: type[BaseModel]
    lc_tool: StructuredTool


@dataclass
class ToolInvocation:
    name: str
    arguments: dict[str, Any]
    status: str
    error: str | None = None
    latency_ms: int = 0
    is_error: bool = False
    result_text: str = ""

    def summary(self) -> dict[str, Any]:
        return {
            "tool": self.name,
            "status": self.status,
            "latency_ms": self.latency_ms,
        }


@dataclass
class AgentRunResult:
    reply: str
    invocations: list[ToolInvocation] = field(default_factory=list)
    iterations: int = 0
    truncated: bool = False
    truncated_reason: str | None = None
    model_error: str | None = None


def _placeholder(**_: Any) -> str:  # pragma: no cover - never executed
    raise NotImplementedError("tools are executed through the gateway client")


def build_tool_specs(gateway_tools: list[GatewayTool]) -> list[ToolSpec]:
    """Turn gateway tool descriptors into LangChain tools + arg models."""
    specs: list[ToolSpec] = []
    for tool in gateway_tools:
        args_model = json_schema_to_model(tool.name, tool.input_schema)
        lc_tool = StructuredTool(
            name=tool.name,
            description=tool.description or "",
            args_schema=args_model,
            coroutine=_placeholder,
        )
        specs.append(
            ToolSpec(
                name=tool.name,
                description=tool.description or "",
                input_schema=tool.input_schema,
                args_model=args_model,
                lc_tool=lc_tool,
            )
        )
    return specs


def message_text(message: BaseMessage) -> str:
    content = getattr(message, "content", "")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for block in content:
            if isinstance(block, str):
                parts.append(block)
            elif isinstance(block, dict) and block.get("type") in (None, "text"):
                parts.append(str(block.get("text", "")))
        return "\n".join(part for part in parts if part)
    return str(content or "")


def _truncate(text: str, limit: int = MAX_TOOL_RESULT_CHARS) -> str:
    if len(text) <= limit:
        return text
    return text[:limit] + "\n... (truncated)"


def _format_validation_error(exc: ValidationError, spec: ToolSpec) -> str:
    """Render a readable argument-validation error for the model to act on."""
    problems: list[str] = []
    allowed = sorted(spec.args_model.model_fields)
    for error in exc.errors(include_url=False, include_context=False):
        kind = error.get("type")
        location = ".".join(str(part) for part in error.get("loc", ())) or "arguments"
        if kind == "extra_forbidden":
            unknown = error.get("loc") or ()
            extra = unknown[-1] if unknown else "?"
            problems.append(
                f"unknown argument '{extra}'; allowed arguments: {', '.join(allowed) or 'none'}"
            )
        else:
            problems.append(f"{location}: {error.get('msg', kind)}")
    return "; ".join(problems) or str(exc.errors(include_url=False, include_context=False))


class AgentExecutor:
    def __init__(
        self,
        model: Any,
        specs: list[ToolSpec],
        *,
        max_iterations: int,
        max_tool_calls: int,
        model_timeout_seconds: float,
        tool_timeout_seconds: float,
        max_content_chars: int = MAX_TOOL_RESULT_CHARS,
    ) -> None:
        self.model = model
        self.specs = {spec.name: spec for spec in specs}
        self.max_iterations = max_iterations
        self.max_tool_calls = max_tool_calls
        self.model_timeout_seconds = model_timeout_seconds
        self.tool_timeout_seconds = tool_timeout_seconds
        self.max_content_chars = max_content_chars

    @property
    def lc_tools(self) -> list[StructuredTool]:
        return [spec.lc_tool for spec in self.specs.values()]

    async def _call_model(self, messages: list[BaseMessage]) -> AIMessage:
        return await asyncio.wait_for(
            self.model.ainvoke(messages), timeout=self.model_timeout_seconds
        )

    async def _execute_tool(
        self, call: dict[str, Any], caller: ToolCaller
    ) -> ToolInvocation:
        name = str(call.get("name") or "")
        raw_args = call.get("args") or {}
        if not isinstance(raw_args, dict):
            raw_args = {"input": raw_args}
        spec = self.specs.get(name)
        if spec is None:
            return ToolInvocation(
                name=name or "unknown",
                arguments=raw_args,
                status="unknown_tool",
                error="no such tool is available to this user",
            )
        try:
            validated = spec.args_model.model_validate(raw_args)
            arguments = validated.model_dump(exclude_none=True)
        except ValidationError as exc:
            return ToolInvocation(
                name=name,
                arguments=raw_args,
                status="invalid_arguments",
                error=_format_validation_error(exc, spec),
            )
        started = time.perf_counter()
        try:
            result = await asyncio.wait_for(
                caller(name, arguments), timeout=self.tool_timeout_seconds
            )
        except (TimeoutError, asyncio.TimeoutError):
            latency = int((time.perf_counter() - started) * 1000)
            return ToolInvocation(
                name=name,
                arguments=arguments,
                status="timeout",
                error="tool call timed out",
                latency_ms=latency,
                is_error=True,
            )
        except Exception as exc:  # categorized gateway errors
            latency = int((time.perf_counter() - started) * 1000)
            code = getattr(exc, "code", "tool_error")
            return ToolInvocation(
                name=name,
                arguments=arguments,
                status=code,
                error=str(getattr(exc, "message", None) or exc),
                latency_ms=latency,
                is_error=True,
            )
        latency = int((time.perf_counter() - started) * 1000)
        invocation = ToolInvocation(
            name=name,
            arguments=arguments,
            status="error" if result.is_error else "ok",
            error=None if not result.is_error else _truncate(result.text, 500),
            latency_ms=latency,
            is_error=result.is_error,
        )
        invocation.result_text = result.text
        return invocation

    def _tool_message(self, invocation: ToolInvocation, tool_call_id: str) -> ToolMessage:
        if invocation.is_error or invocation.error:
            payload: dict[str, Any] = {
                "status": invocation.status,
                "error": invocation.error or "tool call failed",
            }
            return ToolMessage(
                content=json.dumps(payload),
                tool_call_id=tool_call_id,
                status="error",
            )
        return ToolMessage(
            content=_truncate(invocation.result_text, self.max_content_chars),
            tool_call_id=tool_call_id,
        )

    async def run(
        self,
        *,
        system_prompt: str,
        history: list[BaseMessage],
        user_text: str,
        caller: ToolCaller,
    ) -> AgentRunResult:
        messages: list[BaseMessage] = [SystemMessage(system_prompt), *history, HumanMessage(user_text)]
        invocations: list[ToolInvocation] = []
        tool_calls_total = 0
        last_text = ""

        for iteration in range(1, self.max_iterations + 1):
            try:
                ai = await self._call_model(messages)
            except (TimeoutError, asyncio.TimeoutError):
                return AgentRunResult(
                    reply="The model timed out before completing the request.",
                    invocations=invocations,
                    iterations=iteration,
                    truncated=True,
                    truncated_reason="model_timeout",
                    model_error="timeout",
                )
            except Exception as exc:
                logger.warning("model invocation failed type=%s", type(exc).__name__)
                return AgentRunResult(
                    reply=(
                        "I could not reach the language model. "
                        "Please check the agent's model configuration and try again."
                    ),
                    invocations=invocations,
                    iterations=iteration,
                    truncated=True,
                    truncated_reason="model_error",
                    model_error=type(exc).__name__,
                )

            messages.append(ai)
            last_text = message_text(ai).strip()
            calls = list(getattr(ai, "tool_calls", None) or [])
            if not calls:
                return AgentRunResult(
                    reply=last_text or "I have nothing further to add.",
                    invocations=invocations,
                    iterations=iteration,
                )

            truncated_reason: str | None = None
            for call in calls:
                if tool_calls_total >= self.max_tool_calls:
                    truncated_reason = "max_tool_calls"
                    break
                tool_calls_total += 1
                invocation = await self._execute_tool(call, caller)
                invocations.append(invocation)
                messages.append(
                    self._tool_message(invocation, str(call.get("id") or ""))
                )
            if truncated_reason:
                return AgentRunResult(
                    reply=last_text
                    or "I reached the configured tool-call limit before finishing; "
                    "please refine the request.",
                    invocations=invocations,
                    iterations=iteration,
                    truncated=True,
                    truncated_reason=truncated_reason,
                )

        return AgentRunResult(
            reply=last_text
            or "I reached the configured iteration limit before finishing; "
            "please refine the request.",
            invocations=invocations,
            iterations=self.max_iterations,
            truncated=True,
            truncated_reason="max_iterations",
        )
