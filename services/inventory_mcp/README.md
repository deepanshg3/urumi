# Inventory MCP Server (Pass 3 — implemented)

Custom Python MCP server: stock lookup, low-stock detection, inventory
summaries, and reorder recommendations. Read-only and bounded; it never updates
stock.

Run: `.venv/bin/python -m services.inventory_mcp` (`127.0.0.1:8102/mcp`).

Tools: `check_stock`, `find_low_stock_products`, `get_inventory_summary`,
`calculate_reorder_quantity`. Monetary valuation is reported as `null` because
cost data is not available from the store.
