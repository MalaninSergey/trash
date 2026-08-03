#!/usr/bin/env bash
# Temporary public tunnel to THIS JupyterHub user server.
# Run inside JupyterLab: File → New → Terminal
set -euo pipefail

PORT="${JUPYTER_PORT:-8888}"
PREFIX="${JUPYTERHUB_SERVICE_PREFIX:-/user/${JUPYTERHUB_USER:-smalanin}/}"
WORKDIR="${HOME}/.local/bin"
mkdir -p "$WORKDIR"
cd "$WORKDIR"

ARCH="$(uname -m)"
case "$ARCH" in
  x86_64|amd64) CF_ARCH="amd64" ;;
  aarch64|arm64) CF_ARCH="arm64" ;;
  *) echo "Unsupported arch: $ARCH"; exit 1 ;;
esac

if [[ ! -x ./cloudflared ]]; then
  echo "Downloading cloudflared..."
  curl -fsSL -o cloudflared \
    "https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-${CF_ARCH}" \
  || curl -fsSL -o cloudflared \
    "https://github.com/cloudflare/cloudflared/releases/download/2025.2.1/cloudflared-linux-${CF_ARCH}"
  chmod +x cloudflared
fi

# Probe local Jupyter port
FOUND=""
for p in "$PORT" 8888 8889 8080 8081; do
  if curl -fsS -o /dev/null -m 2 "http://127.0.0.1:${p}${PREFIX}" 2>/dev/null \
     || curl -fsS -o /dev/null -m 2 "http://127.0.0.1:${p}/api" 2>/dev/null; then
    FOUND="$p"
    break
  fi
done

if [[ -z "$FOUND" ]]; then
  echo "ERROR: local Jupyter server not found on common ports."
  echo "Check: echo \$JUPYTER_PORT; ss -lntp | head"
  exit 1
fi

echo "Local Jupyter port: $FOUND"
echo "Service prefix:     $PREFIX"
echo
echo "After the tunnel starts, copy the https://*.trycloudflare.com URL"
echo "and paste it to the Cursor cloud agent."
echo "Agent will call: https://<tunnel>${PREFIX}api/contents/"
echo "----------------------------------------------------------------"
echo "Keep this terminal open while working."
echo

exec ./cloudflared tunnel --url "http://127.0.0.1:${FOUND}" --no-autoupdate
