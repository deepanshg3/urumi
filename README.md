# Urumi MCP Gateway

A team MCP (Model Context Protocol) gateway platform: three upstream MCP servers
(WooCommerce, Inventory, Shipping & Fulfillment) behind a single gateway that
aggregates tools, routes calls, authenticates users, enforces permissions and
records audit logs — plus a React dashboard and a Gemini-powered chat agent.

> **Status: Passes 0–10 complete.** The local WooCommerce store, the custom
> WooCommerce MCP server, the Inventory and Shipping MCP servers, the
> aggregating gateway with identity/AuthZ/audit, the React dashboard, the Gemini
> chat agent, and the Docker Compose and Kind/Helm deployments are implemented
> and tested. Live end-to-end validation results (Compose + Kind) are recorded
> in `docs/live-validation-report.md`; remaining limitations are listed in
> `docs/implementation-plan.md` (Pass 10) and `docs/security-review.md`.

## Repository layout

```
AGENTS.md                    Project instructions for AI agents
README.md                    This file
.env.example                 Placeholder environment variables (copy to .env)
pyproject.toml               Python project and dependency definitions
config/                      app.yaml, servers.yaml, permissions.yaml, prompts/
apps/dashboard/              React + Vite + TypeScript dashboard (Pass 6)
services/common/             Shared config, logging, errors, WooCommerce client
services/gateway/            Aggregating gateway, identity, management API
services/woocommerce_mcp/    Custom WooCommerce MCP server (5 tools)
services/inventory_mcp/      Inventory MCP server (4 tools)
services/shipping_mcp/       Shipping & fulfillment MCP server (5 tools, mock)
services/agent/              Chat agent (Gemini via LangChain; gateway MCP client)
tests/                       pytest suite (unit + gated integration)
deploy/docker/woocommerce/   Local WordPress + WooCommerce + MariaDB stack
deploy/docker/woocommerce/theme/urumi-supply/  "Urumi Supply" storefront theme
deploy/docker/mcp/           Dockerfile and Compose file for the MCP servers
deploy/docker/agent/         Dockerfile for the chat agent
deploy/helm/urumi/           Helm chart (Kind + k3s)
deploy/kind/                 Kind cluster config
docs/                        architecture, deployment, implementation-plan, threat-model
docs/roles-and-permissions.md Role model (admin / operator / viewer) and permission matrix
scripts/                     Store setup/seeding, REST helpers, Kubernetes scripts
```

## Deploy to Kubernetes

The same Helm chart (`deploy/helm/urumi`) runs on a local **Kind** cluster and
on a production-like **k3s** cluster; only the values overlay differs. Full
details are in [`docs/deployment.md`](docs/deployment.md).

```bash
# Local Kind: cluster + images + secrets + Helm release + store seeding
scripts/k8s/deploy-kind.sh          # dashboard at http://localhost:8088

# Production-like k3s (see docs/deployment.md for the Secret and image registry)
helm upgrade --install urumi deploy/helm/urumi -n urumi \
  -f deploy/helm/urumi/values-prod.yaml
```


## Prerequisites

- **Python 3.12** (supported: `>=3.11`; `.venv` is built with Python 3.12.13).
  Python 3.10.12 is the system default and is **not** supported by
  `pyproject.toml`.
- Git, Docker + Compose plugin (used by the local store)
- Node.js 20+ for the frontend (Node 22 available)
- Kind, kubectl and Helm for Kubernetes deployment (`scripts/k8s/*`)

## Setup

```bash
# 1. Create/refresh the virtual environment
python3.12 -m venv .venv

# 2. Install dependencies (main + dev group)
.venv/bin/pip install -e ".[dev]"

# 3. Start the local store. This also writes the root .env with generated
#    WooCommerce REST credentials (never commit .env).
./scripts/store_setup.sh
```

`scripts/store_setup.sh` is idempotent. It starts MariaDB + WordPress +
WooCommerce, upgrades WordPress to 7.0+ if the existing volume is older, creates
a REST API key, activates the **Urumi Supply** storefront theme, registers the
product illustrations and seeds the catalogue: twelve products in three
categories (one out of stock, three at or below the low-stock threshold of 5)
plus one demo order. Earlier development fixtures are moved to draft instead of
being deleted. See `docs/storefront.md` for the full catalogue and the theme
layout.

