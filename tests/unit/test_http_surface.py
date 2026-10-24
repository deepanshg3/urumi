"""HTTP surface tests: health endpoints and readiness failure behavior."""

from __future__ import annotations

import httpx

from services.common.config import WooCommerceSettings
from services.inventory_mcp.server import create_app as create_inventory_app
from services.inventory_mcp.server import build_tools as build_inventory_tools
from services.woocommerce_mcp.server import build_tools as build_woo_tools
from services.woocommerce_mcp.server import create_app as create_woo_app
from tests.conftest import app_settings, error_response, json_response, make_client


async def test_woocommerce_health_endpoint() -> None:
    settings = app_settings(service_name="woocommerce-mcp")
    tools = build_woo_tools(settings, make_client(lambda r: json_response([])))
    app = create_woo_app(settings, tools)

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.get("/health")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["transport"] == "streamable-http"
    assert body["mcp_path"] == "/mcp"


async def test_woocommerce_readiness_reports_auth_failure_without_secrets() -> None:
    settings = app_settings(service_name="woocommerce-mcp")
    tools = build_woo_tools(
        settings,
        make_client(
            lambda r: error_response(401, "woocommerce_rest_authentication_error", "nope")
        ),
    )
    app = create_woo_app(settings, tools)

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.get("/health/ready")

    assert response.status_code == 503
    body = response.json()
    assert body["status"] == "not_ready"
    assert body["error"] == "authentication_error"
    assert "ck_test_key" not in response.text
    assert "cs_test_secret" not in response.text


async def test_woocommerce_readiness_fails_without_credentials() -> None:
    settings = app_settings(
        service_name="woocommerce-mcp",
        woocommerce=WooCommerceSettings(
            base_url="https://store.test", consumer_key="", consumer_secret=""
        ),
    )
    tools = build_woo_tools(settings, make_client(lambda r: json_response([])))
    app = create_woo_app(settings, tools)

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.get("/health/ready")

    assert response.status_code == 503
    assert response.json()["error"] == "configuration_error"


async def test_inventory_health_and_readiness() -> None:
    settings = app_settings(service_name="inventory-mcp")
    tools = build_inventory_tools(settings, make_client(lambda r: json_response([])))
    app = create_inventory_app(settings, tools)

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        health = await client.get("/health")
        ready = await client.get("/health/ready")

    assert health.status_code == 200
    assert health.json()["service"] == "inventory-mcp"
    assert ready.status_code == 200
    assert ready.json()["status"] == "ready"
    assert ready.json()["low_stock_threshold"] == 5


async def test_mcp_endpoint_rejects_disallowed_host_header() -> None:
    settings = app_settings(service_name="woocommerce-mcp")
    tools = build_woo_tools(settings, make_client(lambda r: json_response([])))
    app = create_woo_app(settings, tools)

    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://evil.example"
        ) as client:
            response = await client.post("/mcp", json={})

    assert response.status_code == 421


async def test_mcp_endpoint_rejects_missing_session_for_streamable_http() -> None:
    settings = app_settings(
        service_name="woocommerce-mcp", allowed_hosts="test,test:*", allowed_origins="http://test"
    )
    tools = build_woo_tools(settings, make_client(lambda r: json_response([])))
    app = create_woo_app(settings, tools)

    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.post("/mcp", json={})

    # Without an MCP initialize handshake the transport rejects the request;
    # the exact code depends on the SDK but it must not be a 500.
    assert response.status_code in {400, 406, 415, 422}
