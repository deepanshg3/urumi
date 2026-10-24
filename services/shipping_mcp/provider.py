"""Mock shipping provider.

The provider interface is intentionally small so a real carrier can replace the
mock without changing MCP tool names or schemas. Every emitted event carries
``mock=True``; nothing here contacts a real carrier.
"""

from __future__ import annotations

import hashlib
import random
import uuid
from datetime import date, datetime, timedelta, timezone

from sqlalchemy import func, select

from services.common.config import ShippingSettings
from services.common.errors import ConflictError, NotFoundError, UpstreamError, ValidationError
from services.shipping_mcp.db import (
    ShipmentEvent,
    ShipmentRecord,
    ShippingDatabase,
    find_shipment,
)
from services.shipping_mcp.models import (
    ALLOWED_STATUS_TRANSITIONS,
    CreateShipmentInput,
    GetShipmentInput,
    ListShipmentsInput,
    Shipment,
    ShipmentDetails,
    ShipmentIdentifierInput,
    ShipmentList,
    ShipmentStatus,
    ShipmentStatusUpdate,
    TrackingEvent,
    UpdateShipmentStatusInput,
)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class ShippingProvider:
    """Persistence-backed mock provider with deterministic estimates."""

    def __init__(self, settings: ShippingSettings, database: ShippingDatabase | None = None) -> None:
        self.settings = settings
        self.db = database or ShippingDatabase(settings.database_url)
        self._owns_db = database is None

    async def initialize(self) -> None:
        await self.db.create_all()

    async def close(self) -> None:
        if self._owns_db:
            await self.db.dispose()

    # -- serialization -----------------------------------------------------
    @staticmethod
    def _to_model(record: ShipmentRecord) -> Shipment:
        return Shipment(
            shipment_id=record.public_id,
            order_id=record.order_id,
            order_number=record.order_number,
            tracking_number=record.tracking_number,
            carrier=record.carrier,
            service=record.service,
            status=record.status,  # type: ignore[arg-type]
            estimated_delivery=record.estimated_delivery,
            notes=record.notes,
            mock=record.mock,
            created_at=record.created_at,
            updated_at=record.updated_at,
        )

    @staticmethod
    def _events(record: ShipmentRecord) -> list[TrackingEvent]:
        return [
            TrackingEvent(
                status=event.status,
                description=event.description,
                timestamp=event.created_at,
                mock=event.mock,
            )
            for event in record.events
        ]

    # -- mock behavior -----------------------------------------------------
    def _simulate_failure(self) -> None:
        if self.settings.mode == "failing":
            raise UpstreamError("mock shipping provider is configured to fail")
        if self.settings.mode == "degraded" and self.settings.failure_rate > 0:
            if random.random() < self.settings.failure_rate:
                raise UpstreamError("mock shipping provider simulated a transient failure")

    def _tracking_number(self) -> str:
        return f"{self.settings.tracking_prefix}-{uuid.uuid4().hex[:12].upper()}"

    def _estimated_delivery(self, seed: str) -> date:
        span = self.settings.delivery_days_max - self.settings.delivery_days_min + 1
        digest = hashlib.sha256(seed.encode()).digest()
        days = self.settings.delivery_days_min + digest[0] % max(span, 1)
        return (_utcnow() + timedelta(days=days)).date()

    # -- operations --------------------------------------------------------
    async def create(
        self, payload: CreateShipmentInput, *, order_number: str | None = None
    ) -> Shipment:
        self._simulate_failure()
        async with self.db.session_factory() as session:
            existing = await find_shipment(session, order_id=payload.order_id, newest_first=True)
            if existing is not None and not (
                self.settings.allow_multiple_shipments_per_order and payload.allow_duplicate
            ):
                raise ConflictError(
                    f"order {payload.order_id} already has shipment {existing.public_id}",
                    details={"shipment_id": existing.public_id},
                )
            public_id = str(uuid.uuid4())
            record = ShipmentRecord(
                public_id=public_id,
                order_id=payload.order_id,
                order_number=order_number,
                tracking_number=self._tracking_number(),
                carrier=payload.carrier or self.settings.default_carrier,
                service=payload.service,
                status="created",
                estimated_delivery=self._estimated_delivery(public_id),
                notes=payload.notes,
                mock=True,
            )
            record.events.append(
                ShipmentEvent(
                    status="created",
                    description=(
                        "Mock shipment record created. No real carrier was contacted."
                    ),
                    mock=True,
                )
            )
            session.add(record)
            await session.commit()
            await session.refresh(record)
            return self._to_model(record)

    async def track(self, payload: ShipmentIdentifierInput) -> ShipmentDetails:
        async with self.db.session_factory() as session:
            record = await find_shipment(
                session,
                public_id=payload.shipment_id,
                tracking_number=payload.tracking_number,
            )
            if record is None:
                identifier = payload.shipment_id or payload.tracking_number
                raise NotFoundError("shipment", identifier)
            detail = ShipmentDetails(
                **self._to_model(record).model_dump(),
                tracking_history=self._events(record),
            )
            return detail

    async def get(self, payload: GetShipmentInput) -> ShipmentDetails:
        async with self.db.session_factory() as session:
            record = await find_shipment(
                session,
                public_id=payload.shipment_id,
                order_id=payload.order_id,
                newest_first=True,
            )
            if record is None:
                identifier = payload.shipment_id or payload.order_id
                raise NotFoundError("shipment", identifier)
            return ShipmentDetails(
                **self._to_model(record).model_dump(),
                tracking_history=self._events(record),
            )

    async def update_status(self, payload: UpdateShipmentStatusInput) -> ShipmentStatusUpdate:
        self._simulate_failure()
        async with self.db.session_factory() as session:
            record = await find_shipment(session, public_id=payload.shipment_id)
            if record is None:
                raise NotFoundError("shipment", payload.shipment_id)
            allowed = ALLOWED_STATUS_TRANSITIONS.get(record.status, set())
            if payload.status not in allowed:
                raise ValidationError(
                    f"invalid status transition {record.status!r} -> {payload.status!r}",
                    details={"allowed": sorted(allowed)},
                )
            previous = record.status
            record.status = payload.status
            record.updated_at = _utcnow()
            description = payload.note or f"Mock status updated to {payload.status}."
            record.events.append(
                ShipmentEvent(status=payload.status, description=description, mock=True)
            )
            await session.commit()
            await session.refresh(record)
            return ShipmentStatusUpdate(
                shipment_id=record.public_id,
                order_id=record.order_id,
                previous_status=previous,  # type: ignore[arg-type]
                status=payload.status,
                tracking_history=self._events(record),
                updated_at=record.updated_at,
            )

    async def list(self, payload: ListShipmentsInput) -> ShipmentList:
        async with self.db.session_factory() as session:
            filters = []
            if payload.status:
                filters.append(ShipmentRecord.status == payload.status)
            if payload.order_id:
                filters.append(ShipmentRecord.order_id == payload.order_id)
            total = (
                await session.execute(select(func.count(ShipmentRecord.id)).where(*filters))
            ).scalar_one()
            stmt = (
                select(ShipmentRecord)
                .where(*filters)
                .order_by(ShipmentRecord.created_at.desc())
                .offset((payload.page - 1) * payload.per_page)
                .limit(payload.per_page)
            )
            records = (await session.execute(stmt)).scalars().all()
            items = [self._to_model(record) for record in records]
            return ShipmentList(
                items=items,
                page=payload.page,
                per_page=payload.per_page,
                total=total,
                has_more=payload.page * payload.per_page < total,
            )
