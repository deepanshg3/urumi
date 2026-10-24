"""FastMCP server factory and HTTP app for the WooCommerce MCP server."""

from __future__ import annotations

import contextlib
from collections.abc import AsyncIterator, Awaitable
from typing import Annotated

from fastapi import FastAPI
from mcp.server.fastmcp import FastMCP
from mcp.server.fastmcp.exceptions import ToolError
from mcp.server.transport_security import TransportSecuritySettings
from pydantic import Field
from pydantic import ValidationError as PydanticValidationError
from starlette.requests import Request
from starlette.responses import JSONResponse

from services.common.config import AppSettings
from services.common.errors import WooCommerceError
from services.common.logging import configure_logging, get_logger
from services.common.woocommerce import WooCommerceClient
from services.woocommerce_mcp.models import (
    CreateProductInput,
    GetOrderInput,
    ListOrdersInput,
    ListProductsInput,
    OrderDetail,
    OrderList,
    OrderStatusUpdate,
    ProductCreated,
    ProductList,
    UpdateOrderStatusInput,
)
from services.woocommerce_mcp.tools import WooCommerceTools

logger = get_logger("urumi.woocommerce_mcp")


def _transport_security(settings: AppSettings) -> TransportSecuritySettings:
    """Build DNS-rebinding protection settings from configuration.

    Defaults to loopback-only hosts when the server binds to a loopback
    address. Container deployments set MCP_ALLOWED_HOSTS explicitly.
    """
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


def build_tools(settings: AppSettings, client: WooCommerceClient | None = None) -> WooCommerceTools:
    return WooCommerceTools(client or WooCommerceClient(settings.woocommerce))


