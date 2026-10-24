"""Authentication: password login, browser sessions and personal API keys."""

from __future__ import annotations

import secrets
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import select

from services.common.config import GatewaySettings
from services.common.errors import ConfigurationError, ConflictError, ValidationError
from services.common.logging import get_logger
from services.gateway.db import ApiKey, Database, LoginSession, Role, User, create_default_roles
from services.gateway.policy import PermissionPolicy
from services.gateway.schemas import UserView
from services.gateway.security import (
    generate_api_key,
    generate_opaque_token,
    hash_api_key,
    hash_password,
    hash_token,
    verify_password,
)

logger = get_logger("urumi.gateway.auth")


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _as_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


@dataclass(frozen=True)
class AuthContext:
    user_id: int
    email: str
    display_name: str
    roles: list[str]
    permissions: frozenset[str] = field(default_factory=frozenset)
    api_key_id: int | None = None
    session_id: int | None = None
    auth_method: str = "session"

    def can(self, policy: PermissionPolicy, permission: str) -> bool:
        """Whether this context holds ``permission``."""
        return policy.can(self.permissions, permission)


def user_view(user: User, policy: PermissionPolicy | None = None) -> UserView:
    roles = sorted(role.name for role in user.roles)
    permissions: list[str] = []
    if policy is not None:
        permissions = sorted(policy.for_roles(roles).patterns)
    return UserView(
        id=user.id,
        email=user.email,
        display_name=user.display_name,
        is_active=user.is_active,
        roles=roles,
        permissions=permissions,
        created_at=user.created_at,
    )


def context_for(
    user: User,
    policy: PermissionPolicy,
    *,
    api_key_id: int | None = None,
    session_id: int | None = None,
    auth_method: str = "session",
) -> AuthContext:
    roles = sorted(role.name for role in user.roles)
    return AuthContext(
        user_id=user.id,
        email=user.email,
        display_name=user.display_name,
        roles=roles,
        permissions=policy.for_roles(roles),
        api_key_id=api_key_id,
        session_id=session_id,
        auth_method=auth_method,
    )


async def login(
    database: Database, email: str, password: str, policy: PermissionPolicy
) -> User | None:
    async with database.session_factory() as session:
        user = (
            await session.execute(select(User).where(User.email == email.strip().lower()))
        ).scalar_one_or_none()
        if user is None or not user.is_active or not verify_password(password, user.password_hash):
            return None
        return user


async def create_login_session(
    database: Database, settings: GatewaySettings, user_id: int
) -> tuple[str, str, datetime]:
    token = generate_opaque_token()
    csrf = generate_opaque_token()
    expires_at = utcnow() + timedelta(minutes=settings.session_ttl_minutes)
    async with database.session_factory() as session:
        session.add(
            LoginSession(
                user_id=user_id,
                token_hash=hash_token(token),
                csrf_token=csrf,
                expires_at=expires_at,
            )
        )
        await session.commit()
    return token, csrf, expires_at


async def authenticate_session(
    database: Database, token: str, policy: PermissionPolicy
) -> tuple[AuthContext, LoginSession] | None:
    if not token:
        return None
    async with database.session_factory() as session:
        record = (
            await session.execute(
                select(LoginSession).where(LoginSession.token_hash == hash_token(token))
            )
        ).scalar_one_or_none()
        if record is None or record.revoked_at is not None:
            return None
        expires_at = _as_utc(record.expires_at)
        if expires_at is None or expires_at <= utcnow():
            return None
        user = record.user
        if user is None or not user.is_active:
            return None
        return context_for(user, policy, session_id=record.id, auth_method="session"), record


async def revoke_session(database: Database, session_id: int) -> None:
    async with database.session_factory() as session:
        record = await session.get(LoginSession, session_id)
        if record is not None and record.revoked_at is None:
            record.revoked_at = utcnow()
            await session.commit()


async def revoke_user_sessions(database: Database, user_id: int) -> int:
    """Revoke every browser session of a user. Returns the number revoked.

    Called after a password change so that a stolen or old session cookie can
    no longer be used.
    """
    async with database.session_factory() as session:
        records = (
            await session.execute(
                select(LoginSession).where(
                    LoginSession.user_id == user_id, LoginSession.revoked_at.is_(None)
                )
            )
        ).scalars().all()
        now = utcnow()
        for record in records:
            record.revoked_at = now
        if records:
            await session.commit()
        return len(records)


async def authenticate_api_key(
    database: Database, plaintext: str, policy: PermissionPolicy
) -> AuthContext | None:
    if not plaintext or not plaintext.startswith("urumi_"):
        return None
    digest = hash_api_key(plaintext)
    async with database.session_factory() as session:
        record = (
            await session.execute(select(ApiKey).where(ApiKey.key_hash == digest))
        ).scalar_one_or_none()
        if record is None or record.revoked_at is not None:
            return None
        expires_at = _as_utc(record.expires_at)
        if expires_at is not None and expires_at <= utcnow():
            return None
        user = record.user
        if user is None or not user.is_active:
            return None
        record.last_used_at = utcnow()
        await session.commit()
        return context_for(
            user, policy, api_key_id=record.id, auth_method="api_key"
        )


