# Implementation Plan

Staged delivery. **Passes 0-10 are complete per their acceptance criteria.** Two
environment-limited items are documented as not executed: a live Gemini chat
completion (no real API key) and a remote k3s install (no VPS); the Kind
deployment is fully verified and the k3s overlay is lint/render-clean.
Passes 4-10 remain pending and must not be started without explicit instruction
(see AGENTS.md).

## Pass 0 — Foundation and architecture ✅ (complete per acceptance criteria)

**Scope:** repo structure, Python env, dependency baseline, config/secrets
layout, AGENTS.md, architecture + threat-model docs, initial test.

**Depends on:** nothing.

**Acceptance criteria:**
- [x] Repository structure exists
- [x] Python virtual environment exists (Python 3.12.13, `.venv/`)
- [x] Dependencies install successfully (verified — versions recorded below)
- [x] `.env.example` and `.gitignore` correct; no real secrets anywhere
- [x] `AGENTS.md`, `docs/architecture.md`, `docs/threat-model.md` exist
- [x] README documents env activation and checks
- [x] Basic test passes (`pytest`)
- [x] Installed/missing infrastructure tools reported

## Pass 1 — WooCommerce and persistent database ✅ complete

**Scope:** WordPress + WooCommerce + MySQL/MariaDB store; gateway database
schema (users, roles, API keys, audit logs) via SQLAlchemy; DB abstraction
proven for SQLite → PostgreSQL switch. No production migrations yet beyond dev.

**Depends on:** Pass 0.

**Acceptance criteria:**
- [x] Store reachable at `http://localhost:8080` with seeded products/order
- [x] Repeatable, idempotent setup (`scripts/store_setup.sh`) and persistence
      across container restarts
- [x] OAuth 1.0a and Basic auth modes (WooCommerce 11+ requires Basic over HTTPS)
- [x] Gateway tables `users`, `roles`, `user_roles`, `api_keys`,
      `server_registrations`, `audit_logs` created from SQLAlchemy models
- [x] Tests for the DB access layer (`tests/unit/test_gateway_db.py`)
- [x] PostgreSQL schema exercised end-to-end against a throwaway `postgres:16-alpine`
      container (`tests/unit/test_gateway_db_postgres.py`, gated by
      `URUMI_POSTGRES_URL`; install with `pip install -e ".[postgres]"`)

## Pass 2 — Custom WooCommerce MCP server ✅ complete

**Scope:** `services/woocommerce_mcp/` — custom Python MCP server over the
official WooCommerce REST API (products, orders); typed tool schemas; server-side
credentials only. **Must be our own implementation, not a third-party server.**

**Depends on:** Pass 1.

**Acceptance criteria:**
- [x] Server starts standalone on Streamable HTTP (`127.0.0.1:8101/mcp`)
- [x] Tools: `list_products`, `create_product`, `list_orders`, `get_order`,
      `update_order_status`; list/call verified through the MCP SDK
- [x] Typed Pydantic input/output models, pagination, error mapping
- [x] PII minimization (order email/phone/address stripped)
- [x] Unit tests with mocked REST responses (`tests/unit/test_woocommerce_tools.py`)
- [x] Live integration tests against the local store

## Pass 3 — Inventory MCP server ✅ complete

**Scope:** `services/inventory_mcp/` — stock lookup, low-stock detection,
inventory summaries, reorder recommendations.

**Depends on:** Pass 2 (shares product/stock data source).

**Acceptance criteria:**
- [x] Server starts standalone on Streamable HTTP (`127.0.0.1:8102/mcp`)
- [x] Tools: `check_stock`, `find_low_stock_products`, `get_inventory_summary`,
      `calculate_reorder_quantity`
- [x] Read-only; bounded scanning; `monetary_value` explicitly unavailable
- [x] Unit tests (`tests/unit/test_inventory_tools.py`) and live integration tests

## Pass 4 — Shipping and fulfillment MCP server ✅ complete

**Scope:** `services/shipping_mcp/` — shipment records, tracking status,
pending fulfillments; configurable mock provider (`shipping_mock` config:
mode, failure rate, prefix).

**Depends on:** Pass 0 (config exists); Pass 2 for order linkage.

