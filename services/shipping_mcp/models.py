"""Typed inputs and outputs for the shipping MCP tools."""

from __future__ import annotations

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

ShipmentStatus = Literal["created", "in_transit", "delivered", "exception", "cancelled"]

ALLOWED_STATUS_TRANSITIONS: dict[str, set[str]] = {
    "created": {"in_transit", "cancelled"},
    "in_transit": {"delivered", "exception", "cancelled"},
    "exception": {"in_transit", "cancelled"},
    "delivered": set(),
    "cancelled": set(),
}


class CreateShipmentInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    order_id: int = Field(ge=1, description="Existing WooCommerce order ID")
    carrier: str | None = Field(None, max_length=64, description="Mock carrier name")
    service: str | None = Field(
        None, max_length=64, description="Shipping service, e.g. standard or express"
    )
    notes: str | None = Field(None, max_length=1000, description="Internal shipping note")
    allow_duplicate: bool = Field(
        False,
        description="Allow a second shipment for the same order when configured to permit it",
    )


class ShipmentIdentifierInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    shipment_id: str | None = Field(None, max_length=64, description="Shipment public ID")
    tracking_number: str | None = Field(None, max_length=64, description="Mock tracking number")

    @model_validator(mode="after")
    def _exactly_one(self) -> "ShipmentIdentifierInput":
        if bool(self.shipment_id) == bool(self.tracking_number):
            raise ValueError("provide exactly one of shipment_id or tracking_number")
        return self


class GetShipmentInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    shipment_id: str | None = Field(None, max_length=64, description="Shipment public ID")
    order_id: int | None = Field(None, ge=1, description="WooCommerce order ID")

    @model_validator(mode="after")
    def _exactly_one(self) -> "GetShipmentInput":
        if bool(self.shipment_id) == bool(self.order_id):
            raise ValueError("provide exactly one of shipment_id or order_id")
        return self


class UpdateShipmentStatusInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    shipment_id: str = Field(min_length=1, max_length=64, description="Shipment public ID")
    status: ShipmentStatus = Field(description="New status")
    note: str | None = Field(None, max_length=500, description="Optional status note")


class ListShipmentsInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    page: int = Field(1, ge=1)
    per_page: int = Field(20, ge=1, le=100)
    status: ShipmentStatus | None = None
    order_id: int | None = Field(None, ge=1)


class TrackingEvent(BaseModel):
    status: str
    description: str
    timestamp: datetime
    mock: bool = True


class Shipment(BaseModel):
    model_config = ConfigDict(extra="ignore")

    shipment_id: str
    order_id: int
    order_number: str | None = None
    tracking_number: str
    carrier: str
    service: str | None = None
    status: ShipmentStatus
    estimated_delivery: date | None = None
    notes: str | None = None
    mock: bool = True
    created_at: datetime
    updated_at: datetime


class ShipmentDetails(Shipment):
    tracking_history: list[TrackingEvent] = Field(default_factory=list)


class ShipmentList(BaseModel):
    items: list[Shipment]
    page: int
    per_page: int
    total: int
    has_more: bool


class ShipmentStatusUpdate(BaseModel):
    shipment_id: str
    order_id: int
    previous_status: ShipmentStatus
    status: ShipmentStatus
    tracking_history: list[TrackingEvent]
    updated_at: datetime
