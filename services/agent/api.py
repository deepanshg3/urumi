"""Authenticated HTTP API for the chat agent."""

from __future__ import annotations

from dataclasses import dataclass

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select

from services.agent import persistence
from services.agent.schemas import (
    AgentToolView,
    ChatRequest,
    ChatResponse,
    ConversationDetail,
    ConversationView,
    Message,
    MessageView,
    ToolCallView,
)
from services.common.config import AppSettings
from services.gateway.api import CSRF_COOKIE, CSRF_HEADER, SESSION_COOKIE
from services.gateway.auth import AuthContext
from services.gateway.db import Database, User

AGENT_API_PREFIX = "/agent/api"


@dataclass
class _Context:
    db: Database
    settings: AppSettings
    service: Any


def _context(request: Request) -> _Context:
    agent = request.app.state.agent
    return _Context(db=agent.db, settings=agent.settings, service=agent.service)


def _conversation_view(record: persistence.ChatConversation) -> ConversationView:
    return ConversationView(
        id=record.id,
        title=record.title,
        created_at=record.created_at,
        updated_at=record.updated_at,
    )


def _message_view(record: persistence.ChatMessage) -> MessageView:
    return MessageView(
        id=record.id,
        role=record.role,
        content=record.content,
        tool_summary=record.tool_summary,
        created_at=record.created_at,
    )


def build_router() -> APIRouter:
    router = APIRouter(prefix=AGENT_API_PREFIX)

    async def require_auth(request: Request) -> AuthContext:
        context = getattr(request.state, "auth", None)
        if context is None:
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "authentication required")
        return context

    def require_csrf(request: Request) -> None:
        if request.method in {"GET", "HEAD", "OPTIONS"}:
            return
        session_csrf = getattr(request.state, "csrf_token", None)
        supplied = request.headers.get(CSRF_HEADER)
        if not session_csrf or not supplied or supplied != session_csrf:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "invalid CSRF token")

    async def _load_user(ctx: _Context, user_id: int) -> User:
        async with ctx.db.session_factory() as session:
            user = (
                await session.execute(select(User).where(User.id == user_id))
            ).scalar_one_or_none()
        if user is None or not user.is_active:
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "user is not active")
        return user

    @router.get("/tools", response_model=list[AgentToolView])
    async def list_tools(request: Request, context: AuthContext = Depends(require_auth)):
        ctx = _context(request)
        tools = await ctx.service.discover_tools(context.user_id)
        return [AgentToolView(name=tool.name, description=tool.description) for tool in tools]

    @router.get("/config")
    async def config(request: Request, context: AuthContext = Depends(require_auth)):
        ctx = _context(request)
        agent = ctx.settings.chat_agent
        return {
            "model": ctx.settings.llm.model,
            "tracing_enabled": bool(ctx.settings.langsmith.tracing_enabled),
            "max_iterations": agent.max_iterations,
            "max_tool_calls": agent.max_tool_calls,
            "max_history_messages": agent.max_history_messages,
            "business_timezone": agent.business_timezone,
        }

    @router.post("/chat", response_model=ChatResponse)
    async def chat(
        payload: ChatRequest,
        request: Request,
        context: AuthContext = Depends(require_auth),
    ):
        require_csrf(request)
        ctx = _context(request)
        user = await _load_user(ctx, context.user_id)
        outcome = await ctx.service.handle_chat(
            user, payload.message, conversation_id=payload.conversation_id
        )
        return ChatResponse(
            conversation_id=outcome.conversation_id,
            reply=outcome.reply,
            tool_calls=[ToolCallView(**item) for item in outcome.tool_calls],
            iterations=outcome.iterations,
            truncated=outcome.truncated,
            truncated_reason=outcome.truncated_reason,
            model_error=outcome.model_error,
        )

    @router.get("/conversations", response_model=list[ConversationView])
    async def list_conversations(request: Request, context: AuthContext = Depends(require_auth)):
        ctx = _context(request)
        records = await persistence.list_conversations(ctx.db, context.user_id)
        return [_conversation_view(record) for record in records]

    @router.get("/conversations/{conversation_id}", response_model=ConversationDetail)
    async def get_conversation(
        conversation_id: int,
        request: Request,
        context: AuthContext = Depends(require_auth),
    ):
        ctx = _context(request)
        conversation = await persistence.get_conversation(
            ctx.db, conversation_id, context.user_id
        )
        if conversation is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "conversation not found")
        messages = await persistence.list_messages(
            ctx.db, conversation_id, limit=ctx.settings.chat_agent.conversation_max_messages
        )
        return ConversationDetail(
            conversation=_conversation_view(conversation),
            messages=[_message_view(message) for message in messages],
        )

    @router.delete("/conversations/{conversation_id}", response_model=Message)
    async def delete_conversation(
        conversation_id: int,
        request: Request,
        context: AuthContext = Depends(require_auth),
    ):
        require_csrf(request)
        ctx = _context(request)
        deleted = await persistence.delete_conversation(
            ctx.db, conversation_id, context.user_id
        )
        if not deleted:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "conversation not found")
        return Message(message="conversation deleted")

    return router


__all__ = [
    "AGENT_API_PREFIX",
    "SESSION_COOKIE",
    "CSRF_COOKIE",
    "build_router",
]