def create_mcp(settings: AppSettings, tools: WooCommerceTools) -> FastMCP:
    """Create the FastMCP instance and register the five WooCommerce tools."""
    mcp = FastMCP(
        name="urumi-woocommerce",
        instructions=(
            "WooCommerce product and order tools for the Urumi MCP Gateway. "
            "All data comes from the store's official WooCommerce REST API. "
            "Prices are decimal strings in the store currency."
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
        name="list_products",
        description=(
            "List WooCommerce products with pagination. Optionally filter by free-text "
            "search, exact SKU, or stock status (instock, outofstock, onbackorder). "
            "Returns compact product records and pagination metadata."
        ),
    )
    async def list_products(
        page: Annotated[int, Field(ge=1, description="Page number, starting at 1")] = 1,
        per_page: Annotated[
            int, Field(ge=1, le=100, description="Results per page (max 100)")
        ] = 20,
        search: Annotated[
            str | None, Field(max_length=200, description="Free-text search")
        ] = None,
        stock_status: Annotated[
            str | None,
            Field(description="instock, outofstock or onbackorder"),
        ] = None,
        sku: Annotated[str | None, Field(max_length=100, description="Exact SKU")] = None,
        status: Annotated[
            str | None,
            Field(description="publish, draft, pending, private or any"),
        ] = "publish",
    ) -> ProductList:
        def invoke() -> Awaitable[ProductList]:
            params = ListProductsInput(
                page=page,
                per_page=per_page,
                search=search,
                stock_status=stock_status,  # type: ignore[arg-type]
                sku=sku,
                status=status,  # type: ignore[arg-type]
            )
            return tools.list_products(params)

        return await _call(invoke)

    @mcp.tool(
        name="create_product",
        description=(
            "Create a WooCommerce product with a name and price. Optionally set a unique "
            "SKU, stock quantity and description. If the SKU already exists the call fails "
            "by default instead of creating a duplicate; pass if_sku_exists='return_existing' "
            "to return the existing product instead."
        ),
    )
    async def create_product(
        name: Annotated[str, Field(min_length=1, max_length=200, description="Product name")],
        price: Annotated[str, Field(description="Regular price, e.g. '19.99'")],
        sku: Annotated[str | None, Field(max_length=100, description="Unique SKU")] = None,
        stock_quantity: Annotated[
            int | None, Field(ge=0, le=1_000_000, description="Initial stock quantity")
        ] = None,
        stock_status: Annotated[
            str | None, Field(description="instock, outofstock or onbackorder")
        ] = None,
        description: Annotated[
            str | None, Field(max_length=5000, description="Plain-text description")
        ] = None,
        if_sku_exists: Annotated[
            str,
            Field(description="error (default) or return_existing"),
        ] = "error",
    ) -> ProductCreated:
        def invoke() -> Awaitable[ProductCreated]:
            params = CreateProductInput(
                name=name,
                price=price,
                sku=sku,
                stock_quantity=stock_quantity,
                stock_status=stock_status,  # type: ignore[arg-type]
                description=description,
                if_sku_exists=if_sku_exists,  # type: ignore[arg-type]
            )
            return tools.create_product(params)

        return await _call(invoke)

    @mcp.tool(
        name="list_orders",
        description=(
            "List WooCommerce orders with pagination and optional status and date filters. "
            "Naive datetimes are interpreted as UTC; results include the applied UTC bounds. "
            "Customer email, phone and address are never returned."
        ),
    )
    async def list_orders(
        page: Annotated[int, Field(ge=1, description="Page number, starting at 1")] = 1,
        per_page: Annotated[int, Field(ge=1, le=100, description="Results per page")] = 20,
        status: Annotated[
            str | None,
            Field(
                description=(
                    "pending, processing, on-hold, completed, cancelled, refunded, "
                    "failed, trash or any"
                )
            ),
        ] = None,
        after: Annotated[
            str | None,
            Field(description="ISO-8601 start bound (inclusive); naive means UTC"),
        ] = None,
        before: Annotated[
            str | None,
            Field(description="ISO-8601 end bound (exclusive); naive means UTC"),
        ] = None,
    ) -> OrderList:
        def invoke() -> Awaitable[OrderList]:
            params = ListOrdersInput(
                page=page,
                per_page=per_page,
                status=status,  # type: ignore[arg-type]
                after=after,  # type: ignore[arg-type]
                before=before,  # type: ignore[arg-type]
            )
            return tools.list_orders(params)

        return await _call(invoke)

    @mcp.tool(
        name="get_order",
        description=(
            "Retrieve a single WooCommerce order by ID, including line items. "
            "Returns a clear not-found error when the order does not exist. "
            "Customer email, phone and address are omitted."
        ),
    )
    async def get_order(
        order_id: Annotated[int, Field(ge=1, description="WooCommerce order ID")],
    ) -> OrderDetail:
        return await _call(lambda: tools.get_order(GetOrderInput(order_id=order_id)))

    @mcp.tool(
        name="update_order_status",
        description=(
            "Update the status of an existing WooCommerce order. Supported statuses: "
            "pending, processing, on-hold, completed, cancelled, refunded, failed, trash. "
            "Fails clearly for missing orders and upstream errors. Not retried automatically."
        ),
    )
    async def update_order_status(
        order_id: Annotated[int, Field(ge=1, description="WooCommerce order ID")],
        status: Annotated[
            str,
            Field(
                description=(
                    "pending, processing, on-hold, completed, cancelled, refunded, "
                    "failed or trash"
                )
            ),
        ],
    ) -> OrderStatusUpdate:
        def invoke() -> Awaitable[OrderStatusUpdate]:
            params = UpdateOrderStatusInput(
                order_id=order_id,
                status=status,  # type: ignore[arg-type]
            )
            return tools.update_order_status(params)

        return await _call(invoke)

    return mcp


def create_app(settings: AppSettings, tools: WooCommerceTools | None = None) -> FastAPI:
    """Create the FastAPI app hosting the MCP endpoint and health checks."""
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
        title="Urumi WooCommerce MCP",
        version="0.1.0",
        description="Custom WooCommerce MCP server (Streamable HTTP).",
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
        """Check configuration and upstream reachability (no credentials leaked)."""
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
            },
        )

    app.mount("/", mcp.streamable_http_app())
    return app
