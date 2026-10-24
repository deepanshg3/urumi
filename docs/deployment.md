# Deployment

Urumi runs locally with Docker Compose and on Kubernetes via a single Helm
chart (`deploy/helm/urumi`) that targets both **Kind** (local) and a
**production-like k3s** cluster. Only the values overlays differ.

```
host  →  dashboard (nginx)  →  gateway  →  upstream MCP servers  →  WooCommerce / inventory / shipping
                            →  agent    →  gateway (MCP client)  →  same upstreams + Gemini
```

The dashboard is the only externally exposed component; its nginx
reverse-proxies `/api` and `/mcp` to the gateway and `/agent/api` to the agent,
keeping all cookies same-origin.

## 1. Docker Compose (local, no Kubernetes)

See the README. In short:

```bash
# one-time: provision WordPress + WooCommerce + seed data
scripts/store_setup.sh
# start the platform
docker compose -f deploy/docker/mcp/compose.yaml --env-file .env up -d --build
```

Services: gateway `:8000`, agent `:8200`, dashboard `:5173`, MCP servers
`:8101–8103`, store `:8080`.

### Assessment demo mode

Compose keeps demo mode off by default. To show the persona picker during an
assessment, start (or restart) the gateway and dashboard with both flags:

```bash
GATEWAY_DEMO_MODE=true GATEWAY_DEMO_ACK=true GATEWAY_DEPLOYMENT_ENV=assessment \
  docker compose -f deploy/docker/mcp/compose.yaml up -d gateway dashboard
```

The Kind overlay enables the same flags in `values-kind.yaml`. Demo mode only
accepts local/origin-allowlisted requests and refuses to start when
`GATEWAY_DEPLOYMENT_ENV=production`. See `docs/demo-mode.md`.

## 2. Kind (local Kubernetes)

Prerequisites (user-local installs, no sudo): `docker`, `kind`, `kubectl`,
`helm`, `openssl`.

```bash
# tools used by the scripts
export PATH="$HOME/.local/bin:$PATH"
```

One command does everything:

```bash
scripts/k8s/deploy-kind.sh
```

It will:

1. create the Kind cluster `urumi` (`deploy/kind/kind-config.yaml`),
2. build the six platform images plus the storefront theme image and load them
   into the cluster,
3. generate secrets (postgres/mariadb/gateway/admin) on a first install, or
   **reuse the existing `urumi-secrets` values** on a re-run, and read
   `GEMINI_API_KEY` from `.env` if present,
4. `helm upgrade --install` with `values-kind.yaml`,
5. provision the bundled WooCommerce store (`seed-store.sh`, idempotent).

The `urumi/urumi-supply-theme` image carries the storefront theme; the chart
copies it into the WordPress pod with an init container and mounts it read-only
at `wp-content/themes/urumi-supply`. See `docs/storefront.md`.

Re-running the script is safe: reusing the stored secret keeps the running
PostgreSQL/MariaDB credentials valid, and the seed script skips products/orders
that already exist. Override any secret on a re-run by exporting the matching
variable (for example `POSTGRES_PASSWORD=...`) before running it.

Access:

| What | URL |
| ---- | --- |
| Dashboard | http://localhost:8088 |
| Storefront / WP admin | http://localhost:8081 (`/wp-admin`) |
| Gateway API (through dashboard) | http://localhost:8088/api |
| Agent API (through dashboard) | http://localhost:8088/agent/api |

The gateway admin email is `admin@urumi.local`; the generated password is
printed by the script and written to the gitignored `.urumi-kind-credentials`.

Individual steps (if you prefer to run them yourself):

```bash
scripts/k8s/kind-up.sh          # create cluster
scripts/k8s/build-and-load.sh   # build + kind load images
helm upgrade --install urumi deploy/helm/urumi -n urumi --create-namespace \
  -f deploy/helm/urumi/values-kind.yaml \
  --set-string secrets.gatewaySecretKey=$(openssl rand -hex 24) \
  --set-string secrets.bootstrapAdminPassword=$(openssl rand -hex 16) \
  --set-string secrets.postgresPassword=$(openssl rand -hex 24) \
  --set-string secrets.mariadbRootPassword=$(openssl rand -hex 24) \
  --set-string secrets.mariadbPassword=$(openssl rand -hex 24) \
  --set-string secrets.geminiApiKey="${GEMINI_API_KEY:-}"
scripts/k8s/seed-store.sh       # provision store + REST keys + seed data
scripts/k8s/verify.sh           # health checks
scripts/k8s/delete.sh           # uninstall the release
scripts/k8s/kind-down.sh        # delete the cluster
```

