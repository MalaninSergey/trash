#!/usr/bin/env bash
# Install cloudflared on macOS if missing, then start tunnel to local bridge.
set -euo pipefail

if ! command -v cloudflared >/dev/null 2>&1; then
  if command -v brew >/dev/null 2>&1; then
    echo "Installing cloudflared via Homebrew..."
    brew install cloudflare/cloudflare/cloudflared
  else
    echo "cloudflared not found and Homebrew missing."
    echo "Install Homebrew: https://brew.sh"
    echo "Then: brew install cloudflare/cloudflare/cloudflared"
    exit 1
  fi
fi

echo "Starting tunnel -> http://127.0.0.1:8787"
echo "Copy the https://*.trycloudflare.com URL to the Cursor agent."
exec cloudflared tunnel --url http://127.0.0.1:8787
