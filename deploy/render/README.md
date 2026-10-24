# Render deployment (single container)

This deployment runs all Urumi components in one Docker container on Render's free tier:
- WooCommerce MCP (8101)
- Inventory MCP (8102) 
- Shipping MCP (8103)
- Gateway (8000)
- Agent (8200)
- Nginx serving React dashboard + proxying to gateway/agent on public PORT

## Quick start

1. Create a new Web Service on Render, connect this repo
2. Use Docker, set Dockerfile path to `deploy/render/Dockerfile` and context to `.`
3. Set required environment variables (see below)
4. Deploy

Or use the `render.yaml` blueprint.

## Required environment variables

- `GATEWAY_SECRET_KEY` (required, >= 16 chars). Used to encrypt credentials and sign sessions. Must be stable across restarts or stored credentials become unreadable.
- `DATABASE_URL` (default set in blueprint) - SQLite in container; data lost on redeploy/restart
- `SHIPPING_DATABASE_URL` (default set) - SQLite in container

## Optional environment variables

**WooCommerce (needed for real WooCommerce operations):**
- `WOOCOMMERCE_BASE_URL` - Your WooCommerce store URL
- `WOOCOMMERCE_CONSUMER_KEY` - WooCommerce REST API consumer key
- `WOOCOMMERCE_CONSUMER_SECRET` - WooCommerce REST API consumer secret
- `WOOCOMMERCE_AUTH_MODE` - auto (default), basic, or oauth1

**Agent/LLM (needed for chat):**
- `GEMINI_API_KEY` - Google Gemini API key
- `GEMINI_MODEL` - gemini-2.5-flash (default)

**Assessment/demo mode (disabled by default):**
- `GATEWAY_DEMO_MODE` - false by default
- `GATEWAY_DEMO_ACK` - false by default  
- `GATEWAY_DEPLOYMENT_ENV` - development (default). Cannot be 'production' if demo mode enabled.
- `GATEWAY_DEMO_ALLOW_REMOTE` - false by default

**Other:**
- `LOG_LEVEL` - INFO (default)
- `SHIPPING_MOCK_MODE` - simulated (default), degraded, failing
- `INVENTORY_LOW_STOCK_THRESHOLD` - 5 (default)

## Health check

Render health check path: `/api/health/ready` (or `/healthz` for simple check)

The readiness check verifies the gateway database and upstream MCP server status.

## Important notes

- **Data is ephemeral** on free tier - SQLite databases will be lost on restart/redeploy/instance replacement
- **All services run in one container** - internal ports (8000, 8101-8103, 8200) are not exposed publicly
- **MCP endpoints are not exposed directly** - only via gateway at `/mcp` on same origin
- **Demo mode disabled by default** - requires explicit env vars and is restricted by security checks
- **Secrets must be provided via environment variables** - never committed to repo
- **No real WooCommerce credentials required to start** - services will start but WooCommerce-dependent features may report not ready

## Bootstrap admin user

After first deployment, you may need to bootstrap an admin user. You can do this via the API or by setting env vars and running bootstrap command - but in a single container, easier to do via API after deployment or modify entrypoint. See main README for bootstrap instructions.
