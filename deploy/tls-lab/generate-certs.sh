#!/usr/bin/env sh
set -eu

SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
OUT_DIR="${1:-$SCRIPT_DIR/certs}"

if command -v uv >/dev/null 2>&1; then
  uv run python "$SCRIPT_DIR/generate_certs.py" --out-dir "$OUT_DIR"
else
  python3 "$SCRIPT_DIR/generate_certs.py" --out-dir "$OUT_DIR"
fi
