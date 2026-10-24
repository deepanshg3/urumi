"""System-prompt loading and rendering for the chat agent."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from services.common.config import AgentSettings, project_root
from services.agent.gateway_client import GatewayTool

DEFAULT_PROMPT = (
    "You are Urumi, the assistant inside the Urumi MCP Gateway dashboard.\n"
    "Only use the tools provided to you. Never invent tool names or results.\n"
    "Never ask the user for API keys, tokens or other secrets.\n"
    "If a question cannot be answered with the available tools, say so directly.\n"
)


def load_system_prompt(settings: AgentSettings) -> str:
    path = Path(settings.system_prompt_path)
    if not path.is_absolute():
        path = project_root() / path
    if not path.is_file():
        return DEFAULT_PROMPT
    return path.read_text(encoding="utf-8").strip() or DEFAULT_PROMPT


def _now(settings: AgentSettings) -> datetime:
    try:
        tz = ZoneInfo(settings.business_timezone)
    except (ZoneInfoNotFoundError, ValueError):
        tz = ZoneInfo("UTC")
    return datetime.now(tz)


def render_system_prompt(
    settings: AgentSettings, tools: list[GatewayTool], *, user_email: str | None = None
) -> str:
    base = load_system_prompt(settings)
    now = _now(settings)
    lines = [base, ""]
    lines.append(f"Current time: {now.isoformat(timespec='seconds')} (timezone {settings.business_timezone}).")
    if user_email:
        lines.append(f"You are assisting: {user_email}.")
    lines.append("")
    lines.append("Available tools (already filtered to this user's permissions):")
    if tools:
        for tool in tools:
            description = (tool.description or "").strip().splitlines()[0] if tool.description else ""
            lines.append(f"- {tool.name}: {description}".rstrip())
    else:
        lines.append("- (none: this user has no authorized tools)")
    lines.append("")
    lines.append(
        "Permissions are enforced by the gateway on every call. If a tool is "
        "denied or fails, explain it plainly and do not retry with changed "
        "arguments more than once."
    )
    return "\n".join(lines)
