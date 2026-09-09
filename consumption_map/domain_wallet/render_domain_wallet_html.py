#!/usr/bin/env python3
"""Render domain_wallet HTML with bars, domain card, assortment."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

PKG = Path(__file__).resolve().parent
ROOT = PKG.parent
DEFAULT_PAYLOAD = ROOT / "outputs" / "domain_wallet_payload.json"
DEFAULT_HTML = ROOT / "outputs" / "domain_wallet_report.html"
MOSCOW = "Москва"
_CITY_NOTE_RE = re.compile(r"^Grocery · [^:]+:\s*")

PALETTE = [
    "#1a6b4a", "#c45c26", "#2a4a6b", "#8b2e2e", "#5b7c3a",
    "#6b4c9a", "#b08900", "#3d7ea6", "#9a4a6a", "#4a6b5c",
    "#d4763a", "#2f5d50", "#7a5c3a", "#4a5a8a", "#8a6a2a", "#5a7a8a",
]


def _shade(hex_color: str, factor: float) -> str:
    h = hex_color.lstrip("#")
    if len(h) != 6:
        return hex_color
    rgb = [int(h[i : i + 2], 16) for i in (0, 2, 4)]
    if factor >= 0:
        out = [round(c + (255 - c) * factor) for c in rgb]
    else:
        out = [round(c * (1 + factor)) for c in rgb]
    return "#" + "".join(f"{max(0, min(255, c)):02x}" for c in out)


def _esc(s) -> str:
    return (
        str(s if s is not None else "")
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def _json(obj) -> str:
    return json.dumps(obj, ensure_ascii=False, default=str).replace("</", "<\\/")


def _sanitize_mp_note(note: str | None) -> str:
    """Drop geography from grocery callout copy (Moscow-only, silent)."""
    if not note:
        return ""
    return _CITY_NOTE_RE.sub("Grocery · ", str(note))


def _moscow_slice(p: dict) -> dict:
    """Bake Moscow-only data; no city switcher / labels in UI."""
    by_city = p.get("by_city") or {}
    default_city = p.get("city") or MOSCOW
    if not by_city:
        mp = dict(p.get("mp_grocery") or {})
        if mp.get("note"):
            mp["note"] = _sanitize_mp_note(mp.get("note"))
        return {
            "coverage": p.get("coverage"),
            "master": p.get("master") or [],
            "sber_wallet": p.get("sber_wallet") or [],
            "samokat_leaves": p.get("samokat_leaves") or [],
            "mp_grocery": mp,
            "bridge_mission_to_mcc": p.get("bridge_mission_to_mcc") or {},
            "bridge_mcc_to_missions": p.get("bridge_mcc_to_missions") or {},
        }
    key = MOSCOW if MOSCOW in by_city else (
        default_city if default_city in by_city else next(iter(by_city))
    )
    slice_ = dict(by_city[key])
    mp = dict(slice_.get("mp_grocery") or {})
    if mp.get("note"):
        mp["note"] = _sanitize_mp_note(mp.get("note"))
    slice_["mp_grocery"] = mp
    return slice_


def render_html(payload_path: Path, html_path: Path, *, include_mp: bool = True) -> None:
    p = json.loads(payload_path.read_text(encoding="utf-8"))
    data_slice = _moscow_slice(p)

    _mp_keys = (
        "magnit_off_wallet_share",
        "pyat_off_wallet_share",
        "magnit_off_retail_gmv",
        "pyat_off_retail_gmv",
        "magnit_off_share_of_mcc",
        "pyat_off_share_of_mcc",
    )
    if not include_mp:
        master = []
        for row in data_slice.get("master") or []:
            master.append({k: v for k, v in row.items() if k not in _mp_keys})
        data_slice = {
            **data_slice,
            "master": master,
            "mp_grocery": {},
        }

    grocery_block = ""
    mp_caveat = ""
    footer_extra = ""
    if include_mp:
        grocery_block = """
    <div class="callout mp" id="groceryMpBlock">
      <h2>Магнит / Пятёрочка · grocery</h2>
      <p class="note" id="groceryMpNote" style="margin:0 0 4px"></p>
      <div class="grocery-mp" id="groceryMpTiles"></div>
    </div>"""
        mp_caveat = (
            '<li><strong>Магнит / 5ка</strong> — отдельные когорты оффлайн; '
            "доля MCC в их кошельке — контекст, не gap. Не суммировать.</li>"
        )
        footer_extra = " · Магнит/5ка"

    title = "Справочник сценариев и категорий"
    variant = str(p.get("variant") or "default")
    if variant == "no_marketplace":
        title += " · без маркетплейсов"
    if not include_mp:
        title += " (без Магнит/5ка)"

    html = f"""<!DOCTYPE html>
