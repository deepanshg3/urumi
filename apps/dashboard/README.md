# Urumi Dashboard (Passes 6–7)

React + Vite + TypeScript frontend for the Urumi MCP Gateway. Independent of the
Python backend: no shared code, no Python imports — HTTP APIs only.

## Views

- **Overview** — upstream online counts, exposed/permitted tool counts, per-server
  status, recent activity.
- **Chat** — Gemini chat agent. Talks to the agent service (`/agent/api/*`), which
  calls the gateway as an MCP client; shows per-turn tool calls and their status.
- **MCP Servers** — live registry: register (admin), enable/disable, refresh
  discovery, remove; shows status, tool count and whether a credential is stored.
- **Tools** — aggregated gateway tools (`server__tool`) and whether the signed-in
  user may call each one.
- **API Keys** — create/list/revoke personal keys; the plaintext is shown once.
- **Audit Log** — filter by status, paginate; user, server, tool, auth method,
  error and latency per entry.
- **Users** (admin) — create users, activate/deactivate, toggle admin/member.

## Development

```bash
npm install
npm run dev        # http://localhost:5173
npm run build      # type-check + production build
npm run typecheck
```

Set `VITE_API_BASE_URL` to point at a gateway other than the page origin (for
example `http://127.0.0.1:8000`) and `VITE_AGENT_BASE_URL` for the chat agent
(for example `http://127.0.0.1:8200`). Both services allow browser origins listed
in `AGENT_CORS_ORIGINS` / `GATEWAY_CORS_ORIGINS` (default `http://localhost:5173`).
When the dashboard is served by the same Ingress host as the APIs, leave both
empty and use relative paths.

Authentication is cookie-based: `POST /api/auth/login` sets an HttpOnly session
cookie and a readable `urumi_csrf` cookie; the client sends the CSRF value in the
`X-CSRF-Token` header on unsafe requests. MCP clients (not the dashboard) use
`Authorization: Bearer urumi_…` at `/mcp`.

## Notes

- No secrets are stored in the frontend; API keys exist only in component state
  until dismissed.
- There is no automated frontend test runner yet; `npm run build` performs a full
  TypeScript type-check.
