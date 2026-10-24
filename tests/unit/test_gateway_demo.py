"""Assessment demo mode: fixed personas, real sessions, real authorization.

Guarantees under test:

* demo mode is off by default and needs an explicit acknowledgement;
* a production deployment cannot enable it;
* the three personas map to dedicated persisted users/roles;
* unknown personas (or role names) are rejected server-side;
* REST and MCP authorization use the normal policy for the selected persona;
* switching revokes the previous session and its CSRF token;
* demo cookie auth on ``/mcp`` only exists while demo mode is on.
"""

from __future__ import annotations

import contextlib
from collections.abc import AsyncIterator

import httpx
import pytest
from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client
from pydantic import ValidationError
from sqlalchemy import select

from services.gateway import demo
from services.gateway.app import create_app
from services.gateway.db import ApiKey, AuditLog, Database, LoginSession, User
from services.gateway.schemas import ServerCreate
from services.gateway.upstream import UpstreamResult, UpstreamTool

from tests.conftest import app_settings, gateway_settings

ADMIN_EMAIL = "admin@urumi.test"
ADMIN_PASSWORD = "admin-password-1"
DEMO_EMAILS = {persona.email for persona in demo.DEMO_PERSONAS.values()}


# -- fixtures --------------------------------------------------------------


@contextlib.asynccontextmanager
async def demo_client(
    tmp_path,
    *,
    enabled: bool = True,
    allow_remote: bool = False,
    origins: str = "",
    client: tuple[str, int] = ("127.0.0.1", 123),
) -> AsyncIterator[httpx.AsyncClient]:
    database = Database(f"sqlite+aiosqlite:///{tmp_path / 'demo.db'}")
    settings = app_settings(
        service_name="gateway",
        gateway=gateway_settings(
            bootstrap_admin_email=ADMIN_EMAIL,
            bootstrap_admin_password=ADMIN_PASSWORD,
            demo_mode=enabled,
            demo_ack=enabled,
            demo_allow_remote=allow_remote,
            demo_origins=origins,
            cors_origins="http://testserver",
        ),
    )
    app = create_app(settings, database=database, seed_servers=False, discover=False)
    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app, client=client)
        async with httpx.AsyncClient(
            transport=transport, base_url="http://testserver"
        ) as http:
            http.app = app  # type: ignore[attr-defined]
            http.database = database  # type: ignore[attr-defined]
            http.transport = transport  # type: ignore[attr-defined]
            yield http


async def _persona_session(
    client: httpx.AsyncClient, persona: str, *, headers: dict | None = None
) -> tuple[dict, str]:
    # A switch that replaces an existing session must carry that session's
    # CSRF token, exactly like every other state-changing request.
    csrf_cookie = client.cookies.get("urumi_csrf")
    if headers is None and csrf_cookie:
        headers = {"X-CSRF-Token": csrf_cookie}
    response = await client.post(
        "/api/auth/demo/session", json={"persona": persona}, headers=headers
    )
    assert response.status_code == 200, response.text
    payload = response.json()
    return payload, payload["csrf_token"]


class FakeStore:
    def __init__(self, tools: list[str]) -> None:
        self.tools = tools
        self.calls: list[tuple[str, dict]] = []

    async def list_tools(self):
        return [
            UpstreamTool(name=name, description=name, input_schema={"type": "object"})
            for name in self.tools
        ]

    async def call_tool(self, name, arguments):
        self.calls.append((name, arguments))
        return UpstreamResult(content=[{"type": "text", "text": f"{name}:ok"}])


