"""Role-based access control: admin, operator (member) and viewer.

The tests run against the *shipped* ``config/permissions.yaml`` so a change to
the policy file has to keep these guarantees:

* the viewer can read, never write, and never touches API keys;
* the operator may update a shipment status but may not create products,
  update order status or create shipments;
* the administrator administers the gateway, including resetting passwords;
* every refusal is enforced by the gateway, not by the dashboard.
"""

from __future__ import annotations

import contextlib
from collections.abc import AsyncIterator

import httpx
import pytest
from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client
from sqlalchemy import select

from services.gateway import audit as audit_module
from services.gateway import auth
from services.gateway.app import create_app
from services.gateway.db import Database, Role, User
from services.gateway.policy import PermissionPolicy
from services.gateway.schemas import ServerCreate
from services.gateway.upstream import UpstreamResult, UpstreamTool

from tests.conftest import app_settings, gateway_settings

ADMIN_EMAIL = "admin@urumi.test"
ADMIN_PASSWORD = "admin-password-1"
OPERATOR_EMAIL = "operator@urumi.test"
OPERATOR_PASSWORD = "operator-password-1"
VIEWER_EMAIL = "viewer@urumi.test"
VIEWER_PASSWORD = "viewer-password-1"

READ_TOOLS = [
    ("woocommerce", "list_products"),
    ("woocommerce", "list_orders"),
    ("woocommerce", "get_order"),
    ("inventory", "check_stock"),
    ("inventory", "find_low_stock"),
    ("inventory", "inventory_summary"),
    ("inventory", "reorder_recommendation"),
    ("shipping", "track_shipment"),
    ("shipping", "get_shipment"),
    ("shipping", "list_shipments"),
]
MUTATION_TOOLS = [
    ("woocommerce", "create_product"),
    ("woocommerce", "update_order_status"),
    ("shipping", "create_shipment"),
]
OPERATOR_ONLY_TOOL = ("shipping", "update_shipment_status")


# -- helpers ---------------------------------------------------------------


@contextlib.asynccontextmanager
async def gateway_client(tmp_path) -> AsyncIterator[httpx.AsyncClient]:
    database = Database(f"sqlite+aiosqlite:///{tmp_path / 'roles.db'}")
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
            http.app = app  # type: ignore[attr-defined]
            http.transport = transport  # type: ignore[attr-defined]
            yield http


async def _login(client: httpx.AsyncClient, email: str, password: str) -> str:
    response = await client.post(
        "/api/auth/login", json={"email": email, "password": password}
    )
    assert response.status_code == 200, response.text
    return response.json()["csrf_token"]


async def _create_account(
    client: httpx.AsyncClient, csrf: str, email: str, password: str, role: str
) -> int:
    response = await client.post(
        "/api/users",
        headers={"X-CSRF-Token": csrf},
        json={
            "email": email,
            "password": password,
            "display_name": email.split("@")[0],
            "roles": [role],
        },
    )
    assert response.status_code == 201, response.text
    return response.json()["id"]


@contextlib.asynccontextmanager
async def _signed_in(
    client: httpx.AsyncClient, email: str, password: str
) -> AsyncIterator[httpx.AsyncClient]:
    """A second client with its own cookie jar, signed in as ``email``."""
    fresh = httpx.AsyncClient(
        transport=client.transport,  # type: ignore[attr-defined]
        base_url=str(client.base_url),
    )
    try:
        token = await _login(fresh, email, password)
        fresh.headers["X-CSRF-Token"] = token
        yield fresh
    finally:
        await fresh.aclose()


# -- policy ----------------------------------------------------------------


def test_shipped_policy_defines_the_three_roles() -> None:
    policy = PermissionPolicy.load()
    assert {"admin", "member", "viewer"} <= policy.role_names()


def test_admin_may_call_every_tool() -> None:
    policy = PermissionPolicy.load()
    permissions = policy.for_roles(["admin"])
    for server_id, tool in READ_TOOLS + MUTATION_TOOLS + [OPERATOR_ONLY_TOOL]:
        assert policy.can_call_tool(permissions, server_id, tool), (server_id, tool)


