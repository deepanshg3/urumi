"""SQLAlchemy persistence layer for the gateway (Pass 1).

The schema is intentionally driver-neutral: SQLite via ``aiosqlite`` for local
development and PostgreSQL via ``asyncpg`` later (``DATABASE_URL``). No
production migrations yet; tables are created from the models at startup.

This module does not authenticate or authorize anything. It only defines and
persists users, roles, API keys, upstream server registrations and audit
entries, which Passes 5/6 use.
"""

from __future__ import annotations

import json
import os
from collections.abc import AsyncIterator
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    select,
)
from sqlalchemy import inspect as sa_inspect
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

DEFAULT_DATABASE_URL = "sqlite+aiosqlite:///./data/gateway.db"

#: Roles that always exist, even when ``config/permissions.yaml`` is missing.
FALLBACK_ROLES: dict[str, str] = {
    "admin": "Full access, including user and server administration.",
    "member": "Operator access: day-to-day store operations, no administration.",
    "viewer": "Read-only access to permitted tools.",
}


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False
    )


class Role(TimestampMixin, Base):
    __tablename__ = "roles"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    description: Mapped[str | None] = mapped_column(Text)

    users: Mapped[list["User"]] = relationship(
        secondary="user_roles", back_populates="roles"
    )


class User(TimestampMixin, Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    email: Mapped[str] = mapped_column(String(320), unique=True, nullable=False)
    display_name: Mapped[str] = mapped_column(String(128), nullable=False, default="")
    password_hash: Mapped[str | None] = mapped_column(String(255))
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    roles: Mapped[list[Role]] = relationship(
        secondary="user_roles", back_populates="users", lazy="selectin"
    )
    api_keys: Mapped[list["ApiKey"]] = relationship(
        back_populates="user", cascade="all, delete-orphan", lazy="selectin"
    )


class UserRole(Base):
    __tablename__ = "user_roles"
    __table_args__ = (UniqueConstraint("user_id", "role_id", name="uq_user_role"),)

    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    role_id: Mapped[int] = mapped_column(
        ForeignKey("roles.id", ondelete="CASCADE"), primary_key=True
    )


class ApiKey(TimestampMixin, Base):
    """A revocable API key. Only the hash is stored; the plaintext is shown once."""

    __tablename__ = "api_keys"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(128), nullable=False, default="")
    prefix: Mapped[str] = mapped_column(String(16), nullable=False)
    key_hash: Mapped[str] = mapped_column(String(128), unique=True, nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    user: Mapped[User] = relationship(back_populates="api_keys", lazy="joined")


class ServerRegistration(TimestampMixin, Base):
    """Runtime view of an upstream MCP server from ``config/servers.yaml``."""

    __tablename__ = "server_registrations"
    __table_args__ = (
        Index("ix_server_registrations_enabled", "enabled"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    server_id: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    transport: Mapped[str] = mapped_column(String(32), nullable=False, default="streamable-http")
    endpoint: Mapped[str | None] = mapped_column(String(512))
    health_url: Mapped[str | None] = mapped_column(String(512))
    command: Mapped[str | None] = mapped_column(String(512))
    args_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="unknown")
    last_checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error: Mapped[str | None] = mapped_column(Text)
    tool_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # Upstream authentication. Only ciphertext is stored; list APIs never decrypt.
    credential_type: Mapped[str] = mapped_column(String(32), nullable=False, default="none")
    credential_ciphertext: Mapped[str | None] = mapped_column(Text)
    credential_header: Mapped[str | None] = mapped_column(String(64))

    @property
    def args(self) -> list[str]:
        return json.loads(self.args_json or "[]")

    @args.setter
    def args(self, value: list[str]) -> None:
        self.args_json = json.dumps(list(value))


class AuditLog(Base):
    """Append-only record of a gateway tool call. Never contains credentials."""

    __tablename__ = "audit_logs"
    __table_args__ = (
        Index("ix_audit_logs_created_status", "created_at", "status"),
        Index("ix_audit_logs_server_tool", "server_id", "tool_name"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False, index=True
    )
    user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), index=True
    )
    api_key_id: Mapped[int | None] = mapped_column(
        ForeignKey("api_keys.id", ondelete="SET NULL")
    )
    server_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    tool_name: Mapped[str] = mapped_column(String(128), nullable=False)
    public_tool_name: Mapped[str | None] = mapped_column(String(128), index=True)
    upstream_tool_name: Mapped[str | None] = mapped_column(String(128))
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    error_code: Mapped[str | None] = mapped_column(String(64))
    latency_ms: Mapped[float | None] = mapped_column(Float)
    detail_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")

    @property
    def detail(self) -> dict[str, Any]:
        return json.loads(self.detail_json or "{}")

    @detail.setter
    def detail(self, value: dict[str, Any]) -> None:
        self.detail_json = json.dumps(value)


class LoginSession(Base):
    """Server-side browser session. Only a hash of the cookie token is stored."""

    __tablename__ = "sessions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    token_hash: Mapped[str] = mapped_column(String(128), unique=True, nullable=False, index=True)
    csrf_token: Mapped[str] = mapped_column(String(128), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )

    user: Mapped[User] = relationship(lazy="selectin")


# Additive, non-destructive schema upgrades for databases created by Pass 1.
# `create_all` does not add columns to existing tables, so these ALTER statements
# bring older local databases forward. No tables or data are dropped.
_ADDITIVE_COLUMNS: dict[str, list[tuple[str, str]]] = {
    "server_registrations": [
        ("description", "TEXT"),
        ("health_url", "VARCHAR(512)"),
        ("last_error", "TEXT"),
        ("tool_count", "INTEGER NOT NULL DEFAULT 0"),
        ("credential_type", "VARCHAR(32) NOT NULL DEFAULT 'none'"),
        ("credential_ciphertext", "TEXT"),
        ("credential_header", "VARCHAR(64)"),
    ],
    "api_keys": [
        ("expires_at", "DATETIME"),
    ],
    "audit_logs": [
        ("public_tool_name", "VARCHAR(128)"),
        ("upstream_tool_name", "VARCHAR(128)"),
        ("error_code", "VARCHAR(64)"),
    ],
}


async def ensure_schema(database: "Database") -> None:
    """Create tables and add columns missing from an older local database."""
    await database.create_all()
    async with database.engine.begin() as connection:
        existing_tables = await connection.run_sync(
            lambda sync: set(sync.dialect.get_table_names(sync))
        )
        for table, columns in _ADDITIVE_COLUMNS.items():
            if table not in existing_tables:
                continue
            current = await connection.run_sync(
                lambda sync, t=table: {
                    column["name"] for column in sa_inspect(sync).get_columns(t)
                }
            )
            for name, ddl in columns:
                if name not in current:
                    await connection.exec_driver_sql(
                        f"ALTER TABLE {table} ADD COLUMN {name} {ddl}"
                    )


class Database:
    """Owns an async engine and session factory for one ``DATABASE_URL``."""

    def __init__(self, url: str | None = None, *, echo: bool = False) -> None:
        self.url = url or os.environ.get("DATABASE_URL") or DEFAULT_DATABASE_URL
        self.engine: AsyncEngine = create_async_engine(self.url, echo=echo, future=True)
        self.session_factory: async_sessionmaker[AsyncSession] = async_sessionmaker(
            self.engine, expire_on_commit=False
        )

    async def create_all(self) -> None:
        async with self.engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)

    async def drop_all(self) -> None:
        async with self.engine.begin() as connection:
            await connection.run_sync(Base.metadata.drop_all)

    async def session(self) -> AsyncIterator[AsyncSession]:
        async with self.session_factory() as session:
            yield session

    async def dispose(self) -> None:
        await self.engine.dispose()


async def create_default_roles(session: AsyncSession) -> None:
    """Seed the roles referenced by ``config/permissions.yaml`` (idempotent).

    The three shipped roles (admin, member, viewer) are always seeded, even if
    the policy file cannot be read, so authentication never depends on a
    configuration file being present. Any additional role declared in the
    policy file is seeded as well.
    """
    existing = set((await session.execute(select(Role.name))).scalars())
    wanted: dict[str, str] = dict(FALLBACK_ROLES)
    try:
        from services.gateway.policy import PermissionPolicy

        policy = PermissionPolicy.load()
    except Exception:  # pragma: no cover - the fallback roles still apply
        policy = None
    if policy is not None:
        for name in policy.role_names():
            wanted.setdefault(name, policy.descriptions.get(name) or f"Role {name}")
    for name, description in wanted.items():
        if name not in existing:
            session.add(Role(name=name, description=description))
    await session.commit()


def model_columns(model: type[Base]) -> list[str]:
    """Small helper used by tests and future migrations."""
    return [column.key for column in sa_inspect(model).columns]
