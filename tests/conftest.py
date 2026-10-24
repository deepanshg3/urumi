"""Shared test fixtures for the MCP service unit tests."""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

import httpx
import pytest

from services.common.config import (
    AppSettings,
    GatewaySettings,
    InventorySettings,
    WooCommerceSettings,
)
from services.common.woocommerce import WooCommerceClient

Handler = Callable[[httpx.Request], httpx.Response]


def woocommerce_settings(**overrides: Any) -> WooCommerceSettings:
    base: dict[str, Any] = {
        "base_url": "https://store.example.test",
        "consumer_key": "ck_test_key",
        "consumer_secret": "cs_test_secret",
        "auth_mode": "basic",
        "timeout_seconds": 5.0,
        "default_page_size": 10,
        "max_page_size": 100,
        "max_retries": 2,
        "retry_backoff_seconds": 0.0,
    }
    base.update(overrides)
    return WooCommerceSettings(**base)


def app_settings(**overrides: Any) -> AppSettings:
    woocommerce = overrides.pop("woocommerce", None) or woocommerce_settings()
    inventory = overrides.pop("inventory", None) or InventorySettings(
        low_stock_threshold=5, summary_max_products=100, summary_scan_page_size=100
    )
    return AppSettings(
        service_name=overrides.pop("service_name", "test-mcp"),
        woocommerce=woocommerce,
        inventory=inventory,
        **overrides,
    )


def make_client(handler: Handler, **settings_overrides: Any) -> WooCommerceClient:
    transport = httpx.MockTransport(handler)
    return WooCommerceClient(
        woocommerce_settings(**settings_overrides), transport=transport
    )


def json_response(
    payload: Any,
    status_code: int = 200,
    headers: dict[str, str] | None = None,
) -> httpx.Response:
    return httpx.Response(
        status_code,
        content=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json", **(headers or {})},
    )


def error_response(
    status_code: int, code: str = "woocommerce_error", message: str = "boom"
) -> httpx.Response:
    return json_response({"code": code, "message": message, "data": {"status": status_code}}, status_code)


def product(
    product_id: int,
    *,
    name: str | None = None,
    sku: str | None = None,
    stock_quantity: int | None = 10,
    stock_status: str = "instock",
    manage_stock: bool = True,
    price: str = "10.00",
    status: str = "publish",
) -> dict[str, Any]:
    return {
        "id": product_id,
        "name": name or f"Product {product_id}",
        "sku": sku or f"SKU-{product_id}",
        "type": "simple",
        "status": status,
        "price": price,
        "regular_price": price,
        "stock_status": stock_status,
        "stock_quantity": stock_quantity,
        "manage_stock": manage_stock,
        "backorders": "no",
        "permalink": f"https://store.example.test/product/{product_id}",
    }


def order(
    order_id: int,
    *,
    status: str = "pending",
    date_created_gmt: str = "2026-01-15T10:00:00",
    customer_email: str = "customer@example.test",
) -> dict[str, Any]:
    return {
        "id": order_id,
        "number": str(order_id),
        "status": status,
        "currency": "USD",
        "total": "24.00",
        "date_created": date_created_gmt,
        "date_created_gmt": date_created_gmt,
        "date_modified_gmt": date_created_gmt,
        "customer_id": 7,
        "billing": {
            "first_name": "Test",
            "last_name": "Customer",
            "email": customer_email,
            "phone": "555-0100",
            "address_1": "1 Secret Street",
            "city": "Testville",
        },
        "payment_method_title": "Cash on delivery",
        "customer_note": "Leave at the door",
        "line_items": [
            {
                "id": 1,
                "product_id": 10,
                "variation_id": 0,
                "name": "Product 10",
                "quantity": 2,
                "sku": "SKU-10",
            }
        ],
    }


def gateway_settings(**overrides: Any) -> GatewaySettings:
    base: dict[str, Any] = {
        "host": "127.0.0.1",
        "port": 8000,
        "audit_enabled": True,
        "secret_key": "unit-test-gateway-secret-key",
        "refresh_interval_seconds": 0,
        "allowed_hosts": "testserver,127.0.0.1",
        "allowed_origins": "http://testserver",
        "discovery_timeout_seconds": 2.0,
        "upstream_timeout_seconds": 2.0,
    }
    base.update(overrides)
    return GatewaySettings(**base)


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"