@contextlib.asynccontextmanager
async def demo_mcp_gateway(tmp_path) -> AsyncIterator[tuple[object, tuple[FakeStore, FakeStore]]]:
    database = Database(f"sqlite+aiosqlite:///{tmp_path / 'demo-mcp.db'}")
    settings = app_settings(
        service_name="gateway",
        gateway=gateway_settings(
            bootstrap_admin_email=ADMIN_EMAIL,
            bootstrap_admin_password=ADMIN_PASSWORD,
            demo_mode=True,
            demo_ack=True,
            model_hidden_tools=["shipping__create_shipment"],
        ),
    )
    app = create_app(settings, database=database, seed_servers=False, discover=False)
    async with app.router.lifespan_context(app):
        ctx = app.state.gateway
        for server_id in ("shipping", "woocommerce"):
            await ctx.registry.create(
                ServerCreate(
                    server_id=server_id,
                    name=server_id.title(),
                    url=f"http://127.0.0.1:9999/{server_id}/mcp",
                )
            )
        shipping = FakeStore(
            [
                "track_shipment",
                "get_shipment",
                "list_shipments",
                "create_shipment",
                "update_shipment_status",
            ]
        )
        commerce = FakeStore(
            [
                "list_products",
                "list_orders",
                "get_order",
                "create_product",
                "update_order_status",
            ]
        )
        stores = {"shipping": shipping, "woocommerce": commerce}
        ctx.aggregator._client_factory = lambda server: stores[server.server_id]
        await ctx.aggregator.refresh()
        yield app, (shipping, commerce)


def _cookie_client_factory(app, token: str):
    def factory(headers=None, timeout=None, auth=None, **kwargs):
        return httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://testserver",
            headers=headers,
            cookies={"urumi_session": token},
            timeout=timeout,
            auth=auth,
        )

    return factory


# -- configuration ---------------------------------------------------------


def test_demo_mode_is_disabled_by_default() -> None:
    settings = gateway_settings()
    assert settings.demo_mode is False
    assert settings.demo_ack is False
    assert settings.demo_allow_remote is False
    assert settings.deployment_env == "development"


def test_demo_mode_requires_explicit_acknowledgement() -> None:
    with pytest.raises(ValidationError, match="GATEWAY_DEMO_ACK"):
        gateway_settings(demo_mode=True)
    enabled = gateway_settings(demo_mode=True, demo_ack=True)
    assert enabled.demo_mode is True


def test_demo_mode_is_rejected_in_production() -> None:
    with pytest.raises(ValidationError, match="production"):
        gateway_settings(
            demo_mode=True, demo_ack=True, deployment_env="production"
        )
    with pytest.raises(ValidationError, match="production"):
        gateway_settings(demo_mode=True, demo_ack=True, deployment_env="prod")


# -- disabled behaviour ----------------------------------------------------


@pytest.mark.anyio
async def test_demo_disabled_reports_off_and_refuses_sessions(tmp_path) -> None:
    async with demo_client(tmp_path, enabled=False) as client:
        config = await client.get("/api/auth/demo")
        assert config.status_code == 200
        assert config.json() == {
            "enabled": False,
            "personas": [],
            "deployment": "development",
        }
        response = await client.post(
            "/api/auth/demo/session", json={"persona": "admin"}
        )
        assert response.status_code == 404


@pytest.mark.anyio
async def test_normal_login_still_works_when_demo_is_disabled(tmp_path) -> None:
    async with demo_client(tmp_path, enabled=False) as client:
        login = await client.post(
            "/api/auth/login",
            json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD},
        )
        assert login.status_code == 200, login.text
        me = await client.get("/api/auth/me")
        assert me.status_code == 200
        assert me.json()["roles"] == ["admin"]
        assert "password" not in login.text.lower()


# -- personas --------------------------------------------------------------


@pytest.mark.anyio
async def test_demo_config_lists_the_three_fixed_personas(tmp_path) -> None:
    async with demo_client(tmp_path) as client:
        body = (await client.get("/api/auth/demo")).json()
        assert body["enabled"] is True
        personas = {item["id"]: item for item in body["personas"]}
        assert set(personas) == {"admin", "operator", "viewer"}
        assert {item["role"] for item in personas.values()} == {
            "admin",
            "member",
            "viewer",
        }
        assert all(item["capabilities"] for item in personas.values())
        assert "password" not in str(body).lower()
        assert "urumi_" not in str(body)


@pytest.mark.anyio
async def test_each_persona_creates_a_real_persisted_session(tmp_path) -> None:
    async with demo_client(tmp_path) as client:
        expectations = {
            "admin": ("admin", "gateway:users:manage"),
            "operator": ("member", "tools:shipping:update_shipment_status"),
            "viewer": ("viewer", "gateway:tools:read"),
        }
        for persona_id, (role, permission) in expectations.items():
            payload, csrf = await _persona_session(client, persona_id)
            user = payload["user"]
            assert user["roles"] == [role]
            assert permission in user["permissions"]
            assert csrf
            me = await client.get("/api/auth/me")
            assert me.status_code == 200
            assert me.json()["email"] == demo.DEMO_PERSONAS[persona_id].email

        database = client.database  # type: ignore[attr-defined]
        async with database.session_factory() as session:
            users = (
                await session.execute(select(User).where(User.email.in_(DEMO_EMAILS)))
            ).scalars().all()
            assert len(users) == 3
            for user in users:
                assert user.is_active is True
                assert len(user.roles) == 1
                assert user.password_hash