def test_operator_matrix() -> None:
    policy = PermissionPolicy.load()
    permissions = policy.for_roles(["member"])
    for server_id, tool in READ_TOOLS:
        assert policy.can_call_tool(permissions, server_id, tool), (server_id, tool)
    assert policy.can_call_tool(permissions, *OPERATOR_ONLY_TOOL)
    for server_id, tool in MUTATION_TOOLS:
        assert not policy.can_call_tool(permissions, server_id, tool), (server_id, tool)


def test_viewer_matrix_is_read_only() -> None:
    policy = PermissionPolicy.load()
    permissions = policy.for_roles(["viewer"])
    for server_id, tool in READ_TOOLS:
        assert policy.can_call_tool(permissions, server_id, tool), (server_id, tool)
    for server_id, tool in MUTATION_TOOLS + [OPERATOR_ONLY_TOOL]:
        assert not policy.can_call_tool(permissions, server_id, tool), (server_id, tool)


def test_operator_differs_from_viewer_by_exactly_one_tool() -> None:
    policy = PermissionPolicy.load()
    operator = policy.for_roles(["member"])
    viewer = policy.for_roles(["viewer"])
    all_tools = READ_TOOLS + MUTATION_TOOLS + [OPERATOR_ONLY_TOOL]
    extra = [
        (server_id, tool)
        for server_id, tool in all_tools
        if policy.can_call_tool(operator, server_id, tool)
        and not policy.can_call_tool(viewer, server_id, tool)
    ]
    assert extra == [OPERATOR_ONLY_TOOL]


def test_deny_rule_narrows_a_wildcard_grant(tmp_path) -> None:
    """A deny rule beats a wildcard grant of the same role."""
    path = tmp_path / "permissions.yaml"
    path.write_text(
        "roles:\n"
        "  operator:\n"
        "    permissions: []\n"
        "grants:\n"
        "  operator:\n"
        '    - "tools:shipping:*"\n'
        "deny:\n"
        "  operator:\n"
        '    - "tools:shipping:create_shipment"\n'
    )
    policy = PermissionPolicy.load(path)
    permissions = policy.for_roles(["operator"])
    assert policy.can_call_tool(permissions, "shipping", "update_shipment_status")
    assert not policy.can_call_tool(permissions, "shipping", "create_shipment")


def test_viewer_holds_no_key_management_permission() -> None:
    policy = PermissionPolicy.load()
    permissions = policy.for_roles(["viewer"])
    for permission in (
        "gateway:keys:manage",
        "gateway:keys:manage:own",
        "gateway:keys:read",
        "gateway:users:manage",
        "gateway:servers:manage",
    ):
        assert not policy.can(permissions, permission)


# -- accounts and permissions ----------------------------------------------


async def test_three_roles_are_seeded_and_assignable(tmp_path) -> None:
    async with gateway_client(tmp_path) as client:
        ctx = client.app.state.gateway  # type: ignore[attr-defined]
        async with ctx.db.session_factory() as session:
            names = set((await session.execute(select(Role.name))).scalars())
        assert {"admin", "member", "viewer"} <= names

        csrf = await _login(client, ADMIN_EMAIL, ADMIN_PASSWORD)
        created = await client.post(
            "/api/users",
            headers={"X-CSRF-Token": csrf},
            json={
                "email": VIEWER_EMAIL,
                "password": VIEWER_PASSWORD,
                "display_name": "Viewer",
                "roles": ["viewer"],
            },
        )
        assert created.status_code == 201, created.text
        assert created.json()["roles"] == ["viewer"]
        assert "gateway:tools:read" in created.json()["permissions"]
        assert "gateway:keys:manage:own" not in created.json()["permissions"]


async def test_me_exposes_effective_permissions(tmp_path) -> None:
    async with gateway_client(tmp_path) as client:
        csrf = await _login(client, ADMIN_EMAIL, ADMIN_PASSWORD)
        await _create_account(client, csrf, VIEWER_EMAIL, VIEWER_PASSWORD, "viewer")
        async with _signed_in(client, VIEWER_EMAIL, VIEWER_PASSWORD) as viewer:
            me = await viewer.get("/api/auth/me")
            assert me.status_code == 200
            body = me.json()
            assert body["roles"] == ["viewer"]
            assert "gateway:tools:read" in body["permissions"]
            assert "gateway:audit:read" in body["permissions"]
            assert "gateway:keys:read" not in body["permissions"]


