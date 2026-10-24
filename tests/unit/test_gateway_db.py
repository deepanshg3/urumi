"""Pass 1: gateway persistence layer tests (SQLite via aiosqlite)."""

from __future__ import annotations

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from services.gateway.db import (
    ApiKey,
    AuditLog,
    Database,
    Role,
    ServerRegistration,
    User,
    create_default_roles,
    model_columns,
)


@pytest.fixture
async def db() -> Database:
    database = Database("sqlite+aiosqlite:///:memory:")
    await database.create_all()
    try:
        yield database
    finally:
        await database.dispose()


async def test_schema_creates_expected_tables(db: Database) -> None:
    async with db.engine.connect() as connection:
        tables = await connection.run_sync(
            lambda sync: set(sync.dialect.get_table_names(sync))
        )
    assert {
        "users",
        "roles",
        "user_roles",
        "api_keys",
        "server_registrations",
        "audit_logs",
    } <= tables


async def test_default_roles_are_idempotent(db: Database) -> None:
    async with db.session_factory() as session:
        await create_default_roles(session)
        await create_default_roles(session)
        names = set((await session.execute(select(Role.name))).scalars())
    assert names == {"admin", "member", "viewer"}


async def test_user_roles_and_api_keys_round_trip(db: Database) -> None:
    async with db.session_factory() as session:
        await create_default_roles(session)
        admin = (await session.execute(select(Role).where(Role.name == "admin"))).scalar_one()
        user = User(email="admin@urumi.test", display_name="Admin", roles=[admin])
        user.api_keys.append(
            ApiKey(name="dashboard", prefix="urumi_ab12", key_hash="sha256:deadbeef")
        )
        session.add(user)
        await session.commit()

    async with db.session_factory() as session:
        stored = (
            await session.execute(select(User).where(User.email == "admin@urumi.test"))
        ).scalar_one()
        assert stored.is_active is True
        assert [role.name for role in stored.roles] == ["admin"]
        assert stored.api_keys[0].name == "dashboard"
        assert stored.created_at is not None


async def test_duplicate_api_key_hash_is_rejected(db: Database) -> None:
    async with db.session_factory() as session:
        user = User(email="a@urumi.test")
        session.add(user)
        await session.flush()
        session.add(ApiKey(user_id=user.id, prefix="urumi_1", key_hash="same"))
        session.add(ApiKey(user_id=user.id, prefix="urumi_2", key_hash="same"))
        with pytest.raises(IntegrityError):
            await session.flush()
        await session.rollback()


async def test_server_registration_args_are_json(db: Database) -> None:
    async with db.session_factory() as session:
        server = ServerRegistration(
            server_id="woocommerce",
            name="WooCommerce MCP",
            transport="streamable-http",
            endpoint="http://127.0.0.1:8101/mcp",
            enabled=True,
            status="ready",
        )
        server.args = ["-m", "services.woocommerce_mcp"]
        session.add(server)
        await session.commit()

    async with db.session_factory() as session:
        stored = (
            await session.execute(
                select(ServerRegistration).where(
                    ServerRegistration.server_id == "woocommerce"
                )
            )
        ).scalar_one()
        assert stored.args == ["-m", "services.woocommerce_mcp"]
        assert stored.enabled is True
        assert stored.status == "ready"


async def test_audit_log_detail_is_json_and_append_only(db: Database) -> None:
    async with db.session_factory() as session:
        entry = AuditLog(
            server_id="woocommerce",
            tool_name="list_products",
            status="success",
            latency_ms=12.5,
        )
        entry.detail = {"per_page": 5}
        session.add(entry)
        await session.commit()

    async with db.session_factory() as session:
        stored = (await session.execute(select(AuditLog))).scalar_one()
        assert stored.detail == {"per_page": 5}
        assert stored.user_id is None
        assert stored.created_at is not None


async def test_model_columns_cover_core_fields() -> None:
    assert {"email", "display_name", "is_active"} <= set(model_columns(User))
    assert {"server_id", "enabled", "status"} <= set(model_columns(ServerRegistration))
    assert {"user_id", "tool_name", "status"} <= set(model_columns(AuditLog))


def test_default_database_url_is_local_sqlite(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("DATABASE_URL", raising=False)
    database = Database()
    try:
        assert database.url.startswith("sqlite+aiosqlite:///")
    finally:
        import asyncio

        asyncio.run(database.dispose())
