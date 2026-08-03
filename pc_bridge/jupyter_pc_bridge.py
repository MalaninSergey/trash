#!/usr/bin/env python3
"""
PC-side reverse proxy: Cloud Agent -> (cloudflared) -> this PC -> JupyterHub.

Run on the PC that already reaches jupyterhub-ml-p02.samokat.ru
(system/corporate VPN must work for Python, not only a browser extension).

Usage:
  python jupyter_pc_bridge.py
  # then in another terminal:
  cloudflared tunnel --url http://127.0.0.1:8787
"""

from __future__ import annotations

import argparse
import ssl
import sys
import traceback
from http.client import HTTPSConnection, HTTPConnection
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit


DEFAULT_UPSTREAM = "https://jupyterhub-ml-p02.samokat.ru"
DEFAULT_BIND = "127.0.0.1"
DEFAULT_PORT = 8787
HOP_BY_HOP = {
    "connection",
    "keep-alive",
    "proxy-authenticate",
    "proxy-authorization",
    "te",
    "trailers",
    "transfer-encoding",
    "upgrade",
    "host",
    "content-length",
}


class BridgeHandler(BaseHTTPRequestHandler):
    upstream_scheme = "https"
    upstream_host = "jupyterhub-ml-p02.samokat.ru"
    upstream_port = 443
    timeout = 120
    verify_ssl = True

    def log_message(self, fmt: str, *args) -> None:
        sys.stderr.write("[%s] %s\n" % (self.log_date_time_string(), fmt % args))

    def _proxy(self) -> None:
        length = int(self.headers.get("Content-Length", "0") or 0)
        body = self.rfile.read(length) if length > 0 else None

        headers = {
            k: v
            for k, v in self.headers.items()
            if k.lower() not in HOP_BY_HOP
        }
        headers["Host"] = self.upstream_host
        # Preserve original host for apps that care (optional).
        headers.setdefault("X-Forwarded-Host", self.headers.get("Host", ""))
        headers.setdefault("X-Forwarded-Proto", "https")

        path = self.path
        try:
            if self.upstream_scheme == "https":
                ctx = ssl.create_default_context()
                if not self.verify_ssl:
                    ctx.check_hostname = False
                    ctx.verify_mode = ssl.CERT_NONE
                conn = HTTPSConnection(
                    self.upstream_host,
                    self.upstream_port,
                    timeout=self.timeout,
                    context=ctx,
                )
            else:
                conn = HTTPConnection(
                    self.upstream_host,
                    self.upstream_port,
                    timeout=self.timeout,
                )

            conn.request(self.command, path, body=body, headers=headers)
            resp = conn.getresponse()
            resp_body = resp.read()

            self.send_response(resp.status, resp.reason)
            for k, v in resp.getheaders():
                if k.lower() in HOP_BY_HOP:
                    continue
                # Avoid broken compression if we already have raw bytes decoded by http.client
                if k.lower() == "content-encoding":
                    continue
                self.send_header(k, v)
            self.send_header("Content-Length", str(len(resp_body)))
            self.end_headers()
            if self.command != "HEAD":
                self.wfile.write(resp_body)
            conn.close()
        except Exception as exc:
            msg = f"bridge error talking to {self.upstream_host}: {exc}\n"
            detail = traceback.format_exc()
            sys.stderr.write(detail)
            data = (msg + detail).encode("utf-8", errors="replace")
            self.send_response(502)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

    def do_GET(self) -> None:
        self._proxy()

    def do_POST(self) -> None:
        self._proxy()

    def do_PUT(self) -> None:
        self._proxy()

    def do_PATCH(self) -> None:
        self._proxy()

    def do_DELETE(self) -> None:
        self._proxy()

    def do_HEAD(self) -> None:
        self._proxy()

    def do_OPTIONS(self) -> None:
        self._proxy()


def parse_upstream(url: str) -> tuple[str, str, int]:
    parts = urlsplit(url)
    if parts.scheme not in ("http", "https") or not parts.hostname:
        raise SystemExit(f"Invalid upstream URL: {url}")
    port = parts.port or (443 if parts.scheme == "https" else 80)
    return parts.scheme, parts.hostname, port


def _upstream_get(scheme: str, host: str, port: int, insecure: bool):
    if scheme == "https":
        ctx = ssl.create_default_context()
        if insecure:
            ctx.check_hostname = False
            ctx.verify_mode = ssl.CERT_NONE
        conn = HTTPSConnection(host, port, timeout=15, context=ctx)
    else:
        conn = HTTPConnection(host, port, timeout=15)
    conn.request("GET", "/hub/api/", headers={"Host": host})
    r = conn.getresponse()
    body = r.read()
    status = r.status
    conn.close()
    return status, body


def main() -> None:
    parser = argparse.ArgumentParser(description="PC bridge to JupyterHub for Cursor cloud agent")
    parser.add_argument("--bind", default=DEFAULT_BIND)
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument("--upstream", default=DEFAULT_UPSTREAM)
    parser.add_argument(
        "--insecure",
        action="store_true",
        help="Skip TLS verify to JupyterHub (corp self-signed MITM/proxy certs)",
    )
    args = parser.parse_args()

    scheme, host, port = parse_upstream(args.upstream)
    BridgeHandler.upstream_scheme = scheme
    BridgeHandler.upstream_host = host
    BridgeHandler.upstream_port = port

    insecure = args.insecure
    # Quick connectivity check before accepting cloud traffic
    try:
        status, _ = _upstream_get(scheme, host, port, insecure=insecure)
        print(f"Upstream check: {scheme}://{host}:{port}/hub/api/ -> HTTP {status}")
    except ssl.SSLCertVerificationError as exc:
        if insecure:
            print("ERROR: TLS verify already disabled, but SSL still failed.")
            print(f"  detail: {exc}")
            raise SystemExit(1)
        print("Corp/self-signed TLS cert detected; retrying with --insecure")
        try:
            status, _ = _upstream_get(scheme, host, port, insecure=True)
            insecure = True
            print(f"Upstream check (insecure): {scheme}://{host}:{port}/hub/api/ -> HTTP {status}")
        except Exception as exc2:
            print("ERROR: this PC cannot reach JupyterHub yet.")
            print(f"  target: {args.upstream}")
            print(f"  detail: {exc2}")
            raise SystemExit(1)
    except Exception as exc:
        print("ERROR: this PC cannot reach JupyterHub yet.")
        print(f"  target: {args.upstream}")
        print(f"  detail: {exc}")
        print()
        print("If VPN works only inside the browser extension, this bridge will NOT work.")
        print("You need a system/corporate VPN (or split tunnel) that Python can use.")
        raise SystemExit(1)

    BridgeHandler.verify_ssl = not insecure
    if insecure:
        print("TLS verify: OFF (corporate certificate chain)")

    server = ThreadingHTTPServer((args.bind, args.port), BridgeHandler)
    print(f"Bridge listening on http://{args.bind}:{args.port}")
    print(f"Forwarding to {args.upstream}")
    print()
    print("Next step — in another terminal on THIS PC run:")
    print(f"  cloudflared tunnel --url http://{args.bind}:{args.port}")
    print("  # or: ./start_tunnel_mac.sh")
    print()
    print("Then paste the https://*.trycloudflare.com URL to the Cursor cloud agent.")
    print("Keep BOTH windows open while working. Ctrl+C to stop.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")


if __name__ == "__main__":
    main()
