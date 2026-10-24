"""Unit tests for the Inventory MCP tools, calculations and MCP surface."""

from __future__ import annotations

import pytest
from mcp.server.fastmcp.exceptions import ToolError

from services.common.errors import NotFoundError, UpstreamError
from services.inventory_mcp.models import (
    CheckStockInput,
    FindLowStockInput,
    InventorySummaryInput,
    ReorderInput,
)
from services.inventory_mcp.server import build_tools, create_mcp
from services.inventory_mcp.tools import InventoryTools
from tests.conftest import app_settings, error_response, json_response, make_client, product


def tools_with(handler, **inventory_overrides) -> InventoryTools:
    settings = app_settings()
    for key, value in inventory_overrides.items():
        setattr(settings.inventory, key, value)
    return InventoryTools(make_client(handler), settings.inventory)


# -- check_stock -----------------------------------------------------------


async def test_check_stock_by_sku() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.params["sku"] == "MUG-1"
        return json_response([product(10, sku="MUG-1", stock_quantity=4)])

    tools = tools_with(handler)
    result = await tools.check_stock(CheckStockInput(sku="MUG-1"))
    await tools.client.aclose()

    assert result.product_id == 10
    assert result.stock_quantity == 4
    assert result.stock_status == "instock"
    assert result.stock_tracked is True
    assert result.in_stock is True


async def test_check_stock_by_product_id() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path.endswith("/products/10")
        return json_response(product(10, stock_quantity=0, stock_status="outofstock"))

    tools = tools_with(handler)
    result = await tools.check_stock(CheckStockInput(product_id=10))
    await tools.client.aclose()

    assert result.stock_quantity == 0
    assert result.in_stock is False


async def test_check_stock_untracked_product_reports_null_quantity() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return json_response(
            product(11, manage_stock=False, stock_quantity=None, stock_status="instock")
        )

    tools = tools_with(handler)
    result = await tools.check_stock(CheckStockInput(product_id=11))
    await tools.client.aclose()
    assert result.stock_quantity is None
    assert result.stock_tracked is False


async def test_check_stock_missing_sku() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return json_response([])

    tools = tools_with(handler)
    with pytest.raises(NotFoundError):
        await tools.check_stock(CheckStockInput(sku="NOPE"))
    await tools.client.aclose()


async def test_check_stock_missing_product_id() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return error_response(404, "woocommerce_rest_product_invalid_id", "Invalid ID.")

    tools = tools_with(handler)
    with pytest.raises(NotFoundError):
        await tools.check_stock(CheckStockInput(product_id=404))
    await tools.client.aclose()


@pytest.mark.parametrize(
    "kwargs",
    [{}, {"product_id": 1, "sku": "X"}, {"product_id": 0}, {"sku": ""}],
)
def test_check_stock_input_validation(kwargs) -> None:
    with pytest.raises(ValueError):
        CheckStockInput(**kwargs)


# -- find_low_stock_products ----------------------------------------------


async def test_find_low_stock_filters_and_reports_threshold() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return json_response(
            [
                product(1, stock_quantity=2),
                product(2, stock_quantity=5),
                product(3, stock_quantity=6),
                product(4, stock_quantity=0, stock_status="outofstock"),
                product(5, manage_stock=False, stock_quantity=None),
            ],
            headers={"X-WP-Total": "5", "X-WP-TotalPages": "1"},
        )

    tools = tools_with(handler)
    result = await tools.find_low_stock_products(FindLowStockInput(threshold=5))
    await tools.client.aclose()

    ids = [item.product_id for item in result.items]
    assert ids == [1, 2, 4]
    assert result.threshold == 5
    assert result.products_scanned == 5
    assert result.scan_truncated is False


async def test_find_low_stock_uses_configured_default_threshold() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return json_response([product(1, stock_quantity=3)])

    tools = tools_with(handler, low_stock_threshold=3)
    result = await tools.find_low_stock_products(FindLowStockInput())
    await tools.client.aclose()
    assert result.threshold == 3
    assert len(result.items) == 1


