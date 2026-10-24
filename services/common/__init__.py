"""Shared, deliberately small building blocks for the Urumi MCP services.

This package contains only cross-service infrastructure: settings loading,
structured errors, redacting logging and a WooCommerce REST client. It must not
contain tool definitions or service-specific business logic.
"""

from services.common.config import (
    AppSettings,
    InventorySettings,
    LoggingSettings,
    WooCommerceSettings,
    load_app_config,
    load_settings,
)
from services.common.errors import (
    AuthenticationError,
    ConfigurationError,
    NotFoundError,
    UpstreamError,
    UpstreamTimeoutError,
    ValidationError,
    WooCommerceError,
)
from services.common.logging import configure_logging, get_logger, redact

__all__ = [
    "AppSettings",
    "AuthenticationError",
    "ConfigurationError",
    "InventorySettings",
    "LoggingSettings",
    "NotFoundError",
    "UpstreamError",
    "UpstreamTimeoutError",
    "ValidationError",
    "WooCommerceError",
    "WooCommerceSettings",
    "configure_logging",
    "get_logger",
    "load_app_config",
    "load_settings",
    "redact",
]
