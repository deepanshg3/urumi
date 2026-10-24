# WooCommerce MCP Server (Pass 2 — implemented)

Custom Python MCP server exposing WooCommerce products and orders through the
official WooCommerce REST API. Credentials stay server-side and are never
returned to clients or placed in LLM context.

Run: `.venv/bin/python -m services.woocommerce_mcp` (`127.0.0.1:8101/mcp`).

Tools: `list_products`, `create_product`, `list_orders`, `get_order`,
`update_order_status`. Scopes are restricted to products and orders; customers,
coupons and settings are intentionally not exposed.

This must remain our own implementation — never replace it with a third-party
WooCommerce MCP server.
