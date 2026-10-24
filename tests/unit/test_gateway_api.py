"""Integration-style tests for the gateway management API (in-process ASGI)."""

from __future__ import annotations

import contextlib
from collections.abc import AsyncIterator

import httpx
import pytest

from services.gateway.app import create_app
from services.gateway.db import Database

from tests.conftest import app_settings, gateway_settings

ADMIN_EMAIL = "admin@urumi.test"
ADMIN_PASSWORD = "admin-password-1"
MEMBER_EMAIL = "member@urumi.test"
MEMBER_PASSWORD = "member-password-1"


@contextlib.asynccontextmanager
async def gateway_client(tmp_path) -> AsyncIterator[httpx.AsyncClient]:
    """Start the real app lifespan inside the calling task so the MCP session
    manager's task group is entered and exited by the same task."""
    database = Database(f"sqlite+aiosqlite:///{tmp_path / 'api.db'}")
    settings = app_settings(
        service_name="gateway",
        gateway=gateway_settings(
            bootstrap_admin_email=ADMIN_EMAIL,
            bootstrap_admin_password=ADMIN_PASSWORD,
        ),
    )
    app = create_app(settings, database=database, seed_servers=False, discover=False)
    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as http:
            yield http


async def _login(client: httpx.AsyncClient, email: str, password: str):
    response = await client.post("/api/auth/login", json={"email": email, "password": password})
    return response


async def _login_admin(client: httpx.AsyncClient) -> str:
    response = await _login(client, ADMIN_EMAIL, ADMIN_PASSWORD)
    assert response.status_code == 200, response.text
    return response.json()["csrf_token"]


async def test_login_required(tmp_path) -> None:
    async with gateway_client(tmp_path) as client:
        assert (await client.get("/api/auth/me")).status_code == 401
        assert (await _login(client, ADMIN_EMAIL, "wrong")).status_code == 401



async def test_login_me_and_logout(tmp_path) -> None:
    async with gateway_client(tmp_path) as client:
        csrf = await _login_admin(client)
        me = await client.get("/api/auth/me")
        assert me.status_code == 200
        assert me.json()["email"] == ADMIN_EMAIL
        assert me.json()["roles"] == ["admin"]
        assert csrf  # non-empty

        logout = await client.post("/api/auth/logout", headers={"X-CSRF-Token": csrf})
        assert logout.status_code == 200
        assert (await client.get("/api/auth/me")).status_code == 401



async def test_csrf_required_for_unsafe_methods(tmp_path) -> None:
    async with gateway_client(tmp_path) as client:
        await _login_admin(client)
        response = await client.post(
            "/api/servers",
            json={"server_id": "alpha", "name": "Alpha", "url": "http://127.0.0.1:9001/mcp"},
        )
        assert response.status_code == 403



async def test_server_crud_roundtrip(tmp_path) -> None:
    async with gateway_client(tmp_path) as client:
        csrf = await _login_admin(client)
        headers = {"X-CSRF-Token": csrf}
        created = await client.post(
            "/api/servers",
            headers=headers,
            json={
                "server_id": "alpha",
                "name": "Alpha",
                "url": "http://127.0.0.1:9001/mcp",
                "health_url": "http://127.0.0.1:9001/health",
            },
        )
        assert created.status_code == 201, created.text
        assert created.json()["server_id"] == "alpha"

        listed = await client.get("/api/servers")
        assert [item["server_id"] for item in listed.json()] == ["alpha"]

        updated = await client.patch(
            "/api/servers/alpha", headers=headers, json={"name": "Renamed"}
        )
        assert updated.json()["name"] == "Renamed"

        disabled = await client.post("/api/servers/alpha/enable?enabled=false", headers=headers)
        assert disabled.json()["enabled"] is False

        removed = await client.delete("/api/servers/alpha", headers=headers)
        assert removed.status_code == 200
        assert (await client.get("/api/servers/alpha")).status_code == 404



async def test_server_url_validation_rejected(tmp_path) -> None:
    async with gateway_client(tmp_path) as client:
        csrf = await _login_admin(client)
        response = await client.post(
            "/api/servers",
            headers={"X-CSRF-Token": csrf},
            json={"server_id": "evil", "name": "Evil", "url": "http://169.254.169.254/mcp"},
        )
        assert response.status_code == 400
        assert response.json()["error"] == "invalid_upstream_url"



