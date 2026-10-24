# Urumi Supply — storefront, catalogue and seed data

The local WooCommerce store is not a bare WordPress install: it runs the
**Urumi Supply** theme, a twelve-product catalogue with custom SVG artwork, and
one demo order. The MCP servers read the same data, so anything the storefront
shows is what the agent and the tools see.

| Surface | URL (Docker Compose) | URL (Kind) |
|---|---|---|
| Storefront | <http://localhost:8080> | <http://localhost:8081> |
| Shop archive | <http://localhost:8080/shop/> | <http://localhost:8081/shop/> |
| WordPress admin | <http://localhost:8080/wp-admin> | <http://localhost:8081/wp-admin> |

---

## 1. The theme

`deploy/docker/woocommerce/theme/urumi-supply/` is a **classic** (non-block)
PHP theme. It ships with the repository and is mounted into the WordPress
container read-only, so editing a file is picked up immediately.

```
urumi-supply/
├── style.css                 # theme header
├── functions.php             # supports, assets, WooCommerce hooks, helpers
├── header.php footer.php     # shell, announcement bar, search, cart
├── front-page.php            # hero, featured products, categories, story
├── index.php page.php single.php search.php 404.php
├── template-parts/product-card.php
├── woocommerce/content-product.php
├── woocommerce/single-product.php
└── assets/
    ├── css/fonts.css         # self-hosted Inter + DM Sans
    ├── css/theme.css         # the full stylesheet
    ├── js/theme.js           # mobile nav, cart count refresh
    ├── fonts/*.woff2         # latin + latin-ext
    └── products/*.svg        # twelve product illustrations
```

### Design tokens

The storefront shares the dashboard palette so the two products feel like one
system.

| Token | Value | Use |
|---|---|---|
| `--ink` | `#18251F` | headings, primary text |
| `--forest` | `#244A3C` | header, footer, primary buttons |
| `--emerald` | `#3E7860` | accents, links, focus rings |
| `--ivory` | `#F7F5EF` | page background |
| `--sage` | `#E5EAE2` | cards, muted surfaces |
| `--line` | `#E5E4DC` | borders |
| `--amber` | `#B87926` | low-stock badge |
| `--red` | `#B84D46` | out-of-stock badge |

Type: **Inter** for UI text, **DM Sans** for display headings. Both are
self-hosted (`assets/fonts`), so the storefront renders identically offline.

### Classic templates, not blocks

WooCommerce 11 defaults the Cart and Checkout pages to the block editor
markup, which renders client-side and ignores the theme. `scripts/woo_storefront.php`
rewrites both pages to the classic shortcodes (`[woocommerce_cart]`,
`[woocommerce_checkout]`) so the theme templates are used. The script is
idempotent and is re-run by `scripts/store_setup.sh` and
`scripts/k8s/seed-store.sh`.

### Why the illustrations are SVG attachments

WordPress blocks SVG uploads by default and no upload plugin is installed
(the demo must not depend on one). Instead the theme's `assets/products/*.svg`
files are copied into `wp-content/uploads/urumi-supply/` and inserted as
attachments with the mime type `image/svg+xml`. WooCommerce's REST product
payload accepts them because `wp_attachment_is_image()` accepts any
`image/*` mime type.

Because WordPress cannot read the pixel size of an SVG, the attachment metadata
is written with the real dimensions (800×1000) — otherwise the rendered `<img>`
tag carries a 1×1 placeholder.

---

## 2. The catalogue

Defined once in `scripts/store_catalog.py` and applied through the WooCommerce
REST API (`scripts/woo_rest.py`). Three categories, twelve products, all with
custom artwork.

| SKU | Product | Price | Stock | Category | Featured |
|---|---|---|---|---|---|
| URS-JRN-001 | Field Notes Journal | $18 | 34 | Desk & Paper | ✅ |
| URS-MUG-001 | Everyday Ceramic Mug | $24 | 28 | Desk & Paper | ✅ |
| URS-ORG-001 | Arc Desk Organizer | $32 | 4 | Desk & Paper | ✅ |
| URS-TOT-001 | Canvas Utility Tote | $38 | 19 | Carry | ✅ |
| URS-POU-001 | Travel Cable Pouch | $26 | 0 | Carry | |
| URS-BTL-001 | Studio Bottle | $29 | 22 | Tabletop | ✅ |
| URS-PEN-001 | Modular Pen Set | $16 | 3 | Desk & Paper | |
| URS-MAT-001 | Soft Grid Desk Mat | $42 | 12 | Desk & Paper | |
| URS-PCK-001 | Weekend Packing Cubes | $34 | 2 | Carry | |
| URS-SLV-001 | Pocket Tech Sleeve | $30 | 16 | Carry | |
| URS-TRY-001 | Stoneware Catchall Tray | $22 | 9 | Tabletop | |
| URS-CRY-001 | Daily Carry Pouch | $28 | 41 | Carry | |

