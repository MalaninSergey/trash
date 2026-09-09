#!/usr/bin/env bash
# Tail JupyterHub run log via local pc_bridge (:8787)
# Usage:
#   ./pc_bridge/tail_hub_log.sh
#   ./pc_bridge/tail_hub_log.sh extend_da_rooms 80
#   ./pc_bridge/tail_hub_log.sh extend_da_rooms 40 --follow

set -euo pipefail
NAME="${1:-extend_da_rooms}"
N="${2:-60}"
FOLLOW="${3:-}"
TOKEN_FILE="${JUPYTERHUB_TOKEN_FILE:-$HOME/trash/.secrets/jupyterhub_token}"
# fallback paths
if [[ ! -f "$TOKEN_FILE" ]]; then
  TOKEN_FILE="/Users/hq-fvfgr2vpq05p/trash/.secrets/jupyterhub_token"
fi
if [[ ! -f "$TOKEN_FILE" ]]; then
  echo "Token file not found. Set JUPYTERHUB_TOKEN_FILE or put token in .secrets/jupyterhub_token" >&2
  exit 1
fi
TOKEN="$(cat "$TOKEN_FILE")"
BASE="${JUPYTER_BRIDGE:-http://127.0.0.1:8787}/user/smalanin/api/contents"
LOG_PATH="data/runs/${NAME}.log"
STATUS_PATH="data/runs/${NAME}.status.json"

fetch() {
  local path="$1"
  python3 - "$BASE" "$TOKEN" "$path" "$N" <<'PY'
import json,sys,urllib.request,base64
from urllib.parse import quote
base,token,path,n=sys.argv[1],sys.argv[2],sys.argv[3],int(sys.argv[4])
enc="/".join(quote(s,safe="") for s in path.split("/"))
req=urllib.request.Request(f"{base}/{enc}", headers={"Authorization": f"token {token}"})
with urllib.request.urlopen(req, timeout=60) as r:
    d=json.load(r)
c=d.get("content") or ""
if d.get("format")=="base64":
    c=base64.b64decode(c).decode("utf-8","replace")
lines=c.splitlines()
# dedupe doubled tee lines
out=[]
for ln in lines:
    if not out or out[-1]!=ln:
        out.append(ln)
print("\n".join(out[-n:]))
print(f"\n# size={d.get('size')} mtime={d.get('last_modified')}", file=sys.stderr)
PY
}

fetch_status() {
  python3 - "$BASE" "$TOKEN" "$STATUS_PATH" <<'PY' 2>/dev/null || true
import json,sys,urllib.request,base64
from urllib.parse import quote
base,token,path=sys.argv[1],sys.argv[2],sys.argv[3]
enc="/".join(quote(s,safe="") for s in path.split("/"))
req=urllib.request.Request(f"{base}/{enc}", headers={"Authorization": f"token {token}"})
with urllib.request.urlopen(req, timeout=30) as r:
    d=json.load(r)
c=d.get("content") or ""
if d.get("format")=="base64":
    c=base64.b64decode(c).decode("utf-8","replace")
print("# status:", c.replace("\n"," "), file=sys.stderr)
PY
}

if [[ "$FOLLOW" == "--follow" || "$FOLLOW" == "-f" ]]; then
  while true; do
    clear 2>/dev/null || true
    date
    fetch_status || true
    echo "=== $LOG_PATH (last $N) ==="
    fetch "$LOG_PATH" || echo "(fetch failed — is pc_bridge on :8787 up?)"
    sleep 15
  done
else
  fetch_status || true
  echo "=== $LOG_PATH (last $N) ==="
  fetch "$LOG_PATH"
fi
