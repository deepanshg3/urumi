"""FastMCP server factory and HTTP app for the Inventory MCP server."""

from __future__ import annotations

import contextlib
from collections.abc import AsyncIterator, Awaitable

from fastapi import FastAPI
from mcp.server.fastmcp import FastMCP
from mcp.server.fastmcp.exceptions import ToolError
from mcp.server.transport_security import TransportSecuritySettings
from pydantic import Field, ValidationError as PydanticValidationError
from typing import Annotated
from starlette.responses import JSONResponse

from services.common.config import AppSettings
from services.common.errors import WooCommerceError
from services.common.logging import configure_logging, get_logger
from services.common.woocommerce import WooCommerceClient
from services.inventory_mcp.models import (
    CheckStockInput,
    FindLowStockInput,
    InventorySummary,
    InventorySummaryInput,
    LowStockList,
    ReorderInput,
    ReorderRecommendation,
    StockInfo,
)
from services.inventory_mcp.tools import InventoryTools

logger = get_logger("urumi.inventory_mcp")


def _transport_security(settings: AppSettings) -> TransportSecuritySettings:
    hosts = settings.allowed_host_list
    origins = settings.allowed_origin_list
    if not hosts and settings.host in {"127.0.0.1", "localhost", "::1"}:
        hosts = ["127.0.0.1:*", "localhost:*", "[::1]:*"]
    if not origins and settings.host in {"127.0.0.1", "localhost", "::1"}:
        origins = ["http://127.0.0.1:*", "http://localhost:*", "http://[::1]:*"]
    return TransportSecuritySettings(
        enable_dns_rebinding_protection=settings.enable_dns_rebinding_protection,
        allowed_hosts=hosts,
        allowed_origins=origins,
    )


def build_tools(settings: AppSettings, client: WooCommerceClient | None = None) -> InventoryTools:
    return InventoryTools(
        client or WooCommerceClient(settings.woocommerce), settings.inventory
    )


