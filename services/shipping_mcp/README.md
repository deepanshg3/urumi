# Shipping & Fulfillment MCP Server (Pass 4 — implemented)

Custom MCP server with a configurable **mock** shipping provider. It never
contacts a real carrier; every shipment and tracking event is marked `mock=true`.

Run: `.venv/bin/python -m services.shipping_mcp` (`127.0.0.1:8103/mcp`).

Tools:
- `create_shipment` — validate a WooCommerce order, prevent duplicates (unless
  `SHIPPING_ALLOW_MULTIPLE_PER_ORDER=true` and the call opts in), generate a
  mock tracking number and estimated delivery.
- `track_shipment` — by shipment ID or tracking number, with history.
- `get_shipment` — by shipment ID or order ID (newest wins).
- `update_shipment_status` — validated transitions, history recorded.
- `list_shipments` — paginated, filter by status/order.

Persistence: `SHIPPING_DATABASE_URL` (default
`sqlite+aiosqlite:///./data/shipping.db`), isolated from the gateway database.

Mock behavior settings: `SHIPPING_MOCK_MODE` (`simulated`, `degraded`,
`failing`), `SHIPPING_MOCK_FAILURE_RATE`, `SHIPPING_DEFAULT_CARRIER`,
`SHIPPING_TRACKING_PREFIX`, delivery-day window and duplicate policy.

Order status is never changed automatically. The provider interface is in
`provider.py`; a real carrier can implement the same operations later.