The three MCP servers stay `NotReady` until the store has REST credentials —
that is expected before `seed-store.sh` runs.

### How the store is provisioned

`seed-store.sh` installs wp-cli into the WordPress pod, installs WordPress +
WooCommerce, creates a read/write REST key (consumer key hashed with
`wc_api_hash`, secret stored plaintext, exactly like `scripts/store_setup.sh`),
injects the key into the Helm release, waits for the MCP servers, and seeds the
demo products + a test order via `scripts/woo_rest.py seed`.

### OAuth 1.0a and `woocommerce.publicUrl`

WooCommerce verifies OAuth 1.0a signatures against WordPress's `home`/`siteurl`
option, **not** the request `Host`. In the cluster the MCP servers connect to
the store over the internal Service (`http://urumi-wordpress:80`) but must
*sign* with the store's public URL. That URL is `woocommerce.publicUrl`
(`http://localhost:8081` for Kind), and the store's `home`/`siteurl` are set to
the same value by `seed-store.sh`. Set `woocommerce.publicUrl` for any
non-default store URL.

### Credentials and the agent

- `GEMINI_API_KEY` must be a real key for chat to work. With a placeholder (or
  no key) the agent returns a clear `configuration_error` instead of failing
  silently.
- LangSmith tracing is off by default (`agent.langsmith.enabled=false`). Enable
  with `--set agent.langsmith.enabled=true --set-string secrets.langsmithApiKey=...`.

## 3. Production-like k3s

Same chart, `values-prod.yaml`. Create the namespace and a Secret out of band
(do not pass credentials on the command line in production):

```bash
kubectl create namespace urumi
kubectl -n urumi create secret generic urumi-secrets \
  --from-literal=gateway-secret-key=... \
  --from-literal=bootstrap-admin-password=... \
  --from-literal=gemini-api-key=... \
  --from-literal=langsmith-api-key=... \
  --from-literal=woocommerce-consumer-key=... \
  --from-literal=woocommerce-consumer-secret=... \
  --from-literal=postgres-password=... \
  --from-literal=mariadb-root-password=... \
  --from-literal=mariadb-password=...

helm upgrade --install urumi deploy/helm/urumi \
  -n urumi -f deploy/helm/urumi/values-prod.yaml \
  --set global.imageRegistry=registry.example.com/urumi
```

`values-prod.yaml` enables an Ingress (default class `traefik`, which ships with
k3s; set `ingress.className=nginx` otherwise), uses 2 replicas for the stateless
components, and sizes persistent volumes for `local-path`.

Checklist for production:

- `database.bundled=false` + `database.url` to use a managed PostgreSQL (set
  `secrets.existingSecret` for the password) — otherwise the bundled StatefulSet
  uses a single PVC with no HA.
- Push images to a registry and set `global.imageRegistry` / image `tag`s —
  including `urumi/urumi-supply-theme` for the storefront theme.
- Serve over TLS (`ingress.tls.enabled=true`, `ingress.tls.secretName=...`);
  WooCommerce Basic auth requires HTTPS.
- Set `woocommerce.publicUrl` to the store's public HTTPS URL and keep the
  store's `home`/`siteurl` in sync.
- Scale `shipping-mcp` to 1 only (its SQLite PVC does not support concurrency).

## Troubleshooting

| Symptom | Cause / fix |
| ------- | ----------- |
| MCP pods `NotReady` with `configuration_error` | Store not seeded yet — run `scripts/k8s/seed-store.sh`. |
| MCP pods `NotReady` with `authentication_error` (HTTP 401) | OAuth signing base ≠ WordPress `home`. Set `woocommerce.publicUrl` to match and re-run seeding. |
| Agent `/agent/api/tools` returns 500, logs show `421 Misdirected Request` | The gateway's DNS-rebinding allowlist does not include the agent's `Host`. Ensure `GATEWAY_ALLOWED_HOSTS` includes `<release>-gateway:*`. |
| Gateway crash-loops, `password authentication failed for user "urumi"` | `DATABASE_URL` was rendered before `POSTGRES_PASSWORD`; the chart defines `POSTGRES_PASSWORD` first so `$(POSTGRES_PASSWORD)` expands. |
| WordPress probe timeouts pre-install | Expected before installation; the probe uses a 5s timeout and a `localhost` Host header. |
| `helm --wait` times out | Expected on the first install — the MCP servers wait for store credentials. Install without `--wait`, then run `seed-store.sh`. |