@pytest.mark.anyio
async def test_unknown_persona_and_role_names_are_rejected(tmp_path) -> None:
    async with demo_client(tmp_path) as client:
        for body in (
            {"persona": "superuser"},
            {"persona": "root"},
            {"persona": "ADMIN"},
            {"persona": "admin "},
            {"persona": ""},
            {"role": "admin"},
        ):
            response = await client.post("/api/auth/demo/session", json=body)
            assert response.status_code in {400, 422}, (body, response.text)
        # Nothing was created or signed in by the rejected requests.
        assert (await client.get("/api/auth/me")).status_code == 401


# -- authorization ---------------------------------------------------------


@pytest.mark.anyio
async def test_admin_persona_can_administrate(tmp_path) -> None:
    async with demo_client(tmp_path) as client:
        payload, csrf = await _persona_session(client, "admin")
        headers = {"X-CSRF-Token": csrf}
        assert (await client.get("/api/users")).status_code == 200
        created = await client.post(
            "/api/users",
            headers=headers,
            json={
                "email": "invited@urumi.test",
                "password": "invited-password-1",
                "roles": ["viewer"],
            },
        )
        assert created.status_code == 201, created.text
        servers = await client.post(
            "/api/servers",
            headers=headers,
            json={"server_id": "probe", "name": "Probe", "url": "http://127.0.0.1:9001/mcp"},
        )
        assert servers.status_code == 201, servers.text
        await client.delete("/api/servers/probe", headers=headers)
        assert (await client.get("/api/audit")).status_code == 200


@pytest.mark.anyio
async def test_operator_persona_is_read_plus_shipment_updates(tmp_path) -> None:
    async with demo_client(tmp_path) as client:
        payload, csrf = await _persona_session(client, "operator")
        headers = {"X-CSRF-Token": csrf}
        assert (await client.get("/api/users")).status_code == 403
        assert (await client.get("/api/tools")).status_code == 200
        assert (
            await client.post(
                "/api/servers",
                headers=headers,
                json={"server_id": "x", "name": "X", "url": "http://127.0.0.1:9001/mcp"},
            )
        ).status_code == 403
        # Own keys are allowed; the user directory is not.
        key = await client.post("/api/keys", headers=headers, json={"name": "own"})
        assert key.status_code == 201, key.text
        assert "gateway:users:manage" not in payload["user"]["permissions"]


@pytest.mark.anyio
async def test_viewer_persona_cannot_mutate_or_manage_keys(tmp_path) -> None:
    async with demo_client(tmp_path) as client:
        payload, csrf = await _persona_session(client, "viewer")
        headers = {"X-CSRF-Token": csrf}
        assert (await client.get("/api/tools")).status_code == 200
        assert (await client.get("/api/servers")).status_code == 200
        assert (await client.get("/api/audit")).status_code == 200
        assert (await client.get("/api/keys")).status_code == 403
        assert (
            await client.post("/api/keys", headers=headers, json={"name": "nope"})
        ).status_code == 403
        assert (await client.get("/api/users")).status_code == 403
        assert "gateway:keys:read" not in payload["user"]["permissions"]
        assert "gateway:keys:manage" not in payload["user"]["permissions"]


@pytest.mark.anyio
async def test_demo_users_have_no_api_keys(tmp_path) -> None:
    async with demo_client(tmp_path) as client:
        for persona in ("admin", "operator", "viewer"):
            await _persona_session(client, persona)
        database = client.database  # type: ignore[attr-defined]
        async with database.session_factory() as session:
            demo_ids = [
                user.id
                for user in (
                    await session.execute(
                        select(User).where(User.email.in_(DEMO_EMAILS))
                    )
                ).scalars()
            ]
            keys = (
                await session.execute(
                    select(ApiKey).where(ApiKey.user_id.in_(demo_ids))
                )
            ).scalars().all()
            assert keys == []


