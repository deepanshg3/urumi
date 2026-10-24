# Image carrying the Urumi Supply WordPress theme.
#
# The theme is copied into the cluster with an init container and mounted into
# the WordPress pod, so the storefront looks the same in Docker Compose and in
# the Kind/Helm deployment.
#
# Build from the repository root:
#   docker build -f deploy/docker/woocommerce/theme/Dockerfile \
#     -t urumi/urumi-supply-theme .
#
# deploy/docker/woocommerce/theme/Dockerfile.dockerignore keeps the build
# context limited to the theme files.

FROM alpine:3.20

COPY deploy/docker/woocommerce/theme/urumi-supply /theme/urumi-supply

CMD ["sh", "-c", "cp -R /theme/urumi-supply/. /theme-target/"]
