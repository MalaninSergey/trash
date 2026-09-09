#!/usr/bin/env python3
"""Upload consumption_map to JupyterHub and run build_consumption_map_draft.py."""

from __future__ import annotations

import base64
import json
import pathlib
import ssl
import time
import uuid
import urllib.error
import urllib.request
from urllib.parse import quote, urlencode

from websocket import create_connection

TOKEN = pathlib.Path("/Users/hq-fvfgr2vpq05p/trash/.secrets/jupyterhub_token").read_text().strip()
API = "https://jupyterhub-ml-p02.samokat.ru/user/smalanin/api"
HUB_ROOT = "data/consumption_map"
LOCAL = pathlib.Path("/Users/hq-fvfgr2vpq05p/trash/consumption_map")
DOWNLOADS = pathlib.Path("/Users/hq-fvfgr2vpq05p/Downloads")
SCENARIO_XLSX = pathlib.Path(
    "/Users/hq-fvfgr2vpq05p/trash/outputs/all_extend_da_rooms/scenarios_gmv_report.xlsx"
)
SSL_OPT = {"cert_reqs": ssl.CERT_NONE}
SSL_CTX = ssl._create_unverified_context()


def enc_path(path: str) -> str:
    return "/".join(quote(p, safe="") for p in path.strip("/").split("/"))


def http(method: str, path: str, data=None, timeout: int = 300):
    headers = {"Authorization": f"token {TOKEN}"}
    body = None
    if data is not None:
        body = json.dumps(data).encode()
        headers["Content-Type"] = "application/json"
    # path may include nested contents/... with unicode names
    if path.startswith("contents/"):
        url_path = "contents/" + enc_path(path[len("contents/") :])
    else:
        url_path = path
    req = urllib.request.Request(f"{API}/{url_path}", data=body, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout, context=SSL_CTX) as r:
            raw = r.read()
            return json.loads(raw) if raw else None
    except urllib.error.HTTPError as e:
        err = e.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"{method} {path} -> {e.code}: {err[:500]}") from e


def ensure_dir(path: str) -> None:
    parts = path.strip("/").split("/")
    cur = []
    for p in parts:
        cur.append(p)
        rel = "/".join(cur)
        try:
            info = http("GET", f"contents/{rel}")
            if info and info.get("type") == "directory":
                continue
        except RuntimeError:
            pass
        http("PUT", f"contents/{rel}", {"type": "directory"})
        print("mkdir", rel)


def upload_text(hub_path: str, text: str) -> None:
    http(
        "PUT",
        f"contents/{hub_path}",
        {"type": "file", "format": "text", "content": text},
    )
    print("upload text", hub_path, len(text))


def upload_bytes(hub_path: str, raw: bytes) -> None:
    http(
        "PUT",
        f"contents/{hub_path}",
        {
            "type": "file",
            "format": "base64",
            "content": base64.b64encode(raw).decode("ascii"),
        },
        timeout=600,
    )
    print("upload bin", hub_path, len(raw))


def upload_tree() -> None:
    ensure_dir(HUB_ROOT)
    ensure_dir(f"{HUB_ROOT}/inputs")
    ensure_dir(f"{HUB_ROOT}/outputs")
    ensure_dir(f"{HUB_ROOT}/notebooks")

    upload_text(f"{HUB_ROOT}/README.md", (LOCAL / "README.md").read_text(encoding="utf-8"))
    upload_text(
        f"{HUB_ROOT}/build_consumption_map_draft.py",
        (LOCAL / "build_consumption_map_draft.py").read_text(encoding="utf-8"),
    )
    upload_text(
        f"{HUB_ROOT}/render_consumption_map_html.py",
        (LOCAL / "render_consumption_map_html.py").read_text(encoding="utf-8"),
    )
    upload_text(
        f"{HUB_ROOT}/intersections.py",
        (LOCAL / "intersections.py").read_text(encoding="utf-8"),
    )
    upload_text(
        f"{HUB_ROOT}/magnit_pyaterochka.py",
        (LOCAL / "magnit_pyaterochka.py").read_text(encoding="utf-8"),
    )
    upload_text(
        f"{HUB_ROOT}/synthesis.py",
        (LOCAL / "synthesis.py").read_text(encoding="utf-8"),
    )
    upload_text(
        f"{HUB_ROOT}/mega_categories.py",
        (LOCAL / "mega_categories.py").read_text(encoding="utf-8"),
    )
    upload_text(
        f"{HUB_ROOT}/inputs/mcc_l1_crosswalk.csv",
        (LOCAL / "inputs" / "mcc_l1_crosswalk.csv").read_text(encoding="utf-8"),
    )
    upload_text(
        f"{HUB_ROOT}/inputs/scenario_mcc_bridge.csv",
        (LOCAL / "inputs" / "scenario_mcc_bridge.csv").read_text(encoding="utf-8"),
    )
    upload_text(
        f"{HUB_ROOT}/notebooks/consumption_map_runbook.ipynb",
        (LOCAL / "notebooks" / "consumption_map_runbook.ipynb").read_text(encoding="utf-8"),
    )

    inputs = {
        "prefs_samokat_audience.xlsx": DOWNLOADS
        / "Анализ предпочтений основной аудитории Самоката (1).xlsx",
        "prefs_magnit_pyaterochka_audience.xlsx": DOWNLOADS
        / "Анализ предпочтений основной аудитории Магнита и Пятерочки.xlsx",
        "offline_top_high_income.xlsx": DOWNLOADS
        / "ТОП offline ритейла у высокодоходных пользователей Сбера (3) (1).xlsx",
        "etalons_qnf.xlsx": DOWNLOADS / "Эталоны QNF 3.0 (05.08).xlsx",
        "scenarios_gmv_report.xlsx": SCENARIO_XLSX,
        "scenarios_descriptions_rooms.xlsx": Path(
            "/Users/hq-fvfgr2vpq05p/trash/.hub_cache/scenaries/Сценарии_описания_ml3_ml4_v9_extend_da_rooms.xlsx"
        ),
    }
    for name, src in inputs.items():
        if not src.exists():
            raise FileNotFoundError(src)
        upload_bytes(f"{HUB_ROOT}/inputs/{name}", src.read_bytes())


