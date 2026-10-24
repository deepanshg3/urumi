"""Entry point: `python -m services.gateway`."""

from __future__ import annotations

import uvicorn

from services.common.config import load_settings
from services.gateway.app import create_app


def main() -> None:
    settings = load_settings("gateway", default_port=8000)
    app = create_app(settings)
    uvicorn.run(
        app,
        host=settings.host,
        port=settings.port,
        log_level=settings.logging.level.lower(),
    )


if __name__ == "__main__":
    main()
