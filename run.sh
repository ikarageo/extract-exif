#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
VENV_DIR="$SCRIPT_DIR/.venv"

if [[ ! -x "$VENV_DIR/bin/python" ]]; then
    if ! command -v python3 >/dev/null 2>&1; then
        echo "Error: install Python 3.10 or newer (including venv support) first." >&2
        exit 1
    fi
    python3 -m venv "$VENV_DIR"
fi

"$VENV_DIR/bin/python" -m pip install --disable-pip-version-check --no-input --no-cache-dir --quiet -r "$SCRIPT_DIR/requirements.txt"
exec "$VENV_DIR/bin/python" "$SCRIPT_DIR/extract_exif.py" "$@"