# -- API keys --------------------------------------------------------------


async def test_viewer_cannot_manage_api_keys_at_all(tmp_path) -> None:
    async with gateway_client(tmp_path) as client:
        csrf = await _login(client, ADMIN_EMAIL, ADMIN_PASSWORD)
        await _create_account(client, csrf, VIEWER_EMAIL, VIEWER_PASSWORD, "viewer")
        async with _signed_in(client, VIEWER_EMAIL, VIEWER_PASSWORD) as viewer:
            assert (await viewer.get("/api/keys")).status_code == 403
            created = await viewer.post("/api/keys", json={"name": "mine"})
            assert created.status_code == 403
            # Even a key that belongs to the viewer may not be revoked.
            assert (await viewer.delete("/api/keys/1")).status_code == 403


async def test_operator_manages_own_keys_only(tmp_path) -> None:
    async with gateway_client(tmp_path) as client:
        csrf = await _login(client, ADMIN_EMAIL, ADMIN_PASSWORD)
        operator_id = await _create_account(
            client, csrf, OPERATOR_EMAIL, OPERATOR_PASSWORD, "member"
        )
        async with _signed_in(client, OPERATOR_EMAIL, OPERATOR_PASSWORD) as operator:
            own = await operator.post("/api/keys", json={"name": "mine"})
            assert own.status_code == 201, own.text
            listed = await operator.get("/api/keys")
            assert listed.status_code == 200
            assert [item["id"] for item in listed.json()] == [own.json()["id"]]
            assert (await operator.delete(f"/api/keys/{own.json()['id']}")).status_code == 200

            # Another user's key is neither visible nor revocable.
            other = await operator.post(
                "/api/keys",
                headers={"X-CSRF-Token": operator.cookies.get("urumi_csrf", "")},
                json={"name": "theirs", "user_id": operator_id + 1},
            )
            assert other.status_code == 403
            assert (await operator.get(f"/api/keys?user_id={operator_id + 1}")).status_code == 403


async def test_admin_manages_any_users_keys(tmp_path) -> None:
    async with gateway_client(tmp_path) as client:
        csrf = await _login(client, ADMIN_EMAIL, ADMIN_PASSWORD)
        operator_id = await _create_account(
            client, csrf, OPERATOR_EMAIL, OPERATOR_PASSWORD, "member"
        )
        async with _signed_in(client, OPERATOR_EMAIL, OPERATOR_PASSWORD) as operator:
            own = await operator.post("/api/keys", json={"name": "mine"})
        assert own.status_code == 201

        listed = await client.get(f"/api/keys?user_id={operator_id}")
        assert listed.status_code == 200
        assert [item["id"] for item in listed.json()] == [own.json()["id"]]


# -- read-only surfaces ---------------------------------------------------


async def test_viewer_reads_but_never_writes(tmp_path) -> None:
    async with gateway_client(tmp_path) as client:
        csrf = await _login(client, ADMIN_EMAIL, ADMIN_PASSWORD)
        await _create_account(client, csrf, VIEWER_EMAIL, VIEWER_PASSWORD, "viewer")
        async with _signed_in(client, VIEWER_EMAIL, VIEWER_PASSWORD) as viewer:
            assert (await viewer.get("/api/tools")).status_code == 200
            assert (await viewer.get("/api/servers")).status_code == 200
            assert (await viewer.get("/api/audit")).status_code == 200
            assert (await viewer.get("/api/overview")).status_code == 200
            # Management surfaces are closed.
            assert (await viewer.get("/api/users")).status_code == 403
            assert (
                await viewer.post(
                    "/api/servers",
                    json={
                        "server_id": "alpha",
                        "name": "Alpha",
                        "url": "http://127.0.0.1:9001/mcp",
                    },
                )
            ).status_code == 403


