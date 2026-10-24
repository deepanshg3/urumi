#!/usr/bin/env bash
# Retire the old assessment accounts on a running deployment and remove the
# credential files from the host checkout.
#
#   scripts/revoke_assessment_credentials.sh compose
#   scripts/revoke_assessment_credentials.sh kind
#   scripts/revoke_assessment_credentials.sh local   # uses $DATABASE_URL
#
# Set KEEP_CREDENTIAL_FILES=1 to keep the local assessment-credentials*.txt
# files. This script never prints passwords or API keys.
set -euo pipefail

target="${1:-compose}"
repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
script="scripts/revoke_assessment_credentials.py"

case "$target" in
  compose)
    docker compose -f "$repo_root/deploy/docker/mcp/compose.yaml" exec -T gateway \
      python "$script"
    ;;
  kind)
    kubectl -n urumi exec deploy/urumi-gateway -- python "$script"
    ;;
  local)
    if [[ -z "${DATABASE_URL:-}" ]]; then
      echo "DATABASE_URL must be set for the local target" >&2
      exit 2
    fi
    "$repo_root/.venv/bin/python" "$repo_root/$script"
    ;;
  *)
    echo "usage: $0 [compose|kind|local]" >&2
    exit 2
    ;;
esac

if [[ "${KEEP_CREDENTIAL_FILES:-0}" != "1" ]]; then
  shopt -s nullglob
  files=("$repo_root"/assessment-credentials*.txt)
  if (( ${#files[@]} > 0 )); then
    rm -f -- "${files[@]}"
    printf 'deleted credential files: %s\n' "$(basename -a "${files[@]}" | paste -sd', ' -)"
  else
    echo "no credential files found on the host"
  fi
fi

if [[ -f "$repo_root/.env" ]] && grep -qE '^\s*(ASSESSMENT_|assess)' "$repo_root/.env"; then
  echo "warning: review .env for leftover assessment credentials (values not shown)" >&2
fi
