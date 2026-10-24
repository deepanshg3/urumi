"""FastAPI application for the central MCP gateway (Passes 5/6)."""

from __future__ import annotations

import asyncio
import contextlib
import os
from collections.abc import AsyncIterator
from pathlib import Path

import yaml
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from mcp.server.streamable_http_manager import StreamableHTTPSessionManager
from sqlalchemy import text
from starlette.types import ASGIApp, Receive, Scope, Send

from services.common.config import AppSettings, GatewaySettings, load_settings
from services.common.errors import (
    AuthenticationError,
    ConfigurationError,
    ConflictError,
    NotFoundError,
    RateLimitError,
    ServiceError,
    UpstreamError,
    ValidationError,
)
from services.common.logging import configure_logging, get_logger
from services.gateway import audit, demo
from services.gateway.aggregator import Aggregator
from services.gateway.api import CSRF_COOKIE, SESSION_COOKIE, GatewayContext, build_router
from services.gateway.auth import authenticate_api_key, authenticate_session, bootstrap_admin
from services.gateway.db import Database, create_default_roles, ensure_schema
from services.gateway.mcp_server import build_server, transport_security
from services.gateway.policy import PermissionPolicy
from services.gateway.registry import ServerRegistry

logger = get_logger("urumi.gateway")


def _load_servers_config() -> list[dict]:
    from services.common.config import PROJECT_ROOT

    override = os.environ.get("GATEWAY_SERVERS_CONFIG")
    path = Path(override) if override else PROJECT_ROOT / "config" / "servers.yaml"
    if not path.is_file():
        return []
    data = yaml.safe_load(path.read_text()) or {}
    servers = data.get("servers") or []
    return [item for item in servers if isinstance(item, dict)]


def _status_for(exc: ServiceError) -> int:
    if isinstance(exc, (ValidationError,)):
        return 400
    if isinstance(exc, AuthenticationError):
        return 401
    if isinstance(exc, NotFoundError):
        return 404
    if isinstance(exc, ConflictError):
        return 409
    if isinstance(exc, RateLimitError):
        return 429
    if isinstance(exc, UpstreamError):
        return 502
    if isinstance(exc, ConfigurationError):
        return 500
    return 500


def _cookie_value(header: str, name: str) -> str | None:
    for part in header.split(";"):
        key, _, value = part.strip().partition("=")
        if key == name:
            return value
    return None


class AuthStateMiddleware:
    """Set request.state.auth for the gateway MCP endpoint and management API.

    Browser sessions use an HttpOnly cookie; the MCP endpoint normally requires
    a personal API key presented as an ``Authorization: Bearer`` header. In
    assessment demo mode only, MCP requests may also authenticate with the demo
    session cookie (restricted to local requests) so the selected persona can be
    verified with direct tool calls. Production MCP access stays key-only.
    """

    def __init__(
        self,
        app: ASGIApp,
        *,
        mcp_path: str,
        database: Database,
        policy: PermissionPolicy,
        settings: GatewaySettings | None = None,
        enforce_mcp_auth: bool = True,
        api_prefix: str = "/api/",
    ) -> None:
        self.app = app
        self.mcp_path = mcp_path.rstrip("/") or "/mcp"
        self.database = database
        self.policy = policy
        self.settings = settings
        self.enforce_mcp_auth = enforce_mcp_auth
        self.api_prefix = api_prefix

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        path = scope.get("path", "")
        state = scope.setdefault("state", {})
        headers = {key.decode().lower(): value.decode() for key, value in scope.get("headers", [])}

        if path == self.mcp_path or path.startswith(self.mcp_path + "/"):
            if self.enforce_mcp_auth:
                authorization = headers.get("authorization", "")
                scheme, _, token = authorization.partition(" ")
                context = None
                if scheme.lower() == "bearer" and token:
                    context = await authenticate_api_key(self.database, token.strip(), self.policy)
                if (
                    context is None
                    and self.settings is not None
                    and self.settings.demo_mode
                ):
                    client = scope.get("client") or (None, None)
                    session_token = _cookie_value(
                        headers.get("cookie", ""), SESSION_COOKIE
                    )
                    if session_token and demo.demo_request_allowed(
                        self.settings,
                        client_host=client[0],
                        host_header=headers.get("host"),
                        origin=headers.get("origin"),
                    ):
                        result = await authenticate_session(
                            self.database, session_token, self.policy
                        )
                        if result is not None:
                            context, record = result
                            state["csrf_token"] = record.csrf_token
                if context is None:
                    response = JSONResponse(
                        {"error": "authentication_error", "message": "valid API key required"},
                        status_code=401,
                        headers={"WWW-Authenticate": "Bearer"},
                    )
                    await response(scope, receive, send)
                    return
                state["auth"] = context
        elif path.startswith(self.api_prefix):
            cookie_header = headers.get("cookie", "")
            cookies = {}
            for part in cookie_header.split(";"):
                key, _, value = part.strip().partition("=")
                if key:
                    cookies[key] = value
            token = cookies.get(SESSION_COOKIE)
            if token:
                result = await authenticate_session(self.database, token, self.policy)
                if result is not None:
                    context, record = result
                    state["auth"] = context
                    state["csrf_token"] = record.csrf_token
                    state["csrf_cookie"] = cookies.get(CSRF_COOKIE)

        await self.app(scope, receive, send)


