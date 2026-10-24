# Threat Model

Scope: Urumi MCP Gateway platform. Baseline established at Pass 0 and reviewed
at Pass 10; see `docs/security-review.md` for the verification evidence.
STRIDE-oriented.

## Assets

| Asset | Sensitivity |
|---|---|
| WooCommerce consumer key/secret | Critical — full store API access |
| Gemini API key, LangSmith key | Critical |
| Gateway DB: users, API keys, audit logs | High |
| Per-user gateway API keys (revocable) | High |
| WooCommerce/WordPress MySQL data | High |
| LLM conversation content | Medium |

## Trust boundaries

1. Internet/VPS → dashboard (public entry point; nginx single origin).
2. Dashboard → gateway / agent (HTTP only; no direct DB or upstream access).
3. Gateway → upstream MCP servers (internal, streamable HTTP).
4. Agent → gateway MCP endpoint (authenticated with a short-lived delegated key).
5. MCP servers → WooCommerce REST API / mock carrier / inventory data (egress).
6. LLM provider (Gemini) ↔ agent: **tool schemas and authorized results only**.

## Threats and mitigations

| # | Threat | Mitigation (status) |
|---|---|---|
| T1 | Stolen/leaked gateway API key | Individual revocable keys, only SHA-256 hashes stored, revocation takes effect on next call (P6 — implemented, tested) |
| T2 | Privilege escalation (member calling admin tools) | AuthZ on every call incl. model-hidden tools; deny-wins rules (P6 — implemented, tested) |
| T3 | Tool call bypassing audit | Audit logging inside the gateway call path; fail-closed when enabled (P6 — implemented, tested) |
| T4 | Upstream credential exfiltration to LLM/clients | Credentials server-side only; encrypted at rest with Fernet; never in tool results, API views, logs, or LLM context (P2+/P6 — implemented, tested) |
| T5 | Prompt injection causing destructive tool calls | Permission gating, per-tool grants/deny in permissions.yaml, audit review; the agent can only call tools the user is permitted, and every call is re-authorized at the gateway (P6/P7 — implemented) |
| T6 | Secrets committed to git | `.gitignore`, `.env.example` placeholders only, secret scan performed at P10 (implemented) |
| T7 | Compromised MCP server poisoning results | Servers isolated/standalone, gateway validates typed outputs and isolates a failing upstream (P5 — implemented, tested) |
| T8 | SQL injection / malformed inputs | SQLAlchemy parameterization + Pydantic validation on all inputs (P1/P6 — implemented, tested) |
| T9 | Mock shipping provider abused as if real | Mock clearly flagged in tool outputs; failure-rate config (P4 — implemented) |
| T10 | Unencrypted traffic in production | Optional ingress TLS; recommend TLS + NetworkPolicy in production (P9 — chart supports; not enforced in the local Kind demo) |
| T11 | SSRF via admin-registered upstream URL | Host allowlist, public opt-in, private/loopback/link-local/metadata address rejection, DNS re-resolution (P5 — implemented, tested) |
| T12 | CSRF on the management API | HttpOnly session cookie + double-submit CSRF header on unsafe methods; SameSite=strict (P6 — implemented, tested) |
| T13 | Session/key brute force or timing attacks | Opaque 256-bit tokens, PBKDF2-SHA256 (600k) password hashing, constant-time comparison, no user enumeration (P6 — implemented) |
| T14 | Agent abused to exceed user rights or loop/exhaust | Agent mints a per-user delegated key scoped to that user; tools are discovered with the user's permissions; the gateway re-authorizes each call; hard caps on iterations, tool calls, message size and history (P7 — implemented, tested) |
| T15 | Kubernetes secret exposure | Secrets only from a Secret object (templated or pre-created); `DATABASE_URL` expands `$(POSTGRES_PASSWORD)` rather than embedding it; no plaintext secrets in values or git (P9 — implemented) |
| T16 | Assessment demo mode mistaken for production auth / used as a bypass | Off by default; requires `GATEWAY_DEMO_MODE` + `GATEWAY_DEMO_ACK`; refuses production; fixed persona allowlist mapped to persisted roles; loopback/Host/Origin gating; CSRF-protected switching that revokes the old session; no API keys or usable passwords for personas (implemented, tested) |

## Out of scope

Multi-tenant network isolation and a production WAF are out of scope; the local
Kind deployment does not enable TLS or NetworkPolicies (the production overlay
provides the hooks).
