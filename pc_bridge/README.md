# PC bridge: Cloud Agent → your PC → JupyterHub

## Architecture

```
Cursor Cloud Agent
        │
        │  HTTPS (public tunnel URL)
        ▼
 cloudflared (on your PC)
        │
        │  http://127.0.0.1:8787
        ▼
 jupyter_pc_bridge.py  (on your PC)
        │
        │  via your VPN / corp network
        ▼
 https://jupyterhub-ml-p02.samokat.ru
```

Cloud does **not** talk to JupyterHub directly.
Your PC executes every request locally and returns the response.

## Requirements on the Mac

1. **Python 3** (stdlib only, no pip) — usually present, or `brew install python`.
2. **cloudflared** — `brew install cloudflare/cloudflare/cloudflared`
3. VPN that works for **Terminal / whole OS** (not only a browser extension).  
   Quick check in Terminal.app:
   ```bash
   nslookup jupyterhub-ml-p02.samokat.ru
   curl -I https://jupyterhub-ml-p02.samokat.ru/hub/api/
   ```
   If DNS fails here, the bridge cannot help until system VPN is on.

## Steps (macOS)

### 0. One-time tools
```bash
# Python (if needed)
brew install python

# cloudflared
brew install cloudflare/cloudflare/cloudflared
```

VPN check (Terminal.app, not browser):
```bash
nslookup jupyterhub-ml-p02.samokat.ru
curl -I https://jupyterhub-ml-p02.samokat.ru/hub/api/
```

### 1. Get this folder
```bash
git clone -b cursor/jupyterhub-tunnel-helper-d5ec https://github.com/MalaninSergey/trash.git
cd trash/pc_bridge
chmod +x start_bridge.command start_tunnel_mac.sh
```

Or download the `pc_bridge/` folder from GitHub in the browser.

### 2. Terminal 1 — bridge
```bash
./start_bridge.command
# or: python3 jupyter_pc_bridge.py
```

You should see: `Upstream check: ... -> HTTP ...` and `Bridge listening on http://127.0.0.1:8787`.

### 3. Terminal 2 — tunnel
```bash
./start_tunnel_mac.sh
# or: cloudflared tunnel --url http://127.0.0.1:8787
```

### 4. Send the URL to the agent
Copy `https://….trycloudflare.com` into the Cursor chat.
Keep **both** terminals open.

The agent will call e.g.:
`https://<tunnel>/user/smalanin/api/contents/` with your JupyterHub token.

### Windows (optional)
Use `start_bridge.bat` and the same `cloudflared tunnel --url http://127.0.0.1:8787`.

## Stop

Ctrl+C in both terminals. Rotate the JupyterHub API token when finished.

## Troubleshooting

| Symptom | Cause |
|---|---|
| `Upstream check` fails / NXDOMAIN | Browser-only VPN; need system VPN |
| Tunnel up but agent gets 502 | Bridge crashed or Hub unreachable from PC |
| 401/403 from Hub | Bad/expired API token |