def run_build_on_hub() -> str:
    ks = http("GET", "kernels") or []
    kid = ks[0]["id"] if ks else http("POST", "kernels", {"name": "python3"})["id"]
    print("kernel", kid)

    ws_url = (
        f"wss://jupyterhub-ml-p02.samokat.ru/user/smalanin/api/kernels/{kid}/channels?"
        + urlencode({"token": TOKEN})
    )
    ws = create_connection(
        ws_url,
        timeout=180,
        header=[f"Authorization: token {TOKEN}"],
        sslopt=SSL_OPT,
    )

    code = r'''
import subprocess, sys, pathlib
base = pathlib.Path("/home/jovyan/data/consumption_map")
print("BASE", base, "exists", base.exists(), flush=True)
print("inputs", sorted(p.name for p in (base/"inputs").iterdir()), flush=True)
cmd = [
    sys.executable, str(base/"build_consumption_map_draft.py"),
    "--downloads", str(base/"inputs"),
    "--repo", str(base),  # scenarios looked up in inputs/ first via resolve
    "--out-dir", str(base/"outputs"),
    "--city", "Москва",
]
# Force scenario path: copy already in inputs/scenarios_gmv_report.xlsx
print("RUN", cmd, flush=True)
r = subprocess.run(cmd, cwd=str(base), capture_output=True, text=True)
print("rc", r.returncode, flush=True)
print(r.stdout, flush=True)
print(r.stderr, flush=True)
out = base/"outputs"/"consumption_map_draft.xlsx"
full = base/"outputs"/"consumption_map_draft_full.xlsx"
brief = base/"outputs"/"consumption_map_draft_brief.md"
print("OUT slim", out.exists(), out.stat().st_size if out.exists() else None, flush=True)
print("OUT full", full.exists(), full.stat().st_size if full.exists() else None, flush=True)
html = base/"outputs"/"consumption_map_report.html"
print("HTML", html.exists(), html.stat().st_size if html.exists() else None, flush=True)
print("BRIEF", brief.read_text(encoding="utf-8")[:1500] if brief.exists() else "missing", flush=True)
'''
    msg_id = str(uuid.uuid4())
    parent = {
        "header": {
            "msg_id": msg_id,
            "username": "smalanin",
            "session": str(uuid.uuid4()),
            "msg_type": "execute_request",
            "version": "5.3",
        },
        "parent_header": {},
        "metadata": {},
        "content": {
            "code": code,
            "silent": False,
            "store_history": False,
            "user_expressions": {},
            "allow_stdin": False,
            "stop_on_error": True,
        },
        "channel": "shell",
    }
    ws.send(json.dumps(parent))

    outputs: list[str] = []
    deadline = time.time() + 600
    while time.time() < deadline:
        ws.settimeout(30)
        try:
            raw = ws.recv()
        except Exception as e:
            print("ws recv", e)
            break
        if isinstance(raw, bytes):
            raw = raw.decode("utf-8", errors="replace")
        msg = json.loads(raw)
        mtype = msg.get("msg_type") or msg.get("header", {}).get("msg_type")
        parent_id = (msg.get("parent_header") or {}).get("msg_id")
        if parent_id and parent_id != msg_id:
            continue
        if mtype in ("stream",):
            outputs.append(msg["content"].get("text", ""))
            print(msg["content"].get("text", ""), end="")
        elif mtype == "error":
            outputs.append("\n".join(msg["content"].get("traceback", [])))
            print("ERROR", outputs[-1][:2000])
            break
        elif mtype == "execute_reply":
            print("execute_reply", msg["content"].get("status"))
            break
        elif mtype == "status" and msg["content"].get("execution_state") == "idle":
            # may arrive before reply; keep waiting for reply
            pass
    ws.close()
    return "".join(outputs)


def main() -> None:
    print("Uploading…")
    upload_tree()
    print("Running build on Hub…")
    run_build_on_hub()
    # verify listing
    listing = http("GET", f"contents/{HUB_ROOT}/outputs")
    names = [x["name"] for x in (listing or {}).get("content", [])]
    print("Hub outputs:", names)


if __name__ == "__main__":
    main()