async def test_operator_cannot_administer_the_gateway(tmp_path) -> None:
    async with gateway_client(tmp_path) as client:
        csrf = await _login(client, ADMIN_EMAIL, ADMIN_PASSWORD)
        await _create_account(client, csrf, OPERATOR_EMAIL, OPERATOR_PASSWORD, "member")
        async with _signed_in(client, OPERATOR_EMAIL, OPERATOR_PASSWORD) as operator:
            assert (await operator.get("/api/users")).status_code == 403
            assert (
                await operator.post(
                    "/api/servers",
                    json={
                        "server_id": "alpha",
                        "name": "Alpha",
                        "url": "http://127.0.0.1:9001/mcp",
                    },
                )
            ).status_code == 403


async def test_audit_is_scoped_to_the_caller(tmp_path) -> None:
    async with gateway_client(tmp_path) as client:
        ctx = client.app.state.gateway  # type: ignore[attr-defined]
        csrf = await _login(client, ADMIN_EMAIL, ADMIN_PASSWORD)
        operator_id = await _create_account(
            client, csrf, OPERATOR_EMAIL, OPERATOR_PASSWORD, "member"
        )
        async with ctx.db.session_factory() as session:
            admin = (
                await session.execute(
                    select(User).where(User.email == ADMIN_EMAIL)
                )
            ).scalar_one()
        await audit_module.record(
            ctx.db,
            ctx.settings,
            auth.context_for(admin, ctx.policy),
            server_id="woocommerce",
            public_tool="woocommerce__list_products",
            upstream_tool="list_products",
            status="success",
        )
        async with ctx.db.session_factory() as session:
            operator = await session.get(User, operator_id)
        await audit_module.record(
            ctx.db,
            ctx.settings,
            auth.context_for(operator, ctx.policy),
            server_id="shipping",
            public_tool="shipping__track_shipment",
            upstream_tool="track_shipment",
            status="success",
        )

        admin_audit = await client.get("/api/audit")
        assert admin_audit.status_code == 200
        assert admin_audit.json()["total"] == 2

        async with _signed_in(client, OPERATOR_EMAIL, OPERATOR_PASSWORD) as operator:
            scoped = await operator.get("/api/audit")
            assert scoped.status_code == 200
            body = scoped.json()
            assert body["total"] == 1
            assert body["items"][0]["user_email"] == OPERATOR_EMAIL


# -- password reset --------------------------------------------------------


async def test_admin_can_reset_a_password(tmp_path) -> None:
    async with gateway_client(tmp_path) as client:
        csrf = await _login(client, ADMIN_EMAIL, ADMIN_PASSWORD)
        user_id = await _create_account(
            client, csrf, OPERATOR_EMAIL, OPERATOR_PASSWORD, "member"
        )
        new_password = "operator-password-2"
        reset = await client.post(
            f"/api/users/{user_id}/password",
            headers={"X-CSRF-Token": csrf},
            json={"password": new_password},
        )
        assert reset.status_code == 200, reset.text
        assert "password" not in reset.text.lower() or new_password not in reset.text

        async with httpx.AsyncClient(
            transport=client.transport, base_url=str(client.base_url)  # type: ignore[attr-defined]
        ) as fresh:
            assert (
                await fresh.post(
                    "/api/auth/login",
                    json={"email": OPERATOR_EMAIL, "password": OPERATOR_PASSWORD},
                )
            ).status_code == 401
            assert (
                await fresh.post(
                    "/api/auth/login",
                    json={"email": OPERATOR_EMAIL, "password": new_password},
                )
            ).status_code == 200


async def test_password_reset_revokes_existing_sessions(tmp_path) -> None:
    async with gateway_client(tmp_path) as client:
        csrf = await _login(client, ADMIN_EMAIL, ADMIN_PASSWORD)
        user_id = await _create_account(
            client, csrf, OPERATOR_EMAIL, OPERATOR_PASSWORD, "member"
        )
        async with _signed_in(client, OPERATOR_EMAIL, OPERATOR_PASSWORD) as operator:
            assert (await operator.get("/api/auth/me")).status_code == 200
            reset = await client.post(
                f"/api/users/{user_id}/password",
                headers={"X-CSRF-Token": csrf},
                json={"password": "operator-password-3"},
            )
            assert reset.status_code == 200
            # The session that was open before the reset is no longer valid.
            assert (await operator.get("/api/auth/me")).status_code == 401


