"""Integration tests against a real local WooCommerce store.

These are skipped unless `URUMI_RUN_INTEGRATION=1` and the root `.env` (or
environment) contains valid WooCommerce credentials. They create and clean up
their own products/orders and never touch seed data destructively.

Run:
    ./scripts/store_setup.sh
    URUMI_RUN_INTEGRATION=1 .venv/bin/pytest tests/integration -v
"""

from __future__ import annotations

import os
import uuid
from collections.abc import AsyncIterator

import httpx
import pytest

from services.common.config import WooCommerceSettings, load_settings
from services.common.errors import NotFoundError
from services.common.woocommerce import WooCommerceClient
from services.inventory_mcp.models import (
    CheckStockInput,
    FindLowStockInput,
    InventorySummaryInput,
    ReorderInput,
)
from services.inventory_mcp.tools import InventoryTools
from services.woocommerce_mcp.models import (
    CreateProductInput,
    GetOrderInput,
    ListOrdersInput,
    ListProductsInput,
    UpdateOrderStatusInput,
)
from services.woocommerce_mcp.tools import WooCommerceTools

pytestmark = pytest.mark.integration

RUN = os.environ.get("URUMI_RUN_INTEGRATION") == "1"


def _settings() -> WooCommerceSettings:
    return load_settings("woocommerce-mcp", default_port=8101).woocommerce


@pytest.fixture(scope="module")
def live_settings() -> WooCommerceSettings:
    if not RUN:
        pytest.skip("set URUMI_RUN_INTEGRATION=1 to run integration tests")
    settings = _settings()
    if not settings.consumer_key or not settings.consumer_secret:
        pytest.skip("WooCommerce credentials are not configured (run scripts/store_setup.sh)")
    return settings


@pytest.fixture
async def client(live_settings: WooCommerceSettings) -> AsyncIterator[WooCommerceClient]:
    async with WooCommerceClient(live_settings) as live_client:
        yield live_client


@pytest.fixture
async def woo_tools(client: WooCommerceClient) -> WooCommerceTools:
    return WooCommerceTools(client)


@pytest.fixture
async def inventory_tools(client: WooCommerceClient) -> InventoryTools:
    return InventoryTools(client, load_settings("inventory-mcp", default_port=8102).inventory)


@pytest.fixture
async def temp_product(client: WooCommerceClient) -> AsyncIterator[dict]:
    sku = f"URUMI-IT-{uuid.uuid4().hex[:10].upper()}"
    product = await client.create_product(
        {
            "name": "Integration Test Product",
            "sku": sku,
            "regular_price": "4.25",
            "manage_stock": True,
            "stock_quantity": 12,
            "stock_status": "instock",
        }
    )
    try:
        yield product
    finally:
        await client._request("DELETE", f"/products/{product['id']}", params={"force": "true"})


async def test_store_reachable_and_authentication_works(client: WooCommerceClient) -> None:
    page = await client.list_products(per_page=1)
    assert page.per_page == 1


async def test_list_products_and_filters(woo_tools: WooCommerceTools) -> None:
    result = await woo_tools.list_products(ListProductsInput(per_page=5))
    assert result.page == 1
    assert result.per_page == 5
    assert result.total is None or result.total >= len(result.items)

    search = await woo_tools.list_products(ListProductsInput(search="Urumi", per_page=5))
    assert all("urumi" in item.name.lower() or item.sku for item in search.items)


async def test_create_product_and_duplicate_sku(woo_tools: WooCommerceTools) -> None:
    sku = f"URUMI-IT-{uuid.uuid4().hex[:10].upper()}"
    created = await woo_tools.create_product(
        CreateProductInput(name="Integration Mug", price="9.99", sku=sku, stock_quantity=4)
    )
    try:
        assert created.created is True
        assert created.stock_quantity == 4

        from services.common.errors import ConflictError

        with pytest.raises(ConflictError):
            await woo_tools.create_product(
                CreateProductInput(name="Duplicate", price="1.00", sku=sku)
            )

        existing = await woo_tools.create_product(
            CreateProductInput(
                name="Duplicate", price="1.00", sku=sku, if_sku_exists="return_existing"
            )
        )
        assert existing.id == created.id
        assert existing.created is False
    finally:
        await woo_tools.client._request(
            "DELETE", f"/products/{created.id}", params={"force": "true"}
        )


async def test_list_and_get_orders(woo_tools: WooCommerceTools) -> None:
    orders = await woo_tools.list_orders(ListOrdersInput(per_page=5))
    if not orders.items:
        pytest.skip("no orders in the local store; run scripts/store_setup.sh to seed one")
    first = orders.items[0]
    detail = await woo_tools.get_order(GetOrderInput(order_id=first.id))
    assert detail.id == first.id
    assert detail.line_items


async def test_list_orders_date_bounds(woo_tools: WooCommerceTools) -> None:
    from datetime import datetime, timedelta, timezone

    after = datetime.now(timezone.utc) - timedelta(days=3650)
    before = datetime.now(timezone.utc) + timedelta(days=1)
    result = await woo_tools.list_orders(
        ListOrdersInput(after=after, before=before, per_page=10)
    )
    assert result.after and result.after.endswith("Z") is False
    assert result.after < result.before


