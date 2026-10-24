# Assessment demo mode

Demo mode lets an evaluator enter the dashboard as one of three fixed personas
without an email or password, so a walkthrough can start in seconds. It is
**not** a second authentication system: each persona is a real persisted user
with a real server-side session, and the gateway enforces the same RBAC on every
REST and MCP request.

It is disabled by default and refuses to start in production.

## How it behaves

| Persona | Persisted role | Dashboard label | May |
|---|---|---|---|
| `admin` | `admin` | Administrator | every tool, user/server/key administration, the whole audit log |
| `operator` | `member` | Operator | all reads plus `shipping__update_shipment_status`; own API keys only |
| `viewer` | `viewer` | Viewer | all reads; no changes and no API-key management |

- `GET /api/auth/demo` is public and returns the allowlist (never a secret).
- `POST /api/auth/demo/session` accepts **only** a persona id. The server maps
  it to the dedicated `demo-<persona>@urumi.demo` user; a role, email or user id
  from the client is never trusted.
- The previous browser session is revoked before the new one is created, so
  switching replaces the identity instead of layering on top of it.
- When a request rides an existing session, switching requires the session's
  CSRF token (`X-CSRF-Token` matching the `urumi_csrf` cookie).
- Demo users get a random, unused password and **no API keys**. They cannot be
  used for normal password login.
- Switches are written to the audit log (`server_id="demo-mode"`,
  `public_tool="demo_persona_switch"`).
- The dashboard shows an **ASSESSMENT DEMO** badge, a persona dropdown and a
  **Switch persona** action. A failed switch re-reads `/api/auth/me`, so the UI
  never keeps displaying a role the gateway has stopped honoring. **Refresh
  data** remounts the role-sensitive pages and reloads them from the deployed
  gateway/database.

## Enabling it

All settings are environment variables:

| Variable | Default | Meaning |
|---|---|---|
| `GATEWAY_DEMO_MODE` | `false` | Turn the persona endpoints and `/mcp` cookie auth on. |
| `GATEWAY_DEMO_ACK` | `false` | Explicit acknowledgement; enabling requires it. |
| `GATEWAY_DEPLOYMENT_ENV` | `development` | `production`/`prod` with demo mode makes startup fail. |
| `GATEWAY_DEMO_ALLOW_REMOTE` | `false` | Skip the loopback-client check. |
| `GATEWAY_DEMO_ORIGINS` | empty | Extra browser origins allowed to start a session. |

Validation happens in `services/common/config.py` (`_validate_demo_mode`), so
the process exits instead of starting a half-configured demo gateway.

Compose is off by default. Enable it for a local assessment by starting the
stack with both flags:

```bash
GATEWAY_DEMO_MODE=true GATEWAY_DEMO_ACK=true \
GATEWAY_DEMO_ORIGINS=http://localhost:5173,http://127.0.0.1:5173 \
  docker compose -f deploy/docker/mcp/compose.yaml up -d gateway dashboard
```

The Kind overlay (`deploy/helm/urumi/values-kind.yaml`) enables it explicitly:

```yaml
gateway:
  env:
    GATEWAY_DEMO_MODE: "true"
    GATEWAY_DEMO_ACK: "true"
    GATEWAY_DEPLOYMENT_ENV: assessment
    GATEWAY_DEMO_ORIGINS: "http://localhost:8088,http://127.0.0.1:8088"
```

The Helm chart fails rendering if `GATEWAY_DEMO_MODE=true` is set without
`GATEWAY_DEMO_ACK=true`:

```text
GATEWAY_DEMO_MODE=true requires GATEWAY_DEMO_ACK=true (assessment deployments only)
```

## Request restrictions

`services/gateway/demo.py::demo_request_allowed` allows a session request when:

1. any `Origin` header is in `GATEWAY_DEMO_ORIGINS` + `GATEWAY_CORS_ORIGINS`; and
2. the client address is loopback, **or** the `Host` header is
   `localhost`/`127.0.0.1`/`::1`, **or** `GATEWAY_DEMO_ALLOW_REMOTE=true`.

Everything else gets `403 demo mode is restricted to local assessment
deployments`. When demo mode is off, both endpoints are `404` and `/mcp`
continues to accept only Bearer API keys; in demo mode the `/mcp` middleware
additionally accepts the session cookie so an MCP client can act as the
selected persona.

## Verifying a deployment

`scripts/verify_demo.py` needs no credentials. It enters every persona and
checks the catalog, persisted roles, empty key lists, REST boundaries, CSRF on
switching, revocation of the replaced session, the audit row, and per-persona
MCP visibility/denials:

```bash
.venv/bin/python scripts/verify_demo.py http://127.0.0.1:8000     # Compose
.venv/bin/python scripts/verify_demo.py http://localhost:8088     # Kind
```

Expected MCP tool counts: admin 13 (one hidden from the model list), operator
11, viewer 10 — 14 upstream tools in total. Unit coverage lives in
`tests/unit/test_gateway_demo.py` (19 tests).

## Retiring the old assessment accounts

Earlier walkthroughs used password-based `assessment-*@urumi.local` accounts.
They are no longer created. To remove any that still exist, run the revocation
script against the deployment:

```bash
scripts/revoke_assessment_credentials.sh compose
scripts/revoke_assessment_credentials.sh kind
```

It deletes those accounts' API keys, revokes their sessions, rotates their
passwords to random values that are never printed, deactivates them, and
deletes `assessment-credentials*.txt` from the checkout. Set
`KEEP_CREDENTIAL_FILES=1` to keep the files. Demo personas are not touched, and
normal accounts continue to sign in through the login form.

## What it does not do

- It does not grant permissions beyond the three roles.
- It does not bypass authorization, CSRF, audit, or upstream credential
  handling.
- It does not enable password login for demo users, and it does not mint API
  keys for them.
- It is not safe on a public host. Keep the deployment loopback/local, or set
  the acknowledgement and origin allowlist deliberately for a time-boxed
  assessment, then turn `GATEWAY_DEMO_MODE` off again.