async def test_password_reset_is_admin_only(tmp_path) -> None:
    async with gateway_client(tmp_path) as client:
        csrf = await _login(client, ADMIN_EMAIL, ADMIN_PASSWORD)
        admin_id = (await client.get("/api/users")).json()[0]["id"]
        await _create_account(client, csrf, OPERATOR_EMAIL, OPERATOR_PASSWORD, "member")
        await _create_account(client, csrf, VIEWER_EMAIL, VIEWER_PASSWORD, "viewer")

        async with _signed_in(client, OPERATOR_EMAIL, OPERATOR_PASSWORD) as operator:
            response = await operator.post(
                f"/api/users/{admin_id}/password",
                headers={"X-CSRF-Token": operator.cookies.get("urumi_csrf", "")},
                json={"password": "operator-password-9"},
            )
            assert response.status_code == 403

        async with _signed_in(client, VIEWER_EMAIL, VIEWER_PASSWORD) as viewer:
            response = await viewer.post(
                f"/api/users/{admin_id}/password",
                headers={"X-CSRF-Token": viewer.cookies.get("urumi_csrf", "")},
                json={"password": "viewer-password-9"},
            )
            assert response.status_code == 403


async def test_password_reset_requires_a_strong_enough_password(tmp_path) -> None:
    async with gateway_client(tmp_path) as client:
        csrf = await _login(client, ADMIN_EMAIL, ADMIN_PASSWORD)
        user_id = await _create_account(
            client, csrf, OPERATOR_EMAIL, OPERATOR_PASSWORD, "member"
        )
        response = await client.post(
            f"/api/users/{user_id}/password",
            headers={"X-CSRF-Token": csrf},
            json={"password": "short"},
        )
        assert response.status_code == 422


async def test_admin_cannot_remove_own_management_permission(tmp_path) -> None:
    async with gateway_client(tmp_path) as client:
        csrf = await _login(client, ADMIN_EMAIL, ADMIN_PASSWORD)
        admin_id = (await client.get("/api/users")).json()[0]["id"]
        response = await client.patch(
            f"/api/users/{admin_id}",
            headers={"X-CSRF-Token": csrf},
            json={"roles": ["viewer"]},
        )
        assert response.status_code == 400


# -- MCP enforcement -------------------------------------------------------


class FakeStore:
    """Upstream that mimics the WooCommerce and shipping tool names."""

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
async def mcp_gateway(tmp_path):
    database = Database(f"sqlite+aiosqlite:///{tmp_path / 'roles-mcp.db'}")
    settings = app_settings(
        service_name="gateway",
        gateway=gateway_settings(
            bootstrap_admin_email=ADMIN_EMAIL,
            bootstrap_admin_password=ADMIN_PASSWORD,
            model_hidden_tools=["shipping__create_shipment"],
        ),
    )
    app = create_app(settings, database=database, seed_servers=False, discover=False)
    async with app.router.lifespan_context(app):
        ctx = app.state.gateway
        await ctx.registry.create(
            ServerCreate(
                server_id="shipping",
                name="Shipping",
                url="http://127.0.0.1:9999/mcp",
            )
        )
        await ctx.registry.create(
            ServerCreate(
                server_id="woocommerce",
                name="WooCommerce",
                url="http://127.0.0.1:9998/mcp",
            )
        )
        upstream = FakeStore(
            [
                "track_shipment",
                "get_shipment",
                "list_shipments",
                "create_shipment",
                "update_shipment_status",
                "list_products",
                "list_orders",
                "get_order",
                "create_product",
                "update_order_status",
            ]
        )
        ctx.aggregator._client_factory = lambda server: upstream
        await ctx.aggregator.refresh()
        yield app, upstream


def _mcp_client_factory(app):
    def factory(headers=None, timeout=None, auth=None, **kwargs):
        return httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://testserver",
            headers=headers,
            timeout=timeout,
            auth=auth,
        )

    return factory


async def _key_for(app, email: str, password: str, name: str) -> str:
    ctx = app.state.gateway
    user = await auth.login(ctx.db, email, password, ctx.policy)
    assert user is not None, email
    _, plaintext = await auth.create_api_key(ctx.db, user.id, name)
    return plaintext


