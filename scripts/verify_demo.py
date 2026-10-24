#!/usr/bin/env python3
"""Live verification of the assessment demo mode against a running gateway.

    .venv/bin/python scripts/verify_demo.py http://127.0.0.1:8000

No credentials are needed: the script enters each fixed persona, then checks
that the resulting sessions are real, that REST and MCP authorization still
enforce the three-role policy, and that switching revokes the old session.
It never prints passwords, API keys or hashes.
"""

from __future__ import annotations

import asyncio
import sys

import httpx
from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client

PASS = 0
FAIL = 0
FAILURES: list[str] = []

PERSONAS = ("admin", "operator", "viewer")
ROLES = {"admin": "admin", "operator": "member", "viewer": "viewer"}
EXPECTED_TOOLS = {"admin": 13, "operator": 11, "viewer": 10}


def check(name: str, ok: bool, detail: str = "") -> None:
    global PASS, FAIL
    if ok:
        PASS += 1
        print(f"  PASS  {name}" + (f"  [{detail}]" if detail else ""))
    else:
        FAIL += 1
        FAILURES.append(f"{name} {detail}")
        print(f"  FAIL  {name}" + (f"  [{detail}]" if detail else ""))


def client_factory(base: str, cookies: dict[str, str] | None = None):
    def factory(headers=None, timeout=None, auth=None, **kwargs):
        client = httpx.AsyncClient(
            headers=headers, timeout=timeout, auth=auth, base_url=base
        )
        for name, value in (cookies or {}).items():
            client.cookies.set(name, value)
        return client

    return factory


async def enter(
    base: str, persona: str, *, origin: str | None = None, csrf: str | None = None
) -> tuple[httpx.AsyncClient, httpx.Response]:
    client = httpx.AsyncClient(base_url=base, timeout=30.0)
    headers: dict[str, str] = {}
    if origin:
        headers["Origin"] = origin
    if csrf:
        headers["X-CSRF-Token"] = csrf
    response = await client.post(
        "/api/auth/demo/session", json={"persona": persona}, headers=headers
    )
    return client, response


async def demo_config(base: str) -> bool:
    print("Demo entry")
    async with httpx.AsyncClient(base_url=base, timeout=30.0) as anon:
        response = await anon.get("/api/auth/demo")
        check("demo config is public", response.status_code == 200,
              f"got {response.status_code}")
        payload = response.json() if response.status_code == 200 else {}
        check("demo mode reports enabled", payload.get("enabled") is True)
        personas = {item["id"]: item for item in payload.get("personas", [])}
        check("demo allowlist is exactly admin/operator/viewer",
              set(personas) == set(PERSONAS), ",".join(sorted(personas)))
        for persona in PERSONAS:
            item = personas.get(persona, {})
            check(f"{persona} maps to the {ROLES[persona]} role",
                  item.get("role") == ROLES[persona], str(item.get("role")))
            check(f"{persona} has no secret material in the catalog",
                  not any(key in item for key in ("password", "api_key", "key_hash")))

        response = await anon.get("/api/overview")
        check("anonymous REST still requires a session", response.status_code == 401,
              f"got {response.status_code}")

        probe = await anon.post("/api/auth/demo/session", json={"persona": "root"})
        check("unknown persona is rejected", probe.status_code == 400,
              f"got {probe.status_code}")
        return bool(payload.get("enabled"))


async def rest_checks(base: str) -> None:
    print("REST / sessions")
    for persona in PERSONAS:
        client, response = await enter(base, persona)
        try:
            check(f"enter {persona} -> 200", response.status_code == 200,
                  f"got {response.status_code}")
            if response.status_code != 200:
                continue
            body = response.json()
            check(f"{persona} response carries a CSRF token",
                  bool(body.get("csrf_token")))
            check(f"{persona} response carries no API key",
                  "api_key" not in str(body).lower())
            me = await client.get("/api/auth/me")
            check(f"{persona} session resolves to the {ROLES[persona]} role",
                  me.status_code == 200
                  and me.json().get("roles") == [ROLES[persona]],
                  str(me.json().get("roles")))
            keys = await client.get("/api/keys")
            if persona == "viewer":
                check("viewer may not list API keys", keys.status_code == 403,
                      f"got {keys.status_code}")
            else:
                check(f"{persona} has no API keys", keys.status_code == 200
                      and keys.json() == [], f"got {keys.status_code}")

            users = await client.get("/api/users")
            audit = await client.get("/api/audit", params={"server_id": "demo-mode"})
            email = me.json().get("email")
            if persona == "admin":
                check("admin may list users", users.status_code == 200,
                      f"got {users.status_code}")
                check("admin may read all demo audit rows",
                      audit.status_code == 200, f"got {audit.status_code}")
            else:
                check(f"{persona} may not list users", users.status_code == 403,
                      f"got {users.status_code}")
                items = audit.json().get("items", []) if audit.status_code == 200 else []
                check(f"{persona} audit view is scoped to itself",
                      audit.status_code == 200
                      and bool(items)
                      and all(item.get("user_email") == email for item in items),
                      f"got {audit.status_code}, {len(items)} rows")
        finally:
            await client.aclose()


