"""Tool handlers for the WooCommerce MCP server.

Handlers are transport-independent: they accept typed input models and return
typed output models. The MCP layer is a thin adapter over this module, which
keeps the business logic unit-testable without an MCP runtime.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from services.common.errors import ConflictError, NotFoundError, UpstreamError
from services.common.logging import get_logger
from services.common.woocommerce import Page, WooCommerceClient
from services.woocommerce_mcp.models import (
    CreateProductInput,
    GetOrderInput,
    ListOrdersInput,
    ListProductsInput,
    OrderDetail,
    OrderLineItem,
    OrderList,
    OrderStatusUpdate,
    OrderSummary,
    ProductCreated,
    ProductList,
    ProductSummary,
    UpdateOrderStatusInput,
)

logger = get_logger("urumi.woocommerce_mcp.tools")


def _to_product_summary(product: dict[str, Any]) -> ProductSummary:
    return ProductSummary(
        id=product["id"],
        name=product.get("name") or "",
        sku=product.get("sku") or None,
        type=product.get("type"),
        status=product.get("status"),
        price=product.get("price"),
        regular_price=product.get("regular_price"),
        stock_status=product.get("stock_status"),
        stock_quantity=product.get("stock_quantity"),
        manage_stock=product.get("manage_stock"),
        permalink=product.get("permalink"),
    )


def _billing_name(order: dict[str, Any]) -> str | None:
    billing = order.get("billing") or {}
    if not isinstance(billing, dict):
        return None
    first = (billing.get("first_name") or "").strip()
    last = (billing.get("last_name") or "").strip()
    name = " ".join(part for part in (first, last) if part).strip()
    return name or None


def _item_count(order: dict[str, Any]) -> int | None:
    line_items = order.get("line_items")
    if not isinstance(line_items, list):
        return None
    total = 0
    for item in line_items:
        if isinstance(item, dict) and isinstance(item.get("quantity"), int):
            total += item["quantity"]
    return total


def _to_order_summary(order: dict[str, Any]) -> OrderSummary:
    return OrderSummary(
        id=order["id"],
        number=order.get("number"),
        status=order.get("status"),
        currency=order.get("currency"),
        total=order.get("total"),
        date_created=order.get("date_created"),
        date_created_gmt=order.get("date_created_gmt"),
        date_modified_gmt=order.get("date_modified_gmt"),
        customer_id=order.get("customer_id"),
        billing_name=_billing_name(order),
        item_count=_item_count(order),
    )


def _to_order_detail(order: dict[str, Any]) -> OrderDetail:
    items = [
        OrderLineItem(
            id=item.get("id"),
            product_id=item.get("product_id"),
            variation_id=item.get("variation_id") or None,
            name=item.get("name"),
            quantity=item.get("quantity"),
            sku=item.get("sku") or None,
        )
        for item in (order.get("line_items") or [])
        if isinstance(item, dict)
    ]
    summary = _to_order_summary(order)
    return OrderDetail(
        **summary.model_dump(),
        line_items=items,
        payment_method_title=order.get("payment_method_title"),
        customer_note=order.get("customer_note") or None,
    )


def _utc_iso(value: datetime | None) -> str | None:
    """Normalize a datetime to an ISO-8601 UTC string.

    Naive datetimes are treated as UTC (documented in the tool schema), so date
    boundaries do not silently shift with the host timezone.
    """
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")


def _page_meta(page: Page) -> dict[str, Any]:
    has_more = (
        page.page < page.total_pages
        if page.total_pages is not None
        else len(page.items) >= page.per_page
    )
    return {
        "page": page.page,
        "per_page": page.per_page,
        "total": page.total,
        "total_pages": page.total_pages,
        "has_more": has_more,
    }


class WooCommerceTools:
    """Business logic for the five WooCommerce tools."""

    def __init__(self, client: WooCommerceClient) -> None:
        self.client = client

    async def list_products(self, params: ListProductsInput) -> ProductList:
        status = None if params.status in (None, "any") else params.status
        page = await self.client.list_products(
            page=params.page,
            per_page=params.per_page,
            search=params.search,
            stock_status=params.stock_status,
            sku=params.sku,
            status=status,
        )
        return ProductList(
            items=[_to_product_summary(p) for p in page.items],
            **_page_meta(page),
        )

    async def create_product(self, params: CreateProductInput) -> ProductCreated:
        if params.sku:
            existing = await self.client.find_product_by_sku(params.sku)
            if existing is not None:
                if params.if_sku_exists == "return_existing":
                    logger.info("create_product returning existing SKU product_id=%s", existing.get("id"))
                    return ProductCreated(
                        id=existing["id"],
                        name=existing.get("name") or params.name,
                        sku=existing.get("sku") or params.sku,
                        status=existing.get("status"),
                        price=existing.get("price"),
                        stock_status=existing.get("stock_status"),
                        stock_quantity=existing.get("stock_quantity"),
                        permalink=existing.get("permalink"),
                        created=False,
                        message="A product with this SKU already exists; returned it unchanged.",
                    )
                raise ConflictError(
                    f"a product with SKU {params.sku!r} already exists",
                    details={"sku": params.sku, "product_id": existing.get("id")},
                )

        payload: dict[str, Any] = {
            "name": params.name,
            "regular_price": params.price,
            "status": "publish",
        }
        if params.sku:
            payload["sku"] = params.sku
        if params.description:
            payload["description"] = params.description
        if params.stock_quantity is not None:
            payload["manage_stock"] = True
            payload["stock_quantity"] = params.stock_quantity
            payload["stock_status"] = (
                "outofstock" if params.stock_quantity == 0 else "instock"
            )
        if params.stock_status is not None:
            payload["stock_status"] = params.stock_status

        try:
            product = await self.client.create_product(payload)
        except UpstreamError as exc:
            # Handle a concurrent create between the SKU lookup and the POST.
            if exc.upstream_code in {"product_invalid_sku", "duplicate_sku"}:
                raise ConflictError(
                    f"a product with SKU {params.sku!r} already exists",
                    details={"sku": params.sku},
                ) from exc
            raise
        logger.info("create_product created product_id=%s", product.get("id"))
        return ProductCreated(
            id=product["id"],
            name=product.get("name") or params.name,
            sku=product.get("sku") or params.sku,
            status=product.get("status"),
            price=product.get("price"),
            stock_status=product.get("stock_status"),
            stock_quantity=product.get("stock_quantity"),
            permalink=product.get("permalink"),
            created=True,
        )

    async def list_orders(self, params: ListOrdersInput) -> OrderList:
        status = None if params.status in (None, "any") else params.status
        after = _utc_iso(params.after)
        before = _utc_iso(params.before)
        page = await self.client.list_orders(
            page=params.page,
            per_page=params.per_page,
            status=status,
            after=after,
            before=before,
        )
        return OrderList(
            items=[_to_order_summary(o) for o in page.items],
            after=after,
            before=before,
            **_page_meta(page),
        )

    async def get_order(self, params: GetOrderInput) -> OrderDetail:
        order = await self.client.get_order(params.order_id)
        return _to_order_detail(order)

    async def update_order_status(
        self, params: UpdateOrderStatusInput
    ) -> OrderStatusUpdate:
        try:
            current = await self.client.get_order(params.order_id)
        except NotFoundError:
            raise
        previous = current.get("status")
        if previous == params.status:
            return OrderStatusUpdate(
                id=current["id"],
                number=current.get("number"),
                previous_status=previous,
                status=params.status,
                date_modified_gmt=current.get("date_modified_gmt"),
                updated=False,
            )
        updated = await self.client.update_order_status(params.order_id, params.status)
        if updated.get("status") != params.status:
            raise UpstreamError(
                "WooCommerce did not apply the requested order status",
                status_code=None,
            )
        logger.info(
            "update_order_status order_id=%s from=%s to=%s",
            params.order_id,
            previous,
            params.status,
        )
        return OrderStatusUpdate(
            id=updated["id"],
            number=updated.get("number"),
            previous_status=previous,
            status=updated.get("status") or params.status,
            date_modified_gmt=updated.get("date_modified_gmt"),
        )