**Delivered:** `models.py` (typed inputs/outputs, status transition rules),
`db.py` (own `ShippingDatabase` on `SHIPPING_DATABASE_URL`, `shipments` +
`shipment_events` tables), `provider.py` (deterministic mock carrier,
tracking numbers, `simulated`/`degraded`/`failing` modes, duplicate
prevention), `tools.py` (order validated through the WooCommerce client
before a shipment is created), `server.py` (five tools:
`create_shipment`, `track_shipment`, `get_shipment`, `update_shipment_status`,
`list_shipments`; `/health`, `/health/ready`). Runs standalone on port 8103.

**Verification:** `tests/unit/test_shipping_tools.py` (10 tests) plus gateway
end-to-end calls through the aggregated MCP endpoint (create/track/update,
duplicate and invalid-order rejections).

## Pass 5 — Gateway aggregation and routing ✅ complete

**Scope:** `services/gateway/` — connect to all three upstream servers,
aggregate tool lists, route tool calls, health/status reporting, server
enable/disable state (config-driven initially).

**Depends on:** Passes 2–4.

**Delivered:** MCP client (`upstream.py`, Streamable HTTP), discovery and
aggregation (`aggregator.py`, public tool names `server__tool`, per-upstream
failure isolation, dropped tools for unhealthy/disabled upstreams), registry
with encrypted credentials (`registry.py`), SSRF-validating registration
(`validation.py`), low-level aggregated MCP server (`mcp_server.py`) exposed at
`/mcp`, and the FastAPI app (`app.py`) with periodic refresh.

**Verification:** `tests/unit/test_gateway_aggregator.py`,
`test_gateway_registry.py`, `test_gateway_validation.py`,
`test_gateway_mcp.py`; Docker Compose stack exposes 14 aggregated tools; an
upstream outage drops only its tools (9 remain) and recovers on restart;
disabled servers are not routed to.

## Pass 6 — Authentication, authorization, dashboard and audit logs ✅ complete

**Scope:** AuthN (sessions + individual revocable API keys), AuthZ on every
tool call including model-hidden tools, admin/member roles, audit logging,
React dashboard (server registry, keys, audit view), runtime registrations
persisted in DB.

**Depends on:** Pass 5, Pass 1 (schema).

**Delivered:** `security.py` (PBKDF2 passwords, `urumi_` API keys stored
hashed, Fernet credential encryption), `auth.py` (sessions, API keys,
bootstrap admin, user creation/roles), `policy.py`
(`tools:<server>:<tool>` grants/deny), `audit.py` (fail-closed audit log),
management API `api.py` (auth, users, servers, tools, keys, audit, overview;
CSRF double-submit), `bootstrap.py` CLI, and the React + Vite + TypeScript
dashboard in `apps/dashboard/`.

**Verification:** `tests/unit/test_gateway_auth.py`, `test_gateway_policy.py`,
`test_gateway_security.py`, `test_gateway_api.py`, `test_gateway_mcp.py`;
live stack: 401 without a key, revoked key rejected immediately, member sees a
permission-filtered tool list and is denied `woocommerce__create_product`,
denied calls are audited with the actor; dashboard `npm run build` passes.

**Follow-up (2026-10-22) — real role model.** The three shipped roles are now
`admin` (Administrator), `member` (Operator) and `viewer` (read-only), and the
`gateway:*` permissions are enforced rather than declarative: `api.py`
authorizes every management route with `require_permission(...)`, the audit
view and the API-key endpoints are owner-scoped, and the REST API rejects what
a role may not do. Added: `POST /api/users/{id}/password` (administrator-only
reset, PBKDF2, sessions revoked), a third role in `config/permissions.yaml`,
permission-aware dashboard navigation. Verified by
`tests/unit/test_gateway_roles.py` (22 tests) and 55 live checks on both Compose
and Kind — see `docs/roles-and-permissions.md` and
`docs/live-validation-report.md` §8.1.

**Follow-up (2026-10-22) — assessment demo mode.** No-login persona switching
for local assessments: fixed server-side allowlist (`admin`/`operator`/`viewer`
mapped to the real `admin`/`member`/`viewer` roles), real persisted sessions,
CSRF-protected switching that revokes the previous session, demo-only `/mcp`
cookie auth, audit rows, and dashboard persona picker + header switcher. Off by
default; requires `GATEWAY_DEMO_MODE` **and** `GATEWAY_DEMO_ACK`, refuses
`GATEWAY_DEPLOYMENT_ENV=production`, and gates on loopback/Host/Origin. The
password-based assessment accounts and their scripts were retired; new checks
are `tests/unit/test_gateway_demo.py` and the credential-free
`scripts/verify_demo.py`. See `docs/demo-mode.md`.

