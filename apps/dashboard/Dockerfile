# Dashboard image: build the Vite app, serve it with nginx, and reverse-proxy
# the gateway (`/api`, `/mcp`) and the agent (`/agent/api`) so the whole platform
# is reachable on one origin (required for SameSite=strict session cookies).
#
# Build from the repository root:
#   docker build -f apps/dashboard/Dockerfile -t urumi/dashboard .

FROM node:22-slim AS build

WORKDIR /app
COPY apps/dashboard/package.json apps/dashboard/package-lock.json* ./
RUN npm install
COPY apps/dashboard/ ./
RUN npm run build

FROM nginx:1.27-alpine AS runtime

# Upstreams are configured at runtime through environment variables.
ENV GATEWAY_UPSTREAM=gateway:8000 \
    AGENT_UPSTREAM=agent:8200

COPY apps/dashboard/nginx/default.conf.template /etc/nginx/templates/default.conf.template
COPY --from=build /app/dist /usr/share/nginx/html

EXPOSE 80

HEALTHCHECK --interval=30s --timeout=5s --start-period=5s --retries=3 \
    CMD wget -q -O /dev/null http://127.0.0.1/ || exit 1
