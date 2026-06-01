#!/usr/bin/env bash
set -euo pipefail

if [[ "${WSL_DISTRO_NAME:-}" == "" ]] && ! grep -qi microsoft /proc/version 2>/dev/null; then
  echo "This helper is intended for WSL. Use scripts/verify.py directly on native Linux or Windows." >&2
  exit 2
fi

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

export UV_PROJECT_ENVIRONMENT="${UV_PROJECT_ENVIRONMENT:-/tmp/seafile-ragflow-connector-wsl-venv}"
export UV_LINK_MODE="${UV_LINK_MODE:-copy}"

cd "${repo_root}"
exec uv run python scripts/verify.py "$@"