The stock levels are deliberate: three products are at or below the
low-stock threshold of 5 and one is out of stock, so
`inventory__find_low_stock_products` and the out-of-stock paths have real data
to work with.

### Seeded demo order

One order is created, marked with the customer note `Urumi Supply demo order`
so re-seeding never creates a second one:

* status `processing`, payment `cod` (cash on delivery), marked paid
* Amara Okafor, 18 Kingsley Road, Brooklyn NY 11211, US
* 2 × Field Notes Journal, 1 × Everyday Ceramic Mug, 1 × Daily Carry Pouch

### Retiring development fixtures

Earlier development runs left probe products in the local store
(`URUMI_LIVE_TEST_*`, `URUMI-DOCKER-*`, `PROBE-M1`, `nope`, …). The seeder
moves them to **draft** and tags them with `_urumi_retired_fixture=1` instead
of deleting them, so historic orders keep a valid line item while the shop
archive and the product listings only show the curated catalogue.

---

## 3. Seeding

```bash
# Compose: full setup (starts the store, activates the theme, seeds everything)
./scripts/store_setup.sh

# Kind: build the theme image, deploy and seed
./scripts/k8s/build-and-load.sh
./scripts/k8s/deploy-kind.sh
```

Both paths run the same three steps:

1. `scripts/woo_storefront.php` (via WP-CLI) — registers the illustrations,
   switches the Cart/Checkout pages to the classic templates, enables cash on
   delivery and free shipping over $60. The script is evaluated with
   `wp eval` (the leading `<?php` is stripped first), because `wp eval-file`
   would print the code instead of running it.
2. The manifest (`SKU → attachment id`) is written to
   `deploy/docker/woocommerce/.catalog-images.json` (gitignored).
3. `scripts/woo_rest.py seed` — creates the categories, upserts the twelve
   products (keyed by SKU), retires the fixtures and syncs the demo order.

Re-running is safe: every step is keyed by a stable identifier.

```bash
# Check the catalogue through the same REST client the MCP servers use
python3 scripts/woo_rest.py check
python3 scripts/woo_rest.py seed      # == catalog
```

---

## 4. Deployment

### Docker Compose

`deploy/docker/woocommerce/compose.yaml` bind-mounts the theme into both the
`wordpress` and `cli` services:

```yaml
volumes:
  - ./theme/urumi-supply:/var/www/html/wp-content/themes/urumi-supply:ro
```

### Kubernetes (Helm / Kind)

The chart builds the theme into a small image
(`deploy/docker/woocommerce/theme/Dockerfile` → `urumi/urumi-supply-theme`)
and copies it into the WordPress pod with an init container:

```yaml
initContainers:
  - name: urumi-supply-theme
    image: urumi/urumi-supply-theme:local
    command: ["sh", "-c", "cp -R /theme/urumi-supply/. /theme-target/ && chmod -R a+rX /theme-target"]
    volumeMounts:
      - name: theme
        mountPath: /theme-target
```

The same `emptyDir` is mounted read-only at
`/var/www/html/wp-content/themes/urumi-supply` in the WordPress container.
`scripts/k8s/build-and-load.sh` builds the image and loads it into the Kind
cluster.

---

## 5. Customising

| Change | Where |
|---|---|
| Product data, prices, stock | `scripts/store_catalog.py` → re-run `scripts/woo_rest.py seed` |
| Product artwork | `deploy/docker/woocommerce/theme/urumi-supply/assets/products/*.svg` (800×1000, shared palette) → re-run `scripts/woo_storefront.php` |
| Colours, spacing, layout | `deploy/docker/woocommerce/theme/urumi-supply/assets/css/theme.css` |
| Announcement bar, menus, footer | `header.php`, `footer.php` |
| Store settings (COD, free shipping) | `scripts/woo_storefront.php` |
