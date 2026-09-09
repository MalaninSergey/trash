# JupyterHub tunnel helper

Run the tunnel **inside JupyterLab Terminal** (already on Samokat network).
Then paste the `https://*.trycloudflare.com` URL to the cloud agent.

## Steps

1. Open https://jupyterhub-ml-p02.samokat.ru/user/smalanin/lab
2. **File → New → Terminal**
3. Paste:

```bash
curl -fsSL -o /tmp/start_tunnel.sh https://raw.githubusercontent.com/MalaninSergey/trash/cursor/jupyterhub-tunnel-helper-d5ec/jupyterhub_tunnel/start_tunnel.sh \
  && bash /tmp/start_tunnel.sh
```

Or one-liner without GitHub:

```bash
mkdir -p "$HOME/.local/bin" && cd "$HOME/.local/bin" \
  && curl -fsSL -o cloudflared "https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64" \
  && chmod +x cloudflared \
  && ./cloudflared tunnel --url "http://127.0.0.1:${JUPYTER_PORT:-8888}" --no-autoupdate
```

4. In the output find a line like:
   `https://random-words-here.trycloudflare.com`
5. Send that URL to the agent (keep the terminal open).

## Fallback if cloudflared download/egress is blocked

In the same JupyterLab Terminal try **localtunnel** (needs Node) or ask the agent for an ngrok variant.

## Security

- Temporary public URL to your Jupyter server — do not share outside this chat.
- Stop the tunnel (`Ctrl+C`) when done.
- Prefer rotating the JupyterHub API token afterwards.
