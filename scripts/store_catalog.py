#!/usr/bin/env python3
"""The Urumi Supply demo catalog.

Single source of truth for the storefront catalogue, shared by the local
Docker store (`scripts/woo_rest.py catalog`) and the Kind deployment
(`scripts/k8s/seed-store.sh`).

Every entry is identified by a stable SKU, so seeding is idempotent: an
existing product with the same SKU is updated in place, never duplicated.
"""

from __future__ import annotations

from typing import Any

# Product categories, in display order.
CATEGORIES: list[tuple[str, str]] = [
    ("Desk & Paper", "URS-DESK"),
    ("Carry", "URS-CARRY"),
    ("Tabletop", "URS-TABLE"),
]

# Legacy development fixtures that shipped with earlier seeds. They are moved
# to draft (never deleted) so historic orders keep a valid line item, and they
# are hidden from the storefront and from the MCP product listing.
RETIRED_FIXTURE_SKUS: tuple[str, ...] = (
    "URUMI-MUG-001",
    "URUMI-NOTE-002",
    "URUMI-POSTER-003",
    "URUMI-DOCKER-421D2383",
    "URUMI-DOCKER-EFC4331A",
    "URUMI-LIVE_TEST_compose6-SKU",
    "URUMI-LIVE_TEST_run1-SKU",
    "URUMI-LIVE_TEST_run2-SKU",
    "URUMI-LIVE_TEST_run3-SKU",
    "URUMI-LIVE_TEST_run4-SKU",
    "URUMI-LIVE_TEST_run5-SKU",
    "URUMI-LIVE_TEST_probe-SKU",
    "URUMI_LIVE_TEST_probe2-SKU",
    "PROBE-M1",
)

