#!/usr/bin/env bash
# Delete the local Kind cluster.
set -euo pipefail

CLUSTER_NAME="${CLUSTER_NAME:-urumi}"
echo "Deleting Kind cluster '${CLUSTER_NAME}'..."
kind delete cluster --name "${CLUSTER_NAME}"
