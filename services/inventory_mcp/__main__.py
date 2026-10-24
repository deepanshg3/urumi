"""Entry point: `python -m services.inventory_mcp`."""

from __future__ import annotations

import uvicorn

from services.common.config import load_settings
from services.inventory_mcp.server import create_app


def main() -> None:
    settings = load_settings("inventory-mcp", default_port=8102)
    app = create_app(settings)
    uvicorn.run(
        app,
        host=settings.host,
        port=settings.port,
        log_level=settings.logging.level.lower(),
    )


if __name__ == "__main__":
    main()
