#!/usr/bin/env python3
"""Small stdlib-only WooCommerce REST helper for local store setup.

Supports OAuth 1.0a (HMAC-SHA1) and Basic authentication. Used by
scripts/store_setup.sh so setup works with a plain-HTTP local store, where
recent WooCommerce releases no longer accept Basic auth.

Secrets are read from the environment and never printed.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import secrets
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

from store_catalog import (  # noqa: E402  (path bootstrap above)
    CATALOG,
    CATEGORIES,
    DEMO_ORDER,
    DEMO_ORDER_MARKER,
    RETIRED_FIXTURE_SKUS,
)


def _quote(value: str) -> str:
    return urllib.parse.quote(str(value), safe="~-._")


class WooRest:
    def __init__(
        self,
        base_url: str,
        consumer_key: str,
        consumer_secret: str,
        auth_mode: str = "auto",
        timeout: float = 30.0,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.consumer_key = consumer_key
        self.consumer_secret = consumer_secret
        self.timeout = timeout
        if auth_mode == "auto":
            auth_mode = "basic" if self.base_url.startswith("https://") else "oauth1"
        if auth_mode not in {"basic", "oauth1"}:
            raise ValueError(f"unsupported auth mode: {auth_mode}")
        self.auth_mode = auth_mode

    def _oauth_header(self, method: str, url: str, query: dict[str, Any]) -> str:
        oauth = {
            "oauth_consumer_key": self.consumer_key,
            "oauth_nonce": secrets.token_hex(16),
            "oauth_signature_method": "HMAC-SHA1",
            "oauth_timestamp": str(int(time.time())),
            "oauth_version": "1.0",
        }
        parsed = urllib.parse.urlsplit(url)
        base_url = f"{parsed.scheme}://{parsed.netloc}{parsed.path}"
        params = {**{k: str(v) for k, v in query.items()}, **oauth}
        param_str = "&".join(f"{_quote(k)}={_quote(v)}" for k, v in sorted(params.items()))
        base_string = f"{method.upper()}&{_quote(base_url)}&{_quote(param_str)}"
        digest = hmac.new(
            f"{self.consumer_secret}&".encode(), base_string.encode(), hashlib.sha1
        ).digest()
        oauth["oauth_signature"] = base64.b64encode(digest).decode()
        return "OAuth " + ", ".join(f'{_quote(k)}="{_quote(v)}"' for k, v in sorted(oauth.items()))

    def request(
        self,
        method: str,
        path: str,
        payload: dict[str, Any] | None = None,
        query: dict[str, Any] | None = None,
    ) -> Any:
        query = {k: v for k, v in (query or {}).items() if v is not None}
        url = f"{self.base_url}/wp-json/wc/v3{path}"
        if query:
            url = f"{url}?{urllib.parse.urlencode(query)}"
        headers = {"Accept": "application/json", "Content-Type": "application/json"}
        if self.auth_mode == "basic":
            token = base64.b64encode(
                f"{self.consumer_key}:{self.consumer_secret}".encode()
            ).decode()
            headers["Authorization"] = f"Basic {token}"
        else:
            headers["Authorization"] = self._oauth_header(method, url, query)

        data = json.dumps(payload).encode() if payload is not None else None
        request = urllib.request.Request(url, data=data, headers=headers, method=method.upper())
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                body = response.read()
                return json.loads(body) if body else None
        except urllib.error.HTTPError as exc:
            body = exc.read().decode(errors="replace")[:500]
            raise SystemExit(f"{method} {path} failed: HTTP {exc.code} {body}") from exc
        except urllib.error.URLError as exc:
            raise SystemExit(f"{method} {path} failed: {exc.reason}") from exc


def from_env() -> WooRest:
    return WooRest(
        base_url=os.environ["WOOCOMMERCE_BASE_URL"],
        consumer_key=os.environ["WOOCOMMERCE_CONSUMER_KEY"],
        consumer_secret=os.environ["WOOCOMMERCE_CONSUMER_SECRET"],
        auth_mode=os.environ.get("WOOCOMMERCE_AUTH_MODE", "auto"),
        timeout=float(os.environ.get("WOOCOMMERCE_TIMEOUT_SECONDS", "30")),
    )


# -- Catalogue helpers -------------------------------------------------------

#: Product names left over from earlier development seeds.
RETIRED_FIXTURE_NAMES: tuple[str, ...] = ("nope", "Docker Probe", "Probe Product")

DEFAULT_MANIFEST = (
    Path(__file__).resolve().parent.parent
    / "deploy"
    / "docker"
    / "woocommerce"
    / ".catalog-images.json"
)


def load_manifest() -> dict[str, int]:
    """Read the SKU -> attachment id manifest produced by scripts/woo_storefront.php."""
    path = Path(os.environ.get("URUMI_CATALOG_MANIFEST", DEFAULT_MANIFEST))
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text())
    except (OSError, ValueError):
        return {}
    if not isinstance(data, dict):
        return {}
    return {str(key): int(value) for key, value in data.items() if str(value).isdigit()}


def find_by_sku(client: WooRest, sku: str) -> dict[str, Any] | None:
    """Find a product by SKU, including drafts."""
    existing = client.request("GET", "/products", query={"sku": sku, "status": "any", "per_page": 1})
    return existing[0] if existing else None


def ensure_categories(client: WooRest) -> dict[str, int]:
    """Create the catalogue categories if needed and return name -> id."""
    ids: dict[str, int] = {}
    for name, slug in CATEGORIES:
        existing = client.request("GET", "/products/categories", query={"slug": slug, "per_page": 1})
        if existing:
            ids[name] = int(existing[0]["id"])
            continue
        created = client.request(
            "POST",
            "/products/categories",
            payload={"name": name, "slug": slug, "description": f"Urumi Supply — {name}."},
        )
        ids[name] = int(created["id"])
        print(f"  category created: {name}")
    return ids


def upsert_product(
    client: WooRest,
    entry: dict[str, Any],
    category_ids: dict[str, int],
    images: dict[str, int],
) -> dict[str, Any]:
    """Create or update one catalogue product, keyed by its stable SKU."""
    sku = entry["sku"]
    stock = int(entry["stock"])
    payload: dict[str, Any] = {
        "name": entry["name"],
        "sku": sku,
        "regular_price": entry["price"],
        "manage_stock": True,
        "stock_quantity": stock,
        "stock_status": "instock" if stock > 0 else "outofstock",
        "status": "publish",
        "description": entry["description"],
        "short_description": entry["short_description"],
        "catalog_visibility": "visible",
        "categories": [{"id": category_ids[entry["category"]]}] if entry["category"] in category_ids else [],
        "meta_data": [{"key": "_urumi_featured", "value": bool(entry.get("featured"))}],
    }

    attachment_id = images.get(sku)
    if attachment_id:
        payload["images"] = [{"id": attachment_id}]

    existing = find_by_sku(client, sku)
    if existing:
        product = client.request("PUT", f"/products/{existing['id']}", payload=payload)
        print(f"  updated: {sku} ({entry['name']})")
        return product

    product = client.request("POST", "/products", payload=payload)
    print(f"  created: {sku} ({entry['name']})")
    return product


def retire_fixtures(client: WooRest) -> None:
    """Move leftover development fixtures to draft without deleting them.

    Historic orders keep a valid line item, and the storefront and the MCP
    product listing only ever expose the curated catalogue.
    """
    products = client.request("GET", "/products", query={"status": "any", "per_page": 100})

    for product in products:
        sku = product.get("sku") or ""
        name = product.get("name") or ""
        is_fixture = (
            sku in RETIRED_FIXTURE_SKUS
            or name in RETIRED_FIXTURE_NAMES
            or name.startswith("URUMI_LIVE_TEST")
            or sku.startswith("URUMI_LIVE_TEST")
        )
        if not is_fixture:
            continue
        if product.get("status") == "draft" and product.get("meta_data"):
            if any(
                meta.get("key") == "_urumi_retired_fixture" for meta in product.get("meta_data", [])
            ):
                continue

        client.request(
            "PUT",
            f"/products/{product['id']}",
            payload={
                "status": "draft",
                "meta_data": [{"key": "_urumi_retired_fixture", "value": True}],
            },
        )
        print(f"  retired: {sku or name}")


def ensure_demo_order(client: WooRest) -> None:
    """Create the demo order once, identified by its customer note."""
    existing = client.request(
        "GET", "/orders", query={"search": DEMO_ORDER_MARKER, "per_page": 1, "status": "any"}
    )
    payload = {key: value for key, value in DEMO_ORDER.items() if key != "line_items"}
    payload["billing"] = dict(DEMO_ORDER["billing"])
    payload["shipping"] = dict(DEMO_ORDER["shipping"])

    if existing:
        order = existing[0]
        # Keep the address and status in sync with the catalogue definition.
        client.request("PUT", f"/orders/{order['id']}", payload=payload)
        print(f"  updated: demo order #{order['id']}")
        return

    line_items = []
    for item in DEMO_ORDER["line_items"]:
        product = find_by_sku(client, item["sku"])
        if not product:
            print(f"  skipped line item {item['sku']}: product missing")
            continue
        line_items.append({"product_id": product["id"], "quantity": item["quantity"]})

    if not line_items:
        print("  skipped: demo order (no catalogue products available)")
        return

    payload["line_items"] = line_items
    payload["customer_note"] = DEMO_ORDER_MARKER

    order = client.request("POST", "/orders", payload=payload)
    print(f"  created: demo order #{order['id']}")


def cmd_check() -> int:
    client = from_env()
    client.request("GET", "/products", query={"per_page": 1})
    print(f"WooCommerce REST authentication OK ({client.auth_mode})")
    return 0


def cmd_seed() -> int:
    """Seed the Urumi Supply catalogue. Safe to re-run."""
    client = from_env()
    images = load_manifest()
    if images:
        print(f"  images: {len(images)} illustrations attached")
    else:
        print("  images: no manifest found (run scripts/woo_storefront.php via WP-CLI)")

    print("Ensuring product categories")
    category_ids = ensure_categories(client)

    print("Seeding catalogue products")
    for entry in CATALOG:
        upsert_product(client, entry, category_ids, images)

    print("Retiring leftover development fixtures")
    retire_fixtures(client)

    print("Ensuring the demo order exists")
    ensure_demo_order(client)

    print(f"Catalogue ready: {len(CATALOG)} products")
    return 0


def main(argv: list[str]) -> int:
    if len(argv) != 2 or argv[1] not in {"check", "seed", "catalog"}:
        print("usage: woo_rest.py {check|seed|catalog}", file=sys.stderr)
        return 2
    if argv[1] == "check":
        return cmd_check()
    return cmd_seed()


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
