"""Typed input/output models for the WooCommerce MCP tools."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

OrderStatus = Literal[
    "pending",
    "processing",
    "on-hold",
    "completed",
    "cancelled",
    "refunded",
    "failed",
    "trash",
]

StockStatus = Literal["instock", "outofstock", "onbackorder"]
ProductStatus = Literal["any", "draft", "pending", "private", "publish"]

ORDER_STATUSES: tuple[str, ...] = (
    "pending",
    "processing",
    "on-hold",
    "completed",
    "cancelled",
    "refunded",
    "failed",
    "trash",
)


class ProductSummary(BaseModel):
    """A compact product representation safe to return to an AI client."""

    model_config = ConfigDict(extra="ignore")

    id: int
    name: str
    sku: str | None = None
    type: str | None = None
    status: str | None = None
    price: str | None = Field(None, description="Active price as reported by WooCommerce")
    regular_price: str | None = None
    stock_status: str | None = None
    stock_quantity: int | None = None
    manage_stock: bool | None = None
    permalink: str | None = None


class ProductList(BaseModel):
    items: list[ProductSummary]
    page: int
    per_page: int
    total: int | None = Field(None, description="Total matching products, when provided by the store")
    total_pages: int | None = None
    has_more: bool


class ProductCreated(BaseModel):
    id: int
    name: str
    sku: str | None = None
    status: str | None = None
    price: str | None = None
    stock_status: str | None = None
    stock_quantity: int | None = None
    permalink: str | None = None
    created: bool = Field(True, description="False when an existing SKU was returned unchanged")
    message: str | None = None


class OrderSummary(BaseModel):
    """Order fields useful for support workflows; customer PII is minimized."""

    model_config = ConfigDict(extra="ignore")

    id: int
    number: str | None = None
    status: str | None = None
    currency: str | None = None
    total: str | None = None
    date_created: str | None = None
    date_created_gmt: str | None = None
    date_modified_gmt: str | None = None
    customer_id: int | None = None
    billing_name: str | None = Field(
        None, description="Customer name only; email, phone and address are omitted"
    )
    item_count: int | None = None


class OrderDetail(OrderSummary):
    line_items: list["OrderLineItem"] = Field(default_factory=list)
    payment_method_title: str | None = None
    customer_note: str | None = None


class OrderLineItem(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: int | None = None
    product_id: int | None = None
    variation_id: int | None = None
    name: str | None = None
    quantity: int | None = None
    sku: str | None = None


class OrderList(BaseModel):
    items: list[OrderSummary]
    page: int
    per_page: int
    total: int | None = None
    total_pages: int | None = None
    has_more: bool
    after: str | None = Field(None, description="UTC start bound applied (inclusive)")
    before: str | None = Field(None, description="UTC end bound applied (exclusive)")


class OrderStatusUpdate(BaseModel):
    id: int
    number: str | None = None
    previous_status: str | None = None
    status: str
    date_modified_gmt: str | None = None
    updated: bool = True


# -- input models ----------------------------------------------------------


class ListProductsInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    page: int = Field(1, ge=1, description="Page number, starting at 1")
    per_page: int = Field(
        20, ge=1, le=100, description="Results per page (max 100, subject to server config)"
    )
    search: str | None = Field(
        None, max_length=200, description="Free-text search over product name/description"
    )
    stock_status: StockStatus | None = Field(
        None, description="Filter by stock status: instock, outofstock or onbackorder"
    )
    sku: str | None = Field(None, max_length=100, description="Exact SKU filter")
    status: ProductStatus | None = Field(
        "publish", description="Product status filter; use 'any' to include drafts"
    )


class CreateProductInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(..., min_length=1, max_length=200, description="Product name")
    price: str = Field(
        ...,
        description="Regular price as a decimal string, e.g. '19.99'",
    )
    sku: str | None = Field(None, min_length=1, max_length=100, description="Unique SKU")
    stock_quantity: int | None = Field(
        None, ge=0, le=1_000_000, description="Initial stock quantity (enables stock management)"
    )
    stock_status: StockStatus | None = Field(
        None, description="Explicit stock status; derived from stock_quantity when omitted"
    )
    description: str | None = Field(
        None, max_length=5000, description="Optional plain-text product description"
    )
    if_sku_exists: Literal["error", "return_existing"] = Field(
        "error",
        description=(
            "Behavior when the SKU already exists: 'error' fails without changes, "
            "'return_existing' returns the existing product with created=false"
        ),
    )

    @field_validator("name", "sku", "description")
    @classmethod
    def _strip(cls, value: str | None) -> str | None:
        if value is None:
            return None
        stripped = value.strip()
        if not stripped:
            raise ValueError("must not be blank")
        return stripped

    @field_validator("price")
    @classmethod
    def _validate_price(cls, value: str) -> str:
        from decimal import Decimal, InvalidOperation

        cleaned = value.strip()
        try:
            amount = Decimal(cleaned)
        except InvalidOperation as exc:
            raise ValueError("price must be a decimal number such as '19.99'") from exc
        if not amount.is_finite() or amount < 0:
            raise ValueError("price must be a non-negative number")
        if amount.as_tuple().exponent < -2:  # type: ignore[operator]
            raise ValueError("price must have at most 2 decimal places")
        return f"{amount:.2f}"

    @model_validator(mode="after")
    def _stock_consistency(self) -> "CreateProductInput":
        if self.stock_status is not None and self.stock_quantity is not None:
            if self.stock_quantity > 0 and self.stock_status == "outofstock":
                raise ValueError(
                    "stock_status 'outofstock' conflicts with a positive stock_quantity"
                )
        return self


class ListOrdersInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    page: int = Field(1, ge=1, description="Page number, starting at 1")
    per_page: int = Field(20, ge=1, le=100, description="Results per page (max 100)")
    status: OrderStatus | Literal["any"] | None = Field(
        None, description="Order status filter; omit or 'any' for all statuses"
    )
    after: datetime | None = Field(
        None,
        description=(
            "Only orders created at/after this time. Naive values are interpreted as UTC. "
            "Sent to WooCommerce as an ISO-8601 UTC timestamp."
        ),
    )
    before: datetime | None = Field(
        None,
        description=(
            "Only orders created strictly before this time. Naive values are interpreted as UTC."
        ),
    )

    @model_validator(mode="after")
    def _validate_range(self) -> "ListOrdersInput":
        if self.after and self.before and self.after >= self.before:
            raise ValueError("after must be earlier than before")
        return self


class GetOrderInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    order_id: int = Field(..., ge=1, description="WooCommerce order ID")


class UpdateOrderStatusInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    order_id: int = Field(..., ge=1, description="WooCommerce order ID")
    status: OrderStatus = Field(
        ...,
        description=(
            "New status. Supported: pending, processing, on-hold, completed, "
            "cancelled, refunded, failed, trash."
        ),
    )


OrderDetail.model_rebuild()