async def switch_checks(base: str) -> None:
    print("Persona switching")
    client, response = await enter(base, "admin")
    try:
        check("admin entry -> 200", response.status_code == 200,
              f"got {response.status_code}")
        if response.status_code != 200:
            return
        csrf = response.json()["csrf_token"]
        old_session = client.cookies.get("urumi_session")
        without = await client.post(
            "/api/auth/demo/session", json={"persona": "viewer"}
        )
        check("switching without CSRF is rejected", without.status_code == 403,
              f"got {without.status_code}")
        switched = await client.post(
            "/api/auth/demo/session",
            json={"persona": "viewer"},
            headers={"X-CSRF-Token": csrf},
        )
        check("switching with CSRF succeeds", switched.status_code == 200,
              f"got {switched.status_code}")
        if switched.status_code == 200:
            check("switch response is the viewer persona",
                  switched.json()["user"]["roles"] == ["viewer"])
        me = await client.get("/api/auth/me")
        check("browser now acts as viewer", me.status_code == 200
              and me.json()["roles"] == ["viewer"], str(me.json().get("roles")))

        if old_session:
            stale = httpx.AsyncClient(base_url=base, timeout=30.0)
            stale.cookies.set("urumi_session", old_session)
            try:
                replay = await stale.get("/api/auth/me")
                check("the replaced session is revoked", replay.status_code == 401,
                      f"got {replay.status_code}")
            finally:
                await stale.aclose()
        else:
            check("the replaced session is revoked", False, "no session cookie")

        admin, _ = await enter(base, "admin")
        try:
            audit = await admin.get(
                "/api/audit", params={"server_id": "demo-mode", "per_page": 50}
            )
            body = audit.json() if audit.status_code == 200 else {}
            items = body.get("items", [])
            check("persona switches are audited",
                  audit.status_code == 200
                  and any(item.get("public_tool_name") == "demo_persona_switch"
                          for item in items),
                  f"{len(items)} rows")
        finally:
            await admin.aclose()
    finally:
        await client.aclose()


async def mcp_checks(base: str) -> None:
    print("MCP / cookies")
    for persona in PERSONAS:
        client, response = await enter(base, persona)
        try:
            if response.status_code != 200:
                check(f"{persona} MCP entry -> 200", False,
                      f"got {response.status_code}")
                continue
            cookies = {name: value for name, value in client.cookies.items()}
            async with streamablehttp_client(
                f"{base}/mcp",
                httpx_client_factory=client_factory(base, cookies),
            ) as (read, write, _):
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    names = {tool.name for tool in (await session.list_tools()).tools}
                    check(f"{persona} advertises {EXPECTED_TOOLS[persona]} tools",
                          len(names) == EXPECTED_TOOLS[persona],
                          f"got {len(names)}")
                    if persona == "admin":
                        result = await session.call_tool(
                            "inventory__check_stock", {"sku": "URUMI-MUG-001"}
                        )
                        check("admin may call inventory__check_stock",
                              result.isError is False, str(result.content[0].text)[:60])
                    if persona == "operator":
                        check("operator does not see create_product",
                              "woocommerce__create_product" not in names)
                        result = await session.call_tool(
                            "shipping__create_shipment", {}
                        )
                        check("operator denied shipping__create_shipment",
                              result.isError is True
                              and "permission_denied" in result.content[0].text,
                              str(result.content[0].text)[:60])
                    if persona == "viewer":
                        for tool in (
                            "shipping__update_shipment_status",
                            "woocommerce__create_product",
                        ):
                            result = await session.call_tool(tool, {})
                            check(f"viewer denied {tool}",
                                  result.isError is True
                                  and "permission_denied" in result.content[0].text,
                                  str(result.content[0].text)[:60])
        finally:
            await client.aclose()


async def main() -> int:
    base = sys.argv[1].rstrip("/") if len(sys.argv) > 1 else "http://127.0.0.1:8000"
    print(f"Verifying assessment demo mode at {base}\n")
    if not await demo_config(base):
        print("demo mode is not enabled at this URL; nothing else to check")
        return 1
    await rest_checks(base)
    await switch_checks(base)
    await mcp_checks(base)
    print(f"\n{PASS} passed, {FAIL} failed")
    for failure in FAILURES:
        print(f"  FAILED: {failure}")
    return 1 if FAIL else 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