## Pass 7 — Gemini chat agent, LangChain tool calling, LangSmith tracing ✅ complete

**Scope:** chat agent wired to gateway tools via LangChain; Gemini via
`langchain-google-genai`; prompt from `config/prompts/chat_agent.txt`;
LangSmith tracing optional and disableable.

**Depends on:** Pass 6.

**Delivered:** `services/agent/` (separate FastAPI service on `:8200`) that
authenticates the dashboard session against the shared gateway DB, mints a
short-lived delegated API key, connects to the gateway `/mcp` as an MCP client,
discovers the user's permission-filtered tools, and executes every call through
the gateway (authz + audit re-enforced there). Custom tool-calling loop over
`ChatGoogleGenerativeAI.bind_tools` (no `create_agent`) for deterministic
iteration/tool limits. Conversation persistence (`ChatConversation`/
`ChatMessage`), dashboard Chat tab, `AGENT_*`/`GEMINI_*`/`LANGSMITH_*`
configuration, and `tests/unit/test_agent.py` (24 tests).

**Acceptance:** 14 tools discovered through the gateway; delegated key mint/
revoke verified; live tool calls (`woocommerce__list_orders`,
`inventory__check_stock`) return real data; tracing toggle defaults off; clear
`configuration_error` when `GEMINI_API_KEY` is a placeholder. A real Gemini key
is required to exercise a full chat completion (not available here).

## Pass 8 — Docker and local Kubernetes ✅ complete

**Scope:** `deploy/docker/` (gateway, MCP servers, WordPress+WooCommerce+MySQL,
dashboard), Kind cluster, manifests.

**Depends on:** Passes 5–7.

**Delivered:** Dockerfiles for the agent and dashboard; MCP Dockerfile gained an
`EXTRAS` build arg; Compose stack extended with `agent` + `dashboard` (nginx
reverse proxy as the single origin). `deploy/kind/kind-config.yaml` and
`scripts/k8s/{kind-up,kind-down,build-and-load,deploy-kind,seed-store,verify,delete}.sh`.

**Acceptance:** Compose stack healthy; the full platform runs in Kind; all five
health endpoints green (`scripts/k8s/verify.sh`); store seeded and 14 tools
served through the gateway.

## Pass 9 — Helm and production-like k3s deployment ✅ complete (chart + Kind verified)

**Scope:** `deploy/helm/` chart; k3s VPS deployment; secrets via environment /
secret manager.

**Depends on:** Pass 8.

**Delivered:** `deploy/helm/urumi` — one chart for Kind and k3s, with
`values.yaml`, `values-kind.yaml`, `values-prod.yaml`; templates for gateway,
agent, dashboard, three MCP servers, bundled WordPress + MariaDB, bundled
PostgreSQL, Secret, servers ConfigMap, Ingress and NOTES. `deploy/helm/README.md`
and `docs/deployment.md`. Secrets templated from `secrets.*` or an existing
Secret; DB/upstream hosts/CORS origins/ingress/DB URL all configurable via values.

**Acceptance:** `helm lint` and `helm template` pass for both overlays; the chart
installs cleanly on Kind and all pods become `Ready`; end-to-end request
(host → dashboard → gateway MCP → WooCommerce/inventory → real data) verified;
no secrets in git. A remote k3s deployment was not executed (no VPS
credentials); the `values-prod.yaml` overlay is provided and lint-clean.

## Pass 10 — End-to-end testing, security review and submission ✅ complete (with documented gaps)

**Scope:** full E2E flows (chat → gateway → each server → backend), security
review against `docs/threat-model.md`, cleanup, final documentation.

**Depends on:** Pass 9.

