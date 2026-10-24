"""Shipping tool handlers: order validation plus the mock provider."""

from __future__ import annotations

from services.common.config import ShippingSettings
from services.common.errors import ValidationError
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


class ShippingTools:
    def __init__(
        self,
        client: WooCommerceClient,
        provider: ShippingProvider,
        settings: ShippingSettings,
    ) -> None:
        self.client = client
        self.provider = provider
        self.settings = settings

    async def create_shipment(self, payload: CreateShipmentInput) -> Shipment:
        order = await self.client.get_order(payload.order_id)
        status = str(order.get("status") or "")
        if status in {"cancelled", "refunded", "trash", "failed"}:
            raise ValidationError(
                f"cannot create a shipment for an order in status {status!r}",
                details={"order_id": payload.order_id},
            )
        number = order.get("number")
        return await self.provider.create(
            payload, order_number=str(number) if number is not None else None
        )

    async def track_shipment(self, payload: ShipmentIdentifierInput) -> ShipmentDetails:
        return await self.provider.track(payload)

    async def get_shipment(self, payload: GetShipmentInput) -> ShipmentDetails:
        return await self.provider.get(payload)

    async def update_shipment_status(
        self, payload: UpdateShipmentStatusInput
    ) -> ShipmentStatusUpdate:
        return await self.provider.update_status(payload)

    async def list_shipments(self, payload: ListShipmentsInput) -> ShipmentList:
        return await self.provider.list(payload)
