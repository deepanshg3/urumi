# Urumi Helm chart

Deploys the full Urumi MCP Gateway platform to Kubernetes: gateway, chat agent,
dashboard, the three custom MCP servers, and (optionally) a bundled
WordPress + MariaDB store and an in-cluster PostgreSQL database.

The same chart targets both the local Kind cluster and a production-like k3s
cluster — only the values overlays differ.

## Components

| Resource                        | Service name (`<fullname>-…`) | Port  | Notes |
| ------------------------------- | ----------------------------- | ----- | ----- |
| `gateway` Deployment            | `-gateway`                    | 8000  | Aggregates upstreams, authz, audit, `/mcp` |
| `agent` Deployment              | `-agent`                      | 8200  | Gemini chat agent; calls the gateway over MCP |
| `dashboard` Deployment          | `-dashboard`                  | 80    | React app + nginx reverse proxy (single origin) |
| `woocommerce-mcp` Deployment    | `-woocommerce-mcp`            | 8101  | Custom WooCommerce MCP server |
| `inventory-mcp` Deployment      | `-inventory-mcp`              | 8102  | Inventory MCP server |
| `shipping-mcp` Deployment       | `-shipping-mcp`               | 8103  | Shipping MCP server (+ SQLite PVC) |
| `wordpress` Deployment          | `-wordpress`                  | 80    | Bundled store (`woocommerce.enabled`) |
| `mariadb` Deployment            | `-mariadb`                    | 3306  | Bundled store database |
| `postgres` StatefulSet          | `-postgres`                   | 5432  | Bundled gateway/agent database (`database.bundled`) |

Only the **dashboard** is exposed externally. Its nginx reverse-proxies
`/api` and `/mcp` to the gateway and `/agent/api` to the agent, so all cookies
stay same-origin (`SameSite=strict`).

## Quick start (Kind)

```bash
scripts/k8s/deploy-kind.sh
```

This creates the cluster, builds/loads images, generates secrets, installs the
release, and provisions the WooCommerce store. See `docs/deployment.md` for the
manual walkthrough and the production (k3s) path.

## Key values

| Value | Default | Description |
| ----- | ------- | ----------- |
| `global.imageRegistry` | `""` | Prefix prepended to all image repositories |
| `database.bundled` | `true` | Deploy in-cluster PostgreSQL |
| `database.url` | `""` | External PostgreSQL URL (disables bundled DB) |
| `woocommerce.enabled` | `true` | Deploy bundled WordPress + MariaDB |
| `woocommerce.publicUrl` | `""` | Store URL matching WordPress `home`/`siteurl`; used as the OAuth 1.0a signing base |
| `dashboard.service.type` | `ClusterIP` | `NodePort` for Kind |
| `ingress.enabled` | `false` | Create an Ingress for the dashboard |
| `ingress.className` | `""` | e.g. `traefik` (k3s) or `nginx` |
| `secrets.existingSecret` | `""` | Use a pre-created Secret instead of templating one |
| `agent.langsmith.enabled` | `false` | Enable LangSmith tracing |
| `gateway.replicas` / `agent.replicas` / `dashboard.replicas` | `1` | Scale stateless components |

## Secrets

By default the chart templates a Secret named `<fullname>-secrets` from the
`secrets.*` values. **Never commit real values**; pass them with `--set-string`
or, preferably, pre-create a Secret and set `secrets.existingSecret`:

```bash
kubectl create secret generic urumi-secrets \
  --from-literal=gateway-secret-key=... \
  --from-literal=bootstrap-admin-password=... \
  --from-literal=gemini-api-key=... \
  --from-literal=langsmith-api-key=... \
  --from-literal=woocommerce-consumer-key=... \
  --from-literal=woocommerce-consumer-secret=... \
  --from-literal=postgres-password=... \
  --from-literal=mariadb-root-password=... \
  --from-literal=mariadb-password=...
```

Available keys: `gateway-secret-key`, `bootstrap-admin-password`,
`gemini-api-key`, `langsmith-api-key`, `woocommerce-consumer-key`,
`woocommerce-consumer-secret`, `postgres-password`, `mariadb-root-password`,
`mariadb-password`.

## Upgrading

Changing the Secret or the rendered `servers.yaml` ConfigMap bumps a
`checksum/…` pod annotation, so the affected Deployments roll automatically.

```bash
helm upgrade urumi deploy/helm/urumi -n urumi -f deploy/helm/urumi/values-kind.yaml --reuse-values
```
