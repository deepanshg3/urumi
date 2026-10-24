# Urumi MCP Gateway — Architecture

## Request flow

```
┌─────────────┐   HTTPS/WS    ┌──────────────────┐   MCP (stdio/HTTP)  ┌─────────────────────┐   REST   ┌──────────────────┐
│ AI client / │ ────────────▶ │   MCP Gateway    │ ──────────────────▶ │  Upstream MCP server │ ──────▶ │ Underlying app/  │
│  dashboard  │ ◀──────────── │ (FastAPI, AuthN, │ ◀────────────────── │ (woo/inventory/      │ ◀────── │ API (Woo REST,   │
└─────────────┘   responses   │  AuthZ, audit)   │      results        │  shipping)           │  results│ mock carrier)    │
                              └──────────────────┘                    └─────────────────────┘         └──────────────────┘
```

1. An AI client (or the dashboard chat panel) sends a request to the **MCP Gateway**.
2. The gateway **authenticates** the caller (API key / session), then resolves the target server and tool.
3. The gateway **authorizes** the call against `config/permissions.yaml` — this check runs on *every* tool call, including direct calls to tools hidden from the model's tool list (`gateway.model_hidden_tools`).
4. If allowed, the gateway routes the call to the selected **upstream MCP server** over MCP transport.
5. The upstream server calls its **underlying application/API** (WooCommerce REST API, inventory store, mock shipping provider).
6. The result travels back through the gateway, which records an **audit log** entry (who, which tool, when, outcome) and returns the response.

## Components

### MCP Gateway (`services/gateway/`)
- FastAPI HTTP service (Passes 5/6); health endpoints; the only public entry point for AI clients and the dashboard.
- Connects to all three upstream MCP servers, aggregates their tool lists (`server__tool` naming), and routes tool calls. Tools from unhealthy or disabled upstreams are dropped from discovery so one outage cannot poison the catalog.
- Responsibilities: AuthN, AuthZ, per-user revocable API keys, server registration/enable-disable with status reporting, audit logging.
- The aggregated MCP endpoint (`/mcp`) uses the MCP low-level `Server` plus the Streamable HTTP session manager; a pure-ASGI middleware requires an API key before the MCP transport runs. The management API (`/api`) authenticates browser sessions (HttpOnly cookie + CSRF double-submit).
- Modules: `db.py` (models), `security.py` (password hashing, API keys, Fernet credential encryption), `auth.py`, `policy.py`, `registry.py` + `validation.py` (SSRF-checked registration), `upstream.py` + `aggregator.py` (MCP client, discovery, routing), `audit.py` (fail-closed), `mcp_server.py`, `api.py`, `app.py`, `bootstrap.py`.
- **Assessment demo mode** (`demo.py`, off by default) maps three fixed persona ids to persisted `admin`/`member`/`viewer` users and issues real sessions through the same auth path as a login. `GET /api/auth/demo` publishes the allowlist; `POST /api/auth/demo/session` is loopback/origin-gated, CSRF-protected when replacing a session, and audited. The auth middleware additionally accepts the session cookie on `/mcp` only while demo mode is enabled. See `docs/demo-mode.md`.

### Upstream MCP servers (`services/*_mcp/`)
- **WooCommerce MCP** (implemented, Pass 2) — custom Python server over the official WooCommerce REST API. Tools: `list_products`, `create_product`, `list_orders`, `get_order`, `update_order_status`. Streamable HTTP at `127.0.0.1:8101/mcp`; health at `/health` and `/health/ready`.
- **Inventory MCP** (implemented, Pass 3) — `check_stock`, `find_low_stock_products`, `get_inventory_summary`, `calculate_reorder_quantity`. Read-only, bounded scans, no monetary valuation (cost data unavailable). Streamable HTTP at `127.0.0.1:8102/mcp`.
- **Shipping & Fulfillment MCP** (implemented, Pass 4) — `create_shipment`, `track_shipment`, `get_shipment`, `update_shipment_status`, `list_shipments`; configurable mock provider (no paid API, no external calls). Own database; Streamable HTTP at `127.0.0.1:8103/mcp`.
- Each is standalone: runnable and testable without the gateway.
- Shared code lives in `services/common/`: typed settings (env > YAML > defaults), redacting logging, typed errors, and a WooCommerce REST client with OAuth 1.0a/Basic auth, bounded GET retries and pagination.