**Delivered:** full test suite green (`232 passed, 14 skipped`); live E2E on
**both** Compose and Kind (host → dashboard → gateway MCP → WooCommerce/
inventory/shipping → real data), with 47 MCP checks, 39 auth/authz checks and 10
live Gemini chat checks passing on each; upstream-outage and automatic-recovery
test; security review with evidence (`docs/security-review.md`), refreshed threat
model (T1–T15), and submission docs (`docs/demo-script.md`,
`docs/submission-checklist.md`). Results and fixes are recorded in
`docs/live-validation-report.md`.

**Fixes made during validation:** unknown tool arguments are now rejected
(agent schema + gateway) instead of silently dropped; the gateway retries
discovery for upstreams that are not ready at startup and refreshes
periodically; Compose `env_file`/`environment` clobbering and startup ordering
fixed; `deploy-kind.sh` reuses existing secrets so re-runs no longer rotate
database passwords; stale pass-status test and README status corrected.

**Gaps (not claimed as working):** a remote k3s install (no VPS) was not
executed; TLS/NetworkPolicy are configuration hooks only; the `gateway:*`
permission entries are documented but not enforced by the REST API. All are
listed in `docs/live-validation-report.md` §8.

---

## Pass 11 — Storefront theme, product catalogue and dashboard redesign ✅ complete

**Scope:** a branded storefront and a coherent demo catalogue on top of the
existing platform, plus a redesign of the dashboard on the shared design
system.

**Depends on:** Pass 1 (WooCommerce), Pass 10 (deployment paths).

**Delivered — storefront:** the classic PHP theme
`deploy/docker/woocommerce/theme/urumi-supply/` (hero, featured products,
categories, story, shop archive, product detail, cart, checkout, my account,
search, 404) with self-hosted Inter/DM Sans, the shared palette and twelve
hand-drawn SVG product illustrations. The illustrations are registered as
`image/svg+xml` attachments by `scripts/woo_storefront.php` (WordPress blocks
SVG uploads by default, so no upload plugin is required). The Cart and
Checkout pages are switched from the WooCommerce blocks to the classic
shortcodes so the theme templates apply. Cash on delivery and free shipping
over $60 are enabled.

**Delivered — catalogue:** `scripts/store_catalog.py` holds the catalogue
(three categories, twelve products with prices, stock and copy) and the demo
order; `scripts/woo_rest.py seed` applies it idempotently — categories are
created if missing, products are upserted by SKU, development fixtures are
moved to draft (never deleted, so historic orders keep a valid line item) and
the demo order is synced.

**Delivered — deployment:** the theme is bind-mounted into the WordPress
container in Docker Compose and copied into the pod by an init container in
the Helm chart (`urumi/urumi-supply-theme` image, built by
`scripts/k8s/build-and-load.sh`).

**Delivered — dashboard:** every page (Overview, Chat, Servers, Tools, Keys,
Audit, Users, Login) was rebuilt on the shared design tokens; `src/styles.css`
was replaced by `src/design/{tokens,base,components}.css`.

**Verification:** `232 passed, 14 skipped` (default suite) and
`13 passed` with `URUMI_RUN_INTEGRATION=1`; storefront pages checked with
`curl` (front page, shop archive, product detail, cart, checkout, my account,
search, 404 — all HTTP 200 with no PHP notices); `npm run typecheck` and
`npm run build` green; `helm lint` and `helm template` green. Both deployment
paths were exercised end to end: `scripts/store_setup.sh` is idempotent on
Docker Compose, and the Kind path (theme image loaded into the cluster,
`scripts/k8s/seed-store.sh` re-seeding the in-cluster store) serves the same
twelve products; a live MCP call through the Kind gateway returns them.

**Known gaps:** the storefront is English-only and has no customer accounts
with stored addresses; the checkout is not exercised end-to-end in the test
suite (it is verified manually through the storefront).

---

## Pass 0 record — installed versions

Python 3.12.13 (`.venv`), pip 26.2.1. Key packages installed and import-verified:

```
mcp==1.30.0
fastapi==0.146.0
uvicorn==0.54.0
langchain==1.4.6
langchain-google-genai==3.2.0
langsmith==0.14.11
pydantic==2.14.1
pydantic-settings==2.16.0
SQLAlchemy==2.1.5
PyYAML==6.0.3
pytest==9.1.1
aiosqlite==0.22.1
httpx==0.28.1
```

Initial test run: **15 passed** (`tests/test_pass0_foundation.py`).
