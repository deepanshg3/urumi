# Multi-stage Dockerfile for single-container Render deployment
# Builds dashboard, sets up Python services, runs all processes with supervisor

# Build dashboard
FROM node:22-slim AS dashboard-build
WORKDIR /app
COPY apps/dashboard/package.json apps/dashboard/package-lock.json* ./
RUN npm ci || npm install
COPY apps/dashboard/ ./
RUN npm run build

# Python base
FROM python:3.12-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    nginx \
    supervisor \
    curl gettext-base \
    && rm -rf /var/lib/apt/lists/*

RUN groupadd --system --gid 1001 urumi \
    && useradd --system --uid 1001 --gid urumi --home /app urumi

# Copy project files
COPY pyproject.toml README.md ./
COPY services ./services
COPY config ./config
COPY scripts ./scripts

# Create data dirs
RUN mkdir -p /app/data /var/log/supervisor /run/nginx && \
    chown -R urumi:urumi /app/data /var/log/supervisor

# Install all dependencies (gateway needs postgres extra per compose, but for single container sqlite is fine; include all needed)
RUN python - <<'PY' > /tmp/requirements.txt
import tomllib

with open("pyproject.toml", "rb") as handle:
    data = tomllib.load(handle)
extras = data["project"]["optional-dependencies"]
# Install everything needed for all services
reqs = []
# common base
for name in ["mcp", "agent", "postgres"]:
    if name in extras:
        for r in extras[name]:
            reqs.append(r)
# Add dev deps not needed, but ensure core deps present
# deduplicate
seen = set()
out = []
for r in reqs:
    key = r.split('>=')[0].split('==')[0].split('<')[0]
    if key not in seen:
        seen.add(key)
        out.append(r)
for r in out:
    print(r)
PY
RUN pip install --no-cache-dir -r /tmp/requirements.txt \
    && pip install --no-cache-dir --no-deps .

# Copy built dashboard
COPY --from=dashboard-build /app/dist /usr/share/nginx/html

# Copy nginx config template and override for PORT
COPY apps/dashboard/nginx/default.conf.template /etc/nginx/templates/default.conf.template
# Create a modified config that listens on PORT
COPY deploy/render/nginx.conf /etc/nginx/conf.d/default.conf.template

# Copy entrypoint and supervisor config
COPY deploy/render/entrypoint.sh /entrypoint.sh
COPY deploy/render/supervisord.conf /etc/supervisor/conf.d/supervisord.conf
RUN chmod +x /entrypoint.sh

ENV PYTHONPATH=/app \
    GATEWAY_UPSTREAM=127.0.0.1:8000 \
    AGENT_UPSTREAM=127.0.0.1:8200

EXPOSE 10000

# Run as root to manage nginx/supervisor, drop privileges inside services as appropriate
CMD ["/entrypoint.sh"]
