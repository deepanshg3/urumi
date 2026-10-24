"""Pass 4: shipping provider, tools, persistence and HTTP surface tests."""

from __future__ import annotations

import httpx
import pytest

from services.common.config import ShippingSettings
from services.common.errors import ConflictError, NotFoundError, ValidationError
from services.shipping_mcp.db import ShippingDatabase
from services.shipping_mcp.models import (
    CreateShipmentInput,
    GetShipmentInput,
    ListShipmentsInput,
    ShipmentIdentifierInput,
    UpdateShipmentStatusInput,
)
from services.shipping_mcp.provider import ShippingProvider
from services.shipping_mcp.server import build_tools, create_app
from services.shipping_mcp.tools import ShippingTools
from tests.conftest import app_settings, json_response, make_client, order


def shipping_settings(tmp_path, **overrides) -> ShippingSettings:
    base = {
        "mode": "simulated",
        "failure_rate": 0.0,
        "default_carrier": "mock-carrier",
        "tracking_prefix": "TEST",
        "delivery_days_min": 2,
        "delivery_days_max": 4,
        "database_url": f"sqlite+aiosqlite:///{tmp_path}/shipping.db",
        "allow_multiple_shipments_per_order": False,
        "timeout_seconds": 5.0,
        "max_retries": 0,
    }
    base.update(overrides)
    return ShippingSettings(_env_file=None, **base)


@pytest.fixture
async def provider(tmp_path):
    p = ShippingProvider(shipping_settings(tmp_path))
    await p.initialize()
    try:
        yield p
    finally:
        await p.close()


@pytest.fixture
def woo_client():
    def handler(request: httpx.Request) -> httpx.Response:
        if "/orders/13" in request.url.path:
            return json_response(order(13))
        if "/orders/404" in request.url.path:
            return httpx.Response(
                404,
                json={"code": "woocommerce_rest_shop_order_invalid_id", "message": "Invalid ID."},
            )
        if request.url.path.endswith("/orders"):
            return json_response([order(13)])
        return httpx.Response(404, json={"code": "not_found", "message": "not found"})

    return make_client(handler)


@pytest.fixture
def tools(provider, woo_client):
    return ShippingTools(woo_client, provider, provider.settings)


async def test_create_shipment_generates_unique_mock_tracking(tools: ShippingTools) -> None:
    shipment = await tools.create_shipment(
        CreateShipmentInput(order_id=13, carrier="Mock Express", service="express")
    )
    assert shipment.order_id == 13
    assert shipment.status == "created"
    assert shipment.tracking_number.startswith("TEST-")
    assert shipment.carrier == "Mock Express"
    assert shipment.mock is True
    assert shipment.estimated_delivery is not None
    assert shipment.order_number == "13"


async def test_duplicate_shipment_is_rejected(tools: ShippingTools) -> None:
    await tools.create_shipment(CreateShipmentInput(order_id=13))
    with pytest.raises(ConflictError):
        await tools.create_shipment(CreateShipmentInput(order_id=13))


async def test_duplicate_allowed_when_configured(tmp_path, woo_client) -> None:
    provider = ShippingProvider(
        shipping_settings(tmp_path, allow_multiple_shipments_per_order=True)
    )
    await provider.initialize()
    try:
        tools = ShippingTools(woo_client, provider, provider.settings)
        first = await tools.create_shipment(CreateShipmentInput(order_id=13))
        second = await tools.create_shipment(
            CreateShipmentInput(order_id=13, allow_duplicate=True)
        )
        assert first.shipment_id != second.shipment_id
        newest = await tools.get_shipment(GetShipmentInput(order_id=13))
        assert newest.shipment_id == second.shipment_id
    finally:
        await provider.close()


async def test_shipment_survives_provider_restart(tmp_path, woo_client) -> None:
    settings = shipping_settings(tmp_path)
    first = ShippingProvider(settings)
    await first.initialize()
    created = await first.create(CreateShipmentInput(order_id=13))
    await first.close()

    second = ShippingProvider(settings)
    await second.initialize()
    try:
        detail = await second.get(GetShipmentInput(shipment_id=created.shipment_id))
        assert detail.tracking_number == created.tracking_number
        assert detail.tracking_history[0].status == "created"
        assert detail.tracking_history[0].mock is True
    finally:
        await second.close()


async def test_track_by_tracking_number_and_missing(tools: ShippingTools) -> None:
    shipment = await tools.create_shipment(CreateShipmentInput(order_id=13))
    detail = await tools.track_shipment(
        ShipmentIdentifierInput(tracking_number=shipment.tracking_number)
    )
    assert detail.shipment_id == shipment.shipment_id
    with pytest.raises(NotFoundError):
        await tools.track_shipment(ShipmentIdentifierInput(shipment_id="missing"))


async def test_status_transitions_are_validated(tools: ShippingTools) -> None:
    shipment = await tools.create_shipment(CreateShipmentInput(order_id=13))
    with pytest.raises(ValidationError):
        await tools.update_shipment_status(
            UpdateShipmentStatusInput(shipment_id=shipment.shipment_id, status="delivered")
        )
    moved = await tools.update_shipment_status(
        UpdateShipmentStatusInput(
            shipment_id=shipment.shipment_id, status="in_transit", note="Handed to mock carrier"
        )
    )
    assert moved.previous_status == "created"
    assert [event.status for event in moved.tracking_history] == ["created", "in_transit"]
    delivered = await tools.update_shipment_status(
        UpdateShipmentStatusInput(shipment_id=shipment.shipment_id, status="delivered")
    )
    assert delivered.status == "delivered"
    with pytest.raises(ValidationError):
        await tools.update_shipment_status(
            UpdateShipmentStatusInput(shipment_id=shipment.shipment_id, status="in_transit")
        )


async def test_failing_mode_rejects_mutations(tmp_path, woo_client) -> None:
    provider = ShippingProvider(shipping_settings(tmp_path, mode="failing"))
    await provider.initialize()
    try:
        tools = ShippingTools(woo_client, provider, provider.settings)
        with pytest.raises(Exception) as excinfo:
            await tools.create_shipment(CreateShipmentInput(order_id=13))
        assert "configured to fail" in str(excinfo.value)
    finally:
        await provider.close()


async def test_invalid_order_is_rejected(tools: ShippingTools) -> None:
    with pytest.raises(NotFoundError):
        await tools.create_shipment(CreateShipmentInput(order_id=404))


async def test_list_shipments_filters(tools: ShippingTools) -> None:
    await tools.create_shipment(CreateShipmentInput(order_id=13))
    listing = await tools.list_shipments(ListShipmentsInput(page=1, per_page=10))
    assert listing.total == 1
    assert listing.items[0].order_id == 13
    empty = await tools.list_shipments(ListShipmentsInput(status="delivered"))
    assert empty.total == 0


async def test_health_and_readiness(tmp_path, woo_client) -> None:
    settings = app_settings(service_name="shipping-mcp")
    provider = ShippingProvider(shipping_settings(tmp_path))
    await provider.initialize()
    tools = ShippingTools(woo_client, provider, provider.settings)
    app = create_app(settings, tools)
    try:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            health = await client.get("/health")
            ready = await client.get("/health/ready")
        assert health.status_code == 200
        assert ready.status_code == 200
        assert ready.json()["provider_mode"] == "simulated"
    finally:
        await provider.close()
