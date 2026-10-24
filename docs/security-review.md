# Security Review (Pass 10)

Review of the platform against `docs/threat-model.md`. Evidence is either a
test, a live check, or a source reference. Anything not exercised here is marked
**not verified** with the reason.

## Threat checklist

| # | Threat | Status | Evidence |
|---|---|---|---|
| T1 | Stolen/leaked API key | ✅ verified | Keys stored as SHA-256 hashes; revocation tested in `tests/unit/test_gateway_identity.py`; live key created/used/revoked against the Kind gateway. |
| T2 | Privilege escalation | ✅ verified | `tests/unit/test_gateway_roles.py` (role matrix, deny precedence, REST and MCP enforcement for admin/operator/viewer), `tests/unit/test_gateway_mcp.py::test_member_cannot_call_ungranted_tool`; authz enforced in `services/gateway/mcp_server.py` and `services/gateway/api.py`. |
| T3 | Audit bypass | ✅ verified | Audit written inside the gateway call path; `services/gateway/audit.py`; fail-closed behaviour covered by gateway tests. |
| T4 | Credential exfiltration to LLM/clients | ✅ verified | Upstream creds live only in settings/Secret; `config/servers.yaml` uses `${VAR}`; tool results sanitized (`tests/unit/test_woocommerce_mcp.py`); agent never receives upstream creds. |
| T5 | Prompt injection → destructive calls | ✅ verified | Agent discovers tools with the *user's* permission filter and every call is re-authorized at the gateway; deny rules in `config/permissions.yaml`. |
| T6 | Secrets committed to git | ✅ verified | Filesystem scan for `AIza…`, `ck_…`, `cs_…`, private keys, and the known local-only credentials returned no matches; `.env` is gitignored (`.env.example` has placeholders only). |
| T7 | Poisoned upstream results | ✅ verified | Gateway isolates failing upstreams (`healthy_only` filtering, `last_error`); typed result validation in the aggregator. |
| T8 | SQL injection / malformed input | ✅ verified | SQLAlchemy parameterization everywhere; Pydantic models on all HTTP inputs and MCP schemas; malformed-input tests in `tests/unit/test_agent.py` and MCP suites. |
| T9 | Mock provider mistaken for real | ✅ verified | Shipping tool outputs flag the mock provider and honor configured failure rates (`tests/unit/test_shipping_mcp.py`). |
| T10 | Plaintext production traffic | ⚠️ partial | Chart supports ingress + TLS (`ingress.tls`); NetworkPolicy not included. The local Kind demo is HTTP by design. |
| T11 | SSRF via upstream URL | ✅ verified | `services/gateway/security.py` rejects private/loopback/link-local/metadata addresses and requires an allowlist; tests in `tests/unit/test_gateway_security.py`. |
| T12 | CSRF | ✅ verified | Live: `POST /agent/api/chat` without `X-CSRF-Token` → **403**; with token → 200. Cookie is `HttpOnly` + `SameSite=strict`. |
| T13 | Brute force / timing | ✅ verified | PBKDF2-SHA256 (600k) password hashing, opaque 256-bit tokens, constant-time compare; identity tests cover enumeration and revocation. |
| T14 | Agent abuse | ✅ verified | Live: `/mcp` without a key → **401**; `/agent/api/tools` without a session → **401**; iteration/tool-call caps exercised live with a real model (4/4); config in `services/common/config.py` (`AgentSettings`), enforcement in `services/agent/executor.py`. |
| T15 | K8s secret exposure | ✅ verified | Rendered manifests contain no plaintext DB password — `DATABASE_URL` uses `$(POSTGRES_PASSWORD)` expanded by Kubernetes after `POSTGRES_PASSWORD` is defined; secrets come from a Secret object. |
| T16 | Demo mode abused as an auth bypass | ✅ verified | Off by default; requires `GATEWAY_DEMO_MODE` **and** `GATEWAY_DEMO_ACK`; startup fails for `GATEWAY_DEPLOYMENT_ENV=production`; only the fixed `admin`/`operator`/`viewer` allowlist is accepted; requests must be loopback/Host-local or origin-allowlisted; switching requires the existing session's CSRF token and revokes that session; personas have no API keys and cannot password-login. Covered by `tests/unit/test_gateway_demo.py`; live checks in `docs/live-validation-report.md` §8.2. |