async def test_find_low_stock_paginates_matches_without_loading_all() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        page = int(request.url.params["page"])
        assert request.url.params["per_page"] == "3"
        batches = {
            1: [product(1, stock_quantity=1), product(2, stock_quantity=2)],
            2: [product(3, stock_quantity=3)],
        }
        return json_response(
            batches.get(page, []),
            headers={"X-WP-Total": "3", "X-WP-TotalPages": "2"},
        )

    tools = tools_with(handler, summary_scan_page_size=3)
    page_one = await tools.find_low_stock_products(
        FindLowStockInput(threshold=5, page=1, per_page=2)
    )
    page_two = await tools.find_low_stock_products(
        FindLowStockInput(threshold=5, page=2, per_page=2)
    )
    await tools.client.aclose()

    assert [i.product_id for i in page_one.items] == [1, 2]
    assert page_one.has_more is True
    assert [i.product_id for i in page_two.items] == [3]
    assert page_two.has_more is False


async def test_find_low_stock_respects_scan_limit() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        page = int(request.url.params["page"])
        return json_response(
            [product(page, stock_quantity=1)],
            headers={"X-WP-Total": "10", "X-WP-TotalPages": "10"},
        )

    tools = tools_with(handler, summary_max_products=2, summary_scan_page_size=1)
    result = await tools.find_low_stock_products(FindLowStockInput(threshold=5))
    await tools.client.aclose()

    assert result.products_scanned == 2
    assert result.scan_truncated is True
    assert len(result.items) == 2


async def test_find_low_stock_rejects_negative_threshold() -> None:
    with pytest.raises(ValueError):
        FindLowStockInput(threshold=-1)


# -- get_inventory_summary -------------------------------------------------


async def test_inventory_summary_metrics() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return json_response(
            [
                product(1, stock_quantity=10),  # tracked, in stock
                product(2, stock_quantity=3),  # tracked, low
                product(3, stock_quantity=0, stock_status="outofstock"),  # tracked, out
                product(4, manage_stock=False, stock_quantity=None),  # untracked
            ],
            headers={"X-WP-Total": "4", "X-WP-TotalPages": "1"},
        )

    tools = tools_with(handler)
    result = await tools.get_inventory_summary(InventorySummaryInput())
    await tools.client.aclose()

    assert result.total_products == 4
    assert result.products_scanned == 4
    assert result.stock_tracked_products == 3
    assert result.untracked_products == 1
    assert result.out_of_stock_products == 1
    assert result.low_stock_products == 1
    assert result.total_units_in_stock == 13
    assert result.monetary_value is None
    assert result.scan_truncated is False


async def test_inventory_summary_does_not_claim_monetary_value() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return json_response([product(1, price="999.00")])

    tools = tools_with(handler)
    result = await tools.get_inventory_summary(InventorySummaryInput())
    await tools.client.aclose()
    assert result.monetary_value is None
    assert any("monetary" in note.lower() for note in result.notes)


async def test_inventory_summary_respects_scan_limit_and_notes_it() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        page = int(request.url.params["page"])
        return json_response(
            [product(page, stock_quantity=1)],
            headers={"X-WP-Total": "50", "X-WP-TotalPages": "50"},
        )

    tools = tools_with(handler, summary_max_products=3, summary_scan_page_size=1)
    result = await tools.get_inventory_summary(InventorySummaryInput())
    await tools.client.aclose()

    assert result.products_scanned == 3
    assert result.total_products == 50
    assert result.scan_truncated is True
    assert any("scan stopped" in note.lower() for note in result.notes)


