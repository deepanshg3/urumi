#!/usr/bin/env bash
# One-command local deployment: Kind cluster + images + Helm release.
#
#   scripts/k8s/deploy-kind.sh
#
# Secrets are generated locally (postgres/mariadb/gateway/admin) and passed to
# Helm with --set; GEMINI_API_KEY is read from .env when present. Nothing is
# written into the chart.
set -euo pipefail

export PATH="${HOME}/.local/bin:${PATH}"

CLUSTER_NAME="${CLUSTER_NAME:-urumi}"
RELEASE="${RELEASE:-urumi}"
NAMESPACE="${NAMESPACE:-urumi}"
IMAGE_TAG="${IMAGE_TAG:-local}"
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "${REPO_ROOT}"

for tool in kind kubectl helm docker; do
  command -v "${tool}" >/dev/null 2>&1 || { echo "missing required tool: ${tool}" >&2; exit 1; }
done

echo "==> Ensuring Kind cluster"
CLUSTER_NAME="${CLUSTER_NAME}" "${REPO_ROOT}/scripts/k8s/kind-up.sh"

echo "==> Building and loading images"
CLUSTER_NAME="${CLUSTER_NAME}" IMAGE_TAG="${IMAGE_TAG}" \
  "${REPO_ROOT}/scripts/k8s/build-and-load.sh"

SECRET_NAME="${RELEASE}-secrets"
read_secret() {
  kubectl -n "${NAMESPACE}" get secret "${SECRET_NAME}" -o jsonpath="{.data.$1}" | base64 -d
}

rand() { openssl rand -hex 24; }
if kubectl -n "${NAMESPACE}" get secret "${SECRET_NAME}" >/dev/null 2>&1; then
  # Re-running this script must not rotate database passwords: the running
  # Postgres/MariaDB already contain data keyed to the old credentials.
  echo "==> Reusing existing secrets from secret/${SECRET_NAME}"
  GATEWAY_SECRET_KEY="${GATEWAY_SECRET_KEY:-$(read_secret gateway-secret-key)}"
  BOOTSTRAP_ADMIN_PASSWORD="${BOOTSTRAP_ADMIN_PASSWORD:-$(read_secret bootstrap-admin-password)}"
  POSTGRES_PASSWORD="${POSTGRES_PASSWORD:-$(read_secret postgres-password)}"
  MARIADB_ROOT_PASSWORD="${MARIADB_ROOT_PASSWORD:-$(read_secret mariadb-root-password)}"
  MARIADB_PASSWORD="${MARIADB_PASSWORD:-$(read_secret mariadb-password)}"
  WOOCOMMERCE_CONSUMER_KEY="${WOOCOMMERCE_CONSUMER_KEY:-$(read_secret woocommerce-consumer-key || true)}"
  WOOCOMMERCE_CONSUMER_SECRET="${WOOCOMMERCE_CONSUMER_SECRET:-$(read_secret woocommerce-consumer-secret || true)}"
else
  echo "==> Generating secrets"
  GATEWAY_SECRET_KEY="$(rand)"
  BOOTSTRAP_ADMIN_PASSWORD="$(rand | cut -c1-16)"
  POSTGRES_PASSWORD="$(rand | cut -c1-24)"
  MARIADB_ROOT_PASSWORD="$(rand | cut -c1-24)"
  MARIADB_PASSWORD="$(rand | cut -c1-24)"
  WOOCOMMERCE_CONSUMER_KEY=""
  WOOCOMMERCE_CONSUMER_SECRET=""
fi

GEMINI_API_KEY=""
if [[ -f "${REPO_ROOT}/.env" ]]; then
  GEMINI_API_KEY="$(grep -E '^GEMINI_API_KEY=' "${REPO_ROOT}/.env" | head -1 | cut -d= -f2- || true)"
fi
if [[ -z "${GEMINI_API_KEY}" || "${GEMINI_API_KEY}" == your-* ]]; then
  echo "    note: no real GEMINI_API_KEY found; the agent will report a configuration error until one is set."
fi

echo "==> Installing/upgrading Helm release '${RELEASE}' in namespace '${NAMESPACE}'"
SET_ARGS=(
  --set-string "secrets.gatewaySecretKey=${GATEWAY_SECRET_KEY}"
  --set-string "secrets.bootstrapAdminPassword=${BOOTSTRAP_ADMIN_PASSWORD}"
  --set-string "secrets.postgresPassword=${POSTGRES_PASSWORD}"
  --set-string "secrets.mariadbRootPassword=${MARIADB_ROOT_PASSWORD}"
  --set-string "secrets.mariadbPassword=${MARIADB_PASSWORD}"
  --set-string "secrets.geminiApiKey=${GEMINI_API_KEY}"
)
if [[ -n "${WOOCOMMERCE_CONSUMER_KEY:-}" && -n "${WOOCOMMERCE_CONSUMER_SECRET:-}" ]]; then
  SET_ARGS+=(
    --set-string "secrets.woocommerceConsumerKey=${WOOCOMMERCE_CONSUMER_KEY}"
    --set-string "secrets.woocommerceConsumerSecret=${WOOCOMMERCE_CONSUMER_SECRET}"
  )
fi
helm upgrade --install "${RELEASE}" "${REPO_ROOT}/deploy/helm/urumi" \
  --namespace "${NAMESPACE}" --create-namespace \
  -f "${REPO_ROOT}/deploy/helm/urumi/values-kind.yaml" \
  "${SET_ARGS[@]}"

# The three MCP servers stay "not ready" until the WooCommerce store is seeded
# with REST credentials, so wait only for the store and core services here.
echo "==> Waiting for core components"
kubectl -n "${NAMESPACE}" rollout status statefulset/"${RELEASE}-postgres" --timeout=300s
kubectl -n "${NAMESPACE}" rollout status deployment/"${RELEASE}-mariadb" --timeout=300s
kubectl -n "${NAMESPACE}" rollout status deployment/"${RELEASE}-wordpress" --timeout=300s
kubectl -n "${NAMESPACE}" rollout status deployment/"${RELEASE}-gateway" --timeout=300s
kubectl -n "${NAMESPACE}" rollout status deployment/"${RELEASE}-agent" --timeout=300s
kubectl -n "${NAMESPACE}" rollout status deployment/"${RELEASE}-dashboard" --timeout=180s

echo
echo "==> Core components are up. Provisioning the WooCommerce store next."
"${REPO_ROOT}/scripts/k8s/seed-store.sh" || {
  echo "Store provisioning did not complete. Re-run scripts/k8s/seed-store.sh." >&2
}

echo
echo "==> Status"
kubectl -n "${NAMESPACE}" get pods

cat <<EOF

Dashboard:   http://localhost:8088
Admin login: admin@urumi.local / ${BOOTSTRAP_ADMIN_PASSWORD}
    (store it now; it is not written to git)

Next:
  scripts/k8s/seed-store.sh     # re-run store provisioning if needed
  scripts/k8s/verify.sh         # check health endpoints
  scripts/k8s/delete.sh         # uninstall the release
  scripts/k8s/kind-down.sh      # delete the cluster
EOF

# Keep the generated admin password in an ignored file for convenience.
if [[ -d "${REPO_ROOT}/.git" ]]; then
  printf 'ADMIN_EMAIL=admin@urumi.local\nADMIN_PASSWORD=%s\n' "${BOOTSTRAP_ADMIN_PASSWORD}" \
    > "${REPO_ROOT}/.urumi-kind-credentials"
  chmod 600 "${REPO_ROOT}/.urumi-kind-credentials"
  echo "Admin credentials also written to .urumi-kind-credentials (gitignored)."
fi
