"""End-to-end tests of the gateway MCP endpoint over Streamable HTTP.

The real FastAPI app, ASGI-aware MCP client, ASGI middleware (API-key auth),
permission filtering and audit logging all run in-process against a fake
upstream server.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
import httpx
import pytest
from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client

from services.gateway import auth
from services.gateway.app import create_app
from services.gateway.db import Database
from services.gateway.schemas import ServerCreate
from services.gateway.upstream import UpstreamResult, UpstreamTool

from tests.conftest import app_settings, gateway_settings

ADMIN_EMAIL = "admin@urumi.test"
ADMIN_PASSWORD = "admin-password-1"
MEMBER_EMAIL = "member@urumi.test"
MEMBER_PASSWORD = "member-password-1"


class FakeUpstream:
    server_id = "fake"

    def __init__(self) -> None:
        self.calls: list[tuple[str, dict]] = []

    async def list_tools(self):
        return [
            UpstreamTool(name="echo", description="Echo", input_schema={"type": "object"}),
            UpstreamTool(name="secret", description=None, input_schema={"type": "object"}),
            UpstreamTool(
                name="greet",
                description="Greet",
                input_schema={
                    "type": "object",
                    "properties": {"message": {"type": "string"}},
                    "required": ["message"],
                },
            ),
        ]

    async def call_tool(self, name, arguments):
        self.calls.append((name, arguments))
        return UpstreamResult(content=[{"type": "text", "text": f"{name}:{arguments}"}])


@asynccontextmanager
async def gateway_app(tmp_path, **setting_overrides):
    database = Database(f"sqlite+aiosqlite:///{tmp_path / 'mcp.db'}")
    settings = app_settings(
        service_name="gateway",
        gateway=gateway_settings(
            bootstrap_admin_email=ADMIN_EMAIL,
            bootstrap_admin_password=ADMIN_PASSWORD,
            model_hidden_tools=["fake__secret"],
            **setting_overrides,
        ),
    )
    app = create_app(settings, database=database, seed_servers=False, discover=False)
    async with app.router.lifespan_context(app):
        yield app


async def _add_fake_upstream(app) -> None:
    ctx = app.state.gateway
    await ctx.registry.create(
        ServerCreate(server_id="fake", name="Fake", url="http://127.0.0.1:9999/mcp")
    )
    client = FakeUpstream()
    ctx.aggregator._client_factory = lambda server: client
    await ctx.aggregator.refresh()


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


async def _make_key(app, user_id: int, name: str = "test") -> str:
    _, plaintext = await auth.create_api_key(app.state.gateway.db, user_id, name)
    return plaintext


@pytest.mark.anyio
async def test_mcp_requires_api_key(tmp_path) -> None:
    async with gateway_app(tmp_path) as app:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://testserver"
        ) as http:
            response = await http.post("/mcp", json={})
            assert response.status_code == 401
            assert response.headers.get("www-authenticate") == "Bearer"


@pytest.mark.anyio
async def test_admin_can_list_and_call_allowed_tools(tmp_path) -> None:
    async with gateway_app(tmp_path) as app:
        admin = await auth.login(
            app.state.gateway.db, ADMIN_EMAIL, ADMIN_PASSWORD, app.state.gateway.policy
        )
        await _add_fake_upstream(app)
        key = await _make_key(app, admin.id)

        async with streamablehttp_client(
            "http://testserver/mcp",
            headers={"Authorization": f"Bearer {key}"},
            httpx_client_factory=_mcp_client_factory(app),
        ) as (read, write, _):
            async with ClientSession(read, write) as session:
                await session.initialize()
                tools = await session.list_tools()
                names = [tool.name for tool in tools.tools]
                assert "fake__echo" in names
                assert "fake__secret" not in names  # hidden from the model

                result = await session.call_tool("fake__echo", {"message": "hi"})
                assert result.isError is False
                assert "echo" in result.content[0].text

                # A hidden tool remains callable by an authorized user.
                hidden = await session.call_tool("fake__secret", {})
                assert hidden.isError is False

                unknown = await session.call_tool("ghost__missing", {})
                assert unknown.isError is True
                assert "unknown_tool" in unknown.content[0].text


@pytest.mark.anyio
async def test_member_cannot_call_ungranted_tool(tmp_path) -> None:
    async with gateway_app(tmp_path) as app:
        ctx = app.state.gateway
        admin = await auth.login(ctx.db, ADMIN_EMAIL, ADMIN_PASSWORD, ctx.policy)
        member = await auth.create_user(
            ctx.db, MEMBER_EMAIL, "Member", MEMBER_PASSWORD, ["member"]
        )
        await _add_fake_upstream(app)
        key = await _make_key(app, member.id, "member-key")

        async with streamablehttp_client(
            "http://testserver/mcp",
            headers={"Authorization": f"Bearer {key}"},
            httpx_client_factory=_mcp_client_factory(app),
        ) as (read, write, _):
            async with ClientSession(read, write) as session:
                await session.initialize()
                tools = await session.list_tools()
                assert [tool.name for tool in tools.tools] == []

                denied = await session.call_tool("fake__echo", {})
                assert denied.isError is True
                assert "permission_denied" in denied.content[0].text

        # The denied attempt is attributed to the member in the audit log.
        from services.gateway import audit as audit_module

        rows, total = await audit_module.query(ctx.db, page=1, per_page=10, user_id=member.id)
        assert total >= 1
        assert any(entry.status == "denied" for entry, _ in rows)


@pytest.mark.anyio
async def test_unknown_tool_arguments_are_rejected(tmp_path) -> None:
    """Arguments the upstream tool does not declare must not be dropped silently."""

    async with gateway_app(tmp_path) as app:
        admin = await auth.login(
            app.state.gateway.db, ADMIN_EMAIL, ADMIN_PASSWORD, app.state.gateway.policy
        )
        await _add_fake_upstream(app)
        key = await _make_key(app, admin.id)

        async with streamablehttp_client(
            "http://testserver/mcp",
            headers={"Authorization": f"Bearer {key}"},
            httpx_client_factory=_mcp_client_factory(app),
        ) as (read, write, _):
            async with ClientSession(read, write) as session:
                await session.initialize()

                ok = await session.call_tool("fake__greet", {"message": "hi"})
                assert ok.isError is False

                bad = await session.call_tool("fake__greet", {"message": "hi", "mesage": "typo"})
                assert bad.isError is True
                assert "invalid_arguments" in bad.content[0].text
                assert "mesage" in bad.content[0].text

        upstream = app.state.gateway.aggregator._client_factory("fake")
        assert [name for name, _ in upstream.calls] == ["greet"]


@pytest.mark.anyio
async def test_revoked_key_is_rejected(tmp_path) -> None:
    async with gateway_app(tmp_path) as app:
        ctx = app.state.gateway
        admin = await auth.login(ctx.db, ADMIN_EMAIL, ADMIN_PASSWORD, ctx.policy)
        record, key = await auth.create_api_key(ctx.db, admin.id, "short-lived")
        await auth.revoke_api_key(ctx.db, record.id)
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://testserver"
        ) as http:
            response = await http.post(
                "/mcp", json={}, headers={"Authorization": f"Bearer {key}"}
            )
            assert response.status_code == 401