# -- switching and CSRF ----------------------------------------------------


@pytest.mark.anyio
async def test_switching_revokes_the_previous_session_and_csrf(tmp_path) -> None:
    async with demo_client(tmp_path) as client:
        _, viewer_csrf = await _persona_session(client, "viewer")
        old_token = client.cookies.get("urumi_session")
        assert old_token

        switched = await client.post(
            "/api/auth/demo/session",
            json={"persona": "admin"},
            headers={"X-CSRF-Token": viewer_csrf},
        )
        assert switched.status_code == 200, switched.text
        assert switched.json()["user"]["roles"] == ["admin"]
        assert client.cookies.get("urumi_session") != old_token

        # The old session cookie is dead.
        transport = client.transport  # type: ignore[attr-defined]
        async with httpx.AsyncClient(
            transport=transport, base_url="http://testserver"
        ) as replay:
            replay.cookies.set("urumi_session", old_token)
            assert (await replay.get("/api/auth/me")).status_code == 401

        # The old CSRF token no longer authorizes writes.
        assert (
            await client.post(
                "/api/users",
                headers={"X-CSRF-Token": viewer_csrf},
                json={
                    "email": "x@urumi.test",
                    "password": "another-password-1",
                    "roles": ["viewer"],
                },
            )
        ).status_code == 403

        database = client.database  # type: ignore[attr-defined]
        async with database.session_factory() as session:
            sessions = (await session.execute(select(LoginSession))).scalars().all()
            revoked = [item for item in sessions if item.revoked_at is not None]
            assert len(revoked) == 1  # the replaced viewer session


@pytest.mark.anyio
async def test_switching_requires_csrf_when_a_session_exists(tmp_path) -> None:
    async with demo_client(tmp_path) as client:
        _, csrf = await _persona_session(client, "viewer")
        missing = await client.post(
            "/api/auth/demo/session", json={"persona": "operator"}
        )
        assert missing.status_code == 403
        wrong = await client.post(
            "/api/auth/demo/session",
            json={"persona": "operator"},
            headers={"X-CSRF-Token": "not-the-token"},
        )
        assert wrong.status_code == 403
        # Still the viewer session, not a half-switched state.
        me = await client.get("/api/auth/me")
        assert me.json()["roles"] == ["viewer"]
        ok = await client.post(
            "/api/auth/demo/session",
            json={"persona": "operator"},
            headers={"X-CSRF-Token": csrf},
        )
        assert ok.status_code == 200
        assert ok.json()["user"]["roles"] == ["member"]


@pytest.mark.anyio
async def test_switch_is_audited(tmp_path) -> None:
    async with demo_client(tmp_path) as client:
        await _persona_session(client, "viewer")
        database = client.database  # type: ignore[attr-defined]
        async with database.session_factory() as session:
            rows = (await session.execute(select(AuditLog))).scalars().all()
        switches = [row for row in rows if row.server_id == "demo-mode"]
        assert switches
        assert switches[-1].tool_name == "demo_persona_switch"
        assert switches[-1].status == "success"


# -- request restrictions --------------------------------------------------


@pytest.mark.anyio
async def test_demo_session_is_restricted_to_local_requests(tmp_path) -> None:
    async with demo_client(
        tmp_path, client=("203.0.113.9", 5000)
    ) as client:
        response = await client.post(
            "/api/auth/demo/session", json={"persona": "admin"}
        )
        assert response.status_code == 403
    async with demo_client(
        tmp_path, client=("203.0.113.9", 5000), allow_remote=True
    ) as client:
        response = await client.post(
            "/api/auth/demo/session", json={"persona": "admin"}
        )
        assert response.status_code == 200


@pytest.mark.anyio
async def test_demo_session_rejects_foreign_origin(tmp_path) -> None:
    async with demo_client(tmp_path) as client:
        response = await client.post(
            "/api/auth/demo/session",
            json={"persona": "admin"},
            headers={"Origin": "https://evil.example.net"},
        )
        assert response.status_code == 403
        allowed = await client.post(
            "/api/auth/demo/session",
            json={"persona": "admin"},
            headers={"Origin": "http://testserver"},
        )
        assert allowed.status_code == 200, allowed.text


