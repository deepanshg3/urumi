# MCP Gateway (Passes 5/6)

FastAPI service that aggregates the WooCommerce, Inventory and Shipping MCP
servers, exposes one Streamable HTTP MCP endpoint at `/mcp`, authenticates
users, enforces permissions on **every** tool call, records audit logs, and
manages API keys and server enable/disable state.

## Run

```bash
export GATEWAY_SECRET_KEY="$(openssl rand -hex 24)"   # required for stored credentials
export BOOTSTRAP_ADMIN_EMAIL=admin@example.com
export BOOTSTRAP_ADMIN_PASSWORD='a-long-password'
.venv/bin/python -m services.gateway.bootstrap        # idempotent, never resets a password
.venv/bin/python -m services.gateway                  # http://127.0.0.1:8000
```

- MCP endpoint: `/mcp` — `Authorization: Bearer urumi_…` (individual revocable
  API keys; only hashes are stored).
- Management API: `/api/auth`, `/api/users`, `/api/servers`, `/api/tools`,
  `/api/keys`, `/api/audit`, `/api/overview`. Browser sessions use an HttpOnly
  cookie plus a double-submit CSRF token (`urumi_csrf` → `X-CSRF-Token`).
- Health: `/health`, `/health/ready` (DB check + upstream re-discovery).

## Modules

| File | Responsibility |
|---|---|
| `db.py` | SQLAlchemy models (users, roles, API keys, sessions, server registrations, audit logs) and non-destructive `ensure_schema()` |
| `security.py` | PBKDF2 password hashing, API-key/session token generation, Fernet credential encryption |
| `auth.py` | Login, sessions, API-key auth, bootstrap admin, user creation and roles |
| `policy.py` | Roles/grants/deny from `config/permissions.yaml`; public tool name form `tools:<server>:<tool>` |
| `validation.py` | Upstream URL validation / SSRF protection |
| `registry.py` | Server registration CRUD, credential encryption, health marking, config seeding |
| `upstream.py` | Streamable HTTP MCP client with categorized errors |
| `aggregator.py` | Discovery, `server__tool` naming, failure isolation, routing |
| `audit.py` | Fail-closed audit writes and filtered reads |
| `mcp_server.py` | Aggregated low-level MCP server with per-user tool filtering |
| `api.py` | Management REST API router |
| `app.py` | FastAPI app, ASGI auth middleware, lifespan (schema, bootstrap, seed, refresh) |
| `bootstrap.py` | `python -m services.gateway.bootstrap` CLI |

## Authorization

- The model's tool list is filtered per user via `PermissionPolicy`; tools listed
  in `GATEWAY_MODEL_HIDDEN_TOOLS` are hidden from the list but remain callable by
  authorized users and are still authorized and audited on every call.
- Deny rules always win over grants.
- `GATEWAY_AUDIT_ENABLED=true` makes audit writes fail-closed: the call is
  reported as an error if the audit entry cannot be written.

## Configuration

Environment variables (see `.env.example`) override the `gateway` section of
`config/app.yaml`. Upstream defaults come from `config/servers.yaml`, or
`GATEWAY_SERVERS_CONFIG` for an alternate file (Compose uses
`config/servers.docker.yaml`).
