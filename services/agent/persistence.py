"""Conversation persistence for the chat agent.

Tables live in the same database as the gateway (``DATABASE_URL``) so
conversations are tied to real users, but use a separate declarative base so
the agent's schema stays logically independent of the gateway's.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import (
    DateTime,
    Integer,
    JSON,
    String,
    Text,
    delete,
    func,
    select,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from services.gateway.db import Database


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class AgentBase(DeclarativeBase):
    pass


class ChatConversation(AgentBase):
    __tablename__ = "chat_conversations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(Integer, index=True, nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False, default="")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False
    )


class ChatMessage(AgentBase):
    __tablename__ = "chat_messages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    conversation_id: Mapped[int] = mapped_column(Integer, index=True, nullable=False)
    role: Mapped[str] = mapped_column(String(16), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False, default="")
    tool_summary: Mapped[list[dict[str, Any]] | None] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )


async def ensure_agent_schema(database: Database) -> None:
    async with database.engine.begin() as connection:
        await connection.run_sync(AgentBase.metadata.create_all)


async def create_conversation(
    database: Database, user_id: int, title: str = ""
) -> ChatConversation:
    async with database.session_factory() as session:
        record = ChatConversation(user_id=user_id, title=title[:200])
        session.add(record)
        await session.commit()
        await session.refresh(record)
        return record


async def list_conversations(
    database: Database, user_id: int, *, limit: int = 50
) -> list[ChatConversation]:
    async with database.session_factory() as session:
        rows = await session.execute(
            select(ChatConversation)
            .where(ChatConversation.user_id == user_id)
            .order_by(ChatConversation.updated_at.desc())
            .limit(limit)
        )
        return list(rows.scalars())


async def get_conversation(
    database: Database, conversation_id: int, user_id: int
) -> ChatConversation | None:
    async with database.session_factory() as session:
        record = await session.get(ChatConversation, conversation_id)
        if record is None or record.user_id != user_id:
            return None
        return record


async def delete_conversation(
    database: Database, conversation_id: int, user_id: int
) -> bool:
    async with database.session_factory() as session:
        record = await session.get(ChatConversation, conversation_id)
        if record is None or record.user_id != user_id:
            return False
        await session.execute(
            delete(ChatMessage).where(ChatMessage.conversation_id == conversation_id)
        )
        await session.delete(record)
        await session.commit()
        return True


async def append_message(
    database: Database,
    conversation_id: int,
    role: str,
    content: str,
    tool_summary: list[dict[str, Any]] | None = None,
) -> ChatMessage:
    async with database.session_factory() as session:
        record = ChatMessage(
            conversation_id=conversation_id,
            role=role,
            content=content,
            tool_summary=tool_summary,
        )
        session.add(record)
        conversation = await session.get(ChatConversation, conversation_id)
        if conversation is not None:
            conversation.updated_at = utcnow()
        await session.commit()
        await session.refresh(record)
        return record


async def list_messages(
    database: Database, conversation_id: int, *, limit: int = 40
) -> list[ChatMessage]:
    async with database.session_factory() as session:
        rows = await session.execute(
            select(ChatMessage)
            .where(ChatMessage.conversation_id == conversation_id)
            .order_by(ChatMessage.id.desc())
            .limit(limit)
        )
        return list(reversed(list(rows.scalars())))


async def count_messages(database: Database, conversation_id: int) -> int:
    async with database.session_factory() as session:
        total = await session.execute(
            select(func.count(ChatMessage.id)).where(
                ChatMessage.conversation_id == conversation_id
            )
        )
        return int(total.scalar_one())


async def trim_conversation(
    database: Database, conversation_id: int, *, max_messages: int
) -> None:
    """Delete the oldest messages once the cap is exceeded."""
    async with database.session_factory() as session:
        keep = await session.execute(
            select(ChatMessage.id)
            .where(ChatMessage.conversation_id == conversation_id)
            .order_by(ChatMessage.id.desc())
            .limit(max_messages)
        )
        keep_ids = [row for row in keep.scalars()]
        if len(keep_ids) < max_messages:
            return
        await session.execute(
            delete(ChatMessage).where(
                ChatMessage.conversation_id == conversation_id,
                ChatMessage.id < min(keep_ids),
            )
        )
        await session.commit()