# -- MCP -------------------------------------------------------------------


@pytest.mark.anyio
async def test_direct_mcp_calls_follow_the_selected_persona(tmp_path) -> None:
    async with demo_mcp_gateway(tmp_path) as (app, stores):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(
            transport=transport, base_url="http://testserver"
        ) as http:
            entered = await http.post(
                "/api/auth/demo/session", json={"persona": "viewer"}
            )
            assert entered.status_code == 200, entered.text
            viewer_token = http.cookies.get("urumi_session")
            assert viewer_token

            async with streamablehttp_client(
                "http://testserver/mcp",
                httpx_client_factory=_cookie_client_factory(app, viewer_token),
            ) as (read, write, _):
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    names = {tool.name for tool in (await session.list_tools()).tools}
                    # The fixture has 10 upstream tools; the viewer may read 6.
                    assert len(names) == 6
                    denied = await session.call_tool(
                        "shipping__create_shipment", {"order_id": 1}
                    )
                    assert denied.isError is True
                    assert "permission_denied" in denied.content[0].text

            switched = await http.post(
                "/api/auth/demo/session",
                json={"persona": "operator"},
                headers={"X-CSRF-Token": entered.json()["csrf_token"]},
            )
            assert switched.status_code == 200, switched.text
            operator_token = http.cookies.get("urumi_session")
            assert operator_token and operator_token != viewer_token

            async with streamablehttp_client(
                "http://testserver/mcp",
                httpx_client_factory=_cookie_client_factory(app, operator_token),
            ) as (read, write, _):
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    names = {tool.name for tool in (await session.list_tools()).tools}
                    assert len(names) == 7
                    allowed = await session.call_tool(
                        "shipping__update_shipment_status",
                        {"shipment_id": "s1", "status": "in_transit"},
                    )
                    assert allowed.isError is False, allowed.content[0].text
                    denied = await session.call_tool(
                        "woocommerce__create_product", {"name": "x"}
                    )
                    assert denied.isError is True
                    assert "permission_denied" in denied.content[0].text

            admin = await http.post(
                "/api/auth/demo/session",
                json={"persona": "admin"},
                headers={"X-CSRF-Token": switched.json()["csrf_token"]},
            )
            assert admin.status_code == 200, admin.text
            admin_token = http.cookies.get("urumi_session")
            async with streamablehttp_client(
                "http://testserver/mcp",
                httpx_client_factory=_cookie_client_factory(app, admin_token or ""),
            ) as (read, write, _):
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    names = {tool.name for tool in (await session.list_tools()).tools}
                    assert len(names) == 9  # create_shipment is model-hidden
                    created = await session.call_tool(
                        "woocommerce__create_product", {"name": "x"}
                    )
                    assert created.isError is False
        shipping, commerce = stores
        assert shipping.calls or commerce.calls


@pytest.mark.anyio
async def test_mcp_cookie_auth_is_demo_only(tmp_path) -> None:
    async with demo_mcp_gateway(tmp_path) as (app, stores):
        # A normal session exists, but demo cookie auth on /mcp must be off
        # when the deployment does not enable demo mode.
        database = Database(f"sqlite+aiosqlite:///{tmp_path / 'plain.db'}")
        settings = app_settings(
            service_name="gateway",
            gateway=gateway_settings(
                bootstrap_admin_email=ADMIN_EMAIL,
                bootstrap_admin_password=ADMIN_PASSWORD,
            ),
        )
        plain = create_app(settings, database=database, seed_servers=False, discover=False)
        async with plain.router.lifespan_context(plain):
            transport = httpx.ASGITransport(app=plain)
            async with httpx.AsyncClient(
                transport=transport, base_url="http://testserver"
            ) as http:
                login = await http.post(
                    "/api/auth/login",
                    json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD},
                )
                assert login.status_code == 200
                token = http.cookies.get("urumi_session")
                assert token
                with pytest.raises(Exception):
                    # The middleware rejects the cookie before the handshake.
                    async with streamablehttp_client(
                        "http://testserver/mcp",
                        httpx_client_factory=_cookie_client_factory(plain, token),
                    ) as (read, write, _):
                        async with ClientSession(read, write) as session:
                            await session.initialize()
        del stores
