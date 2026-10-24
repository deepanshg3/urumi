#!/usr/bin/env bash
# First-time (and idempotent) setup for the local WordPress + WooCommerce store.
#
# What it does:
#   1. Creates deploy/docker/woocommerce/.env from the example if missing.
#   2. Starts MariaDB + WordPress and waits for health.
#   3. Installs WordPress core (only if not installed) and activates WooCommerce.
#   4. Generates a read/write WooCommerce REST API key and writes it to the
#      gitignored root `.env` (never prints the secret).
#   5. Activates the Urumi Supply theme, registers the product illustrations and
#      seeds the catalogue plus one demo order (idempotent by SKU / marker).
#
# Safe to re-run. It never deletes volumes or data.

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
STORE_DIR="$ROOT_DIR/deploy/docker/woocommerce"
STORE_ENV="$STORE_DIR/.env"
ROOT_ENV="$ROOT_DIR/.env"
COMPOSE=(docker compose -f "$STORE_DIR/compose.yaml" --env-file "$STORE_ENV")

log() { printf '\n[store-setup] %s\n' "$*"; }
fail() { printf '\n[store-setup] ERROR: %s\n' "$*" >&2; exit 1; }

command -v docker >/dev/null 2>&1 || fail "docker is required"
docker info >/dev/null 2>&1 || fail "Docker daemon is not accessible for this user"
command -v curl >/dev/null 2>&1 || fail "curl is required"

if [[ ! -f "$STORE_ENV" ]]; then
  log "Creating $STORE_ENV from .env.example (local development credentials)"
  cp "$STORE_DIR/.env.example" "$STORE_ENV"
fi

# shellcheck disable=SC1090
set -a; source "$STORE_ENV"; set +a
STORE_PORT="${STORE_PORT:-8080}"
STORE_URL="${STORE_URL:-http://localhost:${STORE_PORT}}"

log "Starting MariaDB and WordPress"
"${COMPOSE[@]}" up -d db wordpress

log "Waiting for WordPress to report healthy"
status=""
for _ in $(seq 1 60); do
  status="$(docker inspect --format '{{.State.Health.Status}}' "$("${COMPOSE[@]}" ps -q wordpress)" 2>/dev/null || echo starting)"
  [[ "$status" == "healthy" ]] && break
  sleep 5
done
[[ "$status" == "healthy" ]] || fail "WordPress did not become healthy (last status: ${status:-unknown}). Check: ${COMPOSE[*]} logs wordpress"

wp() { "${COMPOSE[@]}" run --rm -T cli "$@"; }

if wp core is-installed >/dev/null 2>&1; then
  log "WordPress is already installed; leaving existing content untouched"
else
  log "Installing WordPress core"
  wp core install \
    --url="$STORE_URL" \
    --title="${STORE_TITLE:-Urumi Local Store}" \
    --admin_user="${STORE_ADMIN_USER:-admin}" \
    --admin_password="${STORE_ADMIN_PASSWORD:?set STORE_ADMIN_PASSWORD}" \
    --admin_email="${STORE_ADMIN_EMAIL:-admin@example.test}" \
    --skip-email
fi

# WooCommerce 11+ requires WordPress 7+. A volume created by an older image may
# still hold an older core; upgrade in place (data is preserved).
if [[ "$(wp core version 2>/dev/null | tail -1)" == 6.* ]]; then
  log "Upgrading WordPress core in the existing volume to the image version"
  wp core update --version="$(wp core version --extra --allow-root 2>/dev/null | true)" >/dev/null 2>&1 || true
  wp core update --force
fi

log "Ensuring WooCommerce is installed and active"
if wp plugin is-installed woocommerce >/dev/null 2>&1; then
  wp plugin activate woocommerce >/dev/null
else
  wp plugin install woocommerce --activate
fi

log "Applying deterministic local settings (UTC timezone, USD, no tax)"
wp option update timezone_string UTC >/dev/null
wp option update woocommerce_currency USD >/dev/null
wp option update woocommerce_calc_taxes no >/dev/null
wp option update blogname "Urumi Supply" >/dev/null
wp option update blogdescription "Considered everyday goods" >/dev/null
wp rewrite structure '/%postname%/' >/dev/null
wp rewrite flush >/dev/null

log "Activating the Urumi Supply storefront theme"
if wp theme is-installed urumi-supply >/dev/null 2>&1; then
  wp theme activate urumi-supply >/dev/null
else
  fail "theme urumi-supply not found; check the bind mount in deploy/docker/woocommerce/compose.yaml"
fi

