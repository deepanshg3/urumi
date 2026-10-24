"""Urumi chat agent (Pass 7).

A FastAPI service that lets an authenticated dashboard user chat with Gemini
(LangChain tool calling). The agent is an MCP *client* of the gateway: it
discovers only the tools the user is authorized to see and executes every call
through the gateway, which re-checks authentication, authorization and audit
for each call. The agent never holds upstream credentials and never bypasses
the gateway.
"""

from __future__ import annotations

__all__ = ["__version__"]

__version__ = "0.1.0"
