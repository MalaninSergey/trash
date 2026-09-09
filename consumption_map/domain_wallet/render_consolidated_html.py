#!/usr/bin/env python3
"""Interactive HTML table for consolidated RK×BG domain wallet export."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

try:
    from domain_wallet.export_domain_wallet_excel import (
        TITLE,
        build_cards_sheet,
        build_ml4_scenario_sheet,
        build_ml4_summary_sheet,
        build_scenario_summary_sheet,
    )
except ImportError:
    from export_domain_wallet_excel import (
        TITLE,
        build_cards_sheet,
        build_ml4_scenario_sheet,
        build_ml4_summary_sheet,
        build_scenario_summary_sheet,
    )

PKG = Path(__file__).resolve().parent
ROOT = PKG.parent
DEFAULT_PAYLOAD = ROOT / "outputs" / "domain_wallet_payload.json"
DEFAULT_HTML = ROOT / "outputs" / "domain_wallet_consolidated.html"

_NUM_COL_RE = re.compile(
    r"(GMV|Доля|Gap|n_|Эталон|Σ|п\.п\.|%,|₽)",
    re.I,
)


def _esc(s: object) -> str:
    return (
        str(s if s is not None else "")
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def _json(obj: object) -> str:
    return json.dumps(obj, ensure_ascii=False, default=str).replace("</", "<\\/")


def _df_to_records(df) -> tuple[list[str], list[list[object]]]:
    if df.empty:
        return [], []
    cols = [str(c) for c in df.columns]
    rows: list[list[object]] = []
    for rec in df.to_dict(orient="records"):
        rows.append([rec.get(c) for c in cols])
    return cols, rows


def _build_sheet_payload(assortment: dict, *, mcc_gap: dict[str, float] | None) -> dict:
    sheets = {
        "ML4×Сценарии": build_ml4_scenario_sheet(assortment, mcc_gap=mcc_gap),
        "ML4 свод": build_ml4_summary_sheet(assortment),
        "Сценарии свод": build_scenario_summary_sheet(assortment, mcc_gap=mcc_gap),
        "Карточки": build_cards_sheet(assortment),
    }
    out: dict[str, dict] = {}
    for name, df in sheets.items():
        cols, rows = _df_to_records(df)
        num_cols = [i for i, c in enumerate(cols) if _NUM_COL_RE.search(c)]
        out[name] = {"columns": cols, "rows": rows, "num_cols": num_cols}
    return out


def _rk_bg_index(assortment: dict) -> list[dict]:
    idx = assortment.get("rk_index") or []
    if idx:
        return [{"rk": str(x.get("rk") or ""), "bgs": [str(b) for b in (x.get("bgs") or [])]} for x in idx]
    cards = assortment.get("cards") or {}
    by_rk: dict[str, set[str]] = {}
    for card in cards.values():
        rk = str(card.get("rk") or "")
        bg = str(card.get("bg") or "")
        by_rk.setdefault(rk, set()).add(bg)
    return [{"rk": rk, "bgs": sorted(bgs)} for rk, bgs in sorted(by_rk.items())]


def render_consolidated_html(
    assortment: dict,
    out_path: Path,
    *,
    city: str = "Москва",
    variant: str = "default",
    mcc_gap: dict[str, float] | None = None,
) -> Path:
    """Write interactive consolidated table HTML."""
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    sheets = _build_sheet_payload(assortment, mcc_gap=mcc_gap)
    rk_index = _rk_bg_index(assortment)
    meta = {
        "title": TITLE,
        "city": city,
        "variant": variant,
        "note": str(assortment.get("note") or ""),
        "snapshot": assortment.get("snapshot_meta") or {},
    }
    payload = {"meta": meta, "rk_index": rk_index, "sheets": sheets}

    title = TITLE
    if variant == "no_marketplace":
        title += " · без маркетплейсов"

    html = f"""<!DOCTYPE html>
