"""Assessment demo mode: fixed personas backed by real, persisted users.

This is an explicit, opt-in test deployment feature. It never lets the browser
choose a role: the requested *persona* is looked up in a hard-coded allowlist
and mapped to a dedicated user whose role is persisted in the database, so the
existing REST and MCP authorization still decides what the session may do.
"""

from __future__ import annotations

import secrets
from dataclasses import dataclass
from ipaddress import ip_address
from urllib.parse import urlsplit

from sqlalchemy import select

from services.common.config import GatewaySettings
from services.common.logging import get_logger
from services.gateway.db import Database, Role, User, create_default_roles
from services.gateway.security import hash_password

logger = get_logger("urumi.gateway.demo")

LOCAL_HOSTNAMES = {"localhost", "127.0.0.1", "::1"}


@dataclass(frozen=True)
class DemoPersona:
    """One fixed assessment identity. The role name is not client-supplied."""

    id: str
    role: str
    email: str
    display_name: str
    title: str
    summary: str
    capabilities: tuple[str, ...]


DEMO_PERSONAS: dict[str, DemoPersona] = {
    "admin": DemoPersona(
        id="admin",
        role="admin",
        email="demo-admin@urumi.demo",
        display_name="Demo Administrator",
        title="Admin",
        summary="Full gateway administration and every permitted MCP tool.",
        capabilities=(
            "All 14 MCP tools, including product, order and shipment changes",
            "Manage users, roles, servers and API keys",
            "Read the complete audit log",
        ),
    ),
    "operator": DemoPersona(
        id="operator",
        role="member",
        email="demo-operator@urumi.demo",
        display_name="Demo Operator",
        title="Operator",
        summary="Store reads plus the shipment operations the policy allows.",
        capabilities=(
            "Read products, orders, stock and shipments",
            "Update a shipment's status",
            "No product/order changes, no shipment creation, no gateway admin",
        ),
    ),
    "viewer": DemoPersona(
        id="viewer",
        role="viewer",
        email="demo-viewer@urumi.demo",
        display_name="Demo Viewer",
        title="Viewer",
        summary="Read-only observer of the store and its operations.",
        capabilities=(
            "Read products, orders, stock and shipments",
            "See its own audit trail",
            "No mutations and no API-key management",
        ),
    ),
}

PERSONA_IDS = tuple(DEMO_PERSONAS)


def get_persona(persona_id: str) -> DemoPersona | None:
    return DEMO_PERSONAS.get(persona_id)


def persona_catalog() -> list[dict[str, object]]:
    return [
        {
            "id": persona.id,
            "role": persona.role,
            "email": persona.email,
            "display_name": persona.display_name,
            "title": persona.title,
            "summary": persona.summary,
            "capabilities": list(persona.capabilities),
        }
        for persona in DEMO_PERSONAS.values()
    ]


def _is_loopback(host: str | None) -> bool:
    if not host:
        return False
    try:
        address = ip_address(host)
    except ValueError:
        return False
    if address.is_loopback:
        return True
    mapped = getattr(address, "ipv4_mapped", None)
    return bool(mapped and mapped.is_loopback)


def _hostname(host_header: str | None) -> str:
    if not host_header:
        return ""
    try:
        return (urlsplit(f"//{host_header}").hostname or "").lower()
    except ValueError:
        return ""


def demo_request_allowed(
    settings: GatewaySettings,
    *,
    client_host: str | None,
    host_header: str | None,
    origin: str | None,
) -> bool:
    """Whether a demo switch may be served to this request.

    Demo mode is for local/test deployments. Unless remote access is explicitly
    enabled, the request must come from a loopback client or use a loopback
    Host header (which is what the Compose and Kind dashboards do). If the
    browser sends an Origin, it must be allowlisted as well.
    """
    if not settings.demo_mode:
        return False
    if origin:
        allowed = {item.rstrip("/") for item in settings.demo_origin_list}
        # Same-origin requests (dashboard served behind the same host, e.g.
        # the single-container Render deploy) are always acceptable.
        same_origin = bool(host_header) and (
            urlsplit(origin).netloc.lower() == host_header.strip().lower()
        )
        if origin.rstrip("/") not in allowed and not same_origin:
            return False
    if settings.demo_allow_remote:
        return True
    if _is_loopback(client_host):
        return True
    return _hostname(host_header) in LOCAL_HOSTNAMES


async def ensure_demo_users(database: Database) -> dict[str, User]:
    """Create (or repair) the three dedicated demo accounts.

    The accounts are normal persisted users with normal role assignments, so
    every existing authorization check applies. They get a random, never-used
    password; demo signs in through the session endpoint, not credentials.
    """
    created = 0
    repaired = 0
    users: dict[str, User] = {}
    async with database.session_factory() as session:
        await create_default_roles(session)
        roles = {
            role.name: role
            for role in (await session.execute(select(Role))).scalars().all()
        }
        for persona in DEMO_PERSONAS.values():
            role = roles.get(persona.role)
            if role is None:  # pragma: no cover - create_default_roles guarantees it
                raise RuntimeError(f"role {persona.role!r} is missing")
            user = (
                await session.execute(select(User).where(User.email == persona.email))
            ).scalar_one_or_none()
            if user is None:
                user = User(
                    email=persona.email,
                    display_name=persona.display_name,
                    password_hash=hash_password(secrets.token_urlsafe(32)),
                    roles=[role],
                )
                session.add(user)
                created += 1
            else:
                wanted = [role]
                if (
                    sorted(item.name for item in user.roles) != [persona.role]
                    or user.display_name != persona.display_name
                    or not user.is_active
                ):
                    user.roles = wanted
                    user.display_name = persona.display_name
                    user.is_active = True
                    repaired += 1
            users[persona.id] = user
        if created or repaired:
            await session.commit()
            logger.info(
                "assessment demo accounts ready created=%s repaired=%s", created, repaired
            )
        for user in users.values():
            await session.refresh(user)
            # Force the role relationship to load before the session closes.
            _ = [item.name for item in user.roles]
    return users
