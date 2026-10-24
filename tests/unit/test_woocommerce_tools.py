"""Unit tests for WooCommerce MCP tool handlers and MCP discovery/invocation."""

from __future__ import annotations

import json
from datetime import datetime, timezone

import httpx
import pytest
from mcp.server.fastmcp.exceptions import ToolError

from services.common.errors import ConflictError, NotFoundError
from services.woocommerce_mcp.models import (
    CreateProductInput,
    GetOrderInput,
    ListOrdersInput,
    ListProductsInput,
    UpdateOrderStatusInput,
)
from services.woocommerce_mcp.server import build_tools, create_mcp
from services.woocommerce_mcp.tools import WooCommerceTools
from tests.conftest import (
    app_settings,
    error_response,
    json_response,
    make_client,
    order,
    product,
)


def tools_with(handler) -> WooCommerceTools:
    return WooCommerceTools(make_client(handler))


# -- list_products ---------------------------------------------------------


async def test_list_products_maps_fields_and_pagination() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return json_response(
            [product(1, name="Mug", sku="MUG-1", stock_quantity=4)],
            headers={"X-WP-Total": "1", "X-WP-TotalPages": "1"},
        )

    tools = tools_with(handler)
    result = await tools.list_products(ListProductsInput(page=1, per_page=10))
    await tools.client.aclose()

    assert result.items[0].id == 1
    assert result.items[0].name == "Mug"
    assert result.items[0].stock_quantity == 4
    assert result.total == 1
    assert result.has_more is False


async def test_list_products_filters_are_forwarded() -> None:
    captured: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured.update(dict(request.url.params))
        return json_response([])

    tools = tools_with(handler)
    await tools.list_products(
        ListProductsInput(search="mug", stock_status="outofstock", sku="MUG-1", status="any")
    )
    await tools.client.aclose()

    assert captured["search"] == "mug"
    assert captured["stock_status"] == "outofstock"
    assert captured["sku"] == "MUG-1"
    assert "status" not in captured


async def test_list_products_rejects_invalid_stock_status() -> None:
    with pytest.raises(ValueError):
        ListProductsInput(stock_status="bogus")  # type: ignore[arg-type]


async def test_list_products_has_more_when_more_pages() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return json_response([product(1)], headers={"X-WP-Total": "9", "X-WP-TotalPages": "3"})

    tools = tools_with(handler)
    result = await tools.list_products(ListProductsInput(page=1, per_page=1))
    await tools.client.aclose()
    assert result.has_more is True


# -- create_product --------------------------------------------------------


async def test_create_product_sends_expected_payload() -> None:
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "GET":
            return json_response([])
        captured.update(json.loads(request.content))
        return json_response(
            {
                "id": 99,
                "name": captured["name"],
                "sku": captured.get("sku"),
                "status": "publish",
                "price": "12.50",
                "stock_status": "instock",
                "stock_quantity": 7,
            },
            status_code=201,
        )

    tools = tools_with(handler)
    result = await tools.create_product(
        CreateProductInput(name="Mug", price="12.5", sku="MUG-9", stock_quantity=7)
    )
    await tools.client.aclose()

    assert captured["name"] == "Mug"
    assert captured["regular_price"] == "12.50"
    assert captured["sku"] == "MUG-9"
    assert captured["manage_stock"] is True
    assert captured["stock_quantity"] == 7
    assert result.id == 99
    assert result.created is True


async def test_create_product_rejects_duplicate_sku() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return json_response([product(5, sku="MUG-9")])

    tools = tools_with(handler)
    with pytest.raises(ConflictError) as exc:
        await tools.create_product(CreateProductInput(name="Mug", price="1.00", sku="MUG-9"))
    await tools.client.aclose()
    assert exc.value.details["product_id"] == 5


async def test_create_product_can_return_existing_product() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return json_response([product(5, name="Existing", sku="MUG-9")])

    tools = tools_with(handler)
    result = await tools.create_product(
        CreateProductInput(
            name="Mug", price="1.00", sku="MUG-9", if_sku_exists="return_existing"
        )
    )
    await tools.client.aclose()
    assert result.id == 5
    assert result.created is False
    assert "already exists" in (result.message or "")


