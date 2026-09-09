#!/usr/bin/env bash
# Start PC bridge to JupyterHub (macOS / Linux)
set -euo pipefail
cd "$(dirname "$0")"

if command -v python3 >/dev/null 2>&1; then
  PY=python3
elif command -v python >/dev/null 2>&1; then
  PY=python
else
  echo "Python 3 not found. Install: brew install python"
  exit 1
fi

exec "$PY" jupyter_pc_bridge.py "$@"
