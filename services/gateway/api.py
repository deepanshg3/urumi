"""Authenticated management REST API for the gateway.

Authorization is permission-based: every route declares the permission it
needs (``gateway:<area>:<action>``) and the policy from
``config/permissions.yaml`` decides whether the caller holds it. No route
branches on a role name, so adding a role never requires code changes.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from sqlalchemy import select

from services.common.config import GatewaySettings
from services.gateway import audit, demo
from services.gateway.aggregator import Aggregator
from services.gateway.auth import (
    AuthContext,
    context_for,
    create_api_key,
    create_login_session,
    create_user,
    login,
    revoke_api_key,
    revoke_session,
    set_user_password,
    set_user_roles,
    user_view,
)
from services.gateway.db import ApiKey, Database, User
from services.gateway.policy import (
    GATEWAY_AUDIT_READ,
    GATEWAY_AUDIT_READ_ALL,
    GATEWAY_KEYS_MANAGE,
    GATEWAY_KEYS_MANAGE_OWN,
    GATEWAY_KEYS_READ,
    GATEWAY_SERVERS_MANAGE,
    GATEWAY_TOOLS_READ,
    GATEWAY_TOOLS_READ_ALL,
    GATEWAY_USERS_MANAGE,
    PermissionPolicy,
)
from services.gateway.registry import ServerRegistry
from services.gateway.schemas import (
    ApiKeyCreate,
    ApiKeyCreated,
    ApiKeyView,
    AuditPage,
    AuditView,
    DemoConfigView,
    DemoPersonaView,
    DemoSessionRequest,
    LoginRequest,
    LoginResponse,
    Message,
    Overview,
    ServerCreate,
    ServerUpdate,
    ServerView,
    ToolView,
    UserCreate,
    UserPasswordSet,
    UserUpdate,
    UserView,
)

SESSION_COOKIE = "urumi_session"
CSRF_COOKIE = "urumi_csrf"
CSRF_HEADER = "X-CSRF-Token"


@dataclass
class GatewayContext:
    db: Database
    settings: GatewaySettings
    policy: PermissionPolicy
    registry: ServerRegistry
    aggregator: Aggregator


def _context(request: Request) -> GatewayContext:
    return request.app.state.gateway


def _key_view(record: ApiKey, now: datetime, *, user_active: bool = True) -> ApiKeyView:
    expires = record.expires_at
    if expires is not None and expires.tzinfo is None:
        expires = expires.replace(tzinfo=timezone.utc)
    active = (
        record.revoked_at is None
        and (expires is None or expires > now)
        and user_active
    )
    return ApiKeyView(
        id=record.id,
        name=record.name,
        prefix=record.prefix,
        user_id=record.user_id,
        created_at=record.created_at,
        expires_at=record.expires_at,
        last_used_at=record.last_used_at,
        revoked_at=record.revoked_at,
        active=active,
    )


def _audit_view(entry, email: str | None) -> AuditView:
    return AuditView(
        id=entry.id,
        created_at=entry.created_at,
        user_id=entry.user_id,
        user_email=email,
        api_key_id=entry.api_key_id,
        server_id=entry.server_id,
        public_tool_name=entry.public_tool_name or entry.tool_name,
        upstream_tool_name=entry.upstream_tool_name,
        status=entry.status,
        error_code=entry.error_code,
        latency_ms=entry.latency_ms,
    )


def build_router() -> APIRouter:
    router = APIRouter(prefix="/api")

    async def require_auth(request: Request) -> AuthContext:
        context = getattr(request.state, "auth", None)
        if context is None:
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "authentication required")
        return context

    def require_permission(permission: str):
        """Build a dependency that requires a single gateway permission."""

        async def dependency(request: Request) -> AuthContext:
            context = await require_auth(request)
            ctx = _context(request)
            if not ctx.policy.can(context.permissions, permission):
                raise HTTPException(
                    status.HTTP_403_FORBIDDEN, f"missing permission: {permission}"
                )
            return context

        return dependency

    def require_csrf(request: Request) -> None:
        if request.method in {"GET", "HEAD", "OPTIONS"}:
            return
        session_csrf = getattr(request.state, "csrf_token", None)
        supplied = request.headers.get(CSRF_HEADER)
        if not session_csrf or not supplied or supplied != session_csrf:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "invalid CSRF token")

    # -- auth --------------------------------------------------------------
    @router.post("/auth/login", response_model=LoginResponse)
    async def auth_login(payload: LoginRequest, request: Request, response: Response):
        ctx = _context(request)
        user = await login(ctx.db, payload.email, payload.password, ctx.policy)
        if user is None:
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid email or password")
        token, csrf, expires_at = await create_login_session(ctx.db, ctx.settings, user.id)
        response.set_cookie(
            SESSION_COOKIE,
            token,
            httponly=True,
            samesite="strict",
            secure=ctx.settings.cookie_secure,
            expires=expires_at,
            path="/",
        )
        response.set_cookie(
            CSRF_COOKIE,
            csrf,
            httponly=False,
            samesite="strict",
            secure=ctx.settings.cookie_secure,
            expires=expires_at,
            path="/",
        )
        return LoginResponse(user=user_view(user, ctx.policy), csrf_token=csrf)

    @router.post("/auth/logout", response_model=Message)
    async def auth_logout(request: Request, response: Response, context: AuthContext = Depends(require_auth)):
        require_csrf(request)
        ctx = _context(request)
        if context.session_id is not None:
            await revoke_session(ctx.db, context.session_id)
        response.delete_cookie(SESSION_COOKIE, path="/")
        response.delete_cookie(CSRF_COOKIE, path="/")
        return Message(message="logged out")

    @router.get("/auth/me", response_model=UserView)
    async def auth_me(request: Request, context: AuthContext = Depends(require_auth)):
        ctx = _context(request)
        async with ctx.db.session_factory() as session:
            user = await session.get(User, context.user_id)
        if user is None:
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "user no longer exists")
        return user_view(user, ctx.policy)

    # -- assessment demo mode ----------------------------------------------
    @router.get("/auth/demo", response_model=DemoConfigView)
    async def demo_config(request: Request):
        """Public demo-mode metadata; safe to call without a session.

        Returns `enabled: false` (and no personas) unless the deployment
        explicitly enabled assessment demo mode.
        """
        ctx = _context(request)
        if not ctx.settings.demo_mode:
            return DemoConfigView(enabled=False)
        return DemoConfigView(
            enabled=True,
            personas=[DemoPersonaView(**item) for item in demo.persona_catalog()],
            deployment=ctx.settings.deployment_env,
        )

    @router.post("/auth/demo/session", response_model=LoginResponse)
    async def demo_session(
        payload: DemoSessionRequest, request: Request, response: Response
    ):
        """Enter the dashboard as one of the three fixed assessment personas.

        The persona is looked up in a server-side allowlist and mapped to a
        dedicated persisted user. The previous browser session is revoked, so
        switching replaces the identity instead of layering on top of it. All
        REST and MCP authorization keeps running against the real policy.
        """
        ctx = _context(request)
        if not ctx.settings.demo_mode:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "demo mode is not enabled")
        if not demo.demo_request_allowed(
            ctx.settings,
            client_host=request.client.host if request.client else None,
            host_header=request.headers.get("host"),
            origin=request.headers.get("origin"),
        ):
            raise HTTPException(
                status.HTTP_403_FORBIDDEN,
                "demo mode is restricted to local assessment deployments",
            )
        persona = demo.get_persona(payload.persona)
        if persona is None:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST, "unknown demo persona"
            )

        current = getattr(request.state, "auth", None)
        replaced_session = current.session_id if current is not None else None
        if replaced_session is not None:
            # Switching keeps the CSRF guarantee: a request that rides an
            # existing session must prove it can read that session's token.
            require_csrf(request)
            await revoke_session(ctx.db, replaced_session)

        users = await demo.ensure_demo_users(ctx.db)
        user = users[persona.id]
        token, csrf, expires_at = await create_login_session(
            ctx.db, ctx.settings, user.id
        )
        response.set_cookie(
            SESSION_COOKIE,
            token,
            httponly=True,
            samesite="strict",
            secure=ctx.settings.cookie_secure,
            expires=expires_at,
            path="/",
        )
        response.set_cookie(
            CSRF_COOKIE,
            csrf,
            httponly=False,
            samesite="strict",
            secure=ctx.settings.cookie_secure,
            expires=expires_at,
            path="/",
        )
        try:
            await audit.record(
                ctx.db,
                ctx.settings,
                context_for(user, ctx.policy),
                server_id="demo-mode",
                public_tool="demo_persona_switch",
                upstream_tool=None,
                status="success",
                detail={
                    "persona": persona.id,
                    "role": persona.role,
                    "replaced_session": replaced_session,
                },
            )
        except audit.AuditWriteError:
            # The audit helper already logged the failure; a switch that is
            # otherwise complete should still enter the selected persona.
            pass
        return LoginResponse(user=user_view(user, ctx.policy), csrf_token=csrf)

    # -- users -------------------------------------------------------------
    @router.get("/users", response_model=list[UserView])
    async def list_users(
        request: Request,
        context: AuthContext = Depends(require_permission(GATEWAY_USERS_MANAGE)),
    ):
        ctx = _context(request)
        async with ctx.db.session_factory() as session:
            users = (
                await session.execute(select(User).order_by(User.id))
            ).scalars().all()
            return [user_view(user, ctx.policy) for user in users]

    @router.post("/users", response_model=UserView, status_code=201)
    async def create_user_endpoint(
        payload: UserCreate,
        request: Request,
        context: AuthContext = Depends(require_permission(GATEWAY_USERS_MANAGE)),
    ):
        require_csrf(request)
        ctx = _context(request)
        user = await create_user(
            ctx.db,
            payload.email,
            payload.display_name or payload.email.split("@")[0],
            payload.password,
            payload.roles,
        )
        return user_view(user, ctx.policy)

    @router.patch("/users/{user_id}", response_model=UserView)
    async def update_user(
        user_id: int,
        payload: UserUpdate,
        request: Request,
        context: AuthContext = Depends(require_permission(GATEWAY_USERS_MANAGE)),
    ):
        require_csrf(request)
        ctx = _context(request)
        async with ctx.db.session_factory() as session:
            user = await session.get(User, user_id)
            if user is None:
                raise HTTPException(status.HTTP_404_NOT_FOUND, "user not found")
            if payload.display_name is not None:
                user.display_name = payload.display_name
            if payload.is_active is not None:
                if user.id == context.user_id and not payload.is_active:
                    raise HTTPException(status.HTTP_400_BAD_REQUEST, "cannot deactivate yourself")
                user.is_active = payload.is_active
            await session.commit()
        if payload.roles is not None:
            if user_id == context.user_id and not ctx.policy.can(
                ctx.policy.for_roles(payload.roles), GATEWAY_USERS_MANAGE
            ):
                raise HTTPException(
                    status.HTTP_400_BAD_REQUEST,
                    "cannot remove your own user-management permission",
                )
            user = await set_user_roles(ctx.db, user_id, payload.roles)
        async with ctx.db.session_factory() as session:
            user = await session.get(User, user_id)
        return user_view(user, ctx.policy)

    @router.post("/users/{user_id}/password", response_model=UserView)
    async def reset_user_password(
        user_id: int,
        payload: UserPasswordSet,
        request: Request,
        context: AuthContext = Depends(require_permission(GATEWAY_USERS_MANAGE)),
    ):
        """Administrator-only password reset.

        The new password is hashed before it is stored, never echoed back and
        never logged. Every browser session of the target account is revoked so
        the reset takes effect immediately (this also signs the caller out when
        they reset their own password).
        """
        require_csrf(request)
        ctx = _context(request)
        user = await set_user_password(ctx.db, user_id, payload.password)
        return user_view(user, ctx.policy)

    # -- servers -----------------------------------------------------------
    @router.get("/servers", response_model=list[ServerView])
    async def list_servers(
        request: Request, context: AuthContext = Depends(require_permission(GATEWAY_TOOLS_READ))
    ):
        ctx = _context(request)
        return [ctx.registry.view(server) for server in await ctx.registry.list()]

    @router.post("/servers", response_model=ServerView, status_code=201)
    async def create_server(
        payload: ServerCreate,
        request: Request,
        context: AuthContext = Depends(require_permission(GATEWAY_SERVERS_MANAGE)),
    ):
        require_csrf(request)
        ctx = _context(request)
        server = await ctx.registry.create(payload)
        await ctx.aggregator.refresh(server.server_id)
        return ctx.registry.view(await ctx.registry.get(server.server_id))

    @router.get("/servers/{server_id}", response_model=ServerView)
    async def get_server(
        server_id: str,
        request: Request,
        context: AuthContext = Depends(require_permission(GATEWAY_TOOLS_READ)),
    ):
        ctx = _context(request)
        return ctx.registry.view(await ctx.registry.get(server_id))

    @router.patch("/servers/{server_id}", response_model=ServerView)
    async def update_server(
        server_id: str,
        payload: ServerUpdate,
        request: Request,
        context: AuthContext = Depends(require_permission(GATEWAY_SERVERS_MANAGE)),
    ):
        require_csrf(request)
        ctx = _context(request)
        await ctx.registry.update(server_id, payload)
        await ctx.aggregator.refresh(server_id)
        return ctx.registry.view(await ctx.registry.get(server_id))

    @router.delete("/servers/{server_id}", response_model=Message)
    async def delete_server(
        server_id: str,
        request: Request,
        context: AuthContext = Depends(require_permission(GATEWAY_SERVERS_MANAGE)),
    ):
        require_csrf(request)
        ctx = _context(request)
        await ctx.registry.delete(server_id)
        await ctx.aggregator.refresh()
        return Message(message=f"server {server_id} removed")

    @router.post("/servers/{server_id}/enable", response_model=ServerView)
    async def enable_server(
        server_id: str,
        request: Request,
        enabled: bool = Query(True),
        context: AuthContext = Depends(require_permission(GATEWAY_SERVERS_MANAGE)),
    ):
        require_csrf(request)
        ctx = _context(request)
        await ctx.registry.set_enabled(server_id, enabled)
        await ctx.aggregator.refresh(server_id if enabled else None)
        if not enabled:
            await ctx.aggregator.refresh()  # drop the disabled server's tools
        return ctx.registry.view(await ctx.registry.get(server_id))

    @router.post("/servers/{server_id}/refresh", response_model=ServerView)
    async def refresh_server(
        server_id: str,
        request: Request,
        context: AuthContext = Depends(require_permission(GATEWAY_SERVERS_MANAGE)),
    ):
        require_csrf(request)
        ctx = _context(request)
        await ctx.aggregator.refresh(server_id)
        return ctx.registry.view(await ctx.registry.get(server_id))

    @router.get("/servers/{server_id}/tools", response_model=list[ToolView])
    async def server_tools(
        server_id: str,
        request: Request,
        context: AuthContext = Depends(require_permission(GATEWAY_TOOLS_READ)),
    ):
        ctx = _context(request)
        catalog = ctx.aggregator.catalog(server_id)
        if catalog is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "server has not been discovered")
        see_all = ctx.policy.can(context.permissions, GATEWAY_TOOLS_READ_ALL)
        tools = []
        for route in catalog.tools:
            permitted = ctx.policy.can_call_tool(
                context.permissions, route.server_id, route.upstream_name
            )
            if not permitted and not see_all:
                continue
            tools.append(
                ToolView(
                    name=route.public_name,
                    server_id=route.server_id,
                    upstream_tool=route.upstream_name,
                    description=route.description,
                    input_schema=route.input_schema,
                    permitted=permitted,
                )
            )
        return tools

    # -- aggregated tools --------------------------------------------------
    @router.get("/tools", response_model=list[ToolView])
    async def list_tools(
        request: Request, context: AuthContext = Depends(require_permission(GATEWAY_TOOLS_READ))
    ):
        ctx = _context(request)
        see_all = ctx.policy.can(context.permissions, GATEWAY_TOOLS_READ_ALL)
        visible = []
        for route in ctx.aggregator.routes(healthy_only=True):
            permitted = ctx.policy.can_call_tool(
                context.permissions, route.server_id, route.upstream_name
            )
            if permitted or see_all:
                visible.append(
                    ToolView(
                        name=route.public_name,
                        server_id=route.server_id,
                        upstream_tool=route.upstream_name,
                        description=route.description,
                        input_schema=route.input_schema,
                        permitted=permitted,
                    )
                )
        return visible

    # -- API keys ----------------------------------------------------------
    @router.get("/keys", response_model=list[ApiKeyView])
    async def list_keys(
        request: Request,
        user_id: int | None = Query(None, ge=1),
        context: AuthContext = Depends(require_permission(GATEWAY_KEYS_READ)),
    ):
        ctx = _context(request)
        manage_any = ctx.policy.can(context.permissions, GATEWAY_KEYS_MANAGE)
        target = context.user_id
        if user_id is not None:
            if not manage_any and user_id != context.user_id:
                raise HTTPException(
                    status.HTTP_403_FORBIDDEN, "cannot view another user's keys"
                )
            target = user_id
        async with ctx.db.session_factory() as session:
            owner = await session.get(User, target)
            user_active = bool(owner and owner.is_active)
            records = (
                await session.execute(
                    select(ApiKey).where(ApiKey.user_id == target).order_by(ApiKey.id.desc())
                )
            ).scalars().all()
            return [
                _key_view(record, datetime.now(timezone.utc), user_active=user_active)
                for record in records
            ]

    @router.post("/keys", response_model=ApiKeyCreated, status_code=201)
    async def create_key(
        payload: ApiKeyCreate,
        request: Request,
        context: AuthContext = Depends(require_auth),
    ):
        require_csrf(request)
        ctx = _context(request)
        manage_any = ctx.policy.can(context.permissions, GATEWAY_KEYS_MANAGE)
        manage_own = ctx.policy.can(context.permissions, GATEWAY_KEYS_MANAGE_OWN)
        if not manage_any and not manage_own:
            raise HTTPException(
                status.HTTP_403_FORBIDDEN, f"missing permission: {GATEWAY_KEYS_MANAGE_OWN}"
            )
        target = context.user_id
        if payload.user_id is not None and payload.user_id != context.user_id:
            if not manage_any:
                raise HTTPException(
                    status.HTTP_403_FORBIDDEN, "cannot create keys for another user"
                )
            target = payload.user_id
            async with ctx.db.session_factory() as session:
                if await session.get(User, target) is None:
                    raise HTTPException(status.HTTP_404_NOT_FOUND, "user not found")
        record, plaintext = await create_api_key(
            ctx.db, target, payload.name, payload.expires_in_days
        )
        base = _key_view(record, datetime.now(timezone.utc))
        return ApiKeyCreated(**base.model_dump(), api_key=plaintext)

    @router.delete("/keys/{key_id}", response_model=Message)
    async def delete_key(
        key_id: int,
        request: Request,
        context: AuthContext = Depends(require_auth),
    ):
        require_csrf(request)
        ctx = _context(request)
        manage_any = ctx.policy.can(context.permissions, GATEWAY_KEYS_MANAGE)
        manage_own = ctx.policy.can(context.permissions, GATEWAY_KEYS_MANAGE_OWN)
        if not manage_any and not manage_own:
            raise HTTPException(
                status.HTTP_403_FORBIDDEN, f"missing permission: {GATEWAY_KEYS_MANAGE_OWN}"
            )
        async with ctx.db.session_factory() as session:
            record = await session.get(ApiKey, key_id)
        if record is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "API key not found")
        if not manage_any and record.user_id != context.user_id:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "cannot revoke another user's key")
        owner_scope = None if manage_any else context.user_id
        ok = await revoke_api_key(ctx.db, key_id, owner_scope)
        if not ok:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "API key not found")
        return Message(message="API key revoked")

    # -- audit -------------------------------------------------------------
    @router.get("/audit", response_model=AuditPage)
    async def list_audit(
        request: Request,
        page: int = Query(1, ge=1),
        per_page: int = Query(25, ge=1, le=200),
        server_id: str | None = None,
        status_filter: str | None = Query(None, alias="status"),
        tool: str | None = None,
        since: datetime | None = None,
        context: AuthContext = Depends(require_permission(GATEWAY_AUDIT_READ)),
    ):
        ctx = _context(request)
        read_all = ctx.policy.can(context.permissions, GATEWAY_AUDIT_READ_ALL)
        user_filter = None if read_all else context.user_id
        rows, total = await audit.query(
            ctx.db,
            page=page,
            per_page=per_page,
            user_id=user_filter,
            server_id=server_id,
            status=status_filter,
            tool=tool,
            since=since,
        )
        return AuditPage(
            items=[_audit_view(entry, email) for entry, email in rows],
            page=page,
            per_page=per_page,
            total=total,
            has_more=page * per_page < total,
        )

    # -- overview ----------------------------------------------------------
    @router.get("/overview", response_model=Overview)
    async def overview(request: Request, context: AuthContext = Depends(require_auth)):
        ctx = _context(request)
        servers = await ctx.registry.list()
        routes = ctx.aggregator.routes(healthy_only=True)
        permitted = [
            route
            for route in routes
            if ctx.policy.can_call_tool(context.permissions, route.server_id, route.upstream_name)
        ]
        read_all = ctx.policy.can(context.permissions, GATEWAY_AUDIT_READ_ALL)
        rows, _ = await audit.query(
            ctx.db,
            page=1,
            per_page=10,
            user_id=None if read_all else context.user_id,
        )
        return Overview(
            upstreams_enabled=sum(1 for server in servers if server.enabled),
            upstreams_total=len(servers),
            tools_total=len(routes),
            tools_permitted=len(permitted),
            servers=[ctx.registry.view(server) for server in servers],
            recent_activity=[_audit_view(entry, email) for entry, email in rows],
        )

    return router