async def settle_discovery(
    aggregator: Aggregator, *, attempts: int = 5, delay: float = 2.0
) -> None:
    """Retry discovery for upstreams that were not ready at startup.

    In Kubernetes/Compose the gateway may start before every MCP server is
    accepting connections. Without this loop a single early failure would leave
    the upstream's tools missing until an explicit refresh.
    """
    for attempt in range(1, attempts + 1):
        pending = aggregator.unhealthy_servers()
        if not pending:
            return
        logger.info(
            "retrying upstream discovery attempt=%s/%s servers=%s",
            attempt,
            attempts,
            pending,
        )
        await asyncio.sleep(delay)
        for server_id in pending:
            await aggregator.refresh(server_id)
    remaining = aggregator.unhealthy_servers()
    if remaining:
        logger.warning("upstreams still unhealthy after retries servers=%s", remaining)


def create_app(
    settings: AppSettings | None = None,
    *,
    database: Database | None = None,
    seed_servers: bool = True,
    discover: bool = True,
) -> FastAPI:
    settings = settings or load_settings("gateway", default_port=8000)
    gateway_settings = settings.gateway
    configure_logging(settings.logging.level, service=settings.service_name)
    policy = PermissionPolicy.load()
    db = database or Database()
    registry = ServerRegistry(db, gateway_settings)
    aggregator = Aggregator(registry, gateway_settings)
    context = GatewayContext(
        db=db,
        settings=gateway_settings,
        policy=policy,
        registry=registry,
        aggregator=aggregator,
    )
    mcp_server = build_server(aggregator, db, gateway_settings, policy)
    session_manager = StreamableHTTPSessionManager(
        app=mcp_server,
        json_response=settings.json_response,
        stateless=settings.stateless_http,
        security_settings=transport_security(gateway_settings, settings.host),
    )

    async def startup() -> None:
        await ensure_schema(db)
        async with db.session_factory() as session:
            await create_default_roles(session)
        if gateway_settings.bootstrap_admin_email and gateway_settings.bootstrap_admin_password:
            try:
                await bootstrap_admin(
                    db,
                    gateway_settings.bootstrap_admin_email,
                    gateway_settings.bootstrap_admin_password,
                )
            except ConfigurationError as exc:
                logger.error("bootstrap administrator not created: %s", exc.message)
        if gateway_settings.demo_mode:
            logger.warning(
                "ASSESSMENT DEMO MODE ENABLED deployment=%s — persona switching "
                "is restricted to local requests; never enable this in production",
                gateway_settings.deployment_env,
            )
            await demo.ensure_demo_users(db)
        if seed_servers:
            await registry.seed_from_config(_load_servers_config())
        if discover:
            await aggregator.refresh()
            await settle_discovery(aggregator)

    @contextlib.asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        await startup()
        stop = asyncio.Event()

        async def periodic_refresh() -> None:
            interval = gateway_settings.refresh_interval_seconds
            if interval <= 0:
                return
            while not stop.is_set():
                try:
                    await asyncio.wait_for(stop.wait(), timeout=interval)
                except asyncio.TimeoutError:
                    await aggregator.refresh()

        refresh_task = asyncio.create_task(periodic_refresh())
        try:
            async with session_manager.run():
                yield
        finally:
            stop.set()
            refresh_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await refresh_task
            await db.dispose()
            logger.info("stopped %s", settings.service_name)

    app = FastAPI(
        title="Urumi MCP Gateway",
        version="0.1.0",
        description=(
            "Central MCP gateway. One Streamable HTTP endpoint (`/mcp`) exposes "
            "permission-filtered upstream tools; `/api` is the authenticated "
            "management API."
        ),
        lifespan=lifespan,
    )
    app.state.gateway = context
    app.add_middleware(
        AuthStateMiddleware,
        mcp_path=settings.mcp_path,
        database=db,
        policy=policy,
        settings=gateway_settings,
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=gateway_settings.cors_origin_list,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["Content-Type", "Authorization", "X-CSRF-Token"],
    )

    app.include_router(build_router())

    @app.exception_handler(ServiceError)
    async def service_error_handler(request: Request, exc: ServiceError) -> JSONResponse:
        return JSONResponse(
            status_code=_status_for(exc),
            content={"error": exc.code, "message": exc.message},
        )

    @app.exception_handler(audit.AuditWriteError)
    async def audit_error_handler(request: Request, exc: audit.AuditWriteError) -> JSONResponse:
        return JSONResponse(
            status_code=500,
            content={"error": "audit_error", "message": "audit log write failed"},
        )

    @app.get("/health", tags=["health"])
    async def health() -> dict[str, object]:
        return {
            "status": "ok",
            "service": settings.service_name,
            "transport": "streamable-http",
            "mcp_path": settings.mcp_path,
        }

    @app.get("/health/ready", tags=["health"])
    async def readiness() -> JSONResponse:
        try:
            async with db.session_factory() as session:
                await session.execute(text("SELECT 1"))
        except Exception:
            logger.exception("database readiness check failed")
            return JSONResponse(
                status_code=503,
                content={"status": "not_ready", "service": settings.service_name, "error": "database_unavailable"},
            )
        servers = await registry.list()
        unhealthy = [server.server_id for server in servers if server.enabled and server.status != "healthy"]
        return JSONResponse(
            status_code=200,
            content={
                "status": "ready" if not unhealthy else "degraded",
                "service": settings.service_name,
                "upstreams_total": len(servers),
                "upstreams_enabled": sum(1 for server in servers if server.enabled),
                "upstreams_unhealthy": unhealthy,
                "tools": len(aggregator.routes(healthy_only=True)),
            },
        )

    app.mount("/", session_manager.asgi_app)
    return app
