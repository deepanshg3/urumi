# Chat agent image (Pass 7). Build from the repository root:
#   docker build -f deploy/docker/agent/Dockerfile -t urumi/agent .
#
# Installs the shared `mcp` extra plus the LLM-specific `agent` extra so the
# gateway/MCP images stay free of LangChain/Gemini dependencies.
# .env, .venv, tests and caches are excluded by the sibling .dockerignore.

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

RUN python - <<'PY' > /tmp/requirements.txt
import tomllib

with open("pyproject.toml", "rb") as handle:
    data = tomllib.load(handle)
extras = data["project"]["optional-dependencies"]
for requirement in (*extras["mcp"], *extras["agent"], *extras["postgres"]):
    print(requirement)
PY
RUN pip install --no-cache-dir -r /tmp/requirements.txt \
    && pip install --no-cache-dir --no-deps .

ENV URUMI_SERVICE=services.agent \
    PORT=8200 \
    PYTHONPATH=/app

USER urumi

EXPOSE 8200

HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8200/health', timeout=3)" || exit 1

CMD ["sh", "-c", "exec python -m services.agent"]
