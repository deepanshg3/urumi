"""Unit tests for the shared WooCommerce REST client."""

from __future__ import annotations

import httpx
import pytest

from services.common.errors import (
    AuthenticationError,
    ConfigurationError,
    NotFoundError,
    RateLimitError,
    UpstreamError,
    UpstreamTimeoutError,
)
from tests.conftest import (
    error_response,
    json_response,
    make_client,
    product,
    woocommerce_settings,
)


async def test_list_products_sends_pagination_and_parses_headers() -> None:
    seen: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["params"] = dict(request.url.params)
        seen["auth"] = request.headers.get("authorization", "")
        return json_response(
            [product(1), product(2)],
            headers={"X-WP-Total": "42", "X-WP-TotalPages": "5"},
        )

    client = make_client(handler)
    page = await client.list_products(page=2, per_page=2, search="mug", stock_status="instock")
    await client.aclose()

    assert page.items[0]["id"] == 1
    assert page.total == 42
    assert page.total_pages == 5
    assert page.page == 2 and page.per_page == 2
    assert seen["params"] == {
        "search": "mug",
        "stock_status": "instock",
        "page": "2",
        "per_page": "2",
    }
    assert str(seen["auth"]).startswith("Basic ")


async def test_per_page_is_clamped_to_configured_maximum() -> None:
    seen: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen.update(dict(request.url.params))
        return json_response([])

    client = make_client(handler, max_page_size=25)
    page = await client.list_products(per_page=500)
    await client.aclose()

    assert seen["per_page"] == "25"
    assert page.per_page == 25


async def test_oauth1_mode_signs_requests() -> None:
    seen: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["auth"] = request.headers.get("authorization", "")
        return json_response([])

    client = make_client(
        handler,
        base_url="http://localhost:8080",
        auth_mode="oauth1",
    )
    await client.list_products(per_page=1)
    await client.aclose()

    assert seen["auth"].startswith("OAuth ")
    for part in (
        "oauth_consumer_key=",
        "oauth_nonce=",
        "oauth_signature=",
        "oauth_signature_method=",
        "oauth_timestamp=",
    ):
        assert part in seen["auth"]


async def test_oauth1_signature_uses_signing_base_url() -> None:
    import base64
    import hashlib
    import hmac
    from urllib.parse import quote, unquote

    seen: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["auth"] = request.headers["authorization"]
        seen["params"] = dict(request.url.params)
        return json_response([])

    client = make_client(
        handler,
        base_url="http://host.docker.internal:8080",
        auth_mode="oauth1",
        signing_base_url="http://localhost:8080",
    )
    await client.list_products(per_page=1)
    await client.aclose()

    raw = seen["auth"][len("OAuth ") :]
    oauth = {}
    for item in raw.split(", "):
        key, _, value = item.partition("=")
        oauth[unquote(key)] = unquote(value.strip('"'))
    signature = oauth.pop("oauth_signature")
    all_params = {**seen["params"], **oauth}
    param_string = "&".join(
        f"{quote(k, safe='~')}={quote(v, safe='~')}" for k, v in sorted(all_params.items())
    )
    base_url = "http://localhost:8080/wp-json/wc/v3/products"
    base_string = f"GET&{quote(base_url, safe='~')}&{quote(param_string, safe='~')}"
    expected = base64.b64encode(
        hmac.new(
            f"{client.settings.consumer_secret}&".encode(), base_string.encode(), hashlib.sha1
        ).digest()
    ).decode()
    assert signature == expected


async def test_auto_auth_mode_uses_basic_for_https_and_oauth1_for_http() -> None:
    assert woocommerce_settings(base_url="https://x.test", auth_mode="auto").resolved_auth_mode == "basic"
    assert woocommerce_settings(base_url="http://x.test", auth_mode="auto").resolved_auth_mode == "oauth1"


