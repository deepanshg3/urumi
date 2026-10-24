"""Pydantic request/response models for the chat agent HTTP API."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=8000)
    conversation_id: int | None = None


class ToolCallView(BaseModel):
    tool: str
    status: str
    latency_ms: int = 0


class ChatResponse(BaseModel):
    conversation_id: int
    reply: str
    tool_calls: list[ToolCallView] = Field(default_factory=list)
    iterations: int = 0
    truncated: bool = False
    truncated_reason: str | None = None
    model_error: str | None = None


class AgentToolView(BaseModel):
    name: str
    description: str | None = None


class ConversationView(BaseModel):
    id: int
    title: str
    created_at: datetime
    updated_at: datetime


class MessageView(BaseModel):
    id: int
    role: str
    content: str
    tool_summary: list[dict[str, Any]] | None = None
    created_at: datetime


class ConversationDetail(BaseModel):
    conversation: ConversationView
    messages: list[MessageView]


class Message(BaseModel):
    message: str