# --- Credentials ------------------------------------------------------------
# Recent WooCommerce releases only accept Basic auth over HTTPS; a plain-HTTP
# local store must use OAuth 1.0a. The auth mode is stored in the root .env.
api_key_valid() {
  [[ -n "${WOOCOMMERCE_CONSUMER_KEY:-}" && -n "${WOOCOMMERCE_CONSUMER_SECRET:-}" ]] || return 1
  ( cd "$ROOT_DIR" && python3 scripts/woo_rest.py check >/dev/null 2>&1 )
}

if api_key_valid; then
  log "Existing WooCommerce REST key in root .env is valid; keeping it"
else
  log "Generating a read/write WooCommerce REST API key (stored in gitignored .env)"
  keys_json="$(wp eval '
    global $wpdb;
    $user = get_user_by("login", getenv("STORE_ADMIN_USER") ?: "admin");
    if (!$user) { fwrite(STDERR, "admin user not found\n"); exit(1); }
    $consumer_key = "ck_" . wc_rand_hash();
    $consumer_secret = "cs_" . wc_rand_hash();
    $wpdb->insert($wpdb->prefix . "woocommerce_api_keys", array(
      "user_id" => $user->ID,
      "description" => "Urumi local MCP",
      "permissions" => "read_write",
      "consumer_key" => wc_api_hash($consumer_key),
      "consumer_secret" => $consumer_secret,
      "truncated_key" => substr($consumer_key, -7),
    ));
    echo json_encode(array("consumer_key" => $consumer_key, "consumer_secret" => $consumer_secret));
  ')"
  CK="$(printf '%s' "$keys_json" | python3 -c 'import json,sys; print(json.load(sys.stdin)["consumer_key"])')"
  CS="$(printf '%s' "$keys_json" | python3 -c 'import json,sys; print(json.load(sys.stdin)["consumer_secret"])')"
  [[ "$CK" == ck_* && "$CS" == cs_* ]] || fail "failed to generate WooCommerce REST API key"

  if [[ ! -f "$ROOT_ENV" ]]; then
    cp "$ROOT_DIR/.env.example" "$ROOT_ENV"
  fi
  AUTH_MODE="basic"
  [[ "$STORE_URL" == https://* ]] || AUTH_MODE="oauth1"
  python3 - "$ROOT_ENV" "$STORE_URL" "$CK" "$CS" "$AUTH_MODE" <<'PY'
import sys
from pathlib import Path

path = Path(sys.argv[1])
values = {
    "WOOCOMMERCE_BASE_URL": sys.argv[2],
    "WOOCOMMERCE_CONSUMER_KEY": sys.argv[3],
    "WOOCOMMERCE_CONSUMER_SECRET": sys.argv[4],
    "WOOCOMMERCE_AUTH_MODE": sys.argv[5],
}
lines = path.read_text().splitlines() if path.exists() else []
seen = set()
out = []
for line in lines:
    key = line.split("=", 1)[0].strip() if "=" in line and not line.lstrip().startswith("#") else None
    if key in values:
        out.append(f"{key}={values[key]}")
        seen.add(key)
    else:
        out.append(line)
for key, value in values.items():
    if key not in seen:
        out.append(f"{key}={value}")
path.write_text("\n".join(out) + "\n")
path.chmod(0o600)
PY
  # reload for the verification/seed steps below
  set -a; source "$ROOT_ENV"; set +a
  log "REST key written to .env (secret not printed)"
fi

log "Verifying WooCommerce REST authentication"
( cd "$ROOT_DIR" && python3 scripts/woo_rest.py check )

log "Registering the product illustrations (media attachments)"
# The illustrations live in the theme. WordPress does not allow SVG uploads by
# default, so they are registered as attachments directly by WP-CLI.
MANIFEST="$STORE_DIR/.catalog-images.json"
wp eval "$(sed '1d' "$ROOT_DIR/scripts/woo_storefront.php")" 2>/dev/null \
  | grep '^URUMI_MANIFEST:' | sed 's/^URUMI_MANIFEST://' > "$MANIFEST" || true
if [[ -s "$MANIFEST" ]]; then
  log "Wrote illustration manifest to $MANIFEST"
else
  fail "could not register product illustrations"
fi

log "Seeding the Urumi Supply catalogue and demo order (idempotent)"
( cd "$ROOT_DIR" && python3 scripts/woo_rest.py seed )

log "Store is ready"
printf '  Storefront: %s\n' "$STORE_URL"
printf '  WP admin:   %s/wp-admin (user: %s)\n' "$STORE_URL" "${STORE_ADMIN_USER:-admin}"
printf '  MCP config: root .env (WOOCOMMERCE_BASE_URL/KEY/SECRET/AUTH_MODE)\n'
