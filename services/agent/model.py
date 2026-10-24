"""Gemini chat-model construction and optional LangSmith tracing."""

from __future__ import annotations

import os
from typing import Any

from services.common.config import LangsmithSettings, LlmSettings
from services.common.errors import ConfigurationError
from services.common.logging import get_logger

logger = get_logger("urumi.agent.model")

_PLACEHOLDER_MARKERS = (
    "your-",
    "replace-with",
    "changeme",
    "change-me",
    "example",
    "xxx",
)


def is_placeholder_secret(value: str) -> bool:
    """True for empty or obviously-placeholder secret values."""
    candidate = (value or "").strip().lower()
    if not candidate:
        return True
    return any(marker in candidate for marker in _PLACEHOLDER_MARKERS)


def require_api_key(llm: LlmSettings) -> str:
    if is_placeholder_secret(llm.api_key):
        raise ConfigurationError(
            "GEMINI_API_KEY is not configured. Set a real Gemini API key via the "
            "environment (or secret manager) before using the chat agent."
        )
    return llm.api_key


def configure_tracing(langsmith: LangsmithSettings) -> bool:
    """Enable/disable LangSmith tracing via env vars read by LangChain.

    Tracing is off unless explicitly enabled *and* an API key is present, so a
    missing key can never silently break or leak a request.
    """
    enabled = bool(langsmith.tracing_enabled) and not is_placeholder_secret(
        langsmith.api_key
    )
    if not enabled:
        for key in ("LANGSMITH_TRACING", "LANGCHAIN_TRACING_V2"):
            os.environ[key] = "false"
        if langsmith.tracing_enabled:
            logger.warning(
                "langsmith tracing requested but LANGSMITH_API_KEY is missing/placeholder; tracing disabled"
            )
        return False

    os.environ["LANGSMITH_TRACING"] = "true"
    os.environ["LANGCHAIN_TRACING_V2"] = "true"
    os.environ["LANGSMITH_API_KEY"] = langsmith.api_key
    os.environ["LANGCHAIN_API_KEY"] = langsmith.api_key
    if langsmith.project:
        os.environ["LANGSMITH_PROJECT"] = langsmith.project
        os.environ["LANGCHAIN_PROJECT"] = langsmith.project
    if langsmith.endpoint:
        os.environ["LANGSMITH_ENDPOINT"] = langsmith.endpoint
    return True


def build_chat_model(llm: LlmSettings, *, tools: list[Any] | None = None) -> Any:
    """Create a Gemini chat model, optionally bound to LangChain tools.

    Imported lazily so the agent's non-LLM endpoints (health, tool listing)
    keep working even if the optional LLM dependencies are absent.
    """
    api_key = require_api_key(llm)
    try:
        from langchain_google_genai import ChatGoogleGenerativeAI
    except ImportError as exc:  # pragma: no cover - dependency present in .venv
        raise ConfigurationError(
            "langchain-google-genai is not installed; install the 'agent' extras"
        ) from exc

    model = ChatGoogleGenerativeAI(
        model=llm.model,
        google_api_key=api_key,
        temperature=llm.temperature,
        max_output_tokens=llm.max_output_tokens,
        timeout=llm.request_timeout_seconds,
        max_retries=llm.max_retries,
    )
    if tools:
        return model.bind_tools(tools)
    return model
