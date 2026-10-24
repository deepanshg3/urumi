"""Structured error types shared by the MCP services.

Tool handlers raise `WooCommerceError` subclasses; the MCP layer converts them
into clear tool errors. Messages are safe to return to an AI client: they never
contain credentials, request headers, or customer PII.
"""

from __future__ import annotations

from typing import Any


class ServiceError(Exception):
    """Base class for expected, user-facing service failures."""

    code = "service_error"

    def __init__(self, message: str, *, details: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.details = details or {}

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {"error": self.code, "message": self.message}
        if self.details:
            payload["details"] = self.details
        return payload


class WooCommerceError(ServiceError):
    """Base class for expected, user-facing WooCommerce failures."""

    code = "woocommerce_error"


class ConfigurationError(WooCommerceError):
    code = "configuration_error"


class ValidationError(WooCommerceError):
    code = "validation_error"


class AuthenticationError(WooCommerceError):
    """Upstream rejected the configured credentials (HTTP 401/403)."""

    code = "authentication_error"


class NotFoundError(WooCommerceError):
    code = "not_found"

    def __init__(self, resource: str, identifier: Any) -> None:
        super().__init__(
            f"{resource} {identifier!r} was not found",
            details={"resource": resource, "identifier": identifier},
        )


class ConflictError(WooCommerceError):
    code = "conflict"


class RateLimitError(WooCommerceError):
    code = "rate_limited"


class UpstreamError(WooCommerceError):
    """Upstream returned an unexpected HTTP error or an invalid payload."""

    code = "upstream_error"

    def __init__(
        self,
        message: str,
        *,
        status_code: int | None = None,
        upstream_code: str | None = None,
    ) -> None:
        details: dict[str, Any] = {}
        if status_code is not None:
            details["status_code"] = status_code
        if upstream_code:
            details["upstream_code"] = upstream_code
        super().__init__(message, details=details)
        self.status_code = status_code
        self.upstream_code = upstream_code


class UpstreamTimeoutError(UpstreamError):
    code = "upstream_timeout"
