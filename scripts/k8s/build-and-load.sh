#!/usr/bin/env bash
# Build all platform images locally and load them into the Kind cluster.
set -euo pipefail

CLUSTER_NAME="${CLUSTER_NAME:-urumi}"
IMAGE_TAG="${IMAGE_TAG:-local}"
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "${REPO_ROOT}"

MCP_DOCKERFILE="deploy/docker/mcp/Dockerfile"

echo "Building MCP server images..."
docker build -f "${MCP_DOCKERFILE}" \
  --build-arg SERVICE=services.woocommerce_mcp --build-arg PORT=8101 \
  -t "urumi/woocommerce-mcp:${IMAGE_TAG}" .
docker build -f "${MCP_DOCKERFILE}" \
  --build-arg SERVICE=services.inventory_mcp --build-arg PORT=8102 \
  -t "urumi/inventory-mcp:${IMAGE_TAG}" .
docker build -f "${MCP_DOCKERFILE}" \
  --build-arg SERVICE=services.shipping_mcp --build-arg PORT=8103 \
  -t "urumi/shipping-mcp:${IMAGE_TAG}" .

echo "Building gateway image..."
docker build -f "${MCP_DOCKERFILE}" \
  --build-arg SERVICE=services.gateway --build-arg PORT=8000 \
  --build-arg EXTRAS=mcp,postgres \
  -t "urumi/gateway:${IMAGE_TAG}" .

echo "Building agent image..."
docker build -f deploy/docker/agent/Dockerfile -t "urumi/agent:${IMAGE_TAG}" .

echo "Building dashboard image..."
docker build -f apps/dashboard/Dockerfile -t "urumi/dashboard:${IMAGE_TAG}" .

echo "Building storefront theme image..."
docker build -f deploy/docker/woocommerce/theme/Dockerfile \
  -t "urumi/urumi-supply-theme:${IMAGE_TAG}" .

if command -v kind >/dev/null 2>&1 && kind get clusters 2>/dev/null | grep -qx "${CLUSTER_NAME}"; then
  echo "Loading images into Kind cluster '${CLUSTER_NAME}'..."
  kind load docker-image --name "${CLUSTER_NAME}" \
    "urumi/woocommerce-mcp:${IMAGE_TAG}" \
    "urumi/inventory-mcp:${IMAGE_TAG}" \
    "urumi/shipping-mcp:${IMAGE_TAG}" \
    "urumi/gateway:${IMAGE_TAG}" \
    "urumi/agent:${IMAGE_TAG}" \
    "urumi/dashboard:${IMAGE_TAG}" \
    "urumi/urumi-supply-theme:${IMAGE_TAG}"
else
  echo "Kind cluster '${CLUSTER_NAME}' not found; built images only." >&2
fi
