"""Unit tests for upstream server registration, credentials and seeding."""

from __future__ import annotations

import pytest

from services.common.errors import ConfigurationError, NotFoundError, ValidationError
from services.gateway.db import Database, ensure_schema
from services.gateway.registry import ServerRegistry
from services.gateway.schemas import ServerCreate, ServerUpdate

from tests.conftest import gateway_settings


@pytest.fixture
async def registry(tmp_path) -> ServerRegistry:
    database = Database(f"sqlite+aiosqlite:///{tmp_path / 'registry.db'}")
    await ensure_schema(database)
    try:
        yield ServerRegistry(database, gateway_settings())
    finally:
        await database.dispose()


async def test_create_and_list(registry: ServerRegistry) -> None:
    created = await registry.create(
        ServerCreate(server_id="alpha", name="Alpha", url="http://127.0.0.1:9001/mcp")
    )
    assert created.server_id == "alpha"
    assert created.endpoint == "http://127.0.0.1:9001/mcp"
    assert [server.server_id for server in await registry.list()] == ["alpha"]


async def test_duplicate_id_rejected(registry: ServerRegistry) -> None:
    payload = ServerCreate(server_id="alpha", name="Alpha", url="http://127.0.0.1:9001/mcp")
    await registry.create(payload)
    with pytest.raises(ValidationError):
        await registry.create(payload)


async def test_update_enable_disable_and_delete(registry: ServerRegistry) -> None:
    await registry.create(
        ServerCreate(server_id="alpha", name="Alpha", url="http://127.0.0.1:9001/mcp")
    )
    disabled = await registry.set_enabled("alpha", False)
    assert disabled.enabled is False
    assert await registry.enabled() == []
    updated = await registry.update("alpha", ServerUpdate(name="Renamed", enabled=True))
    assert updated.name == "Renamed"
    assert updated.enabled is True
    await registry.delete("alpha")
    with pytest.raises(NotFoundError):
        await registry.get("alpha")


async def test_credential_is_encrypted_and_usable(registry: ServerRegistry) -> None:
    server = await registry.create(
        ServerCreate(
            server_id="secured",
            name="Secured",
            url="http://127.0.0.1:9002/mcp",
            credential_type="bearer",
            credential="upstream-secret-token",
        )
    )
    assert server.credential_ciphertext
    assert "upstream-secret-token" not in server.credential_ciphertext
    view = ServerRegistry.view(server)
    assert view.has_credential is True
    dumped = view.model_dump_json()
    assert "upstream-secret-token" not in dumped
    assert "credential_ciphertext" not in dumped
    assert registry.auth_headers(server) == {
        "Authorization": "Bearer upstream-secret-token"
    }


async def test_header_credential_requires_header_name(registry: ServerRegistry) -> None:
    with pytest.raises(ValueError):
        await registry.create(
            ServerCreate(
                server_id="secured",
                name="Secured",
                url="http://127.0.0.1:9002/mcp",
                credential_type="header",
                credential="value",
            )
        )
    with pytest.raises(ValidationError):
        registry._encrypt_credential("header", "value", None)


async def test_auth_headers_without_credential(registry: ServerRegistry) -> None:
    server = await registry.create(
        ServerCreate(server_id="open", name="Open", url="http://127.0.0.1:9003/mcp")
    )
    assert registry.auth_headers(server) == {}


async def test_cipher_missing_raises_configuration_error(tmp_path) -> None:
    database = Database(f"sqlite+aiosqlite:///{tmp_path / 'nocipher.db'}")
    await ensure_schema(database)
    try:
        registry = ServerRegistry(database, gateway_settings(secret_key=""))
        with pytest.raises(ConfigurationError):
            await registry.create(
                ServerCreate(
                    server_id="secured",
                    name="Secured",
                    url="http://127.0.0.1:9002/mcp",
                    credential_type="bearer",
                    credential="value",
                )
            )
    finally:
        await database.dispose()


async def test_seed_from_config_is_idempotent(registry: ServerRegistry) -> None:
    servers = [
        {"id": "alpha", "name": "Alpha", "url": "http://127.0.0.1:9001/mcp", "enabled": True},
        {"id": "beta", "name": "Beta", "url": "http://127.0.0.1:9002/mcp", "enabled": False},
        {"id": "bad", "name": "Bad", "url": "ftp://nope/mcp"},
        {"id": "", "name": "Empty", "url": "http://127.0.0.1:9004/mcp"},
    ]
    await registry.seed_from_config(servers)
    await registry.seed_from_config(servers)
    registered = {server.server_id for server in await registry.list()}
    assert registered == {"alpha", "beta"}
    assert [server.server_id for server in await registry.enabled()] == ["alpha"]
