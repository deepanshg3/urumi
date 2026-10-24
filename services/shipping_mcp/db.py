"""Isolated persistence for the shipping mock provider.

Shipment records are operational shipping data, not gateway metadata, so they
live in their own database (`SHIPPING_DATABASE_URL`, default
``sqlite+aiosqlite:///./data/shipping.db``). SQLite is used only for this
mock/operational store; WooCommerce and WordPress stay on MariaDB.
"""

from __future__ import annotations

from datetime import datetime, timezone

import os

from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Integer, String, Text, select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class ShippingBase(DeclarativeBase):
    pass


class ShipmentRecord(ShippingBase):
    __tablename__ = "shipments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    public_id: Mapped[str] = mapped_column(String(36), unique=True, nullable=False, index=True)
    order_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    order_number: Mapped[str | None] = mapped_column(String(64))
    tracking_number: Mapped[str] = mapped_column(
        String(64), unique=True, nullable=False, index=True
    )
    carrier: Mapped[str] = mapped_column(String(64), nullable=False)
    service: Mapped[str | None] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    estimated_delivery: Mapped[datetime | None] = mapped_column(Date)
    notes: Mapped[str | None] = mapped_column(Text)
    mock: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False
    )

    events: Mapped[list["ShipmentEvent"]] = relationship(
        back_populates="shipment",
        cascade="all, delete-orphan",
        order_by="ShipmentEvent.created_at",
        lazy="selectin",
    )


class ShipmentEvent(ShippingBase):
    __tablename__ = "shipment_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    shipment_id: Mapped[int] = mapped_column(
        ForeignKey("shipments.id", ondelete="CASCADE"), nullable=False, index=True
    )
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    mock: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False, index=True
    )

    shipment: Mapped[ShipmentRecord] = relationship(back_populates="events")


class ShippingDatabase:
    """Owns an async engine and session factory for the shipping store."""

    def __init__(self, url: str | None = None, *, echo: bool = False) -> None:
        self.url = (
            url or os.environ.get("SHIPPING_DATABASE_URL") or "sqlite+aiosqlite:///./data/shipping.db"
        )
        self.engine: AsyncEngine = create_async_engine(self.url, echo=echo, future=True)
        self.session_factory: async_sessionmaker[AsyncSession] = async_sessionmaker(
            self.engine, expire_on_commit=False
        )

    async def create_all(self) -> None:
        async with self.engine.begin() as connection:
            await connection.run_sync(ShippingBase.metadata.create_all)

    async def drop_all(self) -> None:
        async with self.engine.begin() as connection:
            await connection.run_sync(ShippingBase.metadata.drop_all)

    async def dispose(self) -> None:
        await self.engine.dispose()


async def find_shipment(
    session,
    *,
    public_id: str | None = None,
    tracking_number: str | None = None,
    order_id: int | None = None,
    newest_first: bool = False,
) -> ShipmentRecord | None:
    stmt = select(ShipmentRecord)
    if public_id:
        stmt = stmt.where(ShipmentRecord.public_id == public_id)
    if tracking_number:
        stmt = stmt.where(ShipmentRecord.tracking_number == tracking_number)
    if order_id:
        stmt = stmt.where(ShipmentRecord.order_id == order_id)
    if newest_first:
        stmt = stmt.order_by(ShipmentRecord.created_at.desc())
    return (await session.execute(stmt)).scalars().first()


async def count_for_order(session, order_id: int) -> int:
    stmt = select(ShipmentRecord.id).where(ShipmentRecord.order_id == order_id)
    return len((await session.execute(stmt)).scalars().all())
