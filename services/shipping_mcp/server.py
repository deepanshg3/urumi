"""FastMCP server and HTTP app for shipping and fulfillment (Pass 4)."""

from __future__ import annotations

import contextlib
from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import FastAPI
from mcp.server.fastmcp import FastMCP
from mcp.server.fastmcp.exceptions import ToolError
from mcp.server.transport_security import TransportSecuritySettings
from pydantic import Field, ValidationError as PydanticValidationError
from sqlalchemy import text
from starlette.responses import JSONResponse

from services.common.config import AppSettings
from services.common.errors import ServiceError
from services.common.logging import configure_logging, get_logger
from services.common.woocommerce import WooCommerceClient
from services.shipping_mcp.models import (
    CreateShipmentInput,
    GetShipmentInput,
    ListShipmentsInput,
    Shipment,
    ShipmentDetails,
    ShipmentIdentifierInput,
    ShipmentList,
    ShipmentStatusUpdate,
    UpdateShipmentStatusInput,
)
from services.shipping_mcp.provider import ShippingProvider
from services.shipping_mcp.tools import ShippingTools

logger = get_logger("urumi.shipping_mcp")


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


def build_tools(
    settings: AppSettings,
    *,
    client: WooCommerceClient | None = None,
    provider: ShippingProvider | None = None,
) -> ShippingTools:
    woo_client = client or WooCommerceClient(settings.woocommerce)
    return ShippingTools(
        woo_client,
        provider or ShippingProvider(settings.shipping),
        settings.shipping,
    )