async def test_api_key_lifecycle(tmp_path) -> None:
    async with gateway_client(tmp_path) as client:
        csrf = await _login_admin(client)
        headers = {"X-CSRF-Token": csrf}
        created = await client.post("/api/keys", headers=headers, json={"name": "laptop"})
        assert created.status_code == 201, created.text
        body = created.json()
        assert body["api_key"].startswith("urumi_")
        key_id = body["id"]

        listed = await client.get("/api/keys")
        assert [item["id"] for item in listed.json()] == [key_id]
        assert "api_key" not in listed.json()[0]

        revoked = await client.delete(f"/api/keys/{key_id}", headers=headers)
        assert revoked.status_code == 200
        assert (await client.delete(f"/api/keys/{key_id}", headers=headers)).status_code == 404



async def test_member_permissions(tmp_path) -> None:
    async with gateway_client(tmp_path) as client:
        admin_csrf = await _login_admin(client)
        admin_headers = {"X-CSRF-Token": admin_csrf}
        created = await client.post(
            "/api/users",
            headers=admin_headers,
            json={
                "email": MEMBER_EMAIL,
                "display_name": "Member",
                "password": MEMBER_PASSWORD,
                "roles": ["member"],
            },
        )
        assert created.status_code == 201, created.text
        member_id = created.json()["id"]
        duplicate = await client.post(
            "/api/users",
            headers=admin_headers,
            json={"email": MEMBER_EMAIL, "password": MEMBER_PASSWORD, "roles": ["member"]},
        )
        assert duplicate.status_code == 409
        await client.post("/api/auth/logout", headers={"X-CSRF-Token": admin_csrf})

        login = await _login(client, MEMBER_EMAIL, MEMBER_PASSWORD)
        assert login.status_code == 200
        member_csrf = login.json()["csrf_token"]
        member_headers = {"X-CSRF-Token": member_csrf}

        assert (await client.get("/api/users")).status_code == 403
        forbidden = await client.post(
            "/api/servers",
            headers=member_headers,
            json={"server_id": "alpha", "name": "Alpha", "url": "http://127.0.0.1:9001/mcp"},
        )
        assert forbidden.status_code == 403

        assert (await client.get("/api/servers")).status_code == 200
        own_key = await client.post("/api/keys", headers=member_headers, json={"name": "mine"})
        assert own_key.status_code == 201
        other = await client.post(
            "/api/keys",
            headers=member_headers,
            json={"name": "theirs", "user_id": member_id + 1},
        )
        assert other.status_code == 403



async def test_users_listing_and_self_protection(tmp_path) -> None:
    async with gateway_client(tmp_path) as client:
        csrf = await _login_admin(client)
        headers = {"X-CSRF-Token": csrf}
        users = await client.get("/api/users")
        assert users.status_code == 200
        admin = users.json()[0]

        deactivate = await client.patch(
            f"/api/users/{admin['id']}", headers=headers, json={"is_active": False}
        )
        assert deactivate.status_code == 400

        demote = await client.patch(
            f"/api/users/{admin['id']}", headers=headers, json={"roles": []}
        )
        assert demote.status_code == 400

        renamed = await client.patch(
            f"/api/users/{admin['id']}", headers=headers, json={"display_name": "Root"}
        )
        assert renamed.status_code == 200
        assert renamed.json()["display_name"] == "Root"



async def test_audit_and_overview_shapes(tmp_path) -> None:
    async with gateway_client(tmp_path) as client:
        await _login_admin(client)
        audit = await client.get("/api/audit")
        assert audit.status_code == 200
        assert {"items", "page", "per_page", "total", "has_more"} <= set(audit.json())

        overview = await client.get("/api/overview")
        assert overview.status_code == 200
        body = overview.json()
        assert body["upstreams_total"] == 0
        assert body["tools_total"] == 0



async def test_unknown_server_returns_404(tmp_path) -> None:
    async with gateway_client(tmp_path) as client:
        await _login_admin(client)
        assert (await client.get("/api/servers/ghost")).status_code == 404