## Assessment demo mode

Demo mode is a deliberately narrow, assessment-only entry path. The review
points are:

- **Fail closed.** `services/common/config.py::_validate_demo_mode` rejects
  `GATEWAY_DEMO_MODE=true` without `GATEWAY_DEMO_ACK=true`, and rejects demo
  mode when `deployment_env` is `production`/`prod`. The Helm chart also fails
  rendering if the acknowledgement is missing.
- **Fixed identities.** `services/gateway/demo.py::DEMO_PERSONAS` is the only
  source of personas; the request body carries just an id and never a role,
  user id or email. Unknown ids return 400.
- **Real sessions and RBAC.** `POST /api/auth/demo/session` creates the same
  server-side session as a password login (`services/gateway/auth.py`), so REST
  and MCP authorization run unchanged. Demo-only cookie auth for `/mcp` is
  enabled only while demo mode is on.
- **No extra credentials.** `ensure_demo_users` stores a random unused password
  and creates no API keys; the persona catalog contains no secret material.
- **Switching.** An existing session must present `X-CSRF-Token`; the old
  session is revoked first, then the new one is issued. Audit rows use
  `server_id="demo-mode"`.
- **Locality.** Origin, if present, must be allowlisted, and the client must be
  loopback or use a local `Host` header unless `GATEWAY_DEMO_ALLOW_REMOTE=true`.

Residual risk: demo mode is an intentional local convenience, not a
production authentication mechanism. Anyone who can reach the dashboard while
it is enabled can switch personas; keep it loopback/local or time-box it, and
turn it off after the assessment.

## Live checks run against the Kind deployment

```
POST /agent/api/chat  (no CSRF header)      -> 403
POST /mcp             (no Authorization)    -> 401
GET  /agent/api/tools (no session cookie)   -> 401
GET  /mcp             (no Authorization)    -> 401
GET  /api/tools       (admin session)       -> 14 tools; MCP list_tools -> 13 (1 hidden)
GET  /api/overview    (admin session)       -> 3/3 upstreams healthy
gateway/agent/MCP /health/ready             -> 200 (all five)
```

A full MCP round trip was executed with a real API key:
`woocommerce__list_products` and `inventory__get_inventory_summary` returned
real store data through the gateway. 47 MCP checks and 39 auth/authz checks
passed on both Compose and Kind; see `docs/live-validation-report.md`.

## Not verified

- **Remote k3s deployment** — no VPS/Supabase credentials available. The
  `values-prod.yaml` overlay lints/renders but was not installed on a remote
  cluster.
- **TLS / NetworkPolicy enforcement** — provided as configuration hooks, not
  exercised locally.

## Residual risks

- Bundled PostgreSQL/WordPress are single-replica with no backups — acceptable
  for a demo, not for production. Use `database.url` + a managed DB in
  production and configure backups.
- The Kind demo uses generated-but-printed credentials stored in a gitignored
  file; rotate anything used outside local development. The old password-based
  `assessment-*@urumi.local` accounts were retired with
  `scripts/revoke_assessment_credentials.sh` once demo mode replaced them.
- **Shared secret scope in Compose.** Every service receives the root `env_file`,
  so the agent container holds WooCommerce credentials and the gateway/MCP
  containers hold the Gemini key. Use per-service secrets or a secret manager
  for production.
- **`gateway:*` permissions are now enforced.** The REST API authorizes with
  `require_permission(...)` (`services/gateway/api.py`) against
  `config/permissions.yaml`, so a custom role granted, e.g.
  `gateway:audit:read` is honoured instead of being denied. The role matrix is
  documented in `docs/roles-and-permissions.md` and covered by
  `tests/unit/test_gateway_roles.py`.
- Upstream tool arguments are validated twice (agent schema + gateway), but an
  upstream that is unhealthy is reported to direct MCP clients as
  `unknown_tool` rather than `upstream_unavailable`; operators should check
  `/health/ready` for the precise cause.