CATALOG: list[dict[str, Any]] = [
    {
        "sku": "URS-JRN-001",
        "name": "Field Notes Journal",
        "price": "18.00",
        "stock": 34,
        "category": "Desk & Paper",
        "featured": True,
        "image": "field-notes-journal",
        "short_description": "Lay-flat dot-grid journal, 160 pages, soft-touch cover.",
        "description": (
            "A journal that stays open on the desk and disappears into a bag when you are done. "
            "The cover is a soft-touch board that takes a pencil mark without looking worn, the "
            "block is 160 pages of 100gsm dot-grid paper, and the binding lets the book lie flat "
            "from the first page to the last. A single ribbon marker is stitched into the spine."
        ),
    },
    {
        "sku": "URS-MUG-001",
        "name": "Everyday Ceramic Mug",
        "price": "24.00",
        "stock": 28,
        "category": "Tabletop",
        "featured": True,
        "image": "everyday-ceramic-mug",
        "short_description": "Stoneware mug with a 320ml capacity and a handle that fits one finger.",
        "description": (
            "Made in a small stoneware studio and finished in a matte glaze that resists the ring "
            "marks left by coffee. The body holds 320ml — enough for a long pour — and the pulled "
            "handle is sized for one finger and a full hand. Every mug is slightly different; the "
            "glaze pools a little at the base."
        ),
    },
    {
        "sku": "URS-ORG-001",
        "name": "Arc Desk Organizer",
        "price": "32.00",
        "stock": 4,
        "category": "Desk & Paper",
        "featured": True,
        "image": "arc-desk-organizer",
        "short_description": "Four-compartment desk tray in powder-coated steel.",
        "description": (
            "A single folded sheet of powder-coated steel, arched so it reads as one object rather "
            "than a set of cups. Four compartments take pens, clips, a charging cable and whatever "
            "else accumulates beside a keyboard. The base is weighted so it does not travel when "
            "you do."
        ),
    },
    {
        "sku": "URS-TOT-001",
        "name": "Canvas Utility Tote",
        "price": "38.00",
        "stock": 19,
        "category": "Carry",
        "featured": True,
        "image": "canvas-utility-tote",
        "short_description": "Heavyweight cotton tote with a flat base and an internal pocket.",
        "description": (
            "Cut from 16oz cotton canvas with a flat, boxed base so it stands up on the floor and "
            "holds its shape when full. The handles are bar-tacked at the stress points, and a "
            "single slip pocket runs across the inside. It carries a laptop, a notebook and a "
            "week's groceries without complaint."
        ),
    },
    {
        "sku": "URS-POU-001",
        "name": "Travel Cable Pouch",
        "price": "26.00",
        "stock": 0,
        "category": "Carry",
        "featured": False,
        "image": "travel-cable-pouch",
        "short_description": "Structured zip pouch for chargers, cables and adaptors.",
        "description": (
            "A small structured pouch with a zip that opens wide, sized for a charger, two cables "
            "and an adaptor. The lining is a warm sand colour so a black cable is easy to find in "
            "the bottom of a bag. Sold as a single piece; restocks land every few weeks."
        ),
    },
    {
        "sku": "URS-BTL-001",
        "name": "Studio Bottle",
        "price": "29.00",
        "stock": 22,
        "category": "Tabletop",
        "featured": True,
        "image": "studio-bottle",
        "short_description": "Vacuum-insulated bottle with a leak-proof twist cap.",
        "description": (
            "A double-walled steel bottle that holds temperature for most of a working day. The "
            "twist cap seals with an O-ring and does not leak when the bottle is on its side in a "
            "bag. The powder-coated finish grips a wet hand and hides the marks of a long week."
        ),
    },
    {
        "sku": "URS-PEN-001",
        "name": "Modular Pen Set",
        "price": "16.00",
        "stock": 3,
        "category": "Desk & Paper",
        "featured": False,
        "image": "modular-pen-set",
        "short_description": "Three refillable pens that share one grip and one cap.",
        "description": (
            "Three pens — fine, medium and brush — built on the same barrel, so the grip and the "
            "cap are interchangeable and the set stays visually quiet on a desk. Refills are standard "
            "cartridge type and can be replaced without a tool."
        ),
    },
    {
        "sku": "URS-MAT-001",
        "name": "Soft Grid Desk Mat",
        "price": "42.00",
        "stock": 12,
        "category": "Desk & Paper",
        "featured": False,
        "image": "soft-grid-desk-mat",
        "short_description": "Large felt desk mat with a printed alignment grid.",
        "description": (
            "A wide desk mat in dense felt that softens the sound of typing and hides the clutter "
            "line at the back of a desk. The printed grid gives a keyboard and a mouse a shared "
            "baseline. It is thick enough to be comfortable and thin enough to roll into a drawer."
        ),
    },
    {
        "sku": "URS-PCK-001",
        "name": "Weekend Packing Cubes",
        "price": "34.00",
        "stock": 2,
        "category": "Carry",
        "featured": False,
        "image": "weekend-packing-cubes",
        "short_description": "Set of three packing cubes with mesh tops.",
        "description": (
            "Three sizes that nest into each other, so a full set packs down to the volume of the "
            "largest cube. The zip runs around three sides, and a mesh top means you can see what "
            "is inside without opening anything."
        ),
    },
    {
        "sku": "URS-SLV-001",
        "name": "Pocket Tech Sleeve",
        "price": "30.00",
        "stock": 16,
        "category": "Carry",
        "featured": False,
        "image": "pocket-tech-sleeve",
        "short_description": "Felt sleeve with a soft lining for a tablet or e-reader.",
        "description": (
            "A slip sleeve cut from wool felt with a lining soft enough for a screen. It holds a "
            "tablet, an e-reader or a 13-inch laptop, and it slides into a tote without snagging. "
            "A single elastic strap keeps it closed."
        ),
    },
    {
        "sku": "URS-TRY-001",
        "name": "Stoneware Catchall Tray",
        "price": "22.00",
        "stock": 9,
        "category": "Tabletop",
        "featured": False,
        "image": "stoneware-catchall-tray",
        "short_description": "Low-rimmed stoneware dish for keys, coins and small things.",
        "description": (
            "A shallow stoneware dish sized for the things that end up in a pocket — keys, coins, "
            "earbuds, a folded pair of glasses. The rim is low enough to reach into and the glaze "
            "is fired to a matte finish that does not show fingerprints."
        ),
    },
    {
        "sku": "URS-CRY-001",
        "name": "Daily Carry Pouch",
        "price": "28.00",
        "stock": 41,
        "category": "Carry",
        "featured": False,
        "image": "daily-carry-pouch",
        "short_description": "Waxed canvas pouch for the small kit you carry every day.",
        "description": (
            "The pouch that lives in a coat pocket: a waxed canvas shell, a zip that closes with "
            "one hand, and a lining that wipes clean. It fits a wallet, a set of keys, a charger "
            "and a lip balm without turning into a bulge."
        ),
    },
]

# Marker written to the customer note of the demo order so re-seeding never
# creates a second one.
DEMO_ORDER_MARKER = "Urumi Supply demo order"

DEMO_ORDER = {
    "status": "processing",
    "payment_method": "cod",
    "payment_method_title": "Cash on delivery",
    "set_paid": True,
    "billing": {
        "first_name": "Amara",
        "last_name": "Okafor",
        "address_1": "18 Kingsley Road",
        "city": "Brooklyn",
        "state": "NY",
        "postcode": "11211",
        "country": "US",
        "email": "amara@example.test",
        "phone": "0000000000",
    },
    "shipping": {
        "first_name": "Amara",
        "last_name": "Okafor",
        "address_1": "18 Kingsley Road",
        "city": "Brooklyn",
        "state": "NY",
        "postcode": "11211",
        "country": "US",
    },
    "line_items": [
        {"sku": "URS-JRN-001", "quantity": 2},
        {"sku": "URS-MUG-001", "quantity": 1},
        {"sku": "URS-CRY-001", "quantity": 1},
    ],
}
