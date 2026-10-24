# Roles and Permissions

Urumi MCP Gateway ships three roles. Every request — REST or MCP — is
authorized by the gateway against `config/permissions.yaml`; the dashboard only
*hides* what a user may not do, it never grants anything.

| Role | Id | Purpose |
|---|---|---|
| **Administrator** (Super Admin) | `admin` | Runs the gateway: manages servers, users, roles, API keys and reads every audit entry. Full tool access. |
| **Operator** | `member` | Day-to-day store operations: reads everything, updates shipment status, never administers the gateway. |
| **Viewer** (read-only) | `viewer` | Read-only observer: sees tools, servers and their own audit trail, changes nothing. |

The role ids are stable (`admin`, `member`, `viewer`) because they are stored
in the database; the display names live in the dashboard (`Administrator`,
`Operator`, `Viewer`).

## How authorization works

1. **AuthN first.** A session cookie (browser) or a revocable API key (MCP)
   identifies the caller.
2. **Effective permissions.** The user's roles are resolved to a set of
   permission strings at request time (`PermissionPolicy.for_roles`). A user
   with several roles gets the union of their permissions.
3. **Deny wins.** Within a role, a `deny` rule beats every `grant` of the same
   role, including a wildcard grant. A grant from a *different* role still
   applies — a user who holds both `viewer` and `member` gets the operator's
   shipment update.
4. **Every call is checked.** The check runs inside the MCP call path
   (`services/gateway/mcp_server.py`), so a tool that is hidden from the
   model's tool list (`gateway.model_hidden_tools`) is still guarded. Hidden
   ≠ unguarded.
5. **Fail-closed audit.** Denied calls are recorded with status `denied` and
   `error_code=permission_denied`.

## Permission namespaces

### Gateway management (`gateway:<area>:<action>`)

| Permission | Meaning |
|---|---|
| `gateway:servers:manage` | Register, update, enable/disable, refresh and remove upstream MCP servers. |
| `gateway:keys:manage` | Issue and revoke API keys for **any** account. |
| `gateway:keys:manage:own` | Issue and revoke API keys for the **caller's own** account. |
| `gateway:keys:read` | List API keys (own account, or any account with `gateway:keys:manage`). |
| `gateway:users:manage` | Create and update users, change roles, reset passwords. |
| `gateway:audit:read` | Read audit entries — the caller's own unless `gateway:audit:read:all` is also held. |
| `gateway:audit:read:all` | Read every audit entry (admins). |
| `gateway:tools:read` | Read the tool catalog and the server list. |
| `gateway:tools:read:all` | Read the **full** catalog, including tools the caller may not call (they are flagged `permitted: false`). |

### Upstream tools (`tools:<server_id>:<upstream_tool>`)

The separator is `:` (not `__`) so that `*` is an unambiguous wildcard, e.g.
`tools:inventory:*` covers every inventory tool. The upstream tool name is the
name the MCP server exposes — `list_products`, `update_shipment_status`, … —
not the aggregated `server__tool` name.

## REST matrix

| Endpoint | admin | member | viewer |
|---|---|---|---|
| `POST /api/auth/login`, `GET /api/auth/me`, `POST /api/auth/logout` | ✅ | ✅ | ✅ |
| `GET /api/overview` | ✅ | ✅ | ✅ (own activity only) |
| `GET /api/tools`, `GET /api/servers`, `GET /api/servers/{id}/tools` | ✅ full catalog | ✅ permitted tools | ✅ permitted tools |
| `GET /api/audit` | ✅ all entries | ✅ own entries | ✅ own entries |
| `GET /api/keys`, `POST /api/keys`, `DELETE /api/keys/{id}` | ✅ any account | ✅ own account only | ❌ 403 |
| `GET /api/users`, `POST /api/users`, `PATCH /api/users/{id}` | ✅ | ❌ 403 | ❌ 403 |
| `POST /api/users/{id}/password` | ✅ | ❌ 403 | ❌ 403 |
| `POST/PATCH/DELETE /api/servers…`, `…/enable`, `…/refresh` | ✅ | ❌ 403 | ❌ 403 |

## MCP tool matrix

The 14 upstream tools the platform ships:

| Tool (`server__tool`) | Permission | admin | member | viewer |
|---|---|---|---|---|
| `woocommerce__list_products` | `tools:woocommerce:list_products` | ✅ | ✅ | ✅ |
| `woocommerce__list_orders` | `tools:woocommerce:list_orders` | ✅ | ✅ | ✅ |
| `woocommerce__get_order` | `tools:woocommerce:get_order` | ✅ | ✅ | ✅ |
| `woocommerce__create_product` | `tools:woocommerce:create_product` | ✅ | ❌ deny | ❌ deny |
| `woocommerce__update_order_status` | `tools:woocommerce:update_order_status` | ✅ | ❌ deny | ❌ deny |
| `inventory__check_stock` | `tools:inventory:*` | ✅ | ✅ | ✅ |
| `inventory__find_low_stock_products` | `tools:inventory:*` | ✅ | ✅ | ✅ |
| `inventory__get_inventory_summary` | `tools:inventory:*` | ✅ | ✅ | ✅ |
| `inventory__calculate_reorder_quantity` | `tools:inventory:*` | ✅ | ✅ | ✅ |
| `shipping__track_shipment` | `tools:shipping:track_shipment` | ✅ | ✅ | ✅ |
| `shipping__get_shipment` | `tools:shipping:get_shipment` | ✅ | ✅ | ✅ |
| `shipping__list_shipments` | `tools:shipping:list_shipments` | ✅ | ✅ | ✅ |
| `shipping__update_shipment_status` | `tools:shipping:update_shipment_status` | ✅ | ✅ | ❌ deny |
| `shipping__create_shipment` | `tools:shipping:create_shipment` | ✅ | ❌ deny | ❌ deny |

**The operator is the viewer plus exactly one tool**: `shipping__update_shipment_status`.
Creating a shipment, creating a product and changing an order status stay with
the administrator.

Tool *discovery* follows the same rules: a user only sees the tools it may
call (except admins, who see the whole catalog with a `permitted` flag), and a
tool hidden from the model's tool list is still authorized on every call.

## Password reset

`POST /api/users/{user_id}/password` (admin only, CSRF required):

- the new password is PBKDF2-SHA256 hashed before it is stored;
- it is never echoed back and never logged;
- **every browser session of the target account is revoked**, so the reset
  takes effect immediately (resetting your own password signs you out);
- the minimum length is 12 characters.

In the dashboard an administrator uses **Team → Manage → Set password**.
The field is disabled until the new password is at least 12 characters, the
request carries the CSRF token, and the modal closes without ever showing
the secret. This flow is exercised end-to-end (headless Chrome) in
`docs/live-validation-report.md` §8.1.

## Demo personas

For local assessments, enable demo mode (`docs/demo-mode.md`) and pick a
persona from the dashboard entry screen. The gateway maps each fixed persona to
a real persisted user with a real server-side session:

| Persona | Email | Role |
|---|---|---|
| `admin` | `demo-admin@urumi.demo` | admin |
| `operator` | `demo-operator@urumi.demo` | member (Operator) |
| `viewer` | `demo-viewer@urumi.demo` | viewer |

The persona users get random unused passwords and no API keys; they cannot be
used for password login. Switching personas revokes the previous session and
requires its CSRF token, so the browser never holds two identities at once.
Only the three ids are accepted — a role or user id from the client is ignored.
`docs/demo-mode.md` covers the acknowledgement, production refusal, local/origin
restrictions, verification and revocation.

Normal deployments continue to use the login form. The bootstrap administrator
is created with `BOOTSTRAP_ADMIN_EMAIL`/`BOOTSTRAP_ADMIN_PASSWORD`, and
additional users are created from **Team** in the dashboard.

## Changing the policy

`config/permissions.yaml` is the single source of truth for roles, grants and
denies. It is baked into the container images (`deploy/docker/mcp/Dockerfile`)
and loaded at process start, so a change requires a **rebuild and restart** of
the gateway and the agent.

```yaml
roles:
  member:
    description: Operator role — runs store operations, never administers the gateway.
    permissions:
      - "gateway:audit:read"
      - "gateway:keys:manage:own"
      - "gateway:keys:read"
      - "gateway:tools:read"
grants:
  member:
    - "tools:shipping:update_shipment_status"
deny:
  member:
    - "tools:shipping:create_shipment"
```

Notes:

- `roles.<role>.permissions` are the permissions a role grants; `grants` and
  `deny` add per-tool grants and per-tool refusals for the same role.
- Roles are seeded into the database on startup. Users reference role ids, so
  renaming a role id requires a data migration.
- A deny rule only narrows the role that declares it. To deny a tool for
  everyone, declare it in every role's `deny` list.

## Where this is tested

- `tests/unit/test_gateway_roles.py` — the role matrix, deny precedence, key
  and user administration boundaries, audit scoping, password reset and session
  revocation, and the MCP-level enforcement for all three roles.
- `tests/unit/test_gateway_policy.py` — permission parsing and matching.
- `tests/unit/test_gateway_api.py`, `tests/unit/test_gateway_mcp.py` — the
  generic gateway behaviour the roles build on.
- `tests/unit/test_gateway_demo.py` — demo-mode enablement guards, persona
  allowlist, real persisted sessions, REST/MCP boundaries per persona,
  switching/CSRF/revocation, audit rows and the local/origin restrictions.
- `scripts/verify_demo.py` — a live, credential-free harness against a running
  demo deployment:

  ```bash
  .venv/bin/python scripts/verify_demo.py http://127.0.0.1:8000
  ```

  It prints one line per check and never prints a secret. The live results for
  Compose and Kind are recorded in `docs/live-validation-report.md`.