def create_mcp(settings: AppSettings, tools: InventoryTools) -> FastMCP:
    mcp = FastMCP(
        name="urumi-inventory",
        instructions=(
            "Inventory tools backed by the WooCommerce REST API, which is the single "
            "source of truth for products and stock. This server is read-only: it never "
            "places purchase orders and never modifies stock. All thresholds are advisory."
        ),
        host=settings.host,
        port=settings.port,
        streamable_http_path=settings.mcp_path,
        stateless_http=settings.stateless_http,
        json_response=settings.json_response,
        log_level=settings.logging.level,
        transport_security=_transport_security(settings),
    )

    async def _call(coro_factory):
        try:
            return await coro_factory()
        except WooCommerceError as exc:
            logger.warning("tool error code=%s message=%s", exc.code, exc.message)
            raise ToolError(f"{exc.code}: {exc.message}") from exc
        except PydanticValidationError as exc:
            first = exc.errors()[0] if exc.errors() else {}
            location = ".".join(str(part) for part in first.get("loc", ()))
            message = first.get("msg", "invalid input")
            raise ToolError(
                f"validation_error: {location}: {message}" if location else f"validation_error: {message}"
            ) from exc

    @mcp.tool(
        name="check_stock",
        description=(
            "Look up current stock for one product by WooCommerce product_id or SKU. "
            "Returns the available quantity, stock status, backorder policy and whether "
            "stock tracking is enabled. Exactly one identifier must be provided."
        ),
    )
    async def check_stock(
        product_id: Annotated[
            int | None, Field(ge=1, description="WooCommerce product ID")
        ] = None,
        sku: Annotated[str | None, Field(max_length=100, description="Product SKU")] = None,
    ) -> StockInfo:
        return await _call(
            lambda: tools.check_stock(CheckStockInput(product_id=product_id, sku=sku))
        )

    @mcp.tool(
        name="find_low_stock_products",
        description=(
            "List products at or below a configurable stock threshold. Results are "
            "paginated and the catalogue is scanned in bounded pages rather than loaded "
            "into memory. Products with zero stock are included (they are at or below the "
            "threshold); use stock_status to distinguish out-of-stock items."
        ),
    )
    async def find_low_stock_products(
        threshold: Annotated[
            int | None, Field(ge=0, description="Stock threshold; defaults to server config")
        ] = None,
        page: Annotated[int, Field(ge=1, description="Result page, starting at 1")] = 1,
        per_page: Annotated[int, Field(ge=1, le=100, description="Results per page")] = 20,
    ) -> LowStockList:
        return await _call(
            lambda: tools.find_low_stock_products(
                FindLowStockInput(threshold=threshold, page=page, per_page=per_page)
            )
        )

    @mcp.tool(
        name="get_inventory_summary",
        description=(
            "Summarize the published product catalogue: total products, tracked vs "
            "untracked stock, out-of-stock items, low-stock items and total tracked units. "
            "Out-of-stock and low-stock are counted separately. Inventory monetary value "
            "is intentionally not calculated and is always returned as null."
        ),
    )
    async def get_inventory_summary(
        threshold: Annotated[
            int | None, Field(ge=0, description="Low-stock threshold; defaults to server config")
        ] = None,
    ) -> InventorySummary:
        return await _call(
            lambda: tools.get_inventory_summary(InventorySummaryInput(threshold=threshold))
        )

    @mcp.tool(
        name="calculate_reorder_quantity",
        description=(
            "Suggest a replenishment quantity for one product: target stock level plus "
            "optional safety buffer, minus current stock, never negative. Advisory only: "
            "no purchase order is placed and stock is not modified."
        ),
    )
    async def calculate_reorder_quantity(
        product_id: Annotated[
            int | None, Field(ge=1, description="WooCommerce product ID")
        ] = None,
        sku: Annotated[str | None, Field(max_length=100, description="Product SKU")] = None,
        target_stock_level: Annotated[
            int, Field(ge=0, description="Desired stock level after replenishment")
        ] = 0,
        safety_buffer: Annotated[
            int, Field(ge=0, description="Extra units to keep as a safety buffer")
        ] = 0,
    ) -> ReorderRecommendation:
        def invoke() -> Awaitable[ReorderRecommendation]:
            params = ReorderInput(
                product_id=product_id,
                sku=sku,
                target_stock_level=target_stock_level,
                safety_buffer=safety_buffer,
            )
            return tools.calculate_reorder_quantity(params)

        return await _call(invoke)

    return mcp


def create_app(settings: AppSettings, tools: InventoryTools | None = None) -> FastAPI:
    configure_logging(settings.logging.level, service=settings.service_name)
    tools = tools or build_tools(settings)
    mcp = create_mcp(settings, tools)

    @contextlib.asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        logger.info(
            "starting %s mcp_path=%s port=%s", settings.service_name, settings.mcp_path, settings.port
        )
        async with mcp.session_manager.run():
            yield
        await tools.client.aclose()
        logger.info("stopped %s", settings.service_name)

    app = FastAPI(
        title="Urumi Inventory MCP",
        version="0.1.0",
        description="Custom inventory MCP server backed by WooCommerce (Streamable HTTP).",
        lifespan=lifespan,
    )

    @app.get("/health", tags=["health"])
    async def health() -> dict[str, object]:
        return {
            "status": "ok",
            "service": settings.service_name,
            "transport": "streamable-http",
            "mcp_path": settings.mcp_path,
        }

    @app.get("/health/ready", tags=["health"])
    async def readiness() -> JSONResponse:
        try:
            settings.woocommerce.require_credentials()
            await tools.client.list_products(per_page=1)
        except WooCommerceError as exc:
            return JSONResponse(
                status_code=503,
                content={
                    "status": "not_ready",
                    "service": settings.service_name,
                    "error": exc.code,
                    "message": exc.message,
                },
            )
        return JSONResponse(
            status_code=200,
            content={
                "status": "ready",
                "service": settings.service_name,
                "auth_mode": settings.woocommerce.resolved_auth_mode,
                "low_stock_threshold": settings.inventory.low_stock_threshold,
            },
        )

    app.mount("/", mcp.streamable_http_app())
    return app
