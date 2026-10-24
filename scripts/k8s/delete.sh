#!/usr/bin/env bash
# Uninstall the Helm release (keeps the Kind cluster and the generated
# credentials file; use scripts/k8s/kind-down.sh to delete everything).
set -euo pipefail

export PATH="${HOME}/.local/bin:${PATH}"

RELEASE="${RELEASE:-urumi}"
NAMESPACE="${NAMESPACE:-urumi}"

helm uninstall "${RELEASE}" --namespace "${NAMESPACE}" || true
kubectl delete namespace "${NAMESPACE}" --ignore-not-found=true
echo "Removed release '${RELEASE}'."
