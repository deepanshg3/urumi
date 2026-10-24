"""Pass 1: prove the gateway schema also works on PostgreSQL.

Skipped unless ``URUMI_POSTGRES_URL`` is set, e.g.:

    docker run -d --rm --name urumi-pg-test -p 55432:5432 \
      -e POSTGRES_PASSWORD=urumi_test_pw -e POSTGRES_DB=urumi postgres:16-alpine
    URUMI_POSTGRES_URL=postgresql+asyncpg://postgres:urumi_test_pw@127.0.0.1:55432/urumi \
      .venv/bin/pytest tests/unit/test_gateway_db_postgres.py -v
"""

from __future__ import annotations

import os

import pytest
from sqlalchemy import select

from services.gateway.db import (
    ApiKey,
    AuditLog,
    Database,
    Role,
    User,
    create_default_roles,
)

pytestmark = pytest.mark.integration

URL = os.environ.get("URUMI_POSTGRES_URL")


@pytest.fixture
async def db() -> Database:
    if not URL:
        pytest.skip("set URUMI_POSTGRES_URL to exercise PostgreSQL")
    database = Database(URL)
    await database.drop_all()
    await database.create_all()
    try:
        yield database
    finally:
        await database.drop_all()
        await database.dispose()


async def test_postgres_schema_and_round_trip(db: Database) -> None:
    async with db.session_factory() as session:
        await create_default_roles(session)
        admin = (await session.execute(select(Role).where(Role.name == "admin"))).scalar_one()
        user = User(email="pg@urumi.test", display_name="PG", roles=[admin])
        user.api_keys.append(
            ApiKey(name="pg-key", prefix="urumi_pg", key_hash="sha256:pgtest")
        )
        entry = AuditLog(
            server_id="woocommerce", tool_name="list_products", status="success"
        )
        entry.detail = {"page": 1}
        session.add_all([user, entry])
        await session.commit()

    async with db.session_factory() as session:
        stored = (
            await session.execute(select(User).where(User.email == "pg@urumi.test"))
        ).scalar_one()
        assert [role.name for role in stored.roles] == ["admin"]
        assert stored.api_keys[0].key_hash == "sha256:pgtest"
        audit = (await session.execute(select(AuditLog))).scalar_one()
        assert audit.detail == {"page": 1}
        assert audit.created_at is not None
