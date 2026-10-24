#!/usr/bin/env bash
# Check the health/readiness endpoints of the in-cluster services.
set -euo pipefail

export PATH="${HOME}/.local/bin:${PATH}"

RELEASE="${RELEASE:-urumi}"
NAMESPACE="${NAMESPACE:-urumi}"

check() {
  local name="$1" url="$2"
  local out code
  out="$(kubectl -n "${NAMESPACE}" run "verify-${name}-$RANDOM" --rm -i --restart=Never \
    --image=curlimages/curl:8.10.1 --command -- \
    curl -s -o /dev/null -w '%{http_code}' "${url}" 2>/dev/null || true)"
  code="$(printf '%s' "${out}" | head -c 3)"
  if [[ "${code}" == "200" ]]; then
    echo "  OK   ${name}  ${url}"
  else
    echo "  FAIL ${name}  ${url}  (status ${code:-none})"
  fi
}

echo "Health checks in namespace ${NAMESPACE}:"
check gateway          "http://${RELEASE}-gateway:8000/health/ready"
check agent            "http://${RELEASE}-agent:8200/health/ready"
check woocommerce-mcp  "http://${RELEASE}-woocommerce-mcp:8101/health/ready"
check inventory-mcp    "http://${RELEASE}-inventory-mcp:8102/health/ready"
check shipping-mcp     "http://${RELEASE}-shipping-mcp:8103/health/ready"

echo
echo "Pods:"
kubectl -n "${NAMESPACE}" get pods