@pytest.mark.anyio
async def test_operator_may_update_shipment_status_but_not_create_one(tmp_path) -> None:
    async with mcp_gateway(tmp_path) as (app, upstream):
        ctx = app.state.gateway
        operator = await auth.create_user(
            ctx.db, OPERATOR_EMAIL, "Operator", OPERATOR_PASSWORD, ["member"]
        )
        key = await _key_for(app, OPERATOR_EMAIL, OPERATOR_PASSWORD, "operator-key")

        async with streamablehttp_client(
            "http://testserver/mcp",
            headers={"Authorization": f"Bearer {key}"},
            httpx_client_factory=_mcp_client_factory(app),
        ) as (read, write, _):
            async with ClientSession(read, write) as session:
                await session.initialize()
                names = {tool.name for tool in (await session.list_tools()).tools}
                assert "shipping__update_shipment_status" in names
                assert "shipping__create_shipment" not in names
                assert "woocommerce__create_product" not in names

                allowed = await session.call_tool("shipping__update_shipment_status", {})
                assert allowed.isError is False

                denied = await session.call_tool("shipping__create_shipment", {})
                assert denied.isError is True
                assert "permission_denied" in denied.content[0].text

        assert ("update_shipment_status", {}) in upstream.calls
        assert all(name != "create_shipment" for name, _ in upstream.calls)

        rows, total = await audit_module.query(
            ctx.db, page=1, per_page=10, user_id=operator.id
        )
        assert total >= 1
        assert any(entry.status == "denied" for entry, _ in rows)


@pytest.mark.anyio
async def test_viewer_cannot_call_any_mutation(tmp_path) -> None:
    async with mcp_gateway(tmp_path) as (app, upstream):
        ctx = app.state.gateway
        viewer = await auth.create_user(
            ctx.db, VIEWER_EMAIL, "Viewer", VIEWER_PASSWORD, ["viewer"]
        )
        key = await _key_for(app, VIEWER_EMAIL, VIEWER_PASSWORD, "viewer-key")

        async with streamablehttp_client(
            "http://testserver/mcp",
            headers={"Authorization": f"Bearer {key}"},
            httpx_client_factory=_mcp_client_factory(app),
        ) as (read, write, _):
            async with ClientSession(read, write) as session:
                await session.initialize()
                names = {tool.name for tool in (await session.list_tools()).tools}
                assert "shipping__track_shipment" in names
                assert "shipping__update_shipment_status" not in names
                assert "woocommerce__create_product" not in names

                for tool in (
                    "shipping__update_shipment_status",
                    "shipping__create_shipment",
                    "woocommerce__create_product",
                    "woocommerce__update_order_status",
                ):
                    denied = await session.call_tool(tool, {})
                    assert denied.isError is True, tool
                    assert "permission_denied" in denied.content[0].text

        assert upstream.calls == []

        rows, total = await audit_module.query(
            ctx.db, page=1, per_page=10, user_id=viewer.id
        )
        assert total == 4
        assert all(entry.status == "denied" for entry, _ in rows)


@pytest.mark.anyio
async def test_admin_may_call_every_tool(tmp_path) -> None:
    async with mcp_gateway(tmp_path) as (app, upstream):
        key = await _key_for(app, ADMIN_EMAIL, ADMIN_PASSWORD, "admin-key")
        async with streamablehttp_client(
            "http://testserver/mcp",
            headers={"Authorization": f"Bearer {key}"},
            httpx_client_factory=_mcp_client_factory(app),
        ) as (read, write, _):
            async with ClientSession(read, write) as session:
                await session.initialize()
                names = {tool.name for tool in (await session.list_tools()).tools}
                assert "woocommerce__create_product" in names
                assert "shipping__update_shipment_status" in names
                # Hidden from the model's tool list, but still callable.
                assert "shipping__create_shipment" not in names

                for tool in (
                    "woocommerce__create_product",
                    "woocommerce__update_order_status",
                    "shipping__create_shipment",
                    "shipping__update_shipment_status",
                ):
                    result = await session.call_tool(tool, {})
                    assert result.isError is False, tool

        assert len(upstream.calls) == 4
