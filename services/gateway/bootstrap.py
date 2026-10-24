"""One-time administrator bootstrap CLI.

Usage:
    BOOTSTRAP_ADMIN_EMAIL=admin@example.com \
    BOOTSTRAP_ADMIN_PASSWORD='a-long-password' \
    .venv/bin/python -m services.gateway.bootstrap

The password is never echoed. Re-running is idempotent and will not reset an
existing account.
"""

from __future__ import annotations

import asyncio

from services.common.config import load_settings
from services.common.logging import configure_logging
from services.gateway.auth import bootstrap_admin
from services.gateway.db import Database, ensure_schema


async def _run() -> None:
    settings = load_settings("gateway", default_port=8000)
    configure_logging(settings.logging.level, service="gateway-bootstrap")
    database = Database()
    try:
        await ensure_schema(database)
        user = await bootstrap_admin(
            database,
            settings.gateway.bootstrap_admin_email,
            settings.gateway.bootstrap_admin_password,
        )
        if user is None:
            print(
                "No BOOTSTRAP_ADMIN_EMAIL / BOOTSTRAP_ADMIN_PASSWORD set; nothing to do."
            )
        else:
            print(f"Administrator ready: {user.email}")
    finally:
        await database.dispose()


if __name__ == "__main__":
    asyncio.run(_run())
