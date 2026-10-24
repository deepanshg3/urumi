# Submission Checklist

## Deliverables

- [x] Architecture overview — `docs/architecture.md`
- [x] Threat model + Pass 10 security review — `docs/threat-model.md`, `docs/security-review.md`
- [x] Deployment guide (Compose, Kind, k3s) — `docs/deployment.md`, `deploy/helm/README.md`
- [x] Demo script — `docs/demo-script.md`
- [x] Assessment demo mode (personas, safety model, verification, retirement) — `docs/demo-mode.md`
- [x] README with setup and endpoints — `README.md`
- [x] Implementation plan with pass status — `docs/implementation-plan.md`

## Code

- [x] Gateway (aggregation, routing, authz, audit, API keys, MCP endpoint) — `services/gateway/`
- [x] Custom WooCommerce MCP server — `services/woocommerce_mcp/`
- [x] Inventory MCP server — `services/inventory_mcp/`
- [x] Shipping MCP server (mock provider) — `services/shipping_mcp/`
- [x] Chat agent (Gemini via LangChain, gateway MCP client) — `services/agent/`
- [x] React + Vite + TypeScript dashboard — `apps/dashboard/`
- [x] Branded WooCommerce storefront theme + product catalogue — `deploy/docker/woocommerce/theme/urumi-supply/`, `docs/storefront.md`
- [x] Dockerfiles + Compose — `deploy/docker/`
- [x] Helm chart (Kind + k3s) — `deploy/helm/urumi/`
- [x] Kubernetes scripts + Kind config — `scripts/k8s/`, `deploy/kind/`

## Tests

- [x] Full suite green: `273 passed, 14 skipped` (integration gated by `URUMI_RUN_INTEGRATION=1`)
- [x] Agent tests — `tests/unit/test_agent.py` (24)
- [x] Gateway authz/audit/identity, MCP, security, each MCP server

## Live verification (this environment)

- [x] Docker Compose stack healthy
- [x] Kind cluster: all pods `Ready`, all five health endpoints `200`
- [x] `helm lint` + `helm template` clean for `values-kind.yaml` and `values-prod.yaml`
- [x] Store provisioned (WordPress + WooCommerce + seed products/order + REST key)
- [x] End-to-end MCP call through the gateway returns real store data
- [x] Security checks: no-CSRF 403, anon `/mcp` 401, anon agent API 401
- [x] 47 MCP + 39 auth/authz + 10 chat checks pass on **both** Compose and Kind
- [x] Demo mode: 47 REST/MCP checks + 27 headless-UI checks pass on **both** Compose and Kind; old assessment keys/sessions retired
- [x] Live Gemini chat with real tool calls (product/stock/order lookups, injection refused)
- [x] Upstream outage → gateway `degraded` → automatic recovery
- [x] `deploy-kind.sh` re-run is idempotent (secrets reused, store seed skipped)
- [x] Storefront validated page by page (front page, shop, product detail, cart, checkout, account, search, 404) with the twelve-product catalogue
- [x] Storefront validated on **both** paths: Docker Compose (`scripts/store_setup.sh`, idempotent) and Kind (theme image loaded, `scripts/k8s/seed-store.sh`, cart → free shipping → cash on delivery at the checkout)

Details: `docs/live-validation-report.md`.

## Not executed here (documented, not claimed as working)

- [ ] Remote k3s install — no VPS credentials; `values-prod.yaml` is lint/render-clean
- [ ] TLS / NetworkPolicy enforcement — configuration hooks provided

## Hygiene

- [x] No secrets in git (`.env` gitignored; `.env.example` placeholders only; scan clean)
- [x] Kubernetes secrets via Secret objects; `DATABASE_URL` uses `$(POSTGRES_PASSWORD)`
- [x] No committed changes without instruction (working tree left for review)
