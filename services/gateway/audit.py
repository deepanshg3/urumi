"""Audit logging for gateway tool calls.

Policy: audit writes are **fail-closed**. If `GATEWAY_AUDIT_ENABLED` is true and
the write fails, the gateway logs the failure to stderr and returns a tool error
rather than claiming success without an audit trail. Upstream mutations may
already have happened in that rare case; the error is explicit about the audit
failure.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import func, select

from services.common.config import GatewaySettings
from services.common.logging import get_logger
from services.gateway.auth import AuthContext
from services.gateway.db import AuditLog, Database, User

logger = get_logger("urumi.gateway.audit")


class AuditWriteError(RuntimeError):
    pass


async def record(
    database: Database,
    settings: GatewaySettings,
    context: AuthContext | None,
    *,
    server_id: str,
    public_tool: str,
    upstream_tool: str | None,
    status: str,
    latency_ms: float | None = None,
    error_code: str | None = None,
    detail: dict[str, Any] | None = None,
) -> None:
    if not settings.audit_enabled:
        return
    entry = AuditLog(
        user_id=context.user_id if context else None,
        api_key_id=context.api_key_id if context else None,
        server_id=server_id or "unknown",
        tool_name=public_tool,
        public_tool_name=public_tool,
        upstream_tool_name=upstream_tool,
        status=status,
        error_code=error_code,
        latency_ms=latency_ms,
        detail_json="{}",
    )
    if detail:
        entry.detail = detail
    try:
        async with database.session_factory() as session:
            session.add(entry)
            await session.commit()
    except Exception as exc:
        logger.error(
            "audit write failed server=%s tool=%s status=%s",
            server_id,
            public_tool,
            status,
        )
        raise AuditWriteError("audit log write failed") from exc


async def query(
    database: Database,
    *,
    page: int,
    per_page: int,
    user_id: int | None = None,
    server_id: str | None = None,
    status: str | None = None,
    tool: str | None = None,
    since: datetime | None = None,
) -> tuple[list[tuple[AuditLog, str | None]], int]:
    filters = []
    if user_id is not None:
        filters.append(AuditLog.user_id == user_id)
    if server_id:
        filters.append(AuditLog.server_id == server_id)
    if status:
        filters.append(AuditLog.status == status)
    if tool:
        filters.append(AuditLog.tool_name == tool)
    if since:
        filters.append(AuditLog.created_at >= since)

    async with database.session_factory() as session:
        total = (
            await session.execute(select(func.count(AuditLog.id)).where(*filters))
        ).scalar_one()
        stmt = (
            select(AuditLog, User.email)
            .outerjoin(User, User.id == AuditLog.user_id)
            .where(*filters)
            .order_by(AuditLog.created_at.desc(), AuditLog.id.desc())
            .offset((page - 1) * per_page)
            .limit(per_page)
        )
        rows = list((await session.execute(stmt)).all())
    return [(row[0], row[1]) for row in rows], total