async def test_authentication_failure_is_reported_without_credentials() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return error_response(401, "woocommerce_rest_authentication_error", "Consumer key is invalid.")

    client = make_client(handler)
    with pytest.raises(AuthenticationError) as exc:
        await client.list_products()
    await client.aclose()

    message = str(exc.value)
    assert "rejected" in message
    assert "ck_test_key" not in message
    assert "cs_test_secret" not in message


async def test_not_found_maps_to_typed_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return error_response(404, "woocommerce_rest_shop_order_invalid_id", "Invalid ID.")

    client = make_client(handler)
    with pytest.raises(NotFoundError) as exc:
        await client.get_order(999)
    await client.aclose()
    assert "order 999" in str(exc.value)


async def test_timeout_is_retried_for_get_then_surfaces_typed_error() -> None:
    calls = {"count": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["count"] += 1
        raise httpx.ReadTimeout("timed out", request=request)

    client = make_client(handler, max_retries=2)
    with pytest.raises(UpstreamTimeoutError):
        await client.list_products()
    await client.aclose()
    assert calls["count"] == 3


async def test_post_is_not_retried() -> None:
    calls = {"count": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["count"] += 1
        return error_response(503, "service_unavailable", "try later")

    client = make_client(handler, max_retries=3)
    with pytest.raises(UpstreamError):
        await client.create_product({"name": "x", "regular_price": "1.00"})
    await client.aclose()
    assert calls["count"] == 1


async def test_get_retries_on_rate_limit_then_succeeds() -> None:
    calls = {"count": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["count"] += 1
        if calls["count"] == 1:
            return error_response(429, "rate_limited", "slow down")
        return json_response([product(1)])

    client = make_client(handler, max_retries=2)
    page = await client.list_products()
    await client.aclose()
    assert calls["count"] == 2
    assert page.items[0]["id"] == 1


async def test_rate_limit_exhaustion_raises_rate_limit_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return error_response(429, "rate_limited", "slow down")

    client = make_client(handler, max_retries=1)
    with pytest.raises(RateLimitError):
        await client.list_products()
    await client.aclose()


async def test_http_500_exhaustion_raises_upstream_error_with_status() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return error_response(500, "internal_error", "kaboom")

    client = make_client(handler, max_retries=1)
    with pytest.raises(UpstreamError) as exc:
        await client.list_products()
    await client.aclose()
    assert exc.value.status_code == 500
    assert exc.value.upstream_code == "internal_error"
    assert "kaboom" in str(exc.value)


async def test_missing_credentials_fail_before_any_request() -> None:
    calls = {"count": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["count"] += 1
        return json_response([])

    client = make_client(handler, consumer_key="", consumer_secret="")
    with pytest.raises(ConfigurationError):
        await client.list_products()
    await client.aclose()
    assert calls["count"] == 0


async def test_non_json_response_is_rejected() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"<html>oops</html>")

    client = make_client(handler)
    with pytest.raises(UpstreamError):
        await client.list_products()
    await client.aclose()


async def test_paginate_stops_at_total_pages() -> None:
    pages_requested: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        page = request.url.params["page"]
        pages_requested.append(page)
        return json_response(
            [product(int(page))],
            headers={"X-WP-Total": "3", "X-WP-TotalPages": "3"},
        )

    client = make_client(handler)
    seen_pages = []
    async for page in client.paginate("/products", per_page=1):
        seen_pages.append(page.page)
    await client.aclose()

    assert seen_pages == [1, 2, 3]
    assert pages_requested == ["1", "2", "3"]


async def test_paginate_honours_max_pages() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return json_response([product(1)], headers={"X-WP-Total": "100", "X-WP-TotalPages": "100"})

    client = make_client(handler)
    count = 0
    async for _ in client.paginate("/products", per_page=1, max_pages=2):
        count += 1
    await client.aclose()
    assert count == 2


async def test_paginate_stops_on_short_page_without_headers() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        page = int(request.url.params["page"])
        return json_response([product(1)] if page == 1 else [])

    client = make_client(handler)
    count = 0
    async for _ in client.paginate("/products", per_page=2):
        count += 1
    await client.aclose()
    assert count == 1