The storefront is served at <http://localhost:8080> (shop archive at
`/shop/`), WordPress admin at `/wp-admin`.

## Run the MCP servers

Uvicorn/Streamable HTTP, loopback only by default:

```bash
.venv/bin/python -m services.woocommerce_mcp   # http://127.0.0.1:8101/mcp
.venv/bin/python -m services.inventory_mcp     # http://127.0.0.1:8102/mcp
.venv/bin/python -m services.shipping_mcp      # http://127.0.0.1:8103/mcp
```

Health: `/health` (liveness) and `/health/ready` (validates credentials and
calls the store).

## Run the gateway

```bash
# 1. Provide a stable secret and create the first administrator.
export GATEWAY_SECRET_KEY="$(openssl rand -hex 24)"
export BOOTSTRAP_ADMIN_EMAIL=admin@example.com
export BOOTSTRAP_ADMIN_PASSWORD='choose-a-long-password'
.venv/bin/python -m services.gateway.bootstrap

# 2. Start the gateway (aggregates config/servers.yaml upstreams).
.venv/bin/python -m services.gateway             # http://127.0.0.1:8000
```

- MCP endpoint: `http://127.0.0.1:8000/mcp` — API-key auth
  (`Authorization: Bearer urumi_…`). Keys are created in the dashboard or via
  `POST /api/keys`; the plaintext is shown once.
- Management API: `/api/auth`, `/api/users`, `/api/servers`, `/api/tools`,
  `/api/keys`, `/api/audit`, `/api/overview`. Browser sessions use an HttpOnly
  cookie plus a double-submit CSRF token (`urumi_csrf` cookie →
  `X-CSRF-Token` header).
- `GET /health` and `GET /health/ready` (checks the gateway DB and
  re-discovers upstreams).

Docker Compose (all four services + store already running):

```bash
docker compose -f deploy/docker/mcp/compose.yaml --env-file .env up -d --build
curl http://127.0.0.1:8103/health/ready
curl http://127.0.0.1:8000/health/ready
docker compose -f deploy/docker/mcp/compose.yaml down
```

In Compose the gateway reads `config/servers.docker.yaml` (service-name URLs)
via `GATEWAY_SERVERS_CONFIG`, and `GATEWAY_SECRET_KEY` /
`BOOTSTRAP_ADMIN_*` are passed through from the shell or `.env`.

## Run the dashboard

```bash
cd apps/dashboard
npm install
npm run dev        # http://localhost:5173 (set VITE_API_BASE_URL to override the API origin)
npm run build      # type-check + production build
```

The dashboard is a standalone frontend (no Python imports) and talks to the
gateway over HTTP only. CORS origins come from `GATEWAY_CORS_ORIGINS`.

The compose file reaches the host-published store through
`host.docker.internal:8080` and sets `WOOCOMMERCE_SIGNING_BASE_URL` to the
WordPress `home_url` (`http://localhost:8080`). Override
`WOOCOMMERCE_DOCKER_BASE_URL` / `WOOCOMMERCE_SIGNING_BASE_URL` for another host.

## WooCommerce authentication

WooCommerce 11+ only performs **Basic** authentication when the request is TLS
(`is_ssl()`); over plain HTTP it requires **OAuth 1.0a**. `WOOCOMMERCE_AUTH_MODE`
selects `auto` (default: HTTPS → Basic, HTTP → OAuth 1.0a), `basic` or `oauth1`.

OAuth 1.0a signatures are verified by WooCommerce against WordPress's configured
`home_url`, not the HTTP `Host` header. If those differ (for example inside a
container), set `WOOCOMMERCE_SIGNING_BASE_URL` to the site's home URL. The
request itself still goes to `WOOCOMMERCE_BASE_URL`.

## Tests

```bash
# Unit/regression suite (integration tests are skipped by default)
.venv/bin/pytest

# Include live tests against the local store (requires store_setup.sh)
URUMI_RUN_INTEGRATION=1 .venv/bin/pytest tests/integration -v
```

Integration tests create their own products/orders and restore order statuses;
they do not delete seed data.

## Configuration

- `config/*.yaml` are the source of defaults; `${VAR}` placeholders are resolved
  from environment variables at load time (unset placeholders are omitted).
- Precedence: environment variables (`.env` locally, secret manager in
  production) override YAML defaults.
