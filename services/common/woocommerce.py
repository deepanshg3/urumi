"""Async WooCommerce REST API client shared by the MCP services.

Design notes:
* Only GET requests are retried, and only for rate limits / transient upstream
  errors. POST/PUT are never retried automatically, so a product or status
  update cannot be executed twice.
* Credentials are sent in headers (Basic) or an OAuth 1.0a Authorization header
  and are never logged or included in error messages.
* Every response is validated before being returned to a tool handler.
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
import secrets
import time
from collections.abc import AsyncIterator, Mapping
from dataclasses import dataclass
from typing import Any
from urllib.parse import quote, urlsplit

import httpx

from services.common.config import WooCommerceSettings
from services.common.errors import (
    AuthenticationError,
    ConfigurationError,
    NotFoundError,
    RateLimitError,
    UpstreamError,
    UpstreamTimeoutError,
    ValidationError,
    WooCommerceError,
)
from services.common.logging import get_logger

logger = get_logger("urumi.woocommerce")

API_ROOT = "/wp-json/wc/v3"
RETRYABLE_STATUS = {429, 500, 502, 503, 504}


def _rfc3986(value: Any) -> str:
    return quote(str(value), safe="~-._")


@dataclass(frozen=True)
class Page:
    """One page of a WooCommerce collection response."""

    items: list[dict[str, Any]]
    total: int | None
    total_pages: int | None
    page: int
    per_page: int


class WooCommerceClient:
    """Thin, typed wrapper over the WooCommerce REST API."""

    def __init__(
        self,
        settings: WooCommerceSettings,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self.settings = settings
        self._owns_client = client is None
        self._client = client or httpx.AsyncClient(
            base_url=settings.base_url,
            timeout=httpx.Timeout(settings.timeout_seconds),
            transport=transport,
            headers={"Accept": "application/json", "User-Agent": "urumi-mcp/0.1"},
        )

    # -- lifecycle ---------------------------------------------------------
    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    async def __aenter__(self) -> "WooCommerceClient":
        return self

    async def __aexit__(self, *exc_info: Any) -> None:
        await self.aclose()

    # -- auth --------------------------------------------------------------
    def _auth_headers(
        self, method: str, url: str, params: Mapping[str, Any]
    ) -> dict[str, str]:
        mode = self.settings.resolved_auth_mode
        if mode == "basic":
            token = base64.b64encode(
                f"{self.settings.consumer_key}:{self.settings.consumer_secret}".encode()
            ).decode()
            return {"Authorization": f"Basic {token}"}
        return {"Authorization": self._oauth1_header(method, url, params)}

    def _oauth1_header(
        self, method: str, url: str, params: Mapping[str, Any]
    ) -> str:
        oauth: dict[str, str] = {
            "oauth_consumer_key": self.settings.consumer_key,
            "oauth_nonce": secrets.token_hex(16),
            "oauth_signature_method": "HMAC-SHA1",
            "oauth_timestamp": str(int(time.time())),
            "oauth_version": "1.0",
        }
        parsed = urlsplit(url)
        if self.settings.signing_base_url:
            signing = urlsplit(self.settings.signing_base_url)
            base_url = f"{signing.scheme}://{signing.netloc}{signing.path}{parsed.path}"
        else:
            base_url = f"{parsed.scheme}://{parsed.netloc}{parsed.path}"
        all_params = {**{k: str(v) for k, v in params.items()}, **oauth}
        param_string = "&".join(
            f"{_rfc3986(k)}={_rfc3986(v)}" for k, v in sorted(all_params.items())
        )
        base_string = f"{method.upper()}&{_rfc3986(base_url)}&{_rfc3986(param_string)}"
        digest = hmac.new(
            f"{self.settings.consumer_secret}&".encode(),
            base_string.encode(),
            hashlib.sha1,
        ).digest()
        oauth["oauth_signature"] = base64.b64encode(digest).decode()
        return "OAuth " + ", ".join(
            f'{_rfc3986(k)}="{_rfc3986(v)}"' for k, v in sorted(oauth.items())
        )

    # -- request core ------------------------------------------------------
    async def _request(
        self,
        method: str,
        path: str,
        *,
        params: Mapping[str, Any] | None = None,
        json: Mapping[str, Any] | None = None,
        idempotent: bool | None = None,
    ) -> tuple[Any, httpx.Headers]:
        if not self.settings.consumer_key or not self.settings.consumer_secret:
            raise ConfigurationError(
                "WooCommerce credentials are not configured; set "
                "WOOCOMMERCE_CONSUMER_KEY and WOOCOMMERCE_CONSUMER_SECRET"
            )

        clean_params = {
            k: v for k, v in (params or {}).items() if v is not None
        }
        url = f"{self.settings.base_url}{API_ROOT}{path}"
        headers = self._auth_headers(method, url, clean_params)

        allow_retry = method.upper() == "GET" if idempotent is None else idempotent
        attempts = (self.settings.max_retries + 1) if allow_retry else 1
        last_error: Exception | None = None

        for attempt in range(attempts):
            try:
                response = await self._client.request(
                    method,
                    url,
                    params=clean_params or None,
                    json=json,
                    headers=headers,
                )
            except httpx.TimeoutException as exc:
                last_error = UpstreamTimeoutError(
                    f"WooCommerce request timed out after "
                    f"{self.settings.timeout_seconds:g}s"
                )
                if attempt + 1 < attempts:
                    await self._sleep(attempt, None)
                    continue
                raise last_error from exc
            except httpx.HTTPError as exc:
                last_error = UpstreamError(
                    "could not reach the WooCommerce store "
                    f"({type(exc).__name__})"
                )
                if attempt + 1 < attempts:
                    await self._sleep(attempt, None)
                    continue
                raise last_error from exc

            if response.status_code in RETRYABLE_STATUS and attempt + 1 < attempts:
                await self._sleep(attempt, response.headers.get("Retry-After"))
                continue
            return self._parse(response), response.headers

        assert last_error is not None
        raise last_error

    async def _sleep(self, attempt: int, retry_after: str | None) -> None:
        delay = self.settings.retry_backoff_seconds * (2**attempt)
        if retry_after:
            try:
                delay = max(delay, min(float(retry_after), 5.0))
            except ValueError:
                pass
        await asyncio.sleep(delay)

    def _parse(self, response: httpx.Response) -> Any:
        if response.status_code in {401, 403}:
            raise AuthenticationError(
                "WooCommerce rejected the configured API credentials "
                f"(HTTP {response.status_code})"
            )
        if response.status_code == 404:
            raise NotFoundError("WooCommerce resource", "requested identifier")
        if response.status_code == 429:
            raise RateLimitError("WooCommerce rate limit exceeded; retry later")
        if response.status_code >= 400:
            message, code = self._error_message(response)
            raise UpstreamError(
                f"WooCommerce returned HTTP {response.status_code}: {message}",
                status_code=response.status_code,
                upstream_code=code,
            )
        try:
            return response.json()
        except ValueError as exc:
            raise UpstreamError(
                "WooCommerce returned a non-JSON response",
                status_code=response.status_code,
            ) from exc

    @staticmethod
    def _error_message(response: httpx.Response) -> tuple[str, str | None]:
        try:
            payload = response.json()
        except ValueError:
            return "unexpected response", None
        if not isinstance(payload, dict):
            return "unexpected response", None
        message = str(payload.get("message") or "unexpected response")
        code = payload.get("code")
        return message[:300], str(code) if code else None

    # -- pagination --------------------------------------------------------
    def _page_size(self, per_page: int | None) -> int:
        size = per_page or self.settings.default_page_size
        if size < 1:
            raise ValidationError("per_page must be at least 1")
        return min(size, self.settings.max_page_size)

    async def _list(
        self, path: str, params: Mapping[str, Any], *, per_page: int | None, page: int
    ) -> Page:
        if page < 1:
            raise ValidationError("page must be at least 1")
        size = self._page_size(per_page)
        data, headers = await self._request(
            "GET", path, params={**params, "page": page, "per_page": size}
        )
        if not isinstance(data, list):
            raise UpstreamError("WooCommerce returned an unexpected collection payload")
        return Page(
            items=[item for item in data if isinstance(item, dict)],
            total=_int_header(headers.get("X-WP-Total")),
            total_pages=_int_header(headers.get("X-WP-TotalPages")),
            page=page,
            per_page=size,
        )

    async def paginate(
        self,
        path: str,
        *,
        params: Mapping[str, Any] | None = None,
        per_page: int | None = None,
        start_page: int = 1,
        max_pages: int | None = None,
    ) -> AsyncIterator[Page]:
        """Yield pages until the last page, optionally capped by `max_pages`."""
        page_number = start_page
        pages_seen = 0
        while True:
            page = await self._list(
                path, params or {}, per_page=per_page, page=page_number
            )
            yield page
            pages_seen += 1
            if max_pages is not None and pages_seen >= max_pages:
                return
            total_pages = page.total_pages
            if total_pages is not None:
                if page_number >= total_pages:
                    return
            elif len(page.items) < page.per_page:
                return
            page_number += 1

    # -- products ----------------------------------------------------------
    async def list_products(
        self,
        *,
        page: int = 1,
        per_page: int | None = None,
        search: str | None = None,
        stock_status: str | None = None,
        sku: str | None = None,
        status: str | None = None,
    ) -> Page:
        params: dict[str, Any] = {}
        if search:
            params["search"] = search
        if stock_status:
            params["stock_status"] = stock_status
        if sku:
            params["sku"] = sku
        if status:
            params["status"] = status
        return await self._list("/products", params, per_page=per_page, page=page)

    async def get_product(self, product_id: int) -> dict[str, Any]:
        try:
            data, _ = await self._request("GET", f"/products/{product_id}")
        except NotFoundError as exc:
            raise NotFoundError("product", product_id) from exc
        if not isinstance(data, dict):
            raise UpstreamError("WooCommerce returned an unexpected product payload")
        return data

    async def find_product_by_sku(self, sku: str) -> dict[str, Any] | None:
        page = await self.list_products(sku=sku, per_page=1)
        return page.items[0] if page.items else None

    async def create_product(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        data, _ = await self._request("POST", "/products", json=payload)
        if not isinstance(data, dict) or "id" not in data:
            raise UpstreamError("WooCommerce returned an unexpected product payload")
        return data

    async def update_product(
        self, product_id: int, payload: Mapping[str, Any]
    ) -> dict[str, Any]:
        data, _ = await self._request("PUT", f"/products/{product_id}", json=payload)
        if not isinstance(data, dict) or "id" not in data:
            raise UpstreamError("WooCommerce returned an unexpected product payload")
        return data

    # -- orders ------------------------------------------------------------
    async def list_orders(
        self,
        *,
        page: int = 1,
        per_page: int | None = None,
        status: str | None = None,
        after: str | None = None,
        before: str | None = None,
    ) -> Page:
        params: dict[str, Any] = {}
        if status:
            params["status"] = status
        if after:
            params["after"] = after
        if before:
            params["before"] = before
        return await self._list("/orders", params, per_page=per_page, page=page)

    async def get_order(self, order_id: int) -> dict[str, Any]:
        try:
            data, _ = await self._request("GET", f"/orders/{order_id}")
        except NotFoundError as exc:
            raise NotFoundError("order", order_id) from exc
        if not isinstance(data, dict):
            raise UpstreamError("WooCommerce returned an unexpected order payload")
        return data

    async def update_order_status(
        self, order_id: int, status: str
    ) -> dict[str, Any]:
        try:
            data, _ = await self._request(
                "PUT", f"/orders/{order_id}", json={"status": status}
            )
        except NotFoundError as exc:
            raise NotFoundError("order", order_id) from exc
        if not isinstance(data, dict) or "id" not in data:
            raise UpstreamError("WooCommerce returned an unexpected order payload")
        return data


def _int_header(value: str | None) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except ValueError:
        return None