async def test_inventory_summary_custom_threshold() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return json_response([product(1, stock_quantity=8), product(2, stock_quantity=2)])

    tools = tools_with(handler)
    result = await tools.get_inventory_summary(InventorySummaryInput(threshold=8))
    await tools.client.aclose()
    assert result.low_stock_threshold == 8
    assert result.low_stock_products == 2


# -- calculate_reorder_quantity -------------------------------------------


async def test_reorder_quantity_calculation() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return json_response([product(1, sku="MUG-1", stock_quantity=3)])

    tools = tools_with(handler)
    result = await tools.calculate_reorder_quantity(
        ReorderInput(sku="MUG-1", target_stock_level=20, safety_buffer=5)
    )
    await tools.client.aclose()

    assert result.current_stock == 3
    assert result.suggested_reorder_quantity == 22
    assert result.action_taken == "none"


async def test_reorder_quantity_never_negative() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return json_response([product(1, stock_quantity=50)])

    tools = tools_with(handler)
    result = await tools.calculate_reorder_quantity(
        ReorderInput(sku="SKU-1", target_stock_level=10, safety_buffer=5)
    )
    await tools.client.aclose()
    assert result.suggested_reorder_quantity == 0
    assert "already meets" in result.rationale


async def test_reorder_quantity_handles_untracked_product() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return json_response([product(1, manage_stock=False, stock_quantity=None)])

    tools = tools_with(handler)
    result = await tools.calculate_reorder_quantity(
        ReorderInput(sku="SKU-1", target_stock_level=10, safety_buffer=2)
    )
    await tools.client.aclose()

    assert result.current_stock is None
    assert result.suggested_reorder_quantity == 12
    assert "does not track stock" in result.rationale


async def test_reorder_quantity_missing_product() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return json_response([])

    tools = tools_with(handler)
    with pytest.raises(NotFoundError):
        await tools.calculate_reorder_quantity(
            ReorderInput(sku="NOPE", target_stock_level=5)
        )
    await tools.client.aclose()


async def test_reorder_quantity_validates_identifiers_and_numbers() -> None:
    with pytest.raises(ValueError):
        ReorderInput(sku="X", product_id=1, target_stock_level=5)
    with pytest.raises(ValueError):
        ReorderInput(sku="X", target_stock_level=-1)
    with pytest.raises(ValueError):
        ReorderInput(sku="X", target_stock_level=5, safety_buffer=-2)


# -- MCP surface -----------------------------------------------------------


async def test_inventory_mcp_exposes_four_tools() -> None:
    settings = app_settings(service_name="inventory-mcp")
    tools = tools_with(lambda request: json_response([]))
    mcp = create_mcp(settings, tools)

    listed = await mcp.list_tools()
    await tools.client.aclose()

    assert {t.name for t in listed} == {
        "check_stock",
        "find_low_stock_products",
        "get_inventory_summary",
        "calculate_reorder_quantity",
    }
    for tool in listed:
        assert tool.description and len(tool.description) > 40
        assert tool.inputSchema["type"] == "object"


async def test_inventory_mcp_invocation_and_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if "sku" in request.url.params:
            return json_response([product(10, sku="MUG-1", stock_quantity=4)])
        return error_response(404, "woocommerce_rest_product_invalid_id", "Invalid ID.")

    settings = app_settings(service_name="inventory-mcp")
    tools = tools_with(handler)
    mcp = create_mcp(settings, tools)

    result = await mcp.call_tool("check_stock", {"sku": "MUG-1"})
    structured = result[1] if isinstance(result, tuple) else result
    assert structured["stock_quantity"] == 4

    with pytest.raises(ToolError) as exc:
        await mcp.call_tool("check_stock", {"product_id": 404})
    assert "not_found" in str(exc.value)
    await tools.client.aclose()


async def test_upstream_payload_without_id_is_rejected() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return json_response({"name": "broken"})

    tools = tools_with(handler)
    with pytest.raises(UpstreamError):
        await tools.check_stock(CheckStockInput(product_id=1))
    await tools.client.aclose()
