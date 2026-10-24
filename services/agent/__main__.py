"""Run the chat agent with uvicorn: ``python -m services.agent``."""

from __future__ import annotations

import uvicorn

from services.agent.app import create_app
from services.common.config import load_settings


def main() -> None:
    settings = load_settings("agent", default_port=8200)
    app = create_app(settings)
    uvicorn.run(
        app,
        host=settings.host,
        port=settings.port,
        log_level=settings.logging.level.lower(),
    )


if __name__ == "__main__":
    main()
