# Shared image for the Urumi MCP servers (WooCommerce and Inventory).
# Build from the repository root:
#   docker build -f deploy/docker/mcp/Dockerfile \
#     --build-arg SERVICE=services.woocommerce_mcp.server \
#     --build-arg PORT=8101 -t urumi/woocommerce-mcp .
#
# The dependency set is read from the `mcp` extra in pyproject.toml so versions
# stay defined in one place. .env, .venv, tests and caches are excluded by
# deploy/docker/mcp/Dockerfile.dockerignore.

FROM python:3.12-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

RUN addgroup --system --gid 1001 urumi \
    && adduser --system --uid 1001 --ingroup urumi --home /app urumi

COPY pyproject.toml README.md ./
COPY services ./services
COPY config ./config
COPY scripts ./scripts

RUN mkdir -p /app/data && chown -R urumi:urumi /app/data

# Which pyproject extras to install (comma separated). The gateway image uses
# `mcp,postgres`; the MCP server images use the default `mcp`.
ARG EXTRAS=mcp

# Extract the runtime dependency list from the requested extras (comma
# separated, default `mcp`), then install. The gateway image passes
# `EXTRAS=mcp,postgres` so it can use an in-cluster PostgreSQL database.
RUN python - <<'PY' > /tmp/requirements.txt
import os
import tomllib

with open("pyproject.toml", "rb") as handle:
    data = tomllib.load(handle)
extras = data["project"]["optional-dependencies"]
names = [name.strip() for name in os.environ.get("EXTRAS", "mcp").split(",") if name.strip()]
for name in names:
    for requirement in extras[name]:
        print(requirement)
PY
RUN pip install --no-cache-dir -r /tmp/requirements.txt \
    && pip install --no-cache-dir --no-deps .

ARG SERVICE=services.woocommerce_mcp
ARG PORT=8101
ENV URUMI_SERVICE=${SERVICE} \
    PORT=${PORT} \
    PYTHONPATH=/app

USER urumi

EXPOSE ${PORT}

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import os,urllib.request; urllib.request.urlopen(f'http://127.0.0.1:{os.environ[\"PORT\"]}/health', timeout=3)" || exit 1

# The module name is passed at build time; the image runs the service entry point.
CMD ["sh", "-c", "exec python -m ${URUMI_SERVICE}"]