def create_mcp(settings: AppSettings, tools: ShippingTools) -> FastMCP:
    mcp = FastMCP(
        name="urumi-shipping",
        instructions=(
            "Mock shipping and fulfillment tools. Shipments are stored locally and "
            "tracking events are simulated; no real carrier is contacted. A shipment "
            "record never changes a WooCommerce order status automatically."
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
        except ServiceError as exc:
            logger.warning("tool error code=%s message=%s", exc.code, exc.message)
            raise ToolError(f"{exc.code}: {exc.message}") from exc
        except PydanticValidationError as exc:
            first = exc.errors()[0] if exc.errors() else {}
            location = ".".join(str(part) for part in first.get("loc", ()))
            message = first.get("msg", "invalid input")
            raise ToolError(
                f"validation_error: {location}: {message}"
                if location
                else f"validation_error: {message}"
            ) from exc

    @mcp.tool(
        name="create_shipment",
        description=(
            "Create a mock shipment for an existing WooCommerce order. Validates the order, "
            "prevents duplicate shipments unless duplicates are explicitly enabled, generates "
            "a mock tracking number and returns the shipment. Does not update the order status."
        ),
    )
    async def create_shipment(
        order_id: Annotated[int, Field(ge=1, description="Existing WooCommerce order ID")],
        carrier: Annotated[str | None, Field(max_length=64, description="Mock carrier")] = None,
        service: Annotated[
            str | None, Field(max_length=64, description="Service level, e.g. standard")
        ] = None,
        notes: Annotated[str | None, Field(max_length=1000, description="Internal note")] = None,
        allow_duplicate: Annotated[
            bool,
            Field(description="Allow another shipment only if server config permits duplicates"),
        ] = False,
    ) -> Shipment:
        return await _call(
            lambda: tools.create_shipment(
                CreateShipmentInput(
                    order_id=order_id,
                    carrier=carrier,
                    service=service,
                    notes=notes,
                    allow_duplicate=allow_duplicate,
                )
            )
        )

    @mcp.tool(
        name="track_shipment",
        description=(
            "Return a shipment's current status and mock tracking history by shipment_id or "
            "tracking_number. Every event is explicitly marked mock=true."
        ),
    )
    async def track_shipment(
        shipment_id: Annotated[str | None, Field(max_length=64)] = None,
        tracking_number: Annotated[str | None, Field(max_length=64)] = None,
    ) -> ShipmentDetails:
        return await _call(
            lambda: tools.track_shipment(
                ShipmentIdentifierInput(
                    shipment_id=shipment_id, tracking_number=tracking_number
                )
            )
        )

    @mcp.tool(
        name="get_shipment",
        description=(
            "Return shipment details by shipment_id or WooCommerce order_id. When multiple "
            "shipments exist for an order, the newest is returned."
        ),
    )
    async def get_shipment(
        shipment_id: Annotated[str | None, Field(max_length=64)] = None,
        order_id: Annotated[int | None, Field(ge=1)] = None,
    ) -> ShipmentDetails:
        return await _call(
            lambda: tools.get_shipment(
                GetShipmentInput(shipment_id=shipment_id, order_id=order_id)
            )
        )

    @mcp.tool(
        name="update_shipment_status",
        description=(
            "Update a mock shipment status with validated transitions: created -> in_transit "
            "or cancelled; in_transit -> delivered, exception or cancelled; exception -> "
            "in_transit or cancelled. Delivered and cancelled are terminal. History is recorded."
        ),
    )
    async def update_shipment_status(
        shipment_id: Annotated[str, Field(min_length=1, max_length=64)],
        status: Annotated[
            str, Field(description="in_transit, delivered, exception or cancelled")
        ],
        note: Annotated[str | None, Field(max_length=500)] = None,
    ) -> ShipmentStatusUpdate:
        return await _call(
            lambda: tools.update_shipment_status(
                UpdateShipmentStatusInput(
                    shipment_id=shipment_id, status=status, note=note  # type: ignore[arg-type]
                )
            )
        )

    @mcp.tool(
        name="list_shipments",
        description="List stored mock shipments with pagination and optional status/order filters.",
    )
    async def list_shipments(
        page: Annotated[int, Field(ge=1)] = 1,
        per_page: Annotated[int, Field(ge=1, le=100)] = 20,
        status: Annotated[
            str | None, Field(description="created, in_transit, delivered, exception or cancelled")
        ] = None,
        order_id: Annotated[int | None, Field(ge=1)] = None,
    ) -> ShipmentList:
        return await _call(
            lambda: tools.list_shipments(
                ListShipmentsInput(
                    page=page,
                    per_page=per_page,
                    status=status,  # type: ignore[arg-type]
                    order_id=order_id,
                )
            )
        )

    return mcp


def create_app(settings: AppSettings, tools: ShippingTools | None = None) -> FastAPI:
    configure_logging(settings.logging.level, service=settings.service_name)
    tools = tools or build_tools(settings)
    mcp = create_mcp(settings, tools)

    @contextlib.asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        await tools.provider.initialize()
        logger.info(
            "starting %s provider_mode=%s mcp_path=%s port=%s",
            settings.service_name,
            settings.shipping.mode,
            settings.mcp_path,
            settings.port,
        )
        try:
            async with mcp.session_manager.run():
                yield
        finally:
            await tools.client.aclose()
            await tools.provider.close()
            logger.info("stopped %s", settings.service_name)

    app = FastAPI(
        title="Urumi Shipping MCP",
        version="0.1.0",
        description="Mock shipping and fulfillment MCP server (Streamable HTTP).",
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
            await tools.client.list_orders(per_page=1)
            async with tools.provider.db.session_factory() as session:
                await session.execute(text("SELECT 1"))
        except ServiceError as exc:
            return JSONResponse(
                status_code=503,
                content={
                    "status": "not_ready",
                    "service": settings.service_name,
                    "error": exc.code,
                    "message": exc.message,
                },
            )
        except Exception:  # pragma: no cover - defensive, no secrets in message
            logger.exception("readiness check failed")
            return JSONResponse(
                status_code=503,
                content={
                    "status": "not_ready",
                    "service": settings.service_name,
                    "error": "storage_unavailable",
                },
            )
        return JSONResponse(
            status_code=200,
            content={
                "status": "ready",
                "service": settings.service_name,
                "provider_mode": settings.shipping.mode,
                "delivery_days": [
                    settings.shipping.delivery_days_min,
                    settings.shipping.delivery_days_max,
                ],
            },
        )

    app.mount("/", mcp.streamable_http_app())
    return app
