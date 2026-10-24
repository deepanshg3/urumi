"""FastAPI application for the Urumi chat agent (Pass 7)."""

from __future__ import annotations

import contextlib
from collections.abc import AsyncIterator
from dataclasses import dataclass
from urllib.parse import urlsplit, urlunsplit

import httpx
from fastapi import FastAPI, HTTPException, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import text

from services.common.config import AppSettings, load_settings
from services.common.errors import (
    AuthenticationError,
    ConfigurationError,
    NotFoundError,
    ServiceError,
    ValidationError,
)
from services.common.logging import configure_logging, get_logger
from services.agent.api import AGENT_API_PREFIX, build_router
from services.agent.model import is_placeholder_secret
from services.agent.persistence import ensure_agent_schema
from services.agent.service import AgentService
from services.gateway.app import AuthStateMiddleware
from services.gateway.auth import authenticate_session
from services.gateway.db import Database, create_default_roles, ensure_schema
from services.gateway.policy import PermissionPolicy

logger = get_logger("urumi.agent")


@dataclass
class AgentContext:
    db: Database
    settings: AppSettings
    service: AgentService
    policy: PermissionPolicy


def _gateway_health_url(mcp_url: str) -> str:
    parts = urlsplit(mcp_url)
    path = parts.path.rstrip("/")
    if path.endswith("/mcp"):
        path = path[: -len("/mcp")]
    return urlunsplit((parts.scheme, parts.netloc, path + "/health/ready", "", ""))


def _status_for(exc: ServiceError) -> int:
    if isinstance(exc, ValidationError):
        return 400
    if isinstance(exc, AuthenticationError):
        return 401
    if isinstance(exc, NotFoundError):
        return 404
    if isinstance(exc, ConfigurationError):
        return 500
    return 500


def create_app(
    settings: AppSettings | None = None,
    *,
    database: Database | None = None,
    service: AgentService | None = None,
) -> FastAPI:
    settings = settings or load_settings("agent", default_port=8200)
    chat = settings.chat_agent
    configure_logging(settings.logging.level, service=settings.service_name)
    policy = PermissionPolicy.load()
    db = database or Database()
    agent_service = service or AgentService(db, settings)
    context = AgentContext(db=db, settings=settings, service=agent_service, policy=policy)

    @contextlib.asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        await ensure_schema(db)
        async with db.session_factory() as session:
            await create_default_roles(session)
        await ensure_agent_schema(db)
        if is_placeholder_secret(settings.llm.api_key):
            logger.warning(
                "GEMINI_API_KEY is not configured; chat requests will fail with a configuration error"
            )
        logger.info("started %s on %s:%s", settings.service_name, settings.host, settings.port)
        yield
        await db.dispose()

    app = FastAPI(
        title="Urumi Chat Agent",
        version="0.1.0",
        description=(
            "Chat agent that calls the MCP gateway as a client using a delegated, "
            "short-lived per-user API key. Authorization stays in the gateway."
        ),
        lifespan=lifespan,
    )
    app.state.agent = context
    app.add_middleware(
        AuthStateMiddleware,
        mcp_path="/__agent_mcp_unused__",
        database=db,
        policy=policy,
        enforce_mcp_auth=False,
        api_prefix=AGENT_API_PREFIX + "/",
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=chat.cors_origin_list,
        allow_credentials=True,
        allow_methods=["GET", "POST", "DELETE", "OPTIONS"],
        allow_headers=["Content-Type", "Authorization", "X-CSRF-Token"],
    )
    app.include_router(build_router())

    @app.exception_handler(ServiceError)
    async def _service_error_handler(_: Request, exc: ServiceError) -> JSONResponse:
        return JSONResponse(
            status_code=_status_for(exc), content={"error": exc.code, "message": exc.message}
        )

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok", "service": settings.service_name}

    @app.get("/health/ready")
    async def readiness() -> JSONResponse:
        details: dict[str, object] = {"service": settings.service_name}
        ok = True
        try:
            async with db.session_factory() as session:
                await session.execute(text("SELECT 1"))
            details["database"] = "ok"
        except Exception:  # pragma: no cover - defensive
            details["database"] = "error"
            ok = False
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                response = await client.get(_gateway_health_url(chat.gateway_mcp_url))
            details["gateway"] = "ok" if response.status_code == 200 else f"status_{response.status_code}"
            ok = ok and response.status_code == 200
        except Exception:
            details["gateway"] = "unreachable"
            ok = False
        details["model_configured"] = not is_placeholder_secret(settings.llm.api_key)
        details["tracing_enabled"] = bool(settings.langsmith.tracing_enabled)
        details["status"] = "ready" if ok else "not_ready"
        return JSONResponse(status_code=200 if ok else status.HTTP_503_SERVICE_UNAVAILABLE, content=details)

    return app
