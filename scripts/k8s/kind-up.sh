#!/usr/bin/env bash
# Create the local Kind cluster (idempotent).
set -euo pipefail

CLUSTER_NAME="${CLUSTER_NAME:-urumi}"
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"

if ! command -v kind >/dev/null 2>&1; then
  echo "kind is not installed. See docs/deployment.md for install instructions." >&2
  exit 1
fi

if kind get clusters 2>/dev/null | grep -qx "${CLUSTER_NAME}"; then
  echo "Kind cluster '${CLUSTER_NAME}' already exists."
else
  echo "Creating Kind cluster '${CLUSTER_NAME}'..."
  kind create cluster --config "${REPO_ROOT}/deploy/kind/kind-config.yaml"
fi

kubectl cluster-info --context "kind-${CLUSTER_NAME}"
