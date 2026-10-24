#!/usr/bin/env bash
# Provision the bundled WooCommerce store inside the cluster:
#   - install WordPress + WooCommerce (via wp-cli, downloaded into the pod)
#   - generate a REST consumer key/secret and inject them into the Helm release
#     so the WooCommerce/Inventory/Shipping MCP servers become ready
#   - seed the demo products and a test order through the REST API
#
# Idempotent: re-running it is safe.
set -euo pipefail

export PATH="${HOME}/.local/bin:${PATH}"

RELEASE="${RELEASE:-urumi}"
NAMESPACE="${NAMESPACE:-urumi}"
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"

# URL the *host* uses to reach the store. Kind maps the WordPress NodePort
# (30081) to host port 8081 via deploy/kind/kind-config.yaml.
SITE_URL="${SITE_URL:-http://localhost:8081}"
ADMIN_USER="${ADMIN_USER:-admin}"
ADMIN_EMAIL="${ADMIN_EMAIL:-admin@urumi.local}"
ADMIN_PASSWORD="${ADMIN_PASSWORD:-$(openssl rand -hex 8)}"

echo "==> Locating WordPress pod"
resolve_pod() {
  POD=""
  for _ in $(seq 1 60); do
    POD="$(kubectl -n "${NAMESPACE}" get pods -l app.kubernetes.io/component=wordpress \
      -o jsonpath='{.items[0].metadata.name}' 2>/dev/null || true)"
    [[ -n "${POD}" ]] && break
    sleep 3
  done
  [[ -n "${POD}" ]] || { echo "WordPress pod not found" >&2; exit 1; }
}

resolve_pod
echo "    using pod ${POD}"

echo "==> Waiting for wp-config.php / database"
kubectl -n "${NAMESPACE}" exec "${POD}" -- bash -lc \
  'for i in $(seq 1 120); do [ -f /var/www/html/wp-config.php ] && exit 0; sleep 2; done; exit 1'

echo "==> Installing wp-cli in the WordPress pod (the official image omits it)"
kubectl -n "${NAMESPACE}" exec "${POD}" -- bash -lc \
  'if ! command -v wp >/dev/null 2>&1; then \
     curl -fsSL -o /usr/local/bin/wp https://raw.githubusercontent.com/wp-cli/builds/gh-pages/phar/wp-cli.phar && \
     chmod +x /usr/local/bin/wp; fi; wp --allow-root --version'

wp() { kubectl -n "${NAMESPACE}" exec "${POD}" -- wp --allow-root "$@"; }

echo "==> Installing WordPress (if needed)"
if ! wp core is-installed >/dev/null 2>&1; then
  wp core install --url="${SITE_URL}" --title="Urumi Store" \
    --admin_user="${ADMIN_USER}" --admin_password="${ADMIN_PASSWORD}" \
    --admin_email="${ADMIN_EMAIL}" --skip-email
fi
# OAuth 1.0a signatures are computed against home/siteurl, so keep them aligned
# with the URL clients sign with (also exposed as woocommerce.publicUrl).
wp option update home "${SITE_URL}" >/dev/null
wp option update siteurl "${SITE_URL}" >/dev/null

echo "==> Installing/activating WooCommerce (if needed)"
if ! wp plugin is-active woocommerce >/dev/null 2>&1; then
  wp plugin install woocommerce --activate
fi
wp option update timezone_string UTC >/dev/null
wp option update woocommerce_currency USD >/dev/null
wp option update woocommerce_calc_taxes no >/dev/null
wp option update blogdescription "Urumi Supply" >/dev/null
wp rewrite structure '/%postname%/' >/dev/null 2>&1 || true

echo "==> Activating the Urumi Supply theme"
if ! wp theme is-installed urumi-supply >/dev/null 2>&1; then
  echo "theme urumi-supply not found; is the theme image built and loaded into the cluster?" >&2
  exit 1
fi
wp theme activate urumi-supply >/dev/null

