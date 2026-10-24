"""Inventory tool handlers backed by the WooCommerce REST API.

This service is read-only: it never creates purchase orders and never modifies
stock. WooCommerce remains the single source of truth.
"""

from __future__ import annotations

from typing import Any

from services.common.config import InventorySettings
from services.common.errors import NotFoundError, UpstreamError
from services.common.logging import get_logger
from services.common.woocommerce import WooCommerceClient
from services.inventory_mcp.models import (
    CheckStockInput,
    FindLowStockInput,
    InventorySummary,
    InventorySummaryInput,
    LowStockList,
    LowStockProduct,
    ReorderInput,
    ReorderRecommendation,
    StockInfo,
)

logger = get_logger("urumi.inventory_mcp.tools")


def _as_int(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float) and value.is_integer():
        return int(value)
    if isinstance(value, str):
        try:
            return int(value.strip())
        except ValueError:
            return None
    return None


def _stock_tracked(product: dict[str, Any]) -> bool:
    return bool(product.get("manage_stock"))


def _stock_info(product: dict[str, Any]) -> StockInfo:
    ensure_supported_product(product)
    quantity = _as_int(product.get("stock_quantity"))
    tracked = _stock_tracked(product)
    status = product.get("stock_status")
    return StockInfo(
        product_id=product["id"],
        name=product.get("name") or "",
        sku=product.get("sku") or None,
        stock_status=status,
        stock_quantity=quantity,
        manage_stock=product.get("manage_stock"),
        backorders=product.get("backorders"),
        stock_tracked=tracked,
        in_stock=status != "outofstock",
        permalink=product.get("permalink"),
    )


class InventoryTools:
    def __init__(self, client: WooCommerceClient, settings: InventorySettings) -> None:
        self.client = client
        self.settings = settings

    async def _resolve_product(self, product_id: int | None, sku: str | None) -> dict[str, Any]:
        if product_id is not None:
            return ensure_supported_product(await self.client.get_product(product_id))
        assert sku is not None
        product = await self.client.find_product_by_sku(sku)
        if product is None:
            raise NotFoundError("product", sku)
        return ensure_supported_product(product)

    async def check_stock(self, params: CheckStockInput) -> StockInfo:
        product = await self._resolve_product(params.product_id, params.sku)
        return _stock_info(product)

    async def find_low_stock_products(self, params: FindLowStockInput) -> LowStockList:
        threshold = (
            self.settings.low_stock_threshold if params.threshold is None else params.threshold
        )
        matches: list[LowStockProduct] = []
        scanned = 0
        truncated = False

        # Scan in bounded pages rather than loading the whole catalogue.
        async for page in self.client.paginate(
            "/products",
            params={"status": "publish"},
            per_page=self.settings.summary_scan_page_size,
        ):
            for product in page.items:
                scanned += 1
                if not _stock_tracked(product):
                    continue
                quantity = _as_int(product.get("stock_quantity"))
                if quantity is None or quantity > threshold:
                    continue
                matches.append(
                    LowStockProduct(
                        product_id=product["id"],
                        name=product.get("name") or "",
                        sku=product.get("sku") or None,
                        stock_quantity=quantity,
                        stock_status=product.get("stock_status"),
                        threshold=threshold,
                    )
                )
            if scanned >= self.settings.summary_max_products:
                truncated = True
                break

        start = (params.page - 1) * params.per_page
        end = start + params.per_page
        window = matches[start:end]
        return LowStockList(
            items=window,
            threshold=threshold,
            page=params.page,
            per_page=params.per_page,
            returned=len(window),
            has_more=end < len(matches),
            products_scanned=scanned,
            scan_truncated=truncated,
            scan_limit=self.settings.summary_max_products,
        )

    async def get_inventory_summary(
        self, params: InventorySummaryInput
    ) -> InventorySummary:
        threshold = (
            self.settings.low_stock_threshold if params.threshold is None else params.threshold
        )
        tracked = untracked = out_of_stock = low_stock = units = 0
        scanned = 0
        truncated = False
        total_products: int | None = None

        async for page in self.client.paginate(
            "/products",
            params={"status": "publish"},
            per_page=self.settings.summary_scan_page_size,
        ):
            if total_products is None:
                total_products = page.total
            for product in page.items:
                scanned += 1
                if _stock_tracked(product):
                    tracked += 1
                    quantity = _as_int(product.get("stock_quantity"))
                    if quantity is not None and quantity > 0:
                        units += quantity
                    if quantity is not None and 0 < quantity <= threshold:
                        low_stock += 1
                else:
                    untracked += 1
                if product.get("stock_status") == "outofstock":
                    out_of_stock += 1
            if scanned >= self.settings.summary_max_products:
                truncated = True
                break

        notes = [
            "Out-of-stock products are counted separately from low-stock products.",
            "Untracked products have no numeric quantity; their stock is unknown.",
            "Inventory monetary value is not calculated (cost data is not available).",
        ]
        if truncated:
            notes.append(
                f"Scan stopped at the configured limit of {self.settings.summary_max_products} "
                "products; quantity metrics cover only the scanned subset."
            )

        return InventorySummary(
            total_products=total_products,
            products_scanned=scanned,
            stock_tracked_products=tracked,
            untracked_products=untracked,
            out_of_stock_products=out_of_stock,
            low_stock_products=low_stock,
            total_units_in_stock=units,
            low_stock_threshold=threshold,
            scan_truncated=truncated,
            scan_limit=self.settings.summary_max_products,
            notes=notes,
        )

    async def calculate_reorder_quantity(self, params: ReorderInput) -> ReorderRecommendation:
        product = await self._resolve_product(params.product_id, params.sku)
        tracked = _stock_tracked(product)
        current = _as_int(product.get("stock_quantity")) if tracked else None
        effective_current = current if current is not None else 0
        required = params.target_stock_level + params.safety_buffer
        suggested = max(required - effective_current, 0)

        if not tracked:
            rationale = (
                "This product does not track stock in WooCommerce, so its quantity is "
                "unknown. The suggestion assumes zero on hand; verify manually before ordering."
            )
        elif suggested == 0:
            rationale = (
                f"Current stock ({effective_current}) already meets the target "
                f"({params.target_stock_level}) plus safety buffer ({params.safety_buffer})."
            )
        else:
            rationale = (
                f"Target {params.target_stock_level} plus safety buffer "
                f"{params.safety_buffer} minus current stock {effective_current} "
                f"= {suggested} units suggested."
            )

        return ReorderRecommendation(
            product_id=product["id"],
            name=product.get("name") or "",
            sku=product.get("sku") or None,
            current_stock=current,
            target_stock_level=params.target_stock_level,
            safety_buffer=params.safety_buffer,
            suggested_reorder_quantity=suggested,
            stock_status=product.get("stock_status"),
            backorders=product.get("backorders"),
            rationale=rationale,
        )


def ensure_supported_product(product: dict[str, Any]) -> dict[str, Any]:
    """Guard against malformed upstream payloads before tool-level access."""
    if "id" not in product:
        raise UpstreamError("WooCommerce product payload is missing an id")
    return product