- `config/mcp_services.yaml` holds MCP service defaults; `config/servers.yaml`
  registers the upstream servers (`config/servers.docker.yaml` for Compose).
- `config/permissions.yaml` defines the roles and the `tools:<server>:<tool>`
  grants and deny rules; deny always wins. Gateway runtime overrides
  (enable/disable, dynamic registrations) are persisted in the gateway database
  and managed from the dashboard.

### Roles

| Role | Id | May |
|---|---|---|
| Administrator | `admin` | every tool plus gateway administration (users, servers, API keys, full audit log) |
| Operator | `member` | all reads plus `shipping__update_shipment_status`; own API keys only |
| Viewer | `viewer` | all reads; no changes, no API-key management |

The REST API and the MCP endpoint are authorized by the gateway on **every**
call — the dashboard only hides what the gateway would refuse anyway. The full
matrix is in [`docs/roles-and-permissions.md`](docs/roles-and-permissions.md).

For assessments, enable **demo mode** and pick a persona from the dashboard
entry screen — no password file, no account setup:

```bash
GATEWAY_DEMO_MODE=true GATEWAY_DEMO_ACK=true \
  docker compose -f deploy/docker/mcp/compose.yaml up -d gateway dashboard
```

Demo mode is off by default, requires the explicit acknowledgement, only allows
local/origin-allowlisted requests, and refuses to start in production. Each
persona is a real persisted user with a real session; REST/MCP authorization is
unchanged. See [`docs/demo-mode.md`](docs/demo-mode.md) for the Kind overlay,
the safety model, verification and credential revocation.

Normal deployments keep the login form and the bootstrap administrator:

```bash
.venv/bin/python -m services.gateway.bootstrap   # BOOTSTRAP_ADMIN_* from .env
```

## Gateway database

`services/gateway/db.py` defines the SQLAlchemy models (`users`, `roles`,
`user_roles`, `api_keys`, `sessions`, `server_registrations`, `audit_logs`) and
async engine helpers. `DATABASE_URL` defaults to
`sqlite+aiosqlite:///./data/gateway.db`. The shipping server keeps its own
database (`SHIPPING_DATABASE_URL`, default `./data/shipping.db`). PostgreSQL is
supported by changing the URL and installing the `postgres` extra
(`.venv/bin/pip install -e ".[postgres]"`). The schema was verified end-to-end
against PostgreSQL 16 in a throwaway container; `ensure_schema()` adds missing
columns non-destructively, and no production migrations exist yet.

## Supported versions

| Component | Version |
|---|---|
| Python | 3.12.13 (venv), requires `>=3.11` |
| pip | 26.2.1 (in venv) |
| Core deps | pinned as ranges in `pyproject.toml`; exact installed versions in `docs/implementation-plan.md` (Pass 0 record) |

## Infrastructure tools

| Tool | Status |
|---|---|
| Python 3.12.13 / 3.11.15 | installed (system default 3.10.12 unsupported) |
| git 2.34.1 | installed |
| Docker 29.1.3 + Compose v5.0.2 | installed, daemon running |
| Node 22.23.2 / npm 10.9.8 | installed |
| OpenCode 1.19.3 | installed (`~/.opencode/bin/opencode`) |
| kubectl | v1.31.0 (`~/.local/bin/kubectl`) |
| Helm | v3.16.2 |
| Kind | v0.24.0 (local cluster `urumi`) |

Deployment commands are documented in `docs/deployment.md`:
`scripts/k8s/deploy-kind.sh` provisions the cluster, images, release and store.

## Secrets

Never commit `.env` or real credentials. All secrets are supplied via
environment variables (`.env.example` documents every variable) or a secret
manager in production. The local `.env` and the store compose `.env` are
gitignored; the test suite scans tracked files for secret-like patterns.

## Known limitations

- The local store runs over HTTP with a self-generated dev API key; this is for
  local development only.
- Integration tests and the PostgreSQL path require explicit environment
  variables and are not part of the default test run.
- Probe products created during live verification are kept in the local
  database as drafts (no destructive cleanup), so they no longer show up in the
  shop archive, the product listings or the inventory counts.
- The storefront theme is a classic (non-block) WordPress theme; WooCommerce's
  Cart and Checkout blocks are intentionally replaced with the classic
  shortcodes so the theme templates are used.