<html lang="ru">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>{_esc(title)}</title>
<link href="https://fonts.googleapis.com/css2?family=IBM+Plex+Sans:wght@400;500;600&family=IBM+Plex+Serif:wght@600&display=swap" rel="stylesheet"/>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.1/dist/chart.umd.min.js"></script>
<script src="https://cdn.jsdelivr.net/npm/chartjs-plugin-datalabels@2.2.0/dist/chartjs-plugin-datalabels.min.js"></script>
<style>
  :root {{
    --bg:#f4f1eb; --ink:#1a1916; --muted:#5a554c; --line:#d9d2c4;
    --card:#fffcf6; --sber:#1a6b4a; --smkt:#c45c26; --hot:#8b2e2e; --accent:#2a4a6b;
  }}
  * {{ box-sizing:border-box; }}
  body {{
    margin:0; font-family:"IBM Plex Sans",sans-serif; color:var(--ink);
    background: radial-gradient(ellipse 70% 40% at 0% 0%,#e4efe8,transparent 55%), var(--bg);
    line-height:1.45;
  }}
  .wrap {{ max-width:1280px; margin:0 auto; padding:28px 20px 72px; }}
  h1 {{ font-family:"IBM Plex Serif",Georgia,serif; font-size:clamp(1.45rem,3vw,1.95rem); margin:0 0 8px; }}
  h2 {{ font-family:"IBM Plex Serif",Georgia,serif; font-size:1.22rem; margin:0 0 6px; }}
  .lede,.note {{ color:var(--muted); margin:0 0 12px; }}
  section {{ margin:36px 0 0; }}
  .toolbar {{
    display:flex; flex-wrap:wrap; gap:10px; align-items:center;
    margin:12px 0 18px; padding:10px 12px; background:var(--card);
    border:1px solid var(--line); border-radius:10px;
  }}
  .toolbar label {{ font-size:0.85rem; color:var(--muted); }}
  .toolbar select, .toolbar button {{
    font:inherit; font-size:0.9rem; border:1px solid var(--line);
    background:#f3eee4; border-radius:8px; padding:6px 10px; cursor:pointer;
  }}
  .toolbar button.on {{ background:var(--accent); color:#fff; border-color:var(--accent); }}
  .callout {{
    background:var(--card); border-left:4px solid var(--hot);
    border-radius:0 10px 10px 0; padding:14px 18px; margin:12px 0;
  }}
  .pies {{ display:grid; grid-template-columns:1fr 1fr; gap:14px; margin:12px 0; }}
  @media (max-width:860px) {{ .pies {{ grid-template-columns:1fr; }} }}
  .pie-card, .chart-card {{
    background:var(--card); border:1px solid var(--line); border-radius:12px;
    padding:12px 14px 10px; display:flex; flex-direction:column;
  }}
  .pie-card h3, .chart-card h3 {{ margin:0 0 4px; font-size:1rem; }}
  .pie-canvas-wrap {{ position:relative; height:300px; }}
  .bar-wrap {{ position:relative; height:420px; }}
  .domain-legend {{
    display:flex; flex-wrap:wrap; gap:6px 10px; margin-top:8px;
    font-size:0.72rem; color:var(--muted); max-height:64px; overflow:auto;
  }}
  .domain-legend span {{ display:inline-flex; align-items:center; gap:5px; white-space:nowrap; }}
  .domain-legend i {{ width:10px; height:10px; border-radius:2px; display:inline-block; }}
  .hint {{
    min-height:2.2em; font-size:0.88rem; color:var(--muted); margin:8px 0 10px;
    padding:8px 10px; background:#f3eee4; border-radius:8px;
  }}
  .card {{
    background:var(--card); border:1px solid var(--line); border-radius:12px;
    padding:14px 16px; margin:12px 0; min-height:120px;
  }}
  .card.empty {{ color:var(--muted); }}
  .card h3 {{ margin:0 0 6px; font-size:1.05rem; }}
  .card .meta {{ display:flex; flex-wrap:wrap; gap:10px 16px; font-size:0.9rem; margin:8px 0 10px; }}
  .card .meta b {{ color:var(--ink); }}
  .card ul {{ margin:6px 0 0; padding-left:1.2em; }}
  .card li {{ margin:3px 0; font-size:0.9rem; }}
  .table-scroll {{
    overflow-x:auto; -webkit-overflow-scrolling:touch;
    border:1px solid var(--line); border-radius:10px; background:var(--card);
  }}
  table.gaps {{
    width:max-content; min-width:100%; border-collapse:separate; border-spacing:0;
    font-size:0.78rem; background:var(--card);
  }}
  table.gaps th, table.gaps td {{
    padding:8px 10px; border-bottom:1px solid var(--line);
    vertical-align:middle; text-align:left;
  }}
  table.gaps th {{
    position:sticky; top:0; z-index:2;
    background:#efe9df; font-size:0.68rem; font-weight:600;
    text-transform:none; letter-spacing:0; color:var(--muted);
    white-space:nowrap; line-height:1.25;
  }}
  table.gaps th .sub {{ display:block; font-weight:400; font-size:0.62rem; opacity:0.85; }}
  table.gaps td.domain {{
    position:sticky; left:0; z-index:1; background:var(--card);
    font-weight:600; min-width:11rem; max-width:18rem;
  }}
  table.gaps tr.hot td.domain {{ background:#fbf3f0; }}
  table.gaps tr.clickable:hover td.domain {{ background:#f0ebe3; }}
  table.gaps .num {{ text-align:right; font-variant-numeric:tabular-nums; white-space:nowrap; }}
  table.gaps .concl {{
    min-width:14rem; max-width:22rem; color:var(--ink);
    white-space:nowrap; overflow:hidden; text-overflow:ellipsis;
  }}
  .tag {{
    display:inline-block; margin-left:6px; padding:1px 6px;
    border:1px solid #8a9a8a; border-radius:3px;
    font-size:0.68rem; font-weight:600; color:#4a5a4a; background:#f2f5f2;
    vertical-align:middle; white-space:nowrap;
  }}
  .tag.merge {{ border-color:#b07a5a; color:#8a4020; background:#fbf3f0; }}
  .muted {{ color:var(--muted); font-size:0.82rem; }}
  .pos {{ color:var(--hot); font-weight:600; }}
  .neg {{ color:var(--sber); }}
  tr.hot {{ background:#fbf3f0; }}
  tr.clickable {{ cursor:pointer; }}
  tr.clickable:hover {{ background:#f0ebe3; }}
  tr.selected {{ outline:2px solid var(--accent); outline-offset:-2px; }}
  .caveats {{ background:var(--card); border:1px solid var(--line); border-radius:10px; padding:16px 18px; }}
  .caveats li {{ margin:6px 0; color:var(--muted); }}
  .mp-box {{
    margin-top:12px; padding:10px 12px; background:#f3eee4; border-radius:8px;
    border-left:3px solid var(--accent);
  }}
  .mp-box h4 {{ margin:0 0 6px; font-size:0.95rem; }}
  .grocery-mp {{
    display:grid; gap:10px; grid-template-columns:repeat(auto-fit,minmax(200px,1fr));
    margin-top:10px;
  }}
  .grocery-mp .tile {{
    background:var(--card); border:1px solid var(--line); border-radius:10px; padding:12px 14px;
  }}
  .grocery-mp .tile b {{ display:block; font-size:1.1rem; margin:4px 0; }}
  .grocery-mp .tile .lbl {{ color:var(--muted); font-size:0.85rem; }}
  .callout.mp {{ border-left-color:var(--accent); }}
  .bg-chips {{ display:flex; flex-wrap:wrap; gap:6px; align-items:center; }}
  .bg-chips button {{
    font:inherit; font-size:0.85rem; border:1px solid var(--line);
    background:#f3eee4; border-radius:8px; padding:6px 10px; cursor:pointer;
  }}
  .bg-chips button.on {{ background:var(--accent); color:#fff; border-color:var(--accent); }}
  .km-search {{
    font:inherit; font-size:0.9rem; border:1px solid var(--line);
    background:#fff; border-radius:8px; padding:6px 10px; min-width:220px;
  }}
  .toolbar label.filter-check {{
    display:inline-flex; align-items:center; gap:6px;
    color:var(--ink); cursor:pointer; user-select:none; white-space:nowrap;
  }}
  .toolbar label.filter-check input {{ accent-color:var(--accent); }}
  .km-meta {{ display:flex; flex-wrap:wrap; gap:8px 16px; font-size:0.9rem; margin:8px 0 12px; }}
  .km-meta b {{ color:var(--ink); }}
  .block-title {{
    font-size:0.95rem; font-weight:600; margin:16px 0 8px; color:var(--ink);
  }}
  .block-title:first-of-type {{ margin-top:4px; }}
  .block-note {{ font-size:0.78rem; color:var(--muted); margin:0 0 8px; }}
  .mega-pie-wrap {{
    display:grid; grid-template-columns: minmax(160px,220px) 1fr; gap:12px;
    align-items:start; margin:8px 0 16px;
  }}
  @media (max-width:720px) {{
    .mega-pie-wrap {{ grid-template-columns:1fr; }}
  }}
  .mega-list {{
    display:flex; flex-direction:column; gap:4px; max-height:280px; overflow:auto;
  }}
  .mega-list button {{
    font:inherit; font-size:0.8rem; text-align:left; border:1px solid var(--line);
    background:#f3eee4; border-radius:8px; padding:6px 8px; cursor:pointer;
  }}
  .mega-list button.on {{ background:var(--accent); color:#fff; border-color:var(--accent); }}
  .mega-list button .sub {{ display:block; font-size:0.68rem; opacity:0.85; margin-top:2px; }}
  .mega-pie-card {{
    background:#f7f4ee; border:1px solid var(--line); border-radius:10px; padding:8px 10px 4px;
  }}
  .mega-pie-card h4 {{ margin:0 0 4px; font-size:0.88rem; }}
  .mega-pie-canvas-wrap {{ position:relative; height:260px; }}
  .mega-pie-legend {{
    display:flex; flex-wrap:wrap; gap:4px 10px; font-size:0.7rem; color:var(--muted);
    margin:4px 0 6px; max-height:72px; overflow:auto;
  }}
  .mega-pie-legend span {{ white-space:nowrap; }}
  .mega-pie-legend i {{
    display:inline-block; width:8px; height:8px; border-radius:2px; margin-right:3px;
  }}
  table.scen {{
    width:100%; border-collapse:separate; border-spacing:0; font-size:0.8rem;
  }}
  table.scen th, table.scen td {{
    padding:7px 8px; border-bottom:1px solid var(--line); vertical-align:top; text-align:left;
  }}
  table.scen th {{
    background:#efe9df; font-size:0.68rem; font-weight:600; color:var(--muted);
    white-space:nowrap;
  }}
  table.scen .num {{ text-align:right; font-variant-numeric:tabular-nums; white-space:nowrap; }}
  table.scen tr.expandable {{ cursor:pointer; }}
  table.scen tr.expandable:hover {{ background:#f0ebe3; }}
  table.scen tr.open {{ background:#eef3f0; }}
  table.scen tr.detail td {{ background:#f7f4ee; padding:8px 10px 14px; }}
  table.scen tr.detail .scen-block {{
    margin:10px 0 14px; padding-bottom:10px; border-bottom:1px dashed #e0d8c8;
  }}
  table.scen tr.detail .scen-block:last-child {{ border-bottom:none; margin-bottom:0; }}
  table.scen tr.detail .scen-toggle {{
    cursor:pointer; user-select:none; margin:0 0 6px; display:flex; gap:6px; align-items:flex-start;
  }}
  table.scen tr.detail .scen-toggle:hover {{ color:var(--ink); }}
  table.scen tr.detail .scen-toggle .chev {{
    flex:0 0 auto; color:var(--accent); font-size:0.75rem; line-height:1.4; width:0.9em;
  }}
  table.scen tr.detail .scen-block.open .scen-toggle {{ color:var(--ink); }}
  table.ml4 tr.focus-ml4 {{ background:#e8f0ea; font-weight:600; }}
  table.ml4 tr.this-bg {{ background:#eef3f0; }}
  table.ml4 tr.other-bg {{ color:var(--muted); }}
  table.ml4 {{ width:100%; border-collapse:collapse; font-size:0.74rem; }}
  table.ml4 th, table.ml4 td {{
    padding:4px 6px; border-bottom:1px solid #e6dfd2; text-align:left;
  }}
  table.ml4 th {{ color:var(--muted); font-size:0.65rem; }}
  table.ml4 .num {{ text-align:right; font-variant-numeric:tabular-nums; }}
  table.ml4 tr.lost {{ color:var(--muted); }}
  .ml4-head {{ font-size:0.82rem; color:var(--muted); margin:0 0 6px; }}
  .pill-this-bg {{
    display:inline-block; font-size:0.65rem; color:var(--accent);
    border:1px solid #c5d4c8; border-radius:3px; padding:0 4px; margin-left:4px;
    background:#e8f0ea; font-weight:600;
  }}
  details.unused {{ margin-top:12px; }}
  details.unused summary {{ cursor:pointer; color:var(--muted); }}
  .pill-unused {{
    display:inline-block; font-size:0.68rem; color:var(--muted);
    border:1px solid var(--line); border-radius:4px; padding:1px 5px; margin-left:4px;
  }}
  th.sortable {{ cursor:pointer; user-select:none; white-space:nowrap; }}
  th.sortable:hover {{ color:var(--ink); }}
  th.sortable .sort-ind {{ font-size:0.72em; opacity:0.55; margin-left:2px; }}
  th.sortable.active .sort-ind {{ opacity:1; color:var(--accent); }}
  footer {{ margin-top:36px; padding-top:12px; border-top:1px solid var(--line); color:var(--muted); font-size:0.85rem; }}
</style>
</head>
<body>
<div class="wrap">
  <header>
    <h1>Справочник сценариев и категорий</h1>
    <p class="lede">
      Домены Сбера (gmv) × листовые сценарии Самоката (1 сценарий → 1 домен).
      Implied wallet, не user-level join.
      {('<strong>Вариант без Маркетплейсов</strong>: домен исключён, gift-сценарии перенесены.' if variant == 'no_marketplace' else '')}
    </p>
{grocery_block}
  </header>

  <section>
    <h2>Сравнение долей (bar)</h2>
    <p class="note">Рядом: доля Сбера и implied-доля Самоката по домену. Карточка ассортимента ниже — по РК и бизнес-группе, не по MCC.</p>
    <div class="chart-card">
      <div class="bar-wrap"><canvas id="chartBars"></canvas></div>
    </div>
    <h2 style="margin-top:22px">Сравнение долей · без продуктовых</h2>
    <p class="note">Тот же bar без домена «Продуктовые магазины» (доли как в полном кошельке, без перенормировки).</p>
    <div class="chart-card">
      <div class="bar-wrap"><canvas id="chartBarsNoGrocery"></canvas></div>
    </div>
  </section>

  <section>
    <h2>Структура кошельков (pie)</h2>
    <p class="note">Справа сценарии сгруппированы по домену (рядом, оттенки). Hover на Сбере подсвечивает всю группу Самоката.</p>
    <div class="hint" id="hoverHint">Наведите на сегмент pie</div>
    <div class="pies">
      <div class="pie-card">
        <h3>Сбер · домены</h3>
        <div class="pie-canvas-wrap"><canvas id="pieSber"></canvas></div>
        <div class="domain-legend" id="legendSber"></div>
      </div>
      <div class="pie-card">
        <h3>Самокат · сценарии</h3>
        <div class="pie-canvas-wrap"><canvas id="pieSmkt"></canvas></div>
        <div class="domain-legend" id="legendSmkt"></div>
      </div>
    </div>
  </section>

  <section>
    <h2>Карточка ассортимента · РК / БГ</h2>
    <p class="note" id="assortNote">Сценарии и эталон NEW в разрезе руководителя категории и бизнес-группы.</p>
    <div class="toolbar">
      <label>РК
        <select id="rkSelect"></select>
      </label>
      <div class="bg-chips" id="bgChips"></div>
      <input class="km-search" id="scenSearch" type="search" placeholder="Поиск ML4 / сценария / домена"/>
      <label class="filter-check"><input type="checkbox" id="hideZeroEtalon" checked/> Скрыть категории с эталоном 0</label>
    </div>
    <div class="card empty" id="domainCard">Выберите РК и бизнес-группу.</div>
  </section>

  <section>
    <h2>Недоборы</h2>
    <p class="note" id="gapDef">{_esc(p.get('gap_definition'))}</p>
    <div class="table-scroll">
    <table class="gaps" id="gapsTable">
      <thead id="gapsHead"></thead>
      <tbody id="gapBody"></tbody>
    </table>
    </div>
    <p class="note" id="etalonPool"></p>
  </section>

  <section>
    <h2>Как читать</h2>
    <div class="caveats">
      <ul>
        <li><strong>1:1</strong> — сценарий не делится между доменами.</li>
        <li><strong>₽/клиент</strong> — Сбер: smkt_gmv / клиенты Самоката в Сбере (не ARPPU внутри MCC), месяц ÷{int(p.get('period_months_sber') or 12)}; Самокат: GMV сценариев / national_users периода, месяц ÷{int(p.get('period_months_smkt') or 6)}.</li>
        <li><strong>Слияние / неразделимо</strong> — «слияние» у смешанных сценариев (одежда+обувь и т.п.); у остальных «неразделимо» (1 сценарий → 1 MCC без разрезания).</li>
        <li><strong>Эталон</strong> — SKU NEW, эксклюзивно: каждая категория только в одном сценарии (как в scenarios_with_etalon.xlsx). Колонки 15 мин / МАКС / сумма. Σ по доменам = эталон всех сценариев Excel; отдельно — категории вне сценариев.</li>
        <li><strong>Карточка КМ</strong> — РК → бизнес-группа. РК «food» = FMCG с QNF=0. Pie: мегасценарий → доли ML4. Таблицы: ML4→сценарии и сценарии→ML4. Эталон в сценарии — отдельно 15 мин и МАКС (эксклюзив).</li>
        <li><strong>Сценарии</strong> — полная таблица долей в xlsx «Сценарии_доли» рядом с HTML.</li>
        {mp_caveat}
      </ul>
    </div>
  </section>

  <footer>domain_wallet · prefs gmv · Scenario_Aggregates · leaf-bridge · etalons NEW{footer_extra}</footer>
</div>

<script>
Chart.register(ChartDataLabels);

const INCLUDE_MP = {_json(include_mp)};
const DATA = {_json(data_slice)};
const PALETTE = {_json(PALETTE)};
const ETALON_POOL = {_json(p.get('etalon_pool') or {})};
const ASSORTMENT = {_json(p.get('assortment') or {})};

let pieSber, pieSmkt, chartBars, chartBarsNoGrocery;
let selectedRk = null;
let selectedBg = null;
let expandedMission = null;
let expandedLvl4 = null;
let expandedMl4Missions = new Set();
let selectedMega = null;
let assortPieChart = null;
let scenSort = {{ key: 'gmv', type: 'num', dir: -1 }};
let unusedSort = {{ key: 'etalon_sum', type: 'num', dir: -1 }};
let ml4Sort = {{ key: 'etalon_sum', type: 'num', dir: -1 }};
let ml4IndexSort = {{ key: 'gmv_proxy', type: 'num', dir: -1 }};
let gapSort = {{ key: 'gap', type: 'num', dir: -1 }};

function normCat(s) {{
  return String(s || '').trim().toLowerCase().replace(/ё/g, 'е').replace(/\\s+/g, ' ');
}}
function allocateGmv(gmv, weights) {{
  const n = weights.length;
  if (!n) return [];
  const w = weights.map(x => Math.max(Number(x) || 0, 0));
  const total = w.reduce((a, b) => a + b, 0);
  if (total <= 0) {{
    const share = (Number(gmv) || 0) / n;
    return w.map(() => share);
  }}
  const g = Number(gmv) || 0;
  return w.map(x => g * (x / total));
}}
function scenarioByMission(data, mission) {{
  return (data.scenarios || []).find(s => s.mission === mission) || null;
}}
function scenarioMl4Rows(s) {{
  // Full scenario composition for expand; fall back to BG-scoped ml4.
  const all = s && s.ml4_all;
  if (all && all.length) return all.slice();
  return ((s && s.ml4) || []).slice();
}}
function ml4GmvSplit(s, focusLvl4) {{
  const rows = scenarioMl4Rows(s);
  // Prefer precomputed gmv_ml4 from payload; else split scenario GMV by full etalon.
  const hasMl4 = rows.some(m => m.gmv_ml4 != null && !isNaN(Number(m.gmv_ml4)));
  const allocs = hasMl4
    ? rows.map(m => Number(m.gmv_ml4) || 0)
    : allocateGmv(s.gmv, rows.map(m => etalonFullSum(m)));
  const totalAlloc = allocs.reduce((a, b) => a + (Number(b) || 0), 0);
  const focus = normCat(focusLvl4);
  return rows.map((m, i) => ({{
    ...m,
    gmv_allocated: allocs[i] || 0,
    gmv_share: (totalAlloc ? (allocs[i] || 0) / totalAlloc : 0),
    is_focus: focusLvl4 != null && normCat(m.lvl4) === focus,
  }}));
}}
function ml4RowClass(m) {{
  const parts = [];
  if (m.is_focus) parts.push('focus-ml4');
  else if (m.in_this_bg) parts.push('this-bg');
  else if (m.in_this_bg === false) parts.push('other-bg');
  if (!m.exclusive && !m.is_focus) parts.push('lost');
  return parts.join(' ');
}}
function ml4OwnerCells(m) {{
  return `<td>${{m.rk||'—'}}</td><td>${{m.bg||'—'}}</td>`;
}}
function ml4Badge(m) {{
  if (m.is_focus) return ' · эта';
  if (m.in_this_bg) return '<span class="pill-this-bg">эта БГ</span>';
  return '';
}}
function etalonFullSum(m) {{
  if (m && m.etalon_full_sum != null && !isNaN(Number(m.etalon_full_sum))) {{
    return Number(m.etalon_full_sum) || 0;
  }}
  return Number(m && m.etalon_sum) || 0;
}}
function hasEtalonSku(m) {{
  // Category has etalon width if full Σ > 0 (share may round to 0 in a tiny scenario).
  return etalonFullSum(m) > 0;
}}
function hideZeroEtalonOn() {{
  const el = document.getElementById('hideZeroEtalon');
  return el ? !!el.checked : true;
}}
function filterZeroEtalon(rows) {{
  if (!hideZeroEtalonOn()) return rows;
  return rows.filter(hasEtalonSku);
}}
function ml4GmvSplitBg(s, focusLvl4) {{
  // BG-scoped only — for mega pie / card KM view.
  const rows = ((s && s.ml4) || []).slice();
  const hasMl4 = rows.some(m => m.gmv_ml4 != null && !isNaN(Number(m.gmv_ml4)));
  const allocs = hasMl4
    ? rows.map(m => Number(m.gmv_ml4) || 0)
    : allocateGmv(s.gmv, rows.map(m => etalonFullSum(m)));
  const totalAlloc = allocs.reduce((a, b) => a + (Number(b) || 0), 0);
  const focus = normCat(focusLvl4);
  return rows.map((m, i) => ({{
    ...m,
    gmv_allocated: allocs[i] || 0,
    gmv_share: (totalAlloc ? (allocs[i] || 0) / totalAlloc : 0),
    is_focus: focusLvl4 != null && normCat(m.lvl4) === focus,
  }}));
}}
function megaMl4Breakdown(data) {{
  const byMega = {{}};
  (data.scenarios || []).forEach(s => {{
    const mega = s.mega || '—';
    if (!byMega[mega]) byMega[mega] = {{ gmv: 0, etalon_15: 0, etalon_max: 0, etalon_sum: 0, ml4: {{}} }};
    const bucket = byMega[mega];
    bucket.gmv += Number(s.gmv) || 0;
    bucket.etalon_15 += Number(s.etalon_15) || 0;
    bucket.etalon_max += Number(s.etalon_max) || 0;
    bucket.etalon_sum += Number(s.etalon_sum) || 0;
    ml4GmvSplitBg(s, null).forEach(m => {{
      const key = m.lvl4 || '—';
      if (!bucket.ml4[key]) {{
        bucket.ml4[key] = {{
          lvl4: key,
          gmv: 0,
          etalon_15: 0,
          etalon_max: 0,
          etalon_sum: 0,
        }};
      }}
      const row = bucket.ml4[key];
      row.gmv += Number(m.gmv_allocated) || 0;
      if (m.exclusive) {{
        // Exclusive pie uses full BG etalon, not GMV-share display values.
        row.etalon_15 += Number(m.etalon_full_15 != null ? m.etalon_full_15 : m.etalon_15) || 0;
        row.etalon_max += Number(m.etalon_full_max != null ? m.etalon_full_max : m.etalon_max) || 0;
        row.etalon_sum += Number(m.etalon_full_sum != null ? m.etalon_full_sum : m.etalon_sum) || 0;
      }}
    }});
  }});
  return Object.keys(byMega).map(mega => {{
    const b = byMega[mega];
    const ml4 = Object.values(b.ml4).sort((a, c) => c.gmv - a.gmv);
    return {{
      mega,
      gmv: b.gmv,
      etalon_15: b.etalon_15,
      etalon_max: b.etalon_max,
      etalon_sum: b.etalon_sum,
      ml4,
    }};
  }}).sort((a, b) => b.gmv - a.gmv);
}}

function fmtPct(v, d=1) {{
  if (v == null || isNaN(v)) return '—';
  return (100*v).toFixed(d).replace('.', ',') + '%';
}}
function fmtPp(v, d=1) {{
  if (v == null || isNaN(v)) return '—';
  const x = 100*v;
  return (x>0?'+':'') + x.toFixed(d).replace('.', ',') + ' п.п.';
}}
function fmtInt(v) {{
  if (v == null || isNaN(v)) return '—';
  return Math.round(v).toLocaleString('ru-RU');
}}
function fmtMoney(v) {{
  if (v == null || isNaN(v)) return '—';
  if (Math.abs(v) >= 1e9) return (v/1e9).toFixed(1).replace('.', ',') + ' млрд ₽';
  if (Math.abs(v) >= 1e6) return Math.round(v/1e6) + ' млн ₽';
  return Math.round(v).toLocaleString('ru-RU') + ' ₽';
}}
function shade(hex, f) {{
  const h = hex.replace('#','');
  if (h.length !== 6) return hex;
  const rgb = [0,2,4].map(i => parseInt(h.slice(i,i+2),16));
  const out = rgb.map(c => f>=0 ? Math.round(c+(255-c)*f) : Math.round(c*(1+f)));
  return '#' + out.map(c => Math.max(0,Math.min(255,c)).toString(16).padStart(2,'0')).join('');
}}
function withAlpha(hex, a) {{
  const h = (hex||'#999999').replace('#','');
  return '#' + h.slice(0,6) + a;
}}

function data() {{ return DATA; }}

function fmtX(x) {{
  if (x == null || isNaN(x)) return '—';
  return String(Number(x).toFixed(1)).replace('.', ',') + '×';
}}

function renderGroceryMp() {{
  if (!INCLUDE_MP) return;
  const ctx = data().mp_grocery || {{}};
  const note = document.getElementById('groceryMpNote');
  const tiles = document.getElementById('groceryMpTiles');
  if (!note || !tiles) return;
  const cohorts = ctx.cohorts || [];
  if (!cohorts.length) {{
    note.textContent = 'Нет данных Магнит/Пятёрочка.';
    tiles.innerHTML = '';
    return;
  }}
  note.textContent = ctx.note || '';
  const smkt = ctx.samokat_aud_grocery_smkt_gmv;
  const parts = [
    `<div class="tile"><span class="lbl">Аудитория Самоката · grocery (smkt_gmv)</span>
      <b>${{fmtMoney(smkt)}}</b></div>`
  ];
  cohorts.forEach(c => {{
    const sh = c.samokat_share_in_cohort_grocery;
    parts.push(`<div class="tile">
      <span class="lbl">${{c.retail_merch}} · grocery</span>
      <b>${{fmtMoney(c.grocery_retail_gmv)}}</b>
      <span class="lbl">${{fmtX(c.vs_samokat_aud_gmv)}} к аудитории Самоката ·
        Самокат внутри когорты ${{fmtPct(sh, 1)}}</span>
    </div>`);
  }});
  tiles.innerHTML = parts.join('');
}}

function filteredMaster(master) {{
  return master.slice();
}}

function sharesForMode(row) {{
  return {{
    sber: Number(row.sber_full_share)||0,
    smkt: Number(row.samokat_implied_share)||0,
    gap: Number(row.gap_pp)||0,
  }};
}}

function colorMap(master) {{
  const mccs = (data().sber_wallet||[]).map(r => r.mcc_group);
  const map = {{}};
  mccs.forEach((m,i) => {{ map[m] = PALETTE[i % PALETTE.length]; }});
  filteredMaster(master).forEach((r,i) => {{
    if (!map[r.mcc_group]) map[r.mcc_group] = PALETTE[i % PALETTE.length];
  }});
  return map;
}}

function buildSmktPie(leaves, m2m, colors, master) {{
  const total = leaves.reduce((s,r)=>s+(Number(r.GMV)||0),0) || 1;
  const by = {{}};
  leaves.forEach(r => {{
    const mcc = r.mcc_group || m2m[r.mission] || '';
    if (!mcc) return;
    (by[mcc] = by[mcc] || []).push(r);
  }});
  const order = (data().sber_wallet||[]).map(r=>r.mcc_group).filter(m=>by[m]);
  Object.keys(by).forEach(m => {{ if (!order.includes(m)) order.push(m); }});

  const namedN = {{ 'Продуктовые магазины':6, 'Товары для дома':3 }};
  const labels=[], missions=[], values=[], cols=[], mccs=[], domainLegend=[];
  order.forEach(mcc => {{
    const group = by[mcc].slice().sort((a,b)=>(Number(b.GMV)||0)-(Number(a.GMV)||0));
    const mccGmv = group.reduce((s,r)=>s+(Number(r.GMV)||0),0);
    const denom = total;
    domainLegend.push({{ mcc, pct: +(100*mccGmv/denom).toFixed(2), color: colors[mcc]||'#999', n: group.length }});
    const nNamed = namedN[mcc] || 2;
    let rest = 0;
    group.forEach((r,i) => {{
      const pct = 100*(Number(r.GMV)||0)/denom;
      if (i < nNamed && pct >= 0.45) {{
        labels.push(r.scenario || r.mission);
        missions.push(r.mission);
        values.push(+pct.toFixed(2));
        cols.push(shade(colors[mcc]||'#999', [0,0.18,0.32,0.45,0.55,0.65][i%6]));
        mccs.push(mcc);
      }} else rest += Number(r.GMV)||0;
    }});
    if (rest > 0) {{
      const pct = 100*rest/denom;
      if (pct >= 0.05) {{
        labels.push('прочие · ' + (mcc.length>22?mcc.slice(0,20)+'…':mcc));
        missions.push('__other__::'+mcc);
        values.push(+pct.toFixed(2));
        cols.push(shade(colors[mcc]||'#999', 0.72));
        mccs.push(mcc);
      }}
    }}
  }});
  return {{ labels, missions, values, colors: cols, mcc: mccs, domain_legend: domainLegend }};
}}

function setHighlightMany(chart, activeSet) {{
  if (!chart) return;
  const ds = chart.data.datasets[0];
  const all = activeSet == null;
  ds.backgroundColor = ds._baseColors.map((c,i) => all || activeSet.has(i) ? c : withAlpha(c,'38'));
  ds.borderWidth = ds._baseColors.map((_,i) => all || activeSet.has(i) ? 2 : 0.5);
  ds.borderColor = ds._baseColors.map((c,i) => all || activeSet.has(i) ? '#1a1916' : '#fffcf6');
  chart.update('none');
}}

function fillLegend(el, items) {{
  el.innerHTML = items.map(it =>
    `<span><i style="background:${{it.color}}"></i>${{it.mcc}} · ${{String(it.pct).replace('.',',')}}%${{it.n!=null?' ('+it.n+')':''}}</span>`
  ).join('');
}}

function openBgCard(rk, bg) {{
  selectedRk = rk;
  selectedBg = bg;
  expandedMission = null;
  expandedLvl4 = null;
  expandedMl4Missions = new Set();
  selectedMega = null;
  if (assortPieChart) {{ assortPieChart.destroy(); assortPieChart = null; }}
  renderBgChips();
  renderAssortment();
}}

function currentCard() {{
  if (!selectedRk || !selectedBg) return null;
  const cards = ASSORTMENT.cards || {{}};
  return cards[selectedRk + '||' + selectedBg] || null;
}}

function renderRkSelect() {{
  const sel = document.getElementById('rkSelect');
  if (!sel) return;
  const idx = ASSORTMENT.rk_index || [];
  sel.innerHTML = '';
  idx.forEach(item => {{
    const o = document.createElement('option');
    o.value = item.rk;
    o.textContent = item.rk;
    sel.appendChild(o);
  }});
  if (!selectedRk && idx.length) {{
    selectedRk = idx[0].rk;
    selectedBg = (idx[0].bgs || [])[0] || null;
  }}
  if (selectedRk) sel.value = selectedRk;
}}

function renderBgChips() {{
  const wrap = document.getElementById('bgChips');
  if (!wrap) return;
  const idx = (ASSORTMENT.rk_index || []).find(x => x.rk === selectedRk);
  const bgs = (idx && idx.bgs) || [];
  wrap.innerHTML = bgs.map(bg =>
    `<button type="button" data-bg="${{bg.replace(/"/g,'&quot;')}}" class="${{bg===selectedBg?'on':''}}">${{bg}}</button>`
  ).join('');
  wrap.querySelectorAll('button').forEach(btn => {{
    btn.addEventListener('click', () => openBgCard(selectedRk, btn.dataset.bg));
  }});
}}

function cmpSortVal(a, b, type) {{
  if (type === 'num') {{
    const na = Number(a), nb = Number(b);
    const aN = Number.isNaN(na), bN = Number.isNaN(nb);
    if (aN && bN) return 0;
    if (aN) return 1;
    if (bN) return -1;
    return na - nb;
  }}
  return String(a ?? '').localeCompare(String(b ?? ''), 'ru', {{ sensitivity: 'base' }});
}}

function sortByState(rows, state, getter) {{
  const list = rows.slice();
  list.sort((a, b) => state.dir * cmpSortVal(getter(a, state.key), getter(b, state.key), state.type));
  return list;
}}

function toggleSort(state, key, type) {{
  if (state.key === key) {{
    state.dir = -state.dir;
  }} else {{
    state.key = key;
    state.type = type;
    state.dir = type === 'num' ? -1 : 1;
  }}
}}

function sortTh(label, key, type, state, extraClass='') {{
  const active = state.key === key;
  let ind = '↕';
  if (active) {{
    if (type === 'num') ind = state.dir < 0 ? '↓' : '↑';
    else ind = state.dir > 0 ? 'A→Я' : 'Я→A';
  }}
  return `<th class="sortable ${{extraClass}} ${{active?'active':''}}" data-sort-key="${{key}}" data-sort-type="${{type}}">${{label}}<span class="sort-ind">${{ind}}</span></th>`;
}}

function bindSortHeaders(root, state, onChange) {{
  if (!root) return;
  root.querySelectorAll('th.sortable').forEach(th => {{
    th.addEventListener('click', (e) => {{
      e.stopPropagation();
      toggleSort(state, th.dataset.sortKey, th.dataset.sortType);
      onChange();
    }});
  }});
}}

function renderAssortment() {{
  const note = document.getElementById('assortNote');
  if (note) note.textContent = ASSORTMENT.note || note.textContent;
  const card = document.getElementById('domainCard');
  const data = currentCard();
  if (!card) return;
  if (!data) {{
    card.className = 'card empty';
    card.textContent = 'Выберите РК и бизнес-группу.';
    return;
  }}
  const q = (document.getElementById('scenSearch')?.value || '').trim().toLowerCase();
  let scenRows = (data.scenarios || []).filter(s => {{
    if (!q) return true;
    const hitScen = (s.mission || '').toLowerCase().includes(q)
      || (s.mega || '').toLowerCase().includes(q)
      || (s.scenario || '').toLowerCase().includes(q)
      || (s.mcc_group || '').toLowerCase().includes(q);
    const hitMl4 = scenarioMl4Rows(s).some(m =>
      (m.lvl4 || '').toLowerCase().includes(q)
      || (m.lvl3 || '').toLowerCase().includes(q)
      || (m.lvl1 || '').toLowerCase().includes(q)
    );
    return hitScen || hitMl4;
  }});
  scenRows = sortByState(scenRows, scenSort, (s, key) => {{
    if (key === 'scenario') return s.scenario || s.mission || '';
    if (key === 'mcc_group') return s.mcc_group || '';
    if (key === 'status') return s.etalon_status || '';
    return s[key];
  }});
  let ml4Rows = (data.ml4s || []).filter(m => {{
    if (!q) return true;
    const hitSelf = (m.lvl4 || '').toLowerCase().includes(q)
      || (m.lvl3 || '').toLowerCase().includes(q)
      || (m.lvl2 || '').toLowerCase().includes(q)
      || (m.lvl1 || '').toLowerCase().includes(q)
      || (m.exclusive_owner || '').toLowerCase().includes(q);
    const hitScen = (m.missions || []).some(mission => {{
      const s = scenarioByMission(data, mission);
      if (!s) return String(mission).toLowerCase().includes(q);
      return (s.mission || '').toLowerCase().includes(q)
        || (s.mega || '').toLowerCase().includes(q)
        || (s.scenario || '').toLowerCase().includes(q)
        || (s.mcc_group || '').toLowerCase().includes(q);
    }});
    return hitSelf || hitScen;
  }});
  ml4Rows = filterZeroEtalon(ml4Rows);
  ml4Rows = sortByState(ml4Rows, ml4IndexSort, (m, key) => {{
    if (key === 'owner') return m.exclusive_owner || '';
    return m[key];
  }});
  let unused = (data.unused || []).slice();
  unused = sortByState(unused, unusedSort, (u, key) => u[key]);
  card.className = 'card';
  const unusedHtml = unused.length ? `
    <details class="unused">
      <summary>Эталон вне сценариев · ${{unused.length}} кат. · сумма ${{fmtInt(data.unused_sum)}} SKU
        (15 ${{fmtInt(data.unused_15)}} / МАКС ${{fmtInt(data.unused_max)}})</summary>
      <div class="table-scroll" style="margin-top:8px">
      <table class="ml4" id="unusedTable">
        <thead><tr>
          ${{sortTh('Lvl1','lvl1','text',unusedSort)}}
          ${{sortTh('Lvl2','lvl2','text',unusedSort)}}
          ${{sortTh('Lvl3','lvl3','text',unusedSort)}}
          ${{sortTh('Lvl4','lvl4','text',unusedSort)}}
          ${{sortTh('15','etalon_15','num',unusedSort,'num')}}
          ${{sortTh('МАКС','etalon_max','num',unusedSort,'num')}}
          ${{sortTh('Σ','etalon_sum','num',unusedSort,'num')}}
        </tr></thead>
        <tbody>${{unused.map(u => `<tr>
          <td>${{u.lvl1||''}}</td><td>${{u.lvl2||''}}</td><td>${{u.lvl3||''}}</td>
          <td>${{u.lvl4||''}}</td>
          <td class="num">${{fmtInt(u.etalon_15)}}</td>
          <td class="num">${{fmtInt(u.etalon_max)}}</td>
          <td class="num">${{fmtInt(u.etalon_sum)}}</td>
        </tr>`).join('')}}</tbody>
      </table>
      </div>
    </details>` : '<p class="muted">Нет эталона вне сценариев в этой БГ.</p>';

  const ml4BodyHtml = ml4Rows.map(m => {{
    const open = expandedLvl4 === m.lvl4;
    const missions = m.missions || [];
    let detail = '';
    if (open) {{
      if (!missions.length) {{
        detail = `<tr class="detail"><td colspan="11">
          <p class="ml4-head">Нет сценариев с этой ML4 в карточке БГ
            ${{m.in_unused ? '· категория во «вне сценариев»' : ''}}</p>
        </td></tr>`;
      }} else {{
        const blocks = missions.map(mission => {{
          const s = scenarioByMission(data, mission);
          if (!s) {{
            return `<div class="scen-block"><p class="ml4-head">${{mission}} · нет строки сценария</p></div>`;
          }}
          const splitAll = ml4GmvSplit(s, m.lvl4);
          const split = filterZeroEtalon(splitAll);
          const focus = splitAll.find(x => x.is_focus) || split.find(x => x.is_focus);
          const focusGmv = focus ? focus.gmv_allocated : 0;
          const focusShare = focus ? focus.gmv_share : 0;
          const nAll = s.n_ml4_all || splitAll.length;
          const nBg = s.n_ml4 || 0;
          const scenOpen = expandedMl4Missions.has(s.mission);
          const body = scenOpen ? `
            <div class="table-scroll">
            <table class="ml4">
              <thead><tr>
                <th>Lvl4</th>
                <th>РК</th>
                <th>БГ</th>
                <th class="num">15</th>
                <th class="num">МАКС</th>
                <th class="num">Σ</th>
                <th class="num">GMV</th>
                <th class="num">Доля</th>
              </tr></thead>
              <tbody>${{split.map(x => `<tr class="${{ml4RowClass(x)}}">
                <td>${{x.lvl4||''}}${{ml4Badge(x)}}</td>
                ${{ml4OwnerCells(x)}}
                <td class="num">${{fmtInt(x.etalon_15)}}</td>
                <td class="num">${{fmtInt(x.etalon_max)}}</td>
                <td class="num">${{fmtInt(x.etalon_sum)}}</td>
                <td class="num">${{fmtMoney(x.gmv_allocated)}}</td>
                <td class="num">${{fmtPct(x.gmv_share, 1)}}</td>
              </tr>`).join('') || '<tr><td colspan="8" class="muted">Нет ML4 с эталоном</td></tr>'}}</tbody>
            </table>
            </div>` : '';
          return `<div class="scen-block${{scenOpen?' open':''}}">
            <p class="ml4-head scen-toggle" data-mission="${{String(s.mission).replace(/"/g,'&quot;')}}"
               title="${{scenOpen?'Свернуть состав ML4':'Развернуть состав ML4'}}">
              <span class="chev">${{scenOpen?'▾':'▸'}}</span>
              <span><b>${{s.mega||''}} → ${{s.scenario||s.mission||''}}</b>
              · домен ${{s.mcc_group||'—'}}
              · GMV сценария ${{fmtMoney(s.gmv)}}
              · GMV этой ML4 ${{fmtMoney(focusGmv)}} (${{fmtPct(focusShare, 1)}})
              · эт. доля 15/МАКС/Σ: ${{fmtInt(focus ? focus.etalon_15 : 0)}} / ${{fmtInt(focus ? focus.etalon_max : 0)}} / ${{fmtInt(focus ? focus.etalon_sum : 0)}}
              · ML4 всего ${{nAll}} (эта БГ ${{nBg}})</span>
            </p>
            ${{body}}
          </div>`;
        }}).join('');
        detail = `<tr class="detail"><td colspan="11">
          <p class="ml4-head">Сценариев: ${{missions.length}} · сумма GMV сценариев (с пересечениями)
            ${{fmtMoney(m.gmv_touch)}} · сумма GMV ML4 ${{fmtMoney(m.gmv_proxy)}}
            · эксклюзивно у: ${{m.exclusive_owner || '—'}}
            · 15/МАКС/Σ: ${{fmtInt(m.etalon_15)}} / ${{fmtInt(m.etalon_max)}} / ${{fmtInt(m.etalon_sum)}}</p>
          ${{blocks}}
        </td></tr>`;
      }}
    }}
    const ownerLabel = m.exclusive_owner
      ? m.exclusive_owner
      : (m.in_unused ? 'вне сценариев' : '—');
    return `<tr class="expandable ${{open?'open':''}}" data-lvl4="${{String(m.lvl4).replace(/"/g,'&quot;')}}">
      <td>${{m.lvl1||''}}</td>
      <td>${{m.lvl2||''}}</td>
      <td>${{m.lvl3||''}}</td>
      <td>${{m.lvl4||''}}${{m.in_unused?'<span class="pill-unused">вне</span>':''}}</td>
      <td class="num">${{m.n_scenarios||0}}</td>
      <td class="num">${{fmtMoney(m.gmv_proxy)}}</td>
      <td class="num">${{fmtMoney(m.gmv_touch)}}</td>
      <td class="num">${{fmtInt(m.etalon_15)}}</td>
      <td class="num">${{fmtInt(m.etalon_max)}}</td>
      <td class="num">${{fmtInt(m.etalon_sum)}}</td>
      <td class="muted">${{ownerLabel}}</td>
    </tr>${{detail}}`;
  }}).join('') || '<tr><td colspan="11" class="muted">Нет ML4 по фильтру</td></tr>';

  const megaBreakdown = megaMl4Breakdown(data);
  if (!selectedMega || !megaBreakdown.some(x => x.mega === selectedMega)) {{
    selectedMega = megaBreakdown.length ? megaBreakdown[0].mega : null;
  }}
  const megaListHtml = megaBreakdown.length ? megaBreakdown.map(m => `
    <button type="button" data-mega="${{String(m.mega).replace(/"/g,'&quot;')}}" class="${{m.mega===selectedMega?'on':''}}">
      ${{m.mega}}
      <span class="sub">${{fmtMoney(m.gmv)}} · ML4 ${{m.ml4.length}}
        · эт. 15/МАКС ${{fmtInt(m.etalon_15)}}/${{fmtInt(m.etalon_max)}}</span>
    </button>`).join('') : '<p class="muted">Нет мегасценариев в карточке</p>';

  card.innerHTML = `
    <h3>${{data.bg}} · ${{data.rk}}</h3>
    <div class="km-meta">
      <span>Сценариев: <b>${{data.n_scenarios||0}}</b>${{q ? ' · показано '+scenRows.length : ''}}</span>
      <span>ML4 эталона: <b>${{fmtInt(data.n_ml4)}}</b>
        · в сценариях <b>${{fmtInt(data.n_ml4_in_scenarios)}}</b>
        ${{(q || hideZeroEtalonOn()) ? ' · показано '+ml4Rows.length : ''}}</span>
      <span>Эталон 15 / МАКС / сумма: <b>${{fmtInt(data.etalon_15)}}</b> · <b>${{fmtInt(data.etalon_max)}}</b> · <b>${{fmtInt(data.etalon_sum)}}</b></span>
    </div>
    <div class="block-title">Мегасценарий → доли ML4</div>
    <p class="block-note">Выберите мегаслева. Pie — доля каждой ML4 этой БГ внутри мега. Подписи — топ сегменты.</p>
    <div class="mega-pie-wrap">
      <div class="mega-list" id="megaList">${{megaListHtml}}</div>
      <div class="mega-pie-card">
        <h4 id="megaPieTitle">${{selectedMega || '—'}}</h4>
        <div class="mega-pie-canvas-wrap"><canvas id="assortMegaPie"></canvas></div>
        <div class="mega-pie-legend" id="megaPieLegend"></div>
      </div>
    </div>
    <div class="block-title">ML4 бизнес-группы</div>
    <p class="block-note">Клик по строке — список сценариев с этой категорией (свёрнуты). Клик по сценарию — полный состав ML4. Эталон в индексе — полный по категории; в сценариях — доли ∝ GMV ML4 (сумма долей = полный).</p>
    <div class="table-scroll">
    <table class="scen" id="ml4IndexTable">
      <thead>
        <tr>
          ${{sortTh('Lvl1','lvl1','text',ml4IndexSort)}}
          ${{sortTh('Lvl2','lvl2','text',ml4IndexSort)}}
          ${{sortTh('Lvl3','lvl3','text',ml4IndexSort)}}
          ${{sortTh('Lvl4','lvl4','text',ml4IndexSort)}}
          ${{sortTh('Сцен.','n_scenarios','num',ml4IndexSort,'num')}}
          ${{sortTh('GMV ML4','gmv_proxy','num',ml4IndexSort,'num')}}
          ${{sortTh('GMV сцен. Σ','gmv_touch','num',ml4IndexSort,'num')}}
          ${{sortTh('15','etalon_15','num',ml4IndexSort,'num')}}
          ${{sortTh('МАКС','etalon_max','num',ml4IndexSort,'num')}}
          ${{sortTh('Σ','etalon_sum','num',ml4IndexSort,'num')}}
          ${{sortTh('Эксклюзив','owner','text',ml4IndexSort)}}
        </tr>
      </thead>
      <tbody id="ml4IndexBody">${{ml4BodyHtml}}</tbody>
    </table>
    </div>
    <div class="block-title">Сценарии</div>
    <p class="block-note">Строка сценария: эталон колонок — эксклюзив этой БГ. Раскрытие — состав ML4; 15/МАКС/Σ на строках — доли эталона ∝ GMV ML4 (не полный эталон на каждый сценарий).</p>
    <div class="table-scroll">
    <table class="scen" id="scenTable">
      <thead>
        <tr>
          ${{sortTh('Мега','mega','text',scenSort)}}
          ${{sortTh('Сценарий','scenario','text',scenSort)}}
          ${{sortTh('Домен','mcc_group','text',scenSort)}}
          ${{sortTh('GMV','gmv','num',scenSort,'num')}}
          ${{sortTh('Доля','leaf_share','num',scenSort,'num')}}
          ${{sortTh('ML4','n_ml4','num',scenSort,'num')}}
          ${{sortTh('Эталон 15','etalon_15','num',scenSort,'num')}}
          ${{sortTh('МАКС','etalon_max','num',scenSort,'num')}}
          ${{sortTh('Σ','etalon_sum','num',scenSort,'num')}}
          ${{sortTh('Статус','status','text',scenSort)}}
        </tr>
      </thead>
      <tbody id="scenBody"></tbody>
    </table>
    </div>
    ${{unusedHtml}}`;
  const body = document.getElementById('scenBody');
  body.innerHTML = scenRows.map(s => {{
    const open = expandedMission === s.mission;
    let ml4 = scenarioMl4Rows(s);
    ml4 = sortByState(ml4, ml4Sort, (m, key) => {{
      if (key === 'qnf') return (m.qnf||'') + (m.seasonal && m.seasonal!=='0' ? ' '+m.seasonal : '');
      if (key === 'rk') return m.rk || '';
      return m[key];
    }});
    const nZero = ml4.filter(x => !hasEtalonSku(x)).length;
    const nBg = s.n_ml4 || 0;
    const nAll = s.n_ml4_all || ml4.length;
    ml4 = filterZeroEtalon(ml4);
    const detail = open ? `<tr class="detail"><td colspan="10">
      <p class="ml4-head">Домен (Сбер): ${{s.mcc_group||'—'}} · ML4 в сценарии: всего ${{nAll}} (эта БГ ${{nBg}}):
        15 ${{fmtInt(s.etalon_15)}} · МАКС ${{fmtInt(s.etalon_max)}} · Σ ${{fmtInt(s.etalon_sum)}} — эксклюзив этой БГ;
        без SKU ${{nZero}}; ушло в другой сценарий (эта БГ) ${{s.n_lost||0}};
        runtime без эталона ${{s.n_unmatched||0}}.</p>
      <div class="table-scroll">
      <table class="ml4" id="ml4Table">
        <thead><tr>
          ${{sortTh('Lvl1','lvl1','text',ml4Sort)}}
          ${{sortTh('Lvl2','lvl2','text',ml4Sort)}}
          ${{sortTh('Lvl3','lvl3','text',ml4Sort)}}
          ${{sortTh('Lvl4','lvl4','text',ml4Sort)}}
          ${{sortTh('РК','rk','text',ml4Sort)}}
          ${{sortTh('БГ','bg','text',ml4Sort)}}
          ${{sortTh('15','etalon_15','num',ml4Sort,'num')}}
          ${{sortTh('МАКС','etalon_max','num',ml4Sort,'num')}}
          ${{sortTh('Σ','etalon_sum','num',ml4Sort,'num')}}
          ${{sortTh('GMV','gmv_ml4','num',ml4Sort,'num')}}
          ${{sortTh('QNF','qnf','text',ml4Sort)}}
        </tr></thead>
        <tbody>${{ml4.map(m => `<tr class="${{ml4RowClass(m)}}">
          <td>${{m.lvl1||''}}</td><td>${{m.lvl2||''}}</td><td>${{m.lvl3||''}}</td>
          <td>${{m.lvl4||''}}${{ml4Badge(m)}}</td>
          ${{ml4OwnerCells(m)}}
          <td class="num">${{fmtInt(m.etalon_15)}}</td>
          <td class="num">${{fmtInt(m.etalon_max)}}</td>
          <td class="num">${{fmtInt(m.etalon_sum)}}</td>
          <td class="num">${{fmtMoney(m.gmv_ml4)}}</td>
          <td>${{m.qnf||''}}${{m.seasonal && m.seasonal!=='0' ? ' · '+m.seasonal : ''}}</td>
        </tr>`).join('') || '<tr><td colspan="11" class="muted">Нет ML4 с эталоном</td></tr>'}}</tbody>
      </table>
      </div>
    </td></tr>` : '';
    return `<tr class="expandable ${{open?'open':''}}" data-mission="${{String(s.mission).replace(/"/g,'&quot;')}}">
      <td>${{s.mega||''}}</td>
      <td>${{s.scenario||s.mission||''}}</td>
      <td>${{s.mcc_group||'—'}}</td>
      <td class="num">${{fmtMoney(s.gmv)}}</td>
      <td class="num">${{fmtPct(s.leaf_share, 2)}}</td>
      <td class="num">${{s.n_ml4||0}}</td>
      <td class="num">${{fmtInt(s.etalon_15)}}</td>
      <td class="num">${{fmtInt(s.etalon_max)}}</td>
      <td class="num">${{fmtInt(s.etalon_sum)}}</td>
      <td class="muted">${{s.etalon_status||''}}</td>
    </tr>${{detail}}`;
  }}).join('') || '<tr><td colspan="10" class="muted">Нет сценариев по фильтру</td></tr>';
  document.querySelectorAll('#ml4IndexBody tr.expandable').forEach(tr => {{
    tr.addEventListener('click', () => {{
      const lvl4 = tr.dataset.lvl4;
      const next = expandedLvl4 === lvl4 ? null : lvl4;
      expandedLvl4 = next;
      expandedMission = null;
      expandedMl4Missions = new Set();
      renderAssortment();
    }});
  }});
  document.querySelectorAll('#ml4IndexBody .scen-toggle').forEach(el => {{
    el.addEventListener('click', (evt) => {{
      evt.stopPropagation();
      const m = el.dataset.mission;
      if (expandedMl4Missions.has(m)) expandedMl4Missions.delete(m);
      else expandedMl4Missions.add(m);
      renderAssortment();
    }});
  }});
  body.querySelectorAll('tr.expandable').forEach(tr => {{
    tr.addEventListener('click', () => {{
      const m = tr.dataset.mission;
      expandedMission = expandedMission === m ? null : m;
      expandedLvl4 = null;
      expandedMl4Missions = new Set();
      renderAssortment();
    }});
  }});
  document.querySelectorAll('#megaList button').forEach(btn => {{
    btn.addEventListener('click', () => {{
      selectedMega = btn.dataset.mega;
      renderAssortment();
    }});
  }});
  bindSortHeaders(document.getElementById('ml4IndexTable'), ml4IndexSort, renderAssortment);
  bindSortHeaders(document.getElementById('scenTable'), scenSort, renderAssortment);
  bindSortHeaders(document.getElementById('unusedTable'), unusedSort, renderAssortment);
  bindSortHeaders(document.getElementById('ml4Table'), ml4Sort, renderAssortment);
  renderAssortMegaPie(megaBreakdown, selectedMega);
}}

function renderAssortMegaPie(megaBreakdown, megaName) {{
  if (assortPieChart) {{
    assortPieChart.destroy();
    assortPieChart = null;
  }}
  const canvas = document.getElementById('assortMegaPie');
  const legend = document.getElementById('megaPieLegend');
  const title = document.getElementById('megaPieTitle');
  if (!canvas) return;
  const mega = (megaBreakdown || []).find(x => x.mega === megaName);
  if (title) title.textContent = megaName || '—';
  if (!mega || !(mega.ml4 || []).length) {{
    if (legend) legend.textContent = 'Нет ML4 для pie';
    return;
  }}
  const rows = mega.ml4.slice();
  const topN = 12;
  const top = rows.slice(0, topN);
  const rest = rows.slice(topN);
  const restGmv = rest.reduce((a, r) => a + (Number(r.gmv) || 0), 0);
  const labels = top.map(r => r.lvl4);
  const values = top.map(r => Number(r.gmv) || 0);
  if (restGmv > 0) {{
    labels.push('прочие (' + rest.length + ')');
    values.push(restGmv);
  }}
  const total = values.reduce((a, b) => a + b, 0) || 1;
  const colors = labels.map((_, i) => PALETTE[i % PALETTE.length]);
  if (legend) {{
    legend.innerHTML = labels.map((lab, i) =>
      `<span><i style="background:${{colors[i]}}"></i>${{lab}} · ${{fmtPct(values[i]/total, 1)}}</span>`
    ).join('');
  }}
  assortPieChart = new Chart(canvas, {{
    type: 'pie',
    data: {{
      labels,
      datasets: [{{
        data: values,
        backgroundColor: colors,
        borderWidth: 1,
        borderColor: '#fff',
      }}],
    }},
    options: {{
      responsive: true,
      maintainAspectRatio: false,
      plugins: {{
        legend: {{ display: false }},
        datalabels: {{
          color: '#222',
          font: {{ size: 10, weight: '600' }},
          formatter: (v, ctx) => {{
            const p = v / total;
            if (p < 0.045) return '';
            const lab = ctx.chart.data.labels[ctx.dataIndex] || '';
            const short = lab.length > 18 ? lab.slice(0, 16) + '…' : lab;
            return short + '\\n' + (100 * p).toFixed(0) + '%';
          }},
        }},
        tooltip: {{
          callbacks: {{
            label: (ctx) => {{
              const v = Number(ctx.raw) || 0;
              return ' ' + ctx.label + ': ' + fmtMoney(v) + ' (' + fmtPct(v / total, 1) + ')';
            }},
          }},
        }},
      }},
    }},
  }});
}}

function renderEtalonPool() {{
  const el = document.getElementById('etalonPool');
  if (!el) return;
  const p = ETALON_POOL || {{}};
  const inSum = p.in_scenarios_sum;
  if (inSum == null) {{ el.textContent = ''; return; }}
  el.textContent =
    'Эталон сценариев (как в Excel): 15 мин ' + fmtInt(p.in_scenarios_15)
    + ' · МАКС ' + fmtInt(p.in_scenarios_max)
    + ' · сумма ' + fmtInt(p.in_scenarios_sum)
    + '. Вне сценариев: ' + fmtInt(p.unused_15)
    + ' / ' + fmtInt(p.unused_max)
    + ' / ' + fmtInt(p.unused_sum)
    + ' SKU (' + (p.unused_n_cats || 0) + ' категорий).';
}}

function renderGaps(master) {{
  const head = document.getElementById('gapsHead');
  const body = document.getElementById('gapBody');
  if (head) {{
    head.innerHTML = `<tr>
      ${{sortTh('Домен','mcc_group','text',gapSort)}}
      ${{sortTh('Сбер','sber','num',gapSort,'num')}}
      ${{sortTh('Самокат','smkt','num',gapSort,'num')}}
      ${{sortTh('Gap','gap','num',gapSort,'num')}}
      ${{sortTh('₽/кл. Сбер','rub_sber','num',gapSort,'num')}}
      ${{sortTh('₽/кл. Сбер /мес','rub_sber_m','num',gapSort,'num')}}
      ${{sortTh('₽/кл. Самокат','rub_smkt','num',gapSort,'num')}}
      ${{sortTh('₽/кл. Самокат /мес','rub_smkt_m','num',gapSort,'num')}}
      ${{sortTh('Δ ₽/кл.','rub_gap','num',gapSort,'num')}}
      ${{sortTh('Δ ₽/кл. /мес','rub_gap_m','num',gapSort,'num')}}
      ${{sortTh('Сценарии','n_leaves','num',gapSort,'num')}}
      ${{sortTh('Эталон 15','etalon_15_new','num',gapSort,'num')}}
      ${{sortTh('Эталон МАКС','etalon_max_new','num',gapSort,'num')}}
      ${{sortTh('Эталон Σ','etalon_sum_new','num',gapSort,'num')}}
      ${{sortTh('Эталон','etalon_status','text',gapSort)}}
      ${{sortTh('Вывод','conclusion','text',gapSort)}}
    </tr>`;
  }}
  let rows = filteredMaster(master);
  rows = sortByState(rows, gapSort, (r, key) => {{
    const sh = sharesForMode(r);
    if (key === 'sber') return sh.sber;
    if (key === 'smkt') return sh.smkt;
    if (key === 'gap') return sh.gap;
    if (key === 'rub_sber') return r.rub_per_customer_sber;
    if (key === 'rub_sber_m') return r.rub_per_customer_sber_month;
    if (key === 'rub_smkt') return r.rub_per_customer_smkt;
    if (key === 'rub_smkt_m') return r.rub_per_customer_smkt_month;
    if (key === 'rub_gap') return r.rub_per_customer_gap;
    if (key === 'rub_gap_m') return r.rub_per_customer_gap_month;
    return r[key];
  }});
  body.innerHTML = rows.map(r => {{
    const sh = sharesForMode(r);
    const et15 = fmtInt(r.etalon_15_new);
    const etMax = fmtInt(r.etalon_max_new);
    const etSum = fmtInt(r.etalon_sum_new);
    const hot = sh.gap >= 0.01 ? 'hot' : '';
    const gapRub = Number(r.rub_per_customer_gap)||0;
    const gapRubM = Number(r.rub_per_customer_gap_month)||0;
    return `<tr class="clickable ${{hot}}" data-mcc="${{r.mcc_group}}">
      <td class="domain">${{r.mcc_group}}${{r.split_tag ? `<span class="tag${{r.split_tag==='слияние'?' merge':''}}" title="${{(r.inseparable_note||'').replace(/"/g,'&quot;')}}">${{r.split_tag}}</span>` : ''}}${{r.split_tag==='слияние' && r.inseparable_with ? `<span class="muted" style="display:block;font-weight:400;margin-top:2px">↔ ${{r.inseparable_with}}</span>` : ''}}</td>
      <td class="num">${{fmtPct(sh.sber)}}</td>
      <td class="num">${{fmtPct(sh.smkt)}}</td>
      <td class="num ${{sh.gap>0?'pos':'neg'}}">${{fmtPp(sh.gap)}}</td>
      <td class="num">${{fmtMoney(r.rub_per_customer_sber)}}</td>
      <td class="num">${{fmtMoney(r.rub_per_customer_sber_month)}}</td>
      <td class="num">${{fmtMoney(r.rub_per_customer_smkt)}}</td>
      <td class="num">${{fmtMoney(r.rub_per_customer_smkt_month)}}</td>
      <td class="num ${{gapRub>0?'pos':'neg'}}">${{fmtMoney(r.rub_per_customer_gap)}}</td>
      <td class="num ${{gapRubM>0?'pos':'neg'}}">${{fmtMoney(r.rub_per_customer_gap_month)}}</td>
      <td class="num">${{r.n_leaves||0}}</td>
      <td class="num">${{et15}}</td>
      <td class="num">${{etMax}}</td>
      <td class="num">${{etSum}}</td>
      <td class="muted">${{r.etalon_status||''}}</td>
      <td class="concl" title="${{(r.conclusion||'').replace(/"/g,'&quot;')}}">${{r.conclusion||''}}</td>
    </tr>`;
  }}).join('');
  body.querySelectorAll('tr').forEach(tr => {{
    tr.addEventListener('click', () => {{
      body.querySelectorAll('tr').forEach(x => x.classList.toggle('selected', x === tr));
    }});
  }});
  bindSortHeaders(document.getElementById('gapsTable'), gapSort, () => renderGaps(data().master||[]));
}}

function destroyCharts() {{
  [pieSber, pieSmkt, chartBars, chartBarsNoGrocery, assortPieChart].forEach(c => {{ if (c) c.destroy(); }});
  pieSber = pieSmkt = chartBars = chartBarsNoGrocery = null;
  assortPieChart = null;
}}

function makeBarChart(canvasId, rows) {{
  const labels = rows.map(r => r.mcc_group);
  const sberVals = rows.map(r => +(100*sharesForMode(r).sber).toFixed(2));
  const smktVals = rows.map(r => +(100*sharesForMode(r).smkt).toFixed(2));
  return new Chart(document.getElementById(canvasId), {{
    type: 'bar',
    data: {{
      labels,
      datasets: [
        {{ label: 'Сбер, %', data: sberVals, backgroundColor: '#1a6b4a', borderRadius: 3 }},
        {{ label: 'Самокат (сценарии), %', data: smktVals, backgroundColor: '#c45c26', borderRadius: 3 }},
      ],
    }},
    options: {{
      responsive: true,
      maintainAspectRatio: false,
      plugins: {{
        legend: {{ position: 'bottom' }},
        datalabels: {{ display: false }},
      }},
      scales: {{
        x: {{ ticks: {{ maxRotation: 45, minRotation: 30, font: {{ size: 10 }} }}, grid: {{ display:false }} }},
        y: {{ title: {{ display:true, text:'Доля, %' }}, grid: {{ color:'#eee8dc' }} }},
      }},
      onClick: () => {{}},
    }},
  }});
}}

function renderCharts() {{
  destroyCharts();
  const d = data();
  const master = d.master || [];
  const colors = colorMap(master);
  const rows = filteredMaster(master).sort((a,b)=>sharesForMode(b).sber-sharesForMode(a).sber);
  const sberVals = rows.map(r => +(100*sharesForMode(r).sber).toFixed(2));
  chartBars = makeBarChart('chartBars', rows);
  chartBarsNoGrocery = makeBarChart(
    'chartBarsNoGrocery',
    rows.filter(r => r.mcc_group !== 'Продуктовые магазины')
  );

  // Sber pie
  const sberPieLabels = rows.map(r => r.mcc_group);
  const sberPieVals = sberVals.slice();
  const sberPieCols = rows.map(r => colors[r.mcc_group]||'#999');
  pieSber = new Chart(document.getElementById('pieSber'), {{
    type: 'pie',
    data: {{
      labels: sberPieLabels,
      datasets: [{{ data: sberPieVals, backgroundColor: sberPieCols.slice(), _baseColors: sberPieCols.slice(), borderWidth:1, borderColor:'#fffcf6' }}],
    }},
    options: {{
      responsive:true, maintainAspectRatio:false,
      plugins: {{
        legend: {{ display:false }},
        datalabels: {{
          color:'#fff', font:{{ weight:'600', size:10 }},
          textStrokeColor:'rgba(0,0,0,0.35)', textStrokeWidth:2,
          formatter: v => v>=2.5 ? (String(v).replace('.',',')+'%') : '',
        }},
      }},
      onHover: (evt, els) => {{
        if (!els.length) {{ setHighlightMany(pieSber,null); setHighlightMany(pieSmkt,null); return; }}
        const i = els[0].index;
        const mcc = sberPieLabels[i];
        setHighlightMany(pieSber, new Set([i]));
        const idxs = new Set();
        (pieSmkt?.data?.datasets[0] ? SMKT_STATE.mcc : []).forEach((m,j) => {{ if (m===mcc) idxs.add(j); }});
        setHighlightMany(pieSmkt, idxs);
        document.getElementById('hoverHint').textContent =
          'Сбер: '+mcc+' '+String(sberPieVals[i]).replace('.',',')+'% → сегменты Самоката: '+idxs.size;
      }},
      onClick: () => {{}},
    }},
  }});
  fillLegend(document.getElementById('legendSber'),
    sberPieLabels.map((m,i)=>({{ mcc:m, pct:sberPieVals[i], color:sberPieCols[i] }})));

  const smkt = buildSmktPie(d.samokat_leaves||[], d.bridge_mission_to_mcc||{{}}, colors, master);
  window.SMKT_STATE = smkt;
  pieSmkt = new Chart(document.getElementById('pieSmkt'), {{
    type: 'pie',
    data: {{
      labels: smkt.labels,
      datasets: [{{ data: smkt.values, backgroundColor: smkt.colors.slice(), _baseColors: smkt.colors.slice(), borderWidth:1, borderColor:'#fffcf6' }}],
    }},
    options: {{
      responsive:true, maintainAspectRatio:false,
      plugins: {{
        legend: {{ display:false }},
        datalabels: {{
          color:'#fff', font:{{ weight:'600', size:10 }},
          textStrokeColor:'rgba(0,0,0,0.35)', textStrokeWidth:2,
          formatter: v => v>=2.5 ? (String(v).replace('.',',')+'%') : '',
        }},
      }},
      onHover: (evt, els) => {{
        if (!els.length) {{ setHighlightMany(pieSber,null); setHighlightMany(pieSmkt,null); return; }}
        const i = els[0].index;
        const mcc = smkt.mcc[i];
        const idxs = new Set();
        smkt.mcc.forEach((m,j)=>{{ if(m===mcc) idxs.add(j); }});
        setHighlightMany(pieSmkt, idxs);
        const si = sberPieLabels.indexOf(mcc);
        setHighlightMany(pieSber, si>=0 ? new Set([si]) : new Set());
        document.getElementById('hoverHint').textContent =
          'Самокат: '+smkt.labels[i]+' · группа «'+mcc+'»';
      }},
      onClick: () => {{}},
    }},
  }});
  fillLegend(document.getElementById('legendSmkt'), smkt.domain_legend||[]);
}}

function refresh() {{
  const d = data();
  renderGaps(d.master||[]);
  renderEtalonPool();
  renderGroceryMp();
  renderCharts();
  renderAssortment();
}}

// init controls
const rkSel = document.getElementById('rkSelect');
if (rkSel) {{
  renderRkSelect();
  rkSel.addEventListener('change', () => {{
    selectedRk = rkSel.value;
    const idx = (ASSORTMENT.rk_index || []).find(x => x.rk === selectedRk);
    selectedBg = ((idx && idx.bgs) || [])[0] || null;
    expandedMission = null;
    expandedLvl4 = null;
    expandedMl4Missions = new Set();
    selectedMega = null;
    if (assortPieChart) {{ assortPieChart.destroy(); assortPieChart = null; }}
    renderBgChips();
    renderAssortment();
  }});
}}
const scenSearch = document.getElementById('scenSearch');
if (scenSearch) {{
  scenSearch.addEventListener('input', () => renderAssortment());
}}
const hideZeroEl = document.getElementById('hideZeroEtalon');
if (hideZeroEl) {{
  hideZeroEl.addEventListener('change', () => renderAssortment());
}}
renderBgChips();

refresh();
</script>
</body>
</html>
"""
    html_path.parent.mkdir(parents=True, exist_ok=True)
    html_path.write_text(html, encoding="utf-8")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--payload", default=str(DEFAULT_PAYLOAD))
    ap.add_argument("--out", default=str(DEFAULT_HTML))
    ap.add_argument("--no-mp", action="store_true", help="Hide Magnit/Pyaterochka blocks")
    args = ap.parse_args()
    render_html(Path(args.payload), Path(args.out), include_mp=not args.no_mp)
    print(f"Wrote {args.out}")


if __name__ == "__main__":
    main()
