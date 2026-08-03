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

## Requirements on the PC

1. **Python 3** (stdlib only, no pip packages).
2. **cloudflared** — https://developers.cloudflare.com/cloudflare-one/connections/connect-apps/install-and-setup/installation/
3. VPN that works for **the whole OS** (not only a browser extension).  
   Quick check in PowerShell/Terminal:
   ```text
   nslookup jupyterhub-ml-p02.samokat.ru
   curl -I https://jupyterhub-ml-p02.samokat.ru/hub/api/
   ```
   If DNS fails here, the bridge cannot help until system VPN is on.

## Steps

### 1. Download this folder
Copy `pc_bridge/` to the PC (or clone the repo branch).

### 2. Start the bridge
```bash
python jupyter_pc_bridge.py
```
Windows: double-click `start_bridge.bat` or:
```bat
py jupyter_pc_bridge.py
```

You should see: `Upstream check: ... -> HTTP ...` and `Bridge listening on http://127.0.0.1:8787`.

### 3. Start the tunnel (second terminal)
```bash
cloudflared tunnel --url http://127.0.0.1:8787
```

### 4. Send the URL to the agent
Copy `https://….trycloudflare.com` into the Cursor chat.
Keep **both** processes running.

The agent will call e.g.:
`https://<tunnel>/user/smalanin/api/contents/` with your JupyterHub token.

## Stop

Ctrl+C in both terminals. Rotate the JupyterHub API token when finished.

## Troubleshooting

| Symptom | Cause |
|---|---|
| `Upstream check` fails / NXDOMAIN | Browser-only VPN; need system VPN |
| Tunnel up but agent gets 502 | Bridge crashed or Hub unreachable from PC |
| 401/403 from Hub | Bad/expired API token |
