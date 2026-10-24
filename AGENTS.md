# AGENTS.md — Project Instructions for OpenCode

**Urumi MCP Gateway** — a team MCP gateway platform. Read this before any work.

## Hard rules

1. **Do not begin a later implementation pass without explicit instruction.**
   Passes are defined in `docs/implementation-plan.md`. Pass 0 (foundation) is complete only per its acceptance criteria.
2. **Never claim untested features work.** Run the relevant tests and inspect errors before declaring success. If a test could not be run, say so explicitly.
3. **No hardcoded secrets.** All secrets come from environment variables / `.env` (gitignored) or a secret manager. `.env.example` holds placeholders only. Never paste real credentials into any file.
4. **Never replace the custom WooCommerce MCP implementation with an existing/third-party WooCommerce MCP server.** We build our own Python MCP server in `services/woocommerce_mcp/`.
5. **No destructive operations** (deleting data, force-pushing, wiping volumes/databases) and **no pushing to a remote repository** without explicit permission.
6. **No sudo, system package installs, or system configuration changes** without asking first.
7. **Tests are required for every implemented feature.** A feature without a passing test is not done.

## Architecture and responsibilities

```
AI client / dashboard  →  MCP Gateway  →  upstream MCP server  →  underlying app/API  →  result back through gateway
```

- `services/gateway/` — FastAPI service. Aggregates upstream MCP servers, routes tool calls, authenticates users, enforces permissions (AuthZ) on **every** tool call — including direct calls to tools hidden from the model's tool list — records audit logs, manages API keys and server enable/disable state.
- `services/woocommerce_mcp/` — custom Python MCP server exposing WooCommerce products/orders through the official WooCommerce REST API (credentials stay server-side).
- `services/inventory_mcp/` — custom Python MCP server: stock lookup, low-stock detection, inventory summaries, reorder recommendations.
- `services/shipping_mcp/` — custom Python MCP server: shipment records, tracking status, pending fulfillments; configurable mock shipping provider (no paid API).
- `apps/dashboard/` — React + Vite + TypeScript frontend. **Independent of the Python backend** — no shared code, no Python imports; communicates over HTTP APIs only.
- `config/` — YAML configuration (`app.yaml`, `servers.yaml`, `permissions.yaml`) and prompts. Model names, tracing, DB URL, server definitions and mock behavior are configurable without code changes.
- `tests/` — pytest suite for backend; frontend has its own checks.

Authentication (who is the user) and authorization (what may they do) are separate concerns; both are enforced at the gateway before any upstream call.

## Conventions

- **Python-first backend**; use the Python version in `.venv` (see README). Keep services decoupled: each MCP server must be runnable and testable standalone.
- **Typed everything**: Pydantic request/response models for HTTP APIs and validated inputs/outputs for MCP tool schemas.
- **Database abstraction**: SQLAlchemy with `DATABASE_URL`; SQLite for local dev, PostgreSQL/Supabase configurable later. Never use SQLite for WooCommerce/WordPress — that is MySQL/MariaDB.
- **Upstream credentials are server-side only** — never returned in API responses, logs sent to clients, or LLM context.
- Pin dependency ranges in `pyproject.toml`; do not blindly install unverified versions.

## Standard workflow

1. Inspect existing code before changing it; do not overwrite files blindly.
2. Implement → write/update tests → run `pytest` (and frontend checks if frontend changed).
3. Read failures, fix, re-run until green.
4. Summarize what was done with file references; mark anything untested as untested.