async def create_api_key(
    database: Database,
    user_id: int,
    name: str,
    expires_in_days: int | None = None,
) -> tuple[ApiKey, str]:
    plaintext = generate_api_key()
    expires_at = utcnow() + timedelta(days=expires_in_days) if expires_in_days else None
    async with database.session_factory() as session:
        record = ApiKey(
            user_id=user_id,
            name=name,
            prefix=plaintext[:12],
            key_hash=hash_api_key(plaintext),
            expires_at=expires_at,
        )
        session.add(record)
        await session.commit()
        await session.refresh(record)
        return record, plaintext


async def create_ephemeral_api_key(
    database: Database, user_id: int, *, ttl_seconds: int, name: str = "chat-agent (ephemeral)"
) -> tuple[ApiKey, str]:
    """Mint a short-lived key for server-side credential delegation.

    Used by the chat agent to act on behalf of the authenticated user; the
    gateway still authenticates and authorizes it as that user on every call.
    """
    plaintext = generate_api_key()
    expires_at = utcnow() + timedelta(seconds=ttl_seconds)
    async with database.session_factory() as session:
        record = ApiKey(
            user_id=user_id,
            name=name,
            prefix=plaintext[:12],
            key_hash=hash_api_key(plaintext),
            expires_at=expires_at,
        )
        session.add(record)
        await session.commit()
        await session.refresh(record)
        return record, plaintext


async def revoke_api_key(database: Database, key_id: int, user_id: int | None = None) -> bool:
    async with database.session_factory() as session:
        record = await session.get(ApiKey, key_id)
        if record is None or (user_id is not None and record.user_id != user_id):
            return False
        if record.revoked_at is not None:
            return False
        record.revoked_at = utcnow()
        await session.commit()
        return True


async def bootstrap_admin(
    database: Database, email: str, password: str
) -> User | None:
    """Create the first admin from environment variables (idempotent).

    Refuses to update an existing account so a stale environment variable cannot
    silently reset a password.
    """
    email = email.strip().lower()
    if not email or not password:
        return None
    if len(password) < 8:
        raise ConfigurationError("BOOTSTRAP_ADMIN_PASSWORD must be at least 8 characters")
    async with database.session_factory() as session:
        await create_default_roles(session)
        existing = (
            await session.execute(select(User).where(User.email == email))
        ).scalar_one_or_none()
        if existing is not None:
            return existing
        admin_role = (
            await session.execute(select(Role).where(Role.name == "admin"))
        ).scalar_one()
        user = User(
            email=email,
            display_name="Administrator",
            password_hash=hash_password(password),
            roles=[admin_role],
        )
        session.add(user)
        await session.commit()
        await session.refresh(user)
        logger.info("bootstrap administrator created email=%s", email)
        return user


async def create_user(
    database: Database,
    email: str,
    display_name: str,
    password: str,
    roles: list[str],
) -> User:
    """Create a user account (admin action). Raises on duplicates/unknown roles."""
    email = email.strip().lower()
    async with database.session_factory() as session:
        await create_default_roles(session)
        existing = (
            await session.execute(select(User).where(User.email == email))
        ).scalar_one_or_none()
        if existing is not None:
            raise ConflictError(f"user {email!r} already exists")
        found = list(
            (await session.execute(select(Role).where(Role.name.in_(roles)))).scalars()
        )
        if len(found) != len(set(roles)):
            raise ValidationError("unknown role")
        user = User(
            email=email,
            display_name=display_name,
            password_hash=hash_password(password),
            roles=found,
        )
        session.add(user)
        await session.commit()
        await session.refresh(user)
        return user


async def set_user_roles(database: Database, user_id: int, roles: list[str]) -> User:
    async with database.session_factory() as session:
        user = await session.get(User, user_id)
        if user is None:
            from services.common.errors import NotFoundError

            raise NotFoundError("user", user_id)
        found = list(
            (
                await session.execute(select(Role).where(Role.name.in_(roles)))
            ).scalars()
        )
        if len(found) != len(set(roles)):
            raise ValidationError("unknown role")
        user.roles = found
        await session.commit()
        await session.refresh(user)
        return user


async def set_user_password(
    database: Database, user_id: int, password: str, *, revoke_sessions: bool = True
) -> User:
    """Set a user's password (administrator action) and invalidate their sessions.

    The plaintext password is never stored and never logged; only the PBKDF2
    hash is persisted. Existing browser sessions are revoked so that a password
    change takes effect immediately.
    """
    if len(password) < 8:
        raise ValidationError("password must be at least 8 characters")
    try:
        password_hash = hash_password(password)
    except ValueError as exc:  # pragma: no cover - guarded by the length check
        raise ValidationError(str(exc)) from exc
    async with database.session_factory() as session:
        user = await session.get(User, user_id)
        if user is None:
            from services.common.errors import NotFoundError

            raise NotFoundError("user", user_id)
        user.password_hash = password_hash
        await session.commit()
        await session.refresh(user)
    if revoke_sessions:
        await revoke_user_sessions(database, user_id)
    logger.info("password set for user id=%s sessions_revoked=%s", user_id, revoke_sessions)
    return user
