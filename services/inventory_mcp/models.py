"""Typed input/output models for the Inventory MCP tools.

All stock data is read from WooCommerce; this service never keeps a second
inventory database and never mutates stock.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class ProductRef(BaseModel):
    """A product identifier: exactly one of `product_id` or `sku` is required."""

    model_config = ConfigDict(extra="forbid")

    product_id: int | None = Field(None, ge=1, description="WooCommerce product ID")
    sku: str | None = Field(None, min_length=1, max_length=100, description="Product SKU")

    @model_validator(mode="after")
    def _exactly_one(self) -> "ProductRef":
        if (self.product_id is None) == (self.sku is None):
            raise ValueError("provide exactly one of product_id or sku")
        return self


class StockInfo(BaseModel):
    product_id: int
    name: str
    sku: str | None = None
    stock_status: str | None = Field(
        None, description="WooCommerce stock status: instock, outofstock or onbackorder"
    )
    stock_quantity: int | None = Field(
        None, description="Current quantity; null when the product does not track stock"
    )
    manage_stock: bool | None = None
    backorders: str | None = Field(
        None, description="Backorder policy: no, notify or yes"
    )
    stock_tracked: bool = Field(
        True, description="Whether WooCommerce tracks a numeric quantity for this product"
    )
    in_stock: bool = Field(True, description="True when stock_status is not outofstock")
    permalink: str | None = None


class LowStockProduct(BaseModel):
    product_id: int
    name: str
    sku: str | None = None
    stock_quantity: int
    stock_status: str | None = None
    threshold: int


class LowStockList(BaseModel):
    items: list[LowStockProduct]
    threshold: int
    page: int
    per_page: int
    returned: int
    has_more: bool
    products_scanned: int = Field(
        ..., description="Number of catalogue products examined to produce this page"
    )
    scan_truncated: bool = Field(
        False,
        description=(
            "True when the configured scan limit was reached before the catalogue was "
            "exhausted; more matches may exist"
        ),
    )
    scan_limit: int


class InventorySummary(BaseModel):
    """Catalogue stock summary.

    Metric definitions:
      * `total_products` - published products reported by WooCommerce for the
        catalogue (store-wide count, not limited by the scan cap).
      * `products_scanned` - products actually examined to compute the metrics
        below. If `scan_truncated` is true, the quantity-based metrics describe
        only the scanned subset.
      * `stock_tracked_products` - scanned products with numeric stock tracking
        enabled (`manage_stock`).
      * `untracked_products` - scanned products that do not track stock; their
        quantity is unknown.
      * `out_of_stock_products` - scanned products whose stock status is
        `outofstock` (includes tracked products at zero and untracked products
        manually marked out of stock).
      * `low_stock_products` - tracked products with `0 < quantity <= threshold`.
        Out-of-stock products are counted separately and not included here.
      * `total_units_in_stock` - sum of non-negative tracked quantities across
        the scanned products.
      * `monetary_value` - always null: this service does not claim to compute
        inventory value. Cost data is not reliably available from the product
        API, and `regular_price` is a selling price, not inventory cost.
    """

    total_products: int | None = Field(
        None, description="Published products reported by WooCommerce (store-wide)"
    )
    products_scanned: int
    stock_tracked_products: int
    untracked_products: int
    out_of_stock_products: int
    low_stock_products: int
    total_units_in_stock: int
    low_stock_threshold: int
    scan_truncated: bool
    scan_limit: int
    monetary_value: None = Field(
        None,
        description="Always null. Inventory value is intentionally not calculated.",
    )
    notes: list[str] = Field(default_factory=list)


class ReorderRecommendation(BaseModel):
    product_id: int
    name: str
    sku: str | None = None
    current_stock: int | None
    target_stock_level: int
    safety_buffer: int
    suggested_reorder_quantity: int = Field(
        ..., description="Units to order to reach target plus safety buffer; never negative"
    )
    stock_status: str | None = None
    backorders: str | None = None
    rationale: str
    action_taken: Literal["none"] = Field(
        "none",
        description="This tool is advisory only: no purchase order is placed and stock is not modified.",
    )


class CheckStockInput(ProductRef):
    pass


class FindLowStockInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    threshold: int | None = Field(
        None,
        ge=0,
        le=1_000_000,
        description="Stock threshold; products at or below it are low stock. Defaults to config.",
    )
    page: int = Field(1, ge=1, description="Page of matching products, starting at 1")
    per_page: int = Field(20, ge=1, le=100, description="Matches per page (max 100)")


class InventorySummaryInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    threshold: int | None = Field(
        None, ge=0, le=1_000_000, description="Low-stock threshold; defaults to config"
    )


class ReorderInput(ProductRef):
    target_stock_level: int = Field(
        ..., ge=0, le=1_000_000, description="Desired stock level after replenishment"
    )
    safety_buffer: int = Field(
        0, ge=0, le=1_000_000, description="Extra units to keep as a safety buffer"
    )