async def test_create_product_maps_race_condition_sku_error_to_conflict() -> None:
    state = {"gets": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "GET":
            state["gets"] += 1
            return json_response([])
        return error_response(400, "product_invalid_sku", "Invalid or duplicated SKU.")

    tools = tools_with(handler)
    with pytest.raises(ConflictError):
        await tools.create_product(CreateProductInput(name="Mug", price="1.00", sku="MUG-9"))
    await tools.client.aclose()


@pytest.mark.parametrize("price", ["abc", "-1", "1.999", ""])
async def test_create_product_rejects_invalid_prices(price: str) -> None:
    with pytest.raises(ValueError):
        CreateProductInput(name="Mug", price=price)


async def test_create_product_rejects_blank_name() -> None:
    with pytest.raises(ValueError):
        CreateProductInput(name="   ", price="1.00")


async def test_create_product_rejects_conflicting_stock_fields() -> None:
    with pytest.raises(ValueError):
        CreateProductInput(
            name="Mug", price="1.00", stock_quantity=5, stock_status="outofstock"
        )


# -- list_orders -----------------------------------------------------------


async def test_list_orders_normalizes_naive_datetimes_to_utc() -> None:
    captured: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured.update(dict(request.url.params))
        return json_response([order(1)])

    tools = tools_with(handler)
    result = await tools.list_orders(
        ListOrdersInput(
            after=datetime(2026, 1, 1, 9, 30),
            before=datetime(2026, 1, 2, 9, 30),
            status="completed",
        )
    )
    await tools.client.aclose()

    assert captured["after"] == "2026-01-01T09:30:00"
    assert captured["before"] == "2026-01-02T09:30:00"
    assert captured["status"] == "completed"
    assert result.after == "2026-01-01T09:30:00"
    assert result.before == "2026-01-02T09:30:00"


async def test_list_orders_converts_offset_datetimes_to_utc() -> None:
    captured: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured.update(dict(request.url.params))
        return json_response([])

    tz = timezone.utc
    from datetime import timedelta

    plus_five = timezone(timedelta(hours=5))
    tools = tools_with(handler)
    await tools.list_orders(
        ListOrdersInput(after=datetime(2026, 3, 1, 15, 0, tzinfo=plus_five))
    )
    await tools.client.aclose()
    assert captured["after"] == "2026-03-01T10:00:00"
    assert tz is timezone.utc


async def test_list_orders_rejects_inverted_range() -> None:
    with pytest.raises(ValueError):
        ListOrdersInput(
            after=datetime(2026, 2, 1, tzinfo=timezone.utc),
            before=datetime(2026, 1, 1, tzinfo=timezone.utc),
        )


async def test_list_orders_omits_customer_pii() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return json_response([order(1, customer_email="private@example.test")])

    tools = tools_with(handler)
    result = await tools.list_orders(ListOrdersInput())
    await tools.client.aclose()

    payload = result.model_dump_json()
    assert "private@example.test" not in payload
    assert "555-0100" not in payload
    assert "1 Secret Street" not in payload
    assert result.items[0].billing_name == "Test Customer"


# -- get_order -------------------------------------------------------------


async def test_get_order_returns_line_items_without_pii() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return json_response(order(7))

    tools = tools_with(handler)
    result = await tools.get_order(GetOrderInput(order_id=7))
    await tools.client.aclose()

    assert result.id == 7
    assert result.line_items[0].quantity == 2
    payload = result.model_dump_json()
    assert "customer@example.test" not in payload
    assert "555-0100" not in payload


async def test_get_order_not_found_raises_typed_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return error_response(404, "woocommerce_rest_shop_order_invalid_id", "Invalid ID.")

    tools = tools_with(handler)
    with pytest.raises(NotFoundError):
        await tools.get_order(GetOrderInput(order_id=404))
    await tools.client.aclose()


# -- update_order_status ---------------------------------------------------


async def test_update_order_status_updates_and_reports_previous() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "GET":
            return json_response(order(7, status="pending"))
        return json_response(order(7, status="completed"))

    tools = tools_with(handler)
    result = await tools.update_order_status(
        UpdateOrderStatusInput(order_id=7, status="completed")
    )
    await tools.client.aclose()
    assert result.previous_status == "pending"
    assert result.status == "completed"
    assert result.updated is True


async def test_update_order_status_is_idempotent_when_unchanged() -> None:
    calls = {"put": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "GET":
            return json_response(order(7, status="completed"))
        calls["put"] += 1
        return json_response(order(7, status="completed"))

    tools = tools_with(handler)
    result = await tools.update_order_status(
        UpdateOrderStatusInput(order_id=7, status="completed")
    )
    await tools.client.aclose()
    assert calls["put"] == 0
    assert result.updated is False


async def test_update_order_status_missing_order() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return error_response(404, "woocommerce_rest_shop_order_invalid_id", "Invalid ID.")

    tools = tools_with(handler)
    with pytest.raises(NotFoundError):
        await tools.update_order_status(
            UpdateOrderStatusInput(order_id=404, status="completed")
        )
    await tools.client.aclose()


async def test_update_order_status_rejects_unsupported_status() -> None:
    with pytest.raises(ValueError):
        UpdateOrderStatusInput(order_id=1, status="shipped")  # type: ignore[arg-type]


async def test_update_order_status_surfaces_upstream_failure() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "GET":
            return json_response(order(7, status="pending"))
        return error_response(500, "internal_error", "boom")

    tools = tools_with(handler)
    with pytest.raises(Exception) as exc:
        await tools.update_order_status(
            UpdateOrderStatusInput(order_id=7, status="completed")
        )
    await tools.client.aclose()
    assert "boom" in str(exc.value)


# -- MCP surface -----------------------------------------------------------


async def test_mcp_exposes_exactly_the_five_required_tools() -> None:
    settings = app_settings(service_name="woocommerce-mcp")
    tools = tools_with(lambda request: json_response([]))
    mcp = create_mcp(settings, tools)

    listed = await mcp.list_tools()
    await tools.client.aclose()

    names = {tool.name for tool in listed}
    assert names == {
        "list_products",
        "create_product",
        "list_orders",
        "get_order",
        "update_order_status",
    }
    for tool in listed:
        assert tool.description and len(tool.description) > 40
        assert tool.inputSchema["type"] == "object"


async def test_mcp_tool_invocation_returns_structured_output() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return json_response([product(1, name="Mug")], headers={"X-WP-TotalPages": "1"})

    settings = app_settings(service_name="woocommerce-mcp")
    tools = tools_with(handler)
    mcp = create_mcp(settings, tools)

    result = await mcp.call_tool("list_products", {"per_page": 5})
    await tools.client.aclose()

    structured = result[1] if isinstance(result, tuple) else result
    assert structured["items"][0]["name"] == "Mug"


async def test_mcp_tool_errors_are_clear_and_typed() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return error_response(404, "woocommerce_rest_shop_order_invalid_id", "Invalid ID.")

    settings = app_settings(service_name="woocommerce-mcp")
    tools = tools_with(handler)
    mcp = create_mcp(settings, tools)

    with pytest.raises(ToolError) as exc:
        await mcp.call_tool("get_order", {"order_id": 404})
    await tools.client.aclose()
    assert "not_found" in str(exc.value)


async def test_mcp_schema_declares_required_create_fields() -> None:
    settings = app_settings(service_name="woocommerce-mcp")
    tools = tools_with(lambda request: json_response([]))
    mcp = create_mcp(settings, tools)

    tools_listed = {tool.name: tool for tool in await mcp.list_tools()}
    await tools.client.aclose()

    schema = tools_listed["create_product"].inputSchema
    assert set(schema["required"]) == {"name", "price"}
    assert schema["properties"]["name"]["type"] == "string"
    stock_schema = schema["properties"]["stock_quantity"]
    assert stock_schema["anyOf"][0]["minimum"] == 0
    assert stock_schema["anyOf"][0]["maximum"] == 1_000_000
