#!/bin/bash
set -e

# Ensure PORT is set (Render provides it)
export PORT=${PORT:-10000}

# Create necessary directories
mkdir -p /app/data /var/log/supervisor /var/log/nginx /run/nginx

# Substitute PORT in nginx config
envsubst '${PORT}' < /etc/nginx/conf.d/default.conf.template > /etc/nginx/conf.d/default.conf

# Ensure files owned appropriately if running as non-root where possible
chown -R urumi:urumi /app/data 2>/dev/null || true

# Start supervisord
exec /usr/bin/supervisord -c /etc/supervisor/conf.d/supervisord.conf