<html lang="ru">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>{_esc(title)} — таблица</title>
<link href="https://fonts.googleapis.com/css2?family=IBM+Plex+Sans:wght@400;500;600&family=IBM+Plex+Serif:wght@600&display=swap" rel="stylesheet"/>
<style>
  :root {{
    --bg:#f4f1eb; --ink:#1a1916; --muted:#5a554c; --line:#d9d2c4;
    --card:#fffcf6; --accent:#2a4a6b; --sber:#1a6b4a;
  }}
  * {{ box-sizing:border-box; }}
  body {{
    margin:0; font-family:"IBM Plex Sans",sans-serif; color:var(--ink);
    background: radial-gradient(ellipse 70% 40% at 0% 0%,#e4efe8,transparent 55%), var(--bg);
    line-height:1.45;
  }}
  .wrap {{ max-width:100%; margin:0 auto; padding:20px 16px 48px; }}
  h1 {{
    font-family:"IBM Plex Serif",Georgia,serif;
    font-size:clamp(1.2rem,2.5vw,1.65rem); margin:0 0 6px;
  }}
  .lede {{ color:var(--muted); margin:0 0 12px; font-size:0.92rem; max-width:920px; }}
  .toolbar {{
    display:flex; flex-wrap:wrap; gap:10px 14px; align-items:flex-end;
    margin:12px 0 10px; padding:12px 14px; background:var(--card);
    border:1px solid var(--line); border-radius:10px;
    position:sticky; top:0; z-index:10;
    box-shadow:0 2px 8px rgba(26,25,22,0.06);
  }}
  .field {{ display:flex; flex-direction:column; gap:4px; min-width:140px; }}
  .field.grow {{ flex:1 1 220px; min-width:200px; }}
  .field label {{ font-size:0.78rem; color:var(--muted); font-weight:500; }}
  .field select, .field input {{
    font:inherit; font-size:0.9rem; border:1px solid var(--line);
    background:#f3eee4; border-radius:8px; padding:7px 10px;
  }}
  .field select:focus, .field input:focus {{
    outline:2px solid var(--accent); outline-offset:1px;
  }}
  .tabs {{ display:flex; flex-wrap:wrap; gap:6px; margin:8px 0 10px; }}
  .tabs button {{
    font:inherit; font-size:0.85rem; border:1px solid var(--line);
    background:var(--card); border-radius:8px; padding:6px 12px; cursor:pointer;
  }}
  .tabs button.on {{ background:var(--accent); color:#fff; border-color:var(--accent); }}
  .status {{
    margin:0 0 8px; font-size:0.85rem; color:var(--muted);
    display:flex; flex-wrap:wrap; gap:8px 16px; align-items:center;
  }}
  .status b {{ color:var(--ink); }}
  .table-scroll {{
    overflow:auto; max-height:calc(100vh - 220px); min-height:320px;
    border:1px solid var(--line); border-radius:10px; background:var(--card);
    -webkit-overflow-scrolling:touch;
  }}
  table.data {{
    width:max-content; min-width:100%; border-collapse:separate; border-spacing:0;
    font-size:0.78rem;
  }}
  table.data th, table.data td {{
    padding:7px 10px; border-bottom:1px solid var(--line);
    vertical-align:middle; text-align:left; white-space:nowrap;
  }}
  table.data th {{
    position:sticky; top:0; z-index:3;
    background:#efe9df; font-size:0.68rem; font-weight:600;
    color:var(--muted); cursor:pointer; user-select:none;
  }}
  table.data th.sort-asc::after {{ content:" ▲"; font-size:0.6rem; }}
  table.data th.sort-desc::after {{ content:" ▼"; font-size:0.6rem; }}
  table.data th.sticky-col, table.data td.sticky-col {{
    position:sticky; left:0; z-index:2; background:var(--card);
    font-weight:600; box-shadow:1px 0 0 var(--line);
  }}
  table.data th.sticky-col-2, table.data td.sticky-col-2 {{
    position:sticky; left:var(--sticky2, 120px); z-index:2; background:var(--card);
    box-shadow:1px 0 0 var(--line);
  }}
  table.data th.sticky-col {{ z-index:4; background:#efe9df; }}
  table.data th.sticky-col-2 {{ z-index:4; background:#efe9df; }}
  table.data td.num {{ text-align:right; font-variant-numeric:tabular-nums; }}
  table.data tr:hover td {{ background:#f7f2ea; }}
  table.data tr:hover td.sticky-col,
  table.data tr:hover td.sticky-col-2 {{ background:#f0ebe3; }}
  .empty {{ padding:32px; text-align:center; color:var(--muted); }}
  .pill {{
    display:inline-block; padding:2px 8px; border-radius:999px;
    background:#e8efe9; color:var(--sber); font-size:0.78rem; font-weight:500;
  }}
  @media (max-width:720px) {{
    .table-scroll {{ max-height:calc(100vh - 280px); }}
  }}
</style>
</head>
<body>
<div class="wrap">
  <h1>{_esc(title)}</h1>
  <p class="lede">Интерактивная таблица карточек РК×БГ · {_esc(city)}. Фильтры по РК и бизнес-группе — в панели сверху.</p>
  <div class="tabs" id="sheetTabs"></div>
  <div class="toolbar">
    <div class="field">
      <label for="rkFilter">РК</label>
      <select id="rkFilter"><option value="">Все</option></select>
    </div>
    <div class="field">
      <label for="bgFilter">Бизнес-группа</label>
      <select id="bgFilter"><option value="">Все</option></select>
    </div>
    <div class="field grow">
      <label for="searchBox">Поиск (ML4, сценарий, домен…)</label>
      <input id="searchBox" type="search" placeholder="Начните вводить…" autocomplete="off"/>
    </div>
  </div>
  <div class="status">
    <span>Показано: <b id="rowCount">0</b> из <b id="rowTotal">0</b></span>
    <span class="pill" id="activeSheetLabel"></span>
  </div>
  <div class="table-scroll">
    <table class="data" id="dataTable">
      <thead id="tableHead"></thead>
      <tbody id="tableBody"></tbody>
    </table>
    <div class="empty" id="emptyMsg" hidden>Нет строк по выбранным фильтрам</div>
  </div>
</div>
<script>
const PAYLOAD = {_json(payload)};
</script>
<script>
(function () {{
  const sheets = PAYLOAD.sheets;
  const rkIndex = PAYLOAD.rk_index || [];
  const sheetNames = Object.keys(sheets);
  let activeSheet = sheetNames[0] || "";
  let sortCol = -1;
  let sortAsc = true;

  const tabsEl = document.getElementById("sheetTabs");
  const rkEl = document.getElementById("rkFilter");
  const bgEl = document.getElementById("bgFilter");
  const searchEl = document.getElementById("searchBox");
  const headEl = document.getElementById("tableHead");
  const bodyEl = document.getElementById("tableBody");
  const rowCountEl = document.getElementById("rowCount");
  const rowTotalEl = document.getElementById("rowTotal");
  const sheetLabelEl = document.getElementById("activeSheetLabel");
  const emptyEl = document.getElementById("emptyMsg");
  const tableEl = document.getElementById("dataTable");

  function esc(s) {{
    return String(s ?? "")
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }}

  function fmtCell(val, isNum) {{
    if (val === null || val === undefined || val === "") return "";
    if (typeof val === "number") {{
      if (!Number.isFinite(val)) return "";
      if (Math.abs(val) >= 1e6) return val.toLocaleString("ru-RU", {{ maximumFractionDigits: 0 }});
      if (Number.isInteger(val)) return val.toLocaleString("ru-RU");
      return val.toLocaleString("ru-RU", {{ maximumFractionDigits: 4 }});
    }}
    return esc(val);
  }}

  function allRks() {{
    const set = new Set();
    rkIndex.forEach(x => set.add(x.rk));
    sheetNames.forEach(name => {{
      const cols = sheets[name].columns;
      const iRk = cols.indexOf("РК");
      if (iRk < 0) return;
      sheets[name].rows.forEach(r => {{ if (r[iRk]) set.add(String(r[iRk])); }});
    }});
    return [...set].sort((a, b) => a.localeCompare(b, "ru"));
  }}

  function bgsForRk(rk) {{
    if (!rk) {{
      const set = new Set();
      rkIndex.forEach(x => x.bgs.forEach(b => set.add(b)));
      sheetNames.forEach(name => {{
        const cols = sheets[name].columns;
        const iBg = cols.indexOf("БГ");
        if (iBg < 0) return;
        sheets[name].rows.forEach(r => {{ if (r[iBg]) set.add(String(r[iBg])); }});
      }});
      return [...set].sort((a, b) => a.localeCompare(b, "ru"));
    }}
    const hit = rkIndex.find(x => x.rk === rk);
    if (hit) return [...hit.bgs].sort((a, b) => a.localeCompare(b, "ru"));
    const set = new Set();
    sheetNames.forEach(name => {{
      const cols = sheets[name].columns;
      const iRk = cols.indexOf("РК");
      const iBg = cols.indexOf("БГ");
      if (iRk < 0 || iBg < 0) return;
      sheets[name].rows.forEach(r => {{
        if (String(r[iRk]) === rk && r[iBg]) set.add(String(r[iBg]));
      }});
    }});
    return [...set].sort((a, b) => a.localeCompare(b, "ru"));
  }}

  function fillSelect(el, values, current) {{
    const opts = ['<option value="">Все</option>'].concat(
      values.map(v => `<option value="${{esc(v)}}">${{esc(v)}}</option>`)
    );
    el.innerHTML = opts.join("");
    if (current && values.includes(current)) el.value = current;
  }}

  function initTabs() {{
    tabsEl.innerHTML = sheetNames.map(name =>
      `<button type="button" data-sheet="${{esc(name)}}">${{esc(name)}}</button>`
    ).join("");
    tabsEl.querySelectorAll("button").forEach(btn => {{
      btn.addEventListener("click", () => {{
        activeSheet = btn.dataset.sheet;
        sortCol = -1;
        sortAsc = true;
        render();
      }});
    }});
  }}

  function compare(a, b, col, numCols) {{
    const va = a[col];
    const vb = b[col];
    const isNum = numCols.includes(col);
    if (va === vb) return 0;
    if (va === null || va === undefined || va === "") return 1;
    if (vb === null || vb === undefined || vb === "") return -1;
    if (isNum) {{
      const na = Number(va);
      const nb = Number(vb);
      if (!Number.isNaN(na) && !Number.isNaN(nb)) return na - nb;
    }}
    return String(va).localeCompare(String(vb), "ru");
  }}

  function filteredRows() {{
    const sheet = sheets[activeSheet];
    if (!sheet) return {{ rows: [], cols: [], numCols: [] }};
    const {{ columns: cols, rows, num_cols: numCols }} = sheet;
    const iRk = cols.indexOf("РК");
    const iBg = cols.indexOf("БГ");
    const rk = rkEl.value;
    const bg = bgEl.value;
    const q = searchEl.value.trim().toLowerCase();
    let out = rows.filter(r => {{
      if (rk && iRk >= 0 && String(r[iRk]) !== rk) return false;
      if (bg && iBg >= 0 && String(r[iBg]) !== bg) return false;
      if (q) {{
        const hay = r.map(v => String(v ?? "").toLowerCase()).join(" ");
        if (!hay.includes(q)) return false;
      }}
      return true;
    }});
    if (sortCol >= 0) {{
      out = out.slice().sort((a, b) => {{
        const c = compare(a, b, sortCol, numCols);
        return sortAsc ? c : -c;
      }});
    }}
    return {{ rows: out, cols, numCols }};
  }}

  function renderHead(cols, numCols) {{
    const iRk = cols.indexOf("РК");
    const iBg = cols.indexOf("БГ");
    headEl.innerHTML = "<tr>" + cols.map((c, i) => {{
      let cls = "";
      if (i === iRk) cls = "sticky-col";
      else if (i === iBg) cls = "sticky-col-2";
      if (sortCol === i) cls += sortAsc ? " sort-asc" : " sort-desc";
      return `<th class="${{cls}}" data-col="${{i}}">${{esc(c)}}</th>`;
    }}).join("") + "</tr>";
    headEl.querySelectorAll("th").forEach(th => {{
      th.addEventListener("click", () => {{
        const col = Number(th.dataset.col);
        if (sortCol === col) sortAsc = !sortAsc;
        else {{ sortCol = col; sortAsc = true; }}
        renderBodyOnly();
      }});
    }});
    requestAnimationFrame(updateSticky2);
  }}

  function updateSticky2() {{
    const thRk = headEl.querySelector("th.sticky-col");
    if (thRk) {{
      const w = Math.ceil(thRk.getBoundingClientRect().width);
      document.documentElement.style.setProperty("--sticky2", w + "px");
    }}
  }}

  function renderBodyOnly() {{
    const {{ rows, cols, numCols }} = filteredRows();
    rowCountEl.textContent = rows.length.toLocaleString("ru-RU");
    rowTotalEl.textContent = (sheets[activeSheet]?.rows.length || 0).toLocaleString("ru-RU");
    if (!rows.length) {{
      bodyEl.innerHTML = "";
      tableEl.hidden = true;
      emptyEl.hidden = false;
      return;
    }}
    tableEl.hidden = false;
    emptyEl.hidden = true;
    const iRk = cols.indexOf("РК");
    const iBg = cols.indexOf("БГ");
    bodyEl.innerHTML = rows.map(r =>
      "<tr>" + cols.map((_, i) => {{
        let cls = numCols.includes(i) ? "num" : "";
        if (i === iRk) cls += " sticky-col";
        else if (i === iBg) cls += " sticky-col-2";
        return `<td class="${{cls.trim()}}">${{fmtCell(r[i], numCols.includes(i))}}</td>`;
      }}).join("") + "</tr>"
    ).join("");
  }}

  function render() {{
    tabsEl.querySelectorAll("button").forEach(btn => {{
      btn.classList.toggle("on", btn.dataset.sheet === activeSheet);
    }});
    sheetLabelEl.textContent = activeSheet;
    const sheet = sheets[activeSheet];
    if (!sheet) return;
    renderHead(sheet.columns, sheet.num_cols);
    renderBodyOnly();
  }}

  function onRkChange() {{
    const prevBg = bgEl.value;
    fillSelect(bgEl, bgsForRk(rkEl.value), prevBg);
    renderBodyOnly();
  }}

  fillSelect(rkEl, allRks(), "");
  fillSelect(bgEl, bgsForRk(""), "");
  rkEl.addEventListener("change", onRkChange);
  bgEl.addEventListener("change", renderBodyOnly);
  searchEl.addEventListener("input", renderBodyOnly);
  window.addEventListener("resize", updateSticky2);

  initTabs();
  render();
}})();
</script>
</body>
</html>"""

    out_path.write_text(html, encoding="utf-8")
    return out_path


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Render interactive consolidated domain wallet HTML table")
    ap.add_argument("--payload", default=str(DEFAULT_PAYLOAD))
    ap.add_argument("--out", default=str(DEFAULT_HTML))
    args = ap.parse_args()
    payload = json.loads(Path(args.payload).read_text(encoding="utf-8"))
    assortment = payload.get("assortment") or {}
    gap_map = {
        str(r.get("mcc_group") or "").strip(): float(r.get("gap_pp") or 0.0)
        for r in payload.get("master") or []
        if str(r.get("mcc_group") or "").strip()
    }
    out = render_consolidated_html(
        assortment,
        Path(args.out),
        city=str(payload.get("city") or "Москва"),
        variant=str(payload.get("variant") or ""),
        mcc_gap=gap_map,
    )
    print(f"Wrote {out}")