async def test_get_order_not_found(woo_tools: WooCommerceTools) -> None:
    with pytest.raises(NotFoundError):
        await woo_tools.get_order(GetOrderInput(order_id=99_999_999))


async def test_update_order_status_round_trip(woo_tools: WooCommerceTools) -> None:
    orders = await woo_tools.list_orders(ListOrdersInput(per_page=1))
    if not orders.items:
        pytest.skip("no orders in the local store")
    order_id = orders.items[0].id
    current = orders.items[0].status or "pending"
    target = "processing" if current != "processing" else "pending"
    try:
        updated = await woo_tools.update_order_status(
            UpdateOrderStatusInput(order_id=order_id, status=target)
        )
        assert updated.status == target
        fetched = await woo_tools.get_order(GetOrderInput(order_id=order_id))
        assert fetched.status == target
    finally:
        await woo_tools.update_order_status(
            UpdateOrderStatusInput(order_id=order_id, status=current)  # type: ignore[arg-type]
        )


async def test_check_stock_by_id_and_sku(
    inventory_tools: InventoryTools, temp_product: dict
) -> None:
    by_id = await inventory_tools.check_stock(CheckStockInput(product_id=temp_product["id"]))
    by_sku = await inventory_tools.check_stock(CheckStockInput(sku=temp_product["sku"]))
    assert by_id.product_id == by_sku.product_id == temp_product["id"]
    assert by_id.stock_quantity == 12
    assert by_id.stock_status == "instock"


async def test_check_stock_missing(inventory_tools: InventoryTools) -> None:
    with pytest.raises(NotFoundError):
        await inventory_tools.check_stock(CheckStockInput(sku="URUMI-DOES-NOT-EXIST"))


async def test_low_stock_detection(inventory_tools: InventoryTools) -> None:
    result = await inventory_tools.find_low_stock_products(FindLowStockInput(threshold=5))
    assert result.threshold == 5
    assert all(item.stock_quantity <= 5 for item in result.items)
    assert result.products_scanned > 0


async def test_inventory_summary(inventory_tools: InventoryTools) -> None:
    summary = await inventory_tools.get_inventory_summary(InventorySummaryInput())
    assert summary.products_scanned > 0
    assert summary.total_products is not None
    assert summary.stock_tracked_products + summary.untracked_products == summary.products_scanned
    assert summary.monetary_value is None


async def test_reorder_calculation(
    inventory_tools: InventoryTools, temp_product: dict
) -> None:
    result = await inventory_tools.calculate_reorder_quantity(
        ReorderInput(sku=temp_product["sku"], target_stock_level=20, safety_buffer=5)
    )
    assert result.current_stock == 12
    assert result.suggested_reorder_quantity == 13
    assert result.action_taken == "none"


async def test_mcp_servers_over_streamable_http(
    live_settings: WooCommerceSettings,
) -> None:
    """Start both real servers and call them over Streamable HTTP."""
    import asyncio
    import socket

    import uvicorn
    from mcp import ClientSession
    from mcp.client.streamable_http import streamable_http_client

    from services.common.config import load_settings as _load
    from services.inventory_mcp.server import create_app as inventory_app
    from services.woocommerce_mcp.server import create_app as woo_app


    def free_port() -> int:
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            return sock.getsockname()[1]

    ports = {"woo": free_port(), "inv": free_port()}
    woo_settings = _load("woocommerce-mcp", default_port=ports["woo"])
    woo_settings.port = ports["woo"]
    inv_settings = _load("inventory-mcp", default_port=ports["inv"])
    inv_settings.port = ports["inv"]

    servers = [
        uvicorn.Server(
            uvicorn.Config(woo_app(woo_settings), host="127.0.0.1", port=ports["woo"], log_level="warning")
        ),
        uvicorn.Server(
            uvicorn.Config(inventory_app(inv_settings), host="127.0.0.1", port=ports["inv"], log_level="warning")
        ),
    ]
    tasks = [asyncio.create_task(server.serve()) for server in servers]
    try:
        for _ in range(100):
            if all(server.started for server in servers):
                break
            await asyncio.sleep(0.05)
        assert all(server.started for server in servers), "servers did not start"

        async def call(url: str, tool: str, args: dict) -> dict:
            async with streamable_http_client(url) as (read, write, _):
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    tools = await session.list_tools()
                    assert tool in {t.name for t in tools.tools}
                    result = await session.call_tool(tool, args)
                    return result.structuredContent or {}

        woo_result = await call(
            f"http://127.0.0.1:{ports['woo']}/mcp", "list_products", {"per_page": 2}
        )
        assert "items" in woo_result

        inv_result = await call(
            f"http://127.0.0.1:{ports['inv']}/mcp",
            "get_inventory_summary",
            {},
        )
        assert inv_result["monetary_value"] is None
    finally:
        for server in servers:
            server.should_exit = True
        await asyncio.gather(*tasks, return_exceptions=True)
