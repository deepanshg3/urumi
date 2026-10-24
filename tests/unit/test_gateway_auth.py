"""Unit tests for gateway authentication and session/API-key lifecycle."""

from __future__ import annotations

from datetime import timedelta

from sqlalchemy import select

import pytest

from services.common.errors import ConfigurationError, NotFoundError, ValidationError
from services.gateway import auth
from services.gateway.db import ApiKey, Database, LoginSession, User, ensure_schema
from services.gateway.policy import PermissionPolicy

from tests.conftest import gateway_settings

YAML = """
roles:
  admin: {permissions: ["tools:*"]}
  member: {permissions: []}
grants:
  member: ["tools:woocommerce:list_products"]
deny: {}
"""


@pytest.fixture
def policy(tmp_path) -> PermissionPolicy:
    path = tmp_path / "permissions.yaml"
    path.write_text(YAML)
    return PermissionPolicy.load(path)


@pytest.fixture
async def database(tmp_path):
    db = Database(f"sqlite+aiosqlite:///{tmp_path / 'auth.db'}")
    await ensure_schema(db)
    try:
        yield db
    finally:
        await db.dispose()


async def _admin(database: Database) -> User:
    user = await auth.bootstrap_admin(database, "Admin@Example.com", "admin-password-1")
    assert user is not None
    return user


async def test_bootstrap_admin_is_idempotent_and_normalizes_email(database, policy) -> None:
    first = await _admin(database)
    assert first.email == "admin@example.com"
    assert [role.name for role in first.roles] == ["admin"]
    second = await auth.bootstrap_admin(database, "admin@example.com", "different-password")
    assert second is not None and second.id == first.id


async def test_bootstrap_admin_rejects_short_password(database) -> None:
    with pytest.raises(ConfigurationError):
        await auth.bootstrap_admin(database, "a@b.test", "short")


async def test_bootstrap_admin_noop_without_values(database) -> None:
    assert await auth.bootstrap_admin(database, "", "") is None


async def test_login_success_and_failure(database, policy) -> None:
    await _admin(database)
    user = await auth.login(database, "admin@example.com", "admin-password-1", policy)
    assert user is not None
    assert await auth.login(database, "admin@example.com", "wrong", policy) is None
    assert await auth.login(database, "ghost@example.com", "admin-password-1", policy) is None


async def test_session_lifecycle(database, policy) -> None:
    user = await _admin(database)
    token, csrf, expires = await auth.create_login_session(database, gateway_settings(), user.id)
    assert token and csrf and expires > auth.utcnow()

    result = await auth.authenticate_session(database, token, policy)
    assert result is not None
    context, record = result
    assert context.user_id == user.id
    assert "tools:*" in context.permissions
    assert context.auth_method == "session"

    await auth.revoke_session(database, record.id)
    assert await auth.authenticate_session(database, token, policy) is None
    assert await auth.authenticate_session(database, "", policy) is None


async def test_expired_session_rejected(database, policy) -> None:
    user = await _admin(database)
    token, _, _ = await auth.create_login_session(database, gateway_settings(), user.id)
    async with database.session_factory() as session:
        record = (
            await session.execute(
                select(LoginSession)
            )
        ).scalar_one()
        record.expires_at = auth.utcnow() - timedelta(minutes=1)
        await session.commit()
    assert await auth.authenticate_session(database, token, policy) is None


async def test_api_key_lifecycle(database, policy) -> None:
    user = await _admin(database)
    record, plaintext = await auth.create_api_key(database, user.id, "laptop")
    assert plaintext.startswith("urumi_")

    context = await auth.authenticate_api_key(database, plaintext, policy)
    assert context is not None
    assert context.auth_method == "api_key"
    assert context.api_key_id == record.id

    assert await auth.authenticate_api_key(database, "not-a-key", policy) is None
    assert await auth.authenticate_api_key(database, plaintext + "x", policy) is None

    assert await auth.revoke_api_key(database, record.id) is True
    assert await auth.authenticate_api_key(database, plaintext, policy) is None
    assert await auth.revoke_api_key(database, 99999) is False


async def test_expired_api_key_rejected(database, policy) -> None:
    user = await _admin(database)
    record, plaintext = await auth.create_api_key(database, user.id, "old", expires_in_days=1)
    async with database.session_factory() as session:
        stored = await session.get(ApiKey, record.id)
        stored.expires_at = auth.utcnow() - timedelta(minutes=1)
        await session.commit()
    assert await auth.authenticate_api_key(database, plaintext, policy) is None


async def test_api_key_of_inactive_user_rejected(database, policy) -> None:
    user = await _admin(database)
    _, plaintext = await auth.create_api_key(database, user.id, "key")
    async with database.session_factory() as session:
        stored = await session.get(User, user.id)
        stored.is_active = False
        await session.commit()
    assert await auth.authenticate_api_key(database, plaintext, policy) is None


async def test_revoke_api_key_scoped_to_user(database, policy) -> None:
    user = await _admin(database)
    record, _ = await auth.create_api_key(database, user.id, "key")
    assert await auth.revoke_api_key(database, record.id, user_id=user.id + 1) is False
    assert await auth.revoke_api_key(database, record.id, user_id=user.id) is True


async def test_set_user_roles(database) -> None:
    user = await _admin(database)
    updated = await auth.set_user_roles(database, user.id, ["member"])
    assert [role.name for role in updated.roles] == ["member"]
    with pytest.raises(ValidationError):
        await auth.set_user_roles(database, user.id, ["ghost"])
    with pytest.raises(NotFoundError):
        await auth.set_user_roles(database, 424242, ["member"])