### Dashboard (`apps/dashboard/`)
- React + Vite + TypeScript. Talks to the gateway's HTTP APIs only — fully independent of the Python backend (no shared code).
- Implemented views: login, overview (upstream status + recent activity), MCP server registry (register/enable/disable/refresh/remove), tools, API keys, audit log filtering/pagination, and admin-only user/role management.
- In demo mode the login view is replaced by a persona picker (Admin/Operator/Viewer) with an **ASSESSMENT DEMO** badge, a persistent header persona dropdown, **Switch persona** and **Refresh data**. A session epoch remounts the role-sensitive pages after every switch, and a 401 drops back to the picker.

### Chat agent (Pass 7)
- Gemini via `langchain-google-genai` + LangChain tool calling; tools are the aggregated gateway tools.
- Prompt template in `config/prompts/chat_agent.txt`; optional LangSmith tracing (can be disabled).

### Database
- **Gateway DB**: SQLAlchemy async with `DATABASE_URL` — SQLite locally (`sqlite+aiosqlite:///./data/gateway.db`), PostgreSQL/Supabase later. Stores users, roles, API keys, login sessions, runtime server registrations/enabled states, audit logs. `ensure_schema()` creates tables and adds missing columns non-destructively; no production migrations yet.
- **Shipping DB**: separate SQLAlchemy async database (`SHIPPING_DATABASE_URL`), so shipment records never share the gateway schema.
- **WordPress/WooCommerce DB**: MySQL/MariaDB (`mariadb:11.4`), owned entirely by WordPress — SQLite must never be used for it. Named volumes keep data across restarts.

### Local store and MCP runtime
- `deploy/docker/woocommerce/compose.yaml` runs MariaDB, WordPress (Apache) and a one-shot WP-CLI helper. `scripts/store_setup.sh` is idempotent and seeds data.
- MCP servers and the gateway run as standalone Streamable HTTP services (local Python or `deploy/docker/mcp/`). The gateway reaches them through `config/servers.yaml` (local) or `config/servers.docker.yaml` (service-name URLs in Compose).
- Streamable HTTP uses the MCP SDK's DNS-rebinding protection. Allowed hosts/origins come from `MCP_ALLOWED_HOSTS` / `MCP_ALLOWED_ORIGINS`; loopback defaults are used when the server binds to `127.0.0.1`.
- **WooCommerce auth:** Basic is accepted only over HTTPS; HTTP requires OAuth 1.0a. OAuth signatures are verified against WordPress `home_url`, so `WOOCOMMERCE_SIGNING_BASE_URL` exists for cases where the request Host differs (containers).

### Configuration (`config/`)
- YAML: model/provider settings, LangSmith toggling, `DATABASE_URL`, server definitions + default enabled states, permissions, shipping mock behavior.
- Changing model names, tracing, DB URL or server inventory requires no code changes.

### Deployment
- Docker/Compose (`deploy/docker/`), Kind for local Kubernetes, Helm chart (`deploy/helm/`) targeting a production-like k3s VPS.

## Authentication vs Authorization

| Concern | Question | Enforced where |
|---|---|---|
| **Authentication (AuthN)** | *Who* is calling? | Gateway, before any upstream call: validates session or revocable per-user API key. |
| **Authorization (AuthZ)** | *What* may they do? | Gateway, on **every** tool call: role/permission check from `config/permissions.yaml`, including calls to tools hidden from the model's tool list. Hidden ≠ unguarded. |

Deny rules win over grants. Audit log records both successful and denied calls,
attributed to the authenticated user, key or session. Audit writes are
fail-closed: if `GATEWAY_AUDIT_ENABLED=true` and the write fails, the call is
reported as an error rather than silently succeeding.

The three shipped roles — `admin` (Super Admin), `member` (Operator) and
`viewer` (read-only) — and the full REST/MCP permission matrix are documented
in `docs/roles-and-permissions.md`.

## Credential boundaries

- **Upstream credentials** (WooCommerce consumer key/secret, Gemini key, LangSmith key, upstream MCP credentials) live only in server-side environment variables / secret managers.
- Upstream MCP credentials registered through the API are encrypted at rest with Fernet (`GATEWAY_SECRET_KEY`) and never returned by the API; `ServerView` exposes only `has_credential` and `credential_type`.
- They are never returned in API responses, never written to client-visible logs, and never placed in LLM context.
- The LLM sees only tool schemas and tool results the gateway has already authorized.

## Upstream registration safety

- `validate_upstream_url` requires http/https, forbids embedded credentials, and enforces a host allowlist (`GATEWAY_ALLOWED_UPSTREAM_HOSTS`). Public hosts additionally require `GATEWAY_ALLOW_PUBLIC_UPSTREAMS=true`.
- Loopback, link-local, private, reserved and cloud-metadata addresses are rejected unless the host is explicitly allowlisted; known metadata endpoints are always rejected.
