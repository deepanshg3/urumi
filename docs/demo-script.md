# Demo Script

A ~10 minute walkthrough of the Urumi MCP Gateway platform. Commands use the
Kind deployment (`docs/deployment.md`); the dashboard is at
`http://localhost:8088`.

```bash
export PATH="$HOME/.local/bin:$PATH"
scripts/k8s/deploy-kind.sh        # if not already running
PW="$(kubectl -n urumi get secret urumi-secrets \
  -o jsonpath='{.data.bootstrap-admin-password}' | base64 -d)"
```

## 1. The platform is up

```bash
scripts/k8s/verify.sh
```

Five health endpoints green: gateway, agent, and the three MCP servers.

## 2. Dashboard overview (UI)

Open `http://localhost:8088`, sign in as `admin@urumi.local` / `$PW`.

- **Overview** — 3/3 upstreams enabled and healthy, 14 tools.
- **Servers** — WooCommerce, Inventory, Shipping; enable/disable and refresh.
- **Tools** — the 14 aggregated tools (`<server>__<tool>` naming).
- **API keys** — create/revoke per-user keys (plaintext shown once).
- **Audit** — every tool call with user, tool, status.
- **Chat** — the Gemini agent (see step 4).

## 3. Gateway as the single entry point

Each service only faces the dashboard's nginx; the gateway is the only path to
tools. Show the same data from the API:

```bash
curl -s -c /tmp/c -X POST http://localhost:8088/api/auth/login \
  -H 'Content-Type: application/json' \
  -d "{\"email\":\"admin@urumi.local\",\"password\":\"$PW\"}" | python3 -m json.tool
curl -s -b /tmp/c http://localhost:8088/api/overview | python3 -m json.tool
```

## 4. Chat agent → gateway → store

In the **Chat** tab, ask: *"How many products are out of stock, and what are the
low-stock items?"*

The agent discovers the user's permitted tools via the gateway, then calls
`inventory__get_inventory_summary` / `woocommerce__list_products`. The reply
cites real store data and the UI shows each tool call.

> Without a real `GEMINI_API_KEY` the reply is a clear configuration message and
> no tool call runs. Set the key and `helm upgrade` to demonstrate the full turn.

## 5. Authorization on every call

Create a member user with a limited grant (Servers/Tools UI or API), mint a key
for them, and show that a tool outside their grants is rejected — and that a
*model-hidden* tool called directly is also rejected (deny wins). The relevant
unit tests are `tests/unit/test_gateway_mcp.py`.

### 5.1 The three roles, side by side

The assessment deployment runs with **demo mode** on: open the dashboard and the
entry screen offers the three fixed personas. No password or credentials file is
needed.

| Persona | Role | May | May not |
|---|---|---|---|
| Administrator | `admin` | every tool, user/server/key administration, the whole audit log | — |
| Operator | `member` | all reads **plus** `shipping__update_shipment_status`; own API keys | create products, change order status, create shipments, any gateway administration |
| Viewer | `viewer` | all reads | every mutation, and no API-key management at all |

1. Enter as **Administrator**. The header shows the **ASSESSMENT DEMO** badge and
   a persona dropdown. The navigation includes **Users** and **API Keys**.
2. Use **Switch persona** (or the dropdown) to become **Operator**: **Users**
   disappears, **API Keys** remains, and creating a product/order change is
   refused by the gateway even if the request is sent directly.
3. Switch to **Viewer**: **API Keys** disappears too; every mutation is refused.
4. Use **Refresh data** to show the pages reload from the real gateway/database
   for the current persona, then switch back to Administrator.

Each switch is a real session replacement: the previous session is revoked and
the browser carries a new CSRF token. The gateway keeps authorizing REST and MCP
calls against the same `config/permissions.yaml` matrix used by normal logins.

For a scripted pass over the same properties:

```bash
.venv/bin/python scripts/verify_demo.py http://localhost:8088   # Kind
.venv/bin/python scripts/verify_demo.py http://127.0.0.1:8000   # Compose
```

Expected: every check passes — the persona catalog, REST boundaries, session
revocation and CSRF, audit rows, and tool visibility (13 / 11 / 10 of 14
upstream tools, with one model-hidden). Details are in `docs/demo-mode.md`.

## 6. Raw MCP round trip (proof the tools work)

```bash
# create an API key in the UI (or POST /api/keys with X-CSRF-Token), then:
python3 - <<'PY'
import asyncio
from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client
KEY = "urumi_..."  # paste here

async def main():
    async with streamablehttp_client(
        "http://localhost:8088/mcp", headers={"Authorization": f"Bearer {KEY}"}
    ) as (r, w, _):
        async with ClientSession(r, w) as s:
            await s.initialize()
            print(len((await s.list_tools()).tools), "tools")
            out = await s.call_tool("woocommerce__list_products", {})
            print(out.content[0].text[:400])

asyncio.run(main())
PY
```

## 7. Security posture (quick checks)

```bash
curl -s -o /dev/null -w 'no-CSRF chat:   %{http_code}\n' -X POST \
  http://localhost:8088/agent/api/chat -H 'Content-Type: application/json' -d '{"message":"hi"}'
curl -s -o /dev/null -w 'anon /mcp:       %{http_code}\n' -X POST http://localhost:8088/mcp
curl -s -o /dev/null -w 'anon agent api:  %{http_code}\n' http://localhost:8088/agent/api/tools
```

Expected: `403`, `401`, `401`.

## 8. Store

`http://localhost:8081` (WooCommerce storefront; `/wp-admin` for WordPress).

The store runs the **Urumi Supply** theme: a twelve-product catalogue in three
categories (Desk & Paper, Carry, Tabletop) with custom SVG artwork, a working
cart and checkout (cash on delivery, free shipping over $60), and one demo
order. Three products sit at or below the low-stock threshold and one is out of
stock, so the inventory tools have real data to report.

Walkthrough:

1. `/` — hero, featured products, categories.
2. `/shop/` — the full catalogue; filter by category, search from the header.
3. `/product/field-notes-journal/` — product detail with stock state, SKU and
   related products.
4. Add a product to the bag → `/cart/` → `/checkout/` → place the order.
5. The same data is what the MCP tools read — ask the agent about low stock or
   a pending fulfilment and it comes from this store.

See `docs/storefront.md` for the catalogue table and the theme layout.

## Cleanup

```bash
scripts/k8s/delete.sh       # remove the release
scripts/k8s/kind-down.sh    # delete the cluster
```
