"""Upstream server registry: CRUD, credentials, health and seeding."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select

from services.common.config import GatewaySettings
from services.common.errors import ConfigurationError, NotFoundError, ValidationError
from services.gateway.db import Database, ServerRegistration
from services.gateway.schemas import ServerCreate, ServerUpdate, ServerView
from services.gateway.security import CredentialCipher
from services.gateway.validation import validate_upstream_url


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class ServerRegistry:
    def __init__(self, database: Database, settings: GatewaySettings) -> None:
        self.db = database
        self.settings = settings
        self._cipher = CredentialCipher(settings.secret_key) if settings.secret_key else None

    # -- serialization -----------------------------------------------------
    @staticmethod
    def view(server: ServerRegistration) -> ServerView:
        return ServerView(
            server_id=server.server_id,
            name=server.name,
            description=server.description,
            transport=server.transport,
            url=server.endpoint,
            health_url=server.health_url,
            enabled=server.enabled,
            status=server.status,
            has_credential=bool(server.credential_ciphertext),
            credential_type=server.credential_type or "none",
            tool_count=server.tool_count,
            last_error=server.last_error,
            last_checked_at=server.last_checked_at,
            created_at=server.created_at,
            updated_at=server.updated_at,
        )

    # -- reads -------------------------------------------------------------
    async def list(self) -> list[ServerRegistration]:
        async with self.db.session_factory() as session:
            return list(
                (await session.execute(select(ServerRegistration).order_by(ServerRegistration.server_id)))
                .scalars()
                .all()
            )

    async def get(self, server_id: str) -> ServerRegistration:
        async with self.db.session_factory() as session:
            server = (
                await session.execute(
                    select(ServerRegistration).where(
                        ServerRegistration.server_id == server_id
                    )
                )
            ).scalar_one_or_none()
        if server is None:
            raise NotFoundError("upstream server", server_id)
        return server

    async def enabled(self) -> list[ServerRegistration]:
        async with self.db.session_factory() as session:
            return list(
                (
                    await session.execute(
                        select(ServerRegistration)
                        .where(ServerRegistration.enabled.is_(True))
                        .order_by(ServerRegistration.server_id)
                    )
                )
                .scalars()
                .all()
            )

    # -- writes ------------------------------------------------------------
    async def create(self, payload: ServerCreate) -> ServerRegistration:
        url = await validate_upstream_url(payload.url, self.settings)
        health_url = payload.health_url
        if health_url:
            health_url = await validate_upstream_url(health_url, self.settings)
        ciphertext, header = self._encrypt_credential(
            payload.credential_type, payload.credential, payload.credential_header
        )
        async with self.db.session_factory() as session:
            existing = (
                await session.execute(
                    select(ServerRegistration).where(
                        ServerRegistration.server_id == payload.server_id
                    )
                )
            ).scalar_one_or_none()
            if existing is not None:
                raise ValidationError(f"server id {payload.server_id!r} already exists")
            server = ServerRegistration(
                server_id=payload.server_id,
                name=payload.name,
                description=payload.description,
                transport="streamable-http",
                endpoint=url,
                health_url=health_url,
                enabled=payload.enabled,
                status="unknown",
                credential_type=payload.credential_type,
                credential_ciphertext=ciphertext,
                credential_header=header,
            )
            session.add(server)
            await session.commit()
            await session.refresh(server)
            return server

    async def update(self, server_id: str, payload: ServerUpdate) -> ServerRegistration:
        async with self.db.session_factory() as session:
            server = (
                await session.execute(
                    select(ServerRegistration).where(ServerRegistration.server_id == server_id)
                )
            ).scalar_one_or_none()
            if server is None:
                raise NotFoundError("upstream server", server_id)
            if payload.url is not None:
                server.endpoint = await validate_upstream_url(payload.url, self.settings)
            if payload.health_url is not None:
                server.health_url = (
                    await validate_upstream_url(payload.health_url, self.settings)
                    if payload.health_url
                    else None
                )
            if payload.name is not None:
                server.name = payload.name
            if payload.description is not None:
                server.description = payload.description
            if payload.enabled is not None and payload.enabled != server.enabled:
                server.enabled = payload.enabled
                server.status = "unknown" if payload.enabled else "disabled"
            if payload.clear_credential:
                server.credential_type = "none"
                server.credential_ciphertext = None
                server.credential_header = None
            elif payload.credential_type is not None or payload.credential is not None:
                ciphertext, header = self._encrypt_credential(
                    payload.credential_type or server.credential_type,
                    payload.credential,
                    payload.credential_header,
                )
                server.credential_type = payload.credential_type or server.credential_type
                server.credential_ciphertext = ciphertext
                server.credential_header = header
            await session.commit()
            await session.refresh(server)
            return server

    async def delete(self, server_id: str) -> None:
        async with self.db.session_factory() as session:
            server = (
                await session.execute(
                    select(ServerRegistration).where(ServerRegistration.server_id == server_id)
                )
            ).scalar_one_or_none()
            if server is None:
                raise NotFoundError("upstream server", server_id)
            await session.delete(server)
            await session.commit()

    async def set_enabled(self, server_id: str, enabled: bool) -> ServerRegistration:
        return await self.update(server_id, ServerUpdate(enabled=enabled))

    async def mark_health(
        self,
        server_id: str,
        *,
        status: str,
        tool_count: int | None = None,
        error: str | None = None,
    ) -> None:
        async with self.db.session_factory() as session:
            server = (
                await session.execute(
                    select(ServerRegistration).where(ServerRegistration.server_id == server_id)
                )
            ).scalar_one_or_none()
            if server is None:
                return
            server.status = status
            server.last_checked_at = utcnow()
            server.last_error = error
            if tool_count is not None:
                server.tool_count = tool_count
            await session.commit()

    # -- credentials -------------------------------------------------------
    def _encrypt_credential(
        self, credential_type: str, credential: str | None, header: str | None
    ) -> tuple[str | None, str | None]:
        if credential_type == "none":
            return None, None
        if not credential:
            raise ValidationError("credential is required")
        if credential_type == "header" and not header:
            raise ValidationError("credential_header is required")
        if self._cipher is None:
            raise ConfigurationError(
                "GATEWAY_SECRET_KEY must be configured before storing upstream credentials"
            )
        return self._cipher.encrypt(credential), header

    def auth_headers(self, server: ServerRegistration) -> dict[str, str]:
        if not server.credential_ciphertext or server.credential_type in (None, "none"):
            return {}
        if self._cipher is None:
            raise ConfigurationError("GATEWAY_SECRET_KEY is not configured")
        secret = self._cipher.decrypt(server.credential_ciphertext)
        if server.credential_type == "bearer":
            return {"Authorization": f"Bearer {secret}"}
        if server.credential_type == "header":
            if not server.credential_header:
                raise ConfigurationError("stored header credential has no header name")
            return {server.credential_header: secret}
        raise ConfigurationError("unsupported credential type")

    # -- seeding -----------------------------------------------------------
    async def seed_from_config(self, servers: list[dict[str, Any]]) -> None:
        """Insert configured defaults that are not registered yet (idempotent)."""
        async with self.db.session_factory() as session:
            existing = set(
                (await session.execute(select(ServerRegistration.server_id))).scalars()
            )
        for item in servers:
            server_id = str(item.get("id") or "").strip()
            url = item.get("url")
            if not server_id or not url or server_id in existing:
                continue
            try:
                normalized = await validate_upstream_url(str(url), self.settings)
            except (ValidationError, ValueError):
                continue
            async with self.db.session_factory() as session:
                session.add(
                    ServerRegistration(
                        server_id=server_id,
                        name=str(item.get("name") or server_id),
                        description=item.get("description"),
                        transport="streamable-http",
                        endpoint=normalized,
                        health_url=item.get("health_url"),
                        enabled=bool(item.get("enabled", True)),
                        status="unknown",
                        credential_type="none",
                    )
                )
                await session.commit()