echo "==> Generating WooCommerce REST keys"
# Mirrors scripts/store_setup.sh: consumer_key is hashed, secret stored plaintext.
KEYS_JSON="$(wp eval '
  global $wpdb;
  $user = get_user_by("login", getenv("URUMI_ADMIN_USER") ?: "admin");
  if (!$user) { fwrite(STDERR, "admin user not found\n"); exit(1); }
  $consumer_key = "ck_" . wc_rand_hash();
  $consumer_secret = "cs_" . wc_rand_hash();
  $wpdb->insert($wpdb->prefix . "woocommerce_api_keys", array(
    "user_id" => $user->ID,
    "description" => "Urumi Kind MCP",
    "permissions" => "read_write",
    "consumer_key" => wc_api_hash($consumer_key),
    "consumer_secret" => $consumer_secret,
    "truncated_key" => substr($consumer_key, -7),
  ));
  echo json_encode(array("consumer_key" => $consumer_key, "consumer_secret" => $consumer_secret));
')"
CK="$(printf '%s' "${KEYS_JSON}" | python3 -c 'import json,sys; print(json.load(sys.stdin)["consumer_key"])')"
CS="$(printf '%s' "${KEYS_JSON}" | python3 -c 'import json,sys; print(json.load(sys.stdin)["consumer_secret"])')"
[[ "${CK}" == ck_* && "${CS}" == cs_* ]] || { echo "failed to generate REST keys" >&2; exit 1; }
echo "    consumer key: ${CK:0:11}…"

echo "==> Updating Helm release with store credentials"
helm upgrade "${RELEASE}" "${REPO_ROOT}/deploy/helm/urumi" \
  --namespace "${NAMESPACE}" \
  -f "${REPO_ROOT}/deploy/helm/urumi/values-kind.yaml" \
  --reuse-values \
  --set-string secrets.woocommerceConsumerKey="${CK}" \
  --set-string secrets.woocommerceConsumerSecret="${CS}"

echo "==> Waiting for MCP servers to become ready"
for component in woocommerce-mcp inventory-mcp shipping-mcp; do
  kubectl -n "${NAMESPACE}" rollout status "deployment/${RELEASE}-${component}" --timeout=180s
done

# The WordPress pod is recreated by the release upgrade (the deployment carries
# a secret checksum annotation), so resolve the pod again before using WP-CLI.
echo "==> Re-locating WordPress pod"
resolve_pod
echo "    using pod ${POD}"
kubectl -n "${NAMESPACE}" wait --for=condition=Ready "pod/${POD}" --timeout=180s
kubectl -n "${NAMESPACE}" exec "${POD}" -- bash -lc \
  'if ! command -v wp >/dev/null 2>&1; then \
     curl -fsSL -o /usr/local/bin/wp https://raw.githubusercontent.com/wp-cli/builds/gh-pages/phar/wp-cli.phar && \
     chmod +x /usr/local/bin/wp; fi; wp --allow-root --version'

echo "==> Registering the product illustrations (media attachments)"
MANIFEST="$(mktemp -t urumi-catalog-images.XXXXXX.json)"
# `wp eval` takes the code as an argument and evaluates it directly, so the
# leading `<?php` of the script file has to be stripped first.
kubectl -n "${NAMESPACE}" exec "${POD}" -- wp --allow-root eval \
  "$(sed '1d' "${REPO_ROOT}/scripts/woo_storefront.php")" \
  | grep '^URUMI_MANIFEST:' | sed 's/^URUMI_MANIFEST://' > "${MANIFEST}"
if [[ ! -s "${MANIFEST}" ]]; then
  echo "could not register product illustrations" >&2
  exit 1
fi
echo "    manifest written to ${MANIFEST}"

echo "==> Verifying REST auth and seeding the catalogue/order"
WOOCOMMERCE_BASE_URL="${SITE_URL}" \
WOOCOMMERCE_CONSUMER_KEY="${CK}" \
WOOCOMMERCE_CONSUMER_SECRET="${CS}" \
WOOCOMMERCE_AUTH_MODE="oauth1" \
URUMI_CATALOG_MANIFEST="${MANIFEST}" \
  python3 "${REPO_ROOT}/scripts/woo_rest.py" seed

echo
echo "Store provisioning complete."
echo "  Storefront : ${SITE_URL}  (WooCommerce REST: ${SITE_URL}/wp-json/wc/v3)"
echo "  WP admin   : ${SITE_URL}/wp-admin (user: ${ADMIN_USER})"
echo "  Store admin password: ${ADMIN_PASSWORD}"
