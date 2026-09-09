#!/usr/bin/env python3
"""Render budget-gap HTML: single scroll page, linked pie wallets, bars, tables."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

PKG = Path(__file__).resolve().parent
ROOT = PKG.parent
DEFAULT_PAYLOAD = ROOT / "outputs" / "budget_gap_payload.json"
DEFAULT_HTML = ROOT / "outputs" / "budget_gap_report.html"

# Palettes for Sber (MCC) and Samokat (mega) pies — independent label sets.
PIE_PALETTE = [
    "#1a6b4a",
    "#c45c26",
    "#2a4a6b",
    "#8b5a2b",
    "#5c7a3a",
    "#8b2e2e",
    "#3d6b8a",
    "#b8860b",
    "#6b4c7a",
    "#2f6f6a",
    "#a0522d",
    "#4a6741",
    "#7a4e2d",
    "#3a5f7a",
    "#9a3b4a",
    "#5a6b3a",
    "#6a3b5a",
    "#2d5a4a",
]
BRIDGE_CSV = ROOT / "inputs" / "scenario_mcc_bridge.csv"


def _esc(s) -> str:
    return (
        str(s if s is not None else "")
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def _pct(x, digits: int = 1) -> str:
    try:
        v = float(x)
    except (TypeError, ValueError):
        return "—"
    if v != v:
        return "—"
    return f"{100 * v:.{digits}f}%".replace(".", ",")


def _pp(x, digits: int = 1) -> str:
    try:
        v = float(x)
    except (TypeError, ValueError):
        return "—"
    if v != v:
        return "—"
    sign = "+" if v > 0 else ""
    return f"{sign}{100 * v:.{digits}f} п.п.".replace(".", ",")


def _money(x) -> str:
    try:
        v = float(x)
    except (TypeError, ValueError):
        return "—"
    if v != v:
        return "—"
    if abs(v) >= 1e9:
        return f"{v / 1e9:.1f} млрд ₽".replace(".", ",")
    if abs(v) >= 1e6:
        return f"{v / 1e6:.0f} млн ₽"
    return f"{v:,.0f} ₽".replace(",", " ")


def _safe_int(x) -> str | None:
    try:
        if x is None:
            return None
        v = float(x)
        if v != v:
            return None
        return str(int(v))
    except (TypeError, ValueError):
        return None


def _etalon(row: dict) -> str:
    btype = str(row.get("bridge_type") or "")
    status = str(row.get("etalon_status") or "")
    # Channel stays н/п; grocery now rolls food lvl1 like specialty.
    if "channel" in btype or (status.startswith("н/п") and "grocery" not in btype):
        return "н/п"
    return _safe_int(row.get("etalon_sum_new")) or "—"


def _json_embed(obj) -> str:
    return json.dumps(obj, ensure_ascii=False, default=str).replace("</", "<\\/")


def _load_bridge_rows(payload: dict) -> list[dict]:
    """Bridge mega↔MCC: prefer payload, else CSV, else invert master.megas."""
    bridge = payload.get("scenario_bridge")
    if bridge:
        return [
            {
                "mega": str(r.get("mega") or "").strip(),
                "mcc_group": str(r.get("mcc_group") or "").strip(),
                "weight": float(r.get("weight") or 0),
                "role": str(r.get("role") or ""),
            }
            for r in bridge
            if str(r.get("mega") or "").strip() and str(r.get("mcc_group") or "").strip()
        ]
    if BRIDGE_CSV.exists():
        import csv

        with BRIDGE_CSV.open(encoding="utf-8") as f:
            return [
                {
                    "mega": str(r.get("mega") or "").strip(),
                    "mcc_group": str(r.get("mcc_group") or "").strip(),
                    "weight": float(r.get("weight") or 0),
                    "role": str(r.get("role") or ""),
                }
                for r in csv.DictReader(f)
                if str(r.get("mega") or "").strip() and str(r.get("mcc_group") or "").strip()
            ]
    # Fallback: master.megas is "A; B; C" per MCC
    rows: list[dict] = []
    for r in payload.get("master") or []:
        mcc = str(r.get("mcc_group") or "").strip()
        for mega in str(r.get("megas") or "").split(";"):
            mega = mega.strip()
            if mega and mcc:
                rows.append({"mega": mega, "mcc_group": mcc, "weight": 1.0, "role": ""})
    return rows


def _pie_side(
    items: list[tuple[str, float]],
    min_share: float,
    palette: list[str],
) -> dict:
    labels: list[str] = []
    values: list[float] = []
    colors: list[str] = []
    other = 0.0
    for name, share in items:
        if share < min_share:
            other += share
            continue
        labels.append(name)
        values.append(round(100 * share, 2))
        colors.append(palette[len(colors) % len(palette)])
    if other > 0:
        labels.append("Прочее")
        values.append(round(100 * other, 2))
        colors.append("#b0a898")
    return {"labels": labels, "values": values, "colors": colors}


def _pie_wallet_payload(
    master: list[dict],
    mega: list[dict],
    bridge: list[dict],
    min_share_sber: float = 0.008,
    min_share_mega: float = 0.0005,
) -> dict:
    """Sber pie = MCC wallet; Samokat pie = mega scenario shares; bridge for hover."""
    sber_items = sorted(
        [
            (str(r.get("mcc_group") or ""), float(r.get("sber_full_share") or 0))
            for r in master
            if str(r.get("mcc_group") or "")
        ],
        key=lambda x: x[1],
        reverse=True,
    )
    mega_items = sorted(
        [
            (str(r.get("mega") or ""), float(r.get("mega_share") or 0))
            for r in mega
            if str(r.get("mega") or "")
        ],
        key=lambda x: x[1],
        reverse=True,
    )
    sber_pie = _pie_side(sber_items, min_share_sber, PIE_PALETTE)
    smkt_pie = _pie_side(mega_items, min_share_mega, PIE_PALETTE[::-1])

    sber_idx = {lab: i for i, lab in enumerate(sber_pie["labels"])}
    smkt_idx = {lab: i for i, lab in enumerate(smkt_pie["labels"])}

    mega_to_mcc: dict[str, list[str]] = {}
    mcc_to_mega: dict[str, list[str]] = {}
    for link in bridge:
        m = link["mega"]
        c = link["mcc_group"]
        if m not in mega_to_mcc:
            mega_to_mcc[m] = []
        if c not in mega_to_mcc[m]:
            mega_to_mcc[m].append(c)
        if c not in mcc_to_mega:
            mcc_to_mega[c] = []
        if m not in mcc_to_mega[c]:
            mcc_to_mega[c].append(m)

    # Index maps for JS (skip Прочее)
    mega_to_sber_idx: dict[str, list[int]] = {}
    mcc_to_smkt_idx: dict[str, list[int]] = {}
    for mega_name, mccs in mega_to_mcc.items():
        idxs = [sber_idx[c] for c in mccs if c in sber_idx]
        if mega_name in smkt_idx and idxs:
            mega_to_sber_idx[str(smkt_idx[mega_name])] = idxs
    for mcc_name, megas in mcc_to_mega.items():
        idxs = [smkt_idx[m] for m in megas if m in smkt_idx]
        if mcc_name in sber_idx and idxs:
            mcc_to_smkt_idx[str(sber_idx[mcc_name])] = idxs

    return {
        "sber": sber_pie,
        "samokat": smkt_pie,
        "mega_to_mcc": mega_to_mcc,
        "mcc_to_mega": mcc_to_mega,
        "mega_to_sber_idx": mega_to_sber_idx,
        "mcc_to_smkt_idx": mcc_to_smkt_idx,
    }


def render_html(payload_path: Path, html_path: Path) -> None:
    payload = json.loads(payload_path.read_text(encoding="utf-8"))
    city = payload.get("city") or "Москва"
    gap_def = payload.get("gap_definition") or ""
    master = payload.get("master") or []
    sber = payload.get("sber_wallet") or []
    mega = payload.get("samokat_mega") or []
    ml1 = payload.get("samokat_ml1") or []
    audit = payload.get("mission_etalon_audit") or []
    bridge_rows = _load_bridge_rows(payload)

    gaps_pos = sorted(
        [r for r in master if float(r.get("gap_pp") or 0) > 0],
        key=lambda r: float(r.get("gap_pp") or 0),
        reverse=True,
    )
    top3 = gaps_pos[:3]

    chart_mcc = sorted(
        master,
        key=lambda r: abs(float(r.get("gap_pp") or 0)),
        reverse=True,
    )[:14]
    chart_mcc = sorted(chart_mcc, key=lambda r: float(r.get("sber_full_share") or 0), reverse=True)

    compare_payload = {
        "labels": [r.get("mcc_group") for r in chart_mcc],
        "sber_full": [round(100 * float(r.get("sber_full_share") or 0), 2) for r in chart_mcc],
        "sber_smkt": [round(100 * float(r.get("sber_smkt_share") or 0), 2) for r in chart_mcc],
        "samokat": [round(100 * float(r.get("samokat_implied_share") or 0), 2) for r in chart_mcc],
        "gap": [round(100 * float(r.get("gap_pp") or 0), 2) for r in chart_mcc],
    }
    pie_payload = _pie_wallet_payload(master, mega, bridge_rows)

    mega_chart = {
        "labels": [r.get("mega") for r in mega[:18]],
        "share": [round(100 * float(r.get("mega_share") or 0), 2) for r in mega[:18]],
    }

    ml1_real = [r for r in ml1 if not str(r.get("lvl1") or "").startswith("(")]
    ml1_chart = {
        "labels": [r.get("lvl1") for r in ml1_real[:20]],
        "share": [round(100 * float(r.get("ml1_share") or 0), 2) for r in ml1_real[:20]],
        "etalon": [
            None
            if r.get("etalon_sum_new") is None
            or (
                isinstance(r.get("etalon_sum_new"), float)
                and r.get("etalon_sum_new") != r.get("etalon_sum_new")
            )
            else int(float(r.get("etalon_sum_new")))
            for r in ml1_real[:20]
        ],
    }

    top3_html = "".join(
        f"""
        <li>
          <strong>{_esc(r.get('mcc_group'))}</strong>
          — недобор {_pp(r.get('gap_pp'))}
          (Сбер целиком {_pct(r.get('sber_full_share'))} · аудитория СМКТ {_pct(r.get('sber_smkt_share'))}
          vs сценарии {_pct(r.get('samokat_implied_share'))}).
          {_esc(r.get('conclusion'))}
        </li>"""
        for r in top3
    )

    sber_rows = "".join(
        f"""
        <tr>
          <td>{_esc(r.get('mcc_group'))}</td>
          <td class="num">{_pct(r.get('sber_full_share'))}</td>
          <td class="num">{_pct(r.get('sber_smkt_share'))}</td>
          <td class="num">{_money(r.get('gmv'))}</td>
          <td class="num">{_money(r.get('smkt_gmv'))}</td>
          <td class="num">{_money(r.get('rub_per_customer'))}</td>
        </tr>"""
        for r in sber
    )

    mega_rows = "".join(
        f"""
        <tr>
          <td>{_esc(r.get('mega'))}</td>
          <td class="num">{_pct(r.get('mega_share'))}</td>
          <td class="num">{_money(r.get('GMV'))}</td>
        </tr>"""
        for r in mega
    )

    ml1_rows = "".join(
        f"""
        <tr class="{'warn' if str(r.get('etalon_status') or '') in ('нет в NEW-эталоне','эталон = 0','узкий') else ''}">
          <td>{_esc(r.get('lvl1'))}</td>
          <td class="num">{_pct(r.get('ml1_share'))}</td>
          <td class="num">{_money(r.get('GMV'))}</td>
          <td class="num">{
            'н/п' if str(r.get('lvl1','')).startswith('(')
            else (_safe_int(r.get('etalon_sum_new')) or '—')
          }</td>
          <td class="muted">{_esc(r.get('etalon_status'))}</td>
        </tr>"""
        for r in ml1
    )

    gap_rows = "".join(
        f"""
        <tr class="{'gap-hot' if float(r.get('gap_pp') or 0) >= 0.01 else ''}">
          <td>{_esc(r.get('mcc_group'))}</td>
          <td class="muted">{_esc(r.get('bridge_type'))}</td>
          <td class="num">{_pct(r.get('sber_full_share'))}</td>
          <td class="num">{_pct(r.get('sber_smkt_share'))}</td>
          <td class="num">{_pct(r.get('samokat_implied_share'))}</td>
          <td class="num {'pos' if float(r.get('gap_pp') or 0) > 0 else 'neg'}">{_pp(r.get('gap_pp'))}</td>
          <td class="num">{_etalon(r)}</td>
          <td class="muted">{_esc(r.get('etalon_status'))}</td>
          <td>{_esc(r.get('conclusion'))}</td>
        </tr>"""
        for r in master
    )

    audit_rows = "".join(
        f"""
        <tr class="{'warn' if str(r.get('etalon_flag')) in ('узкий','нет моста','нет кроссвока','specialty без lvl1 в кроссвоке','grocery без etalon','канал н/п') or 'пуст' in str(r.get('ml4_status') or '') or '0 сматчено' in str(r.get('ml4_status') or '') else ''}">
          <td>{_esc(r.get('mega'))}</td>
          <td class="num">{_pct(r.get('mega_share'))}</td>
          <td>{_esc(r.get('mcc_links'))}</td>
          <td><span class="flag">{_esc(r.get('etalon_flag'))}</span></td>
          <td class="muted">{_esc(r.get('etalon_note'))}</td>
          <td class="num">{r.get('n_ml4') if r.get('n_ml4') is not None else '—'}</td>
          <td class="num">{r.get('n_ml4_mapped') if r.get('n_ml4_mapped') is not None else '—'}</td>
          <td class="muted">{_esc(r.get('ml4_status'))}</td>
        </tr>"""
        for r in audit
    )

    html = f"""<!DOCTYPE html>
<html lang="ru">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>Кошельки Сбер × Самокат · {_esc(city)}</title>
<link rel="preconnect" href="https://fonts.googleapis.com"/>
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin/>
<link href="https://fonts.googleapis.com/css2?family=IBM+Plex+Sans:wght@400;500;600&family=IBM+Plex+Serif:wght@500;600&display=swap" rel="stylesheet"/>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.1/dist/chart.umd.min.js"></script>
<style>
  :root {{
    --bg: #f4f1eb;
    --ink: #1a1916;
    --muted: #5a554c;
    --line: #d9d2c4;
    --card: #fffcf6;
    --sber: #1a6b4a;
    --sber2: #3d9b72;
    --smkt: #c45c26;
    --hot: #8b2e2e;
    --accent: #2a4a6b;
    --warn-bg: #fbf3f0;
  }}
  * {{ box-sizing: border-box; }}
  body {{
    margin: 0;
    font-family: "IBM Plex Sans", "Segoe UI", sans-serif;
    color: var(--ink);
    background:
      radial-gradient(ellipse 70% 45% at 0% 0%, #e4efe8 0%, transparent 55%),
      radial-gradient(ellipse 50% 35% at 100% 5%, #f0e4d6 0%, transparent 50%),
      var(--bg);
    line-height: 1.45;
  }}
  .wrap {{ max-width: 1100px; margin: 0 auto; padding: 28px 20px 72px; }}
  h1 {{
    font-family: "IBM Plex Serif", Georgia, serif;
    font-weight: 600;
    font-size: clamp(1.55rem, 3vw, 2.05rem);
    margin: 0 0 8px;
    letter-spacing: -0.02em;
  }}
  .lede {{ color: var(--muted); font-size: 1.02rem; max-width: 46em; margin: 0 0 20px; }}
  .steps {{
    list-style: none; padding: 0; margin: 0 0 22px;
    counter-reset: step; display: grid; gap: 10px;
  }}
  .steps li {{
    counter-increment: step;
    background: var(--card);
    border: 1px solid var(--line);
    border-radius: 10px;
    padding: 14px 16px 14px 52px;
    position: relative;
  }}
  .steps li::before {{
    content: counter(step);
    position: absolute; left: 14px; top: 14px;
    width: 26px; height: 26px; border-radius: 50%;
    background: var(--accent); color: #fff;
    font-size: 0.85rem; font-weight: 600;
    display: flex; align-items: center; justify-content: center;
  }}
  .steps strong {{ display: block; margin-bottom: 2px; }}
  .callout {{
    background: var(--card);
    border-left: 4px solid var(--hot);
    border-radius: 0 10px 10px 0;
    padding: 14px 18px; margin: 0 0 16px;
  }}
  .callout h2 {{ margin: 0 0 8px; font-size: 1.05rem; }}
  .callout ol {{ margin: 0; padding-left: 1.2em; }}
  section {{ margin: 48px 0 0; }}
  h2 {{
    font-family: "IBM Plex Serif", Georgia, serif;
    font-size: 1.3rem; margin: 0 0 6px;
  }}
  .section-note {{ color: var(--muted); margin: 0 0 14px; font-size: 0.94rem; }}
  .pies {{
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 16px;
    margin: 0 0 18px;
  }}
  .pie-card {{
    background: var(--card);
    border: 1px solid var(--line);
    border-radius: 12px;
    padding: 12px 14px 8px;
  }}
  .pie-card h3 {{
    margin: 0 0 4px;
    font-size: 0.95rem;
    font-weight: 600;
  }}
  .pie-card .hint {{
    color: var(--muted);
    font-size: 0.8rem;
    margin: 0 0 8px;
  }}
  .pie-card .chart-box {{
    height: 320px;
    margin: 0;
    border: 0;
    padding: 0;
    background: transparent;
  }}
  #pieLinkHint {{
    min-height: 1.4em;
    margin: 0 0 12px;
    font-size: 0.92rem;
    color: var(--accent);
    font-weight: 500;
  }}
  .chart-box {{
    background: var(--card);
    border: 1px solid var(--line);
    border-radius: 12px;
    padding: 14px 16px 8px;
    margin: 0 0 18px;
    position: relative;
    height: 420px;
  }}
  .chart-box.tall {{ height: 480px; }}
  .chart-controls {{
    display: flex; flex-wrap: wrap; gap: 8px; margin: 0 0 10px;
  }}
  .chart-controls button {{
    border: 1px solid var(--line);
    background: #f3eee4;
    border-radius: 8px;
    padding: 6px 10px;
    font: inherit;
    font-size: 0.82rem;
    cursor: pointer;
  }}
  .chart-controls button.on {{
    background: var(--sber);
    color: #fff;
    border-color: var(--sber);
  }}
  table {{
    width: 100%; border-collapse: collapse; font-size: 0.88rem;
    background: var(--card); border: 1px solid var(--line);
    border-radius: 10px; overflow: hidden;
  }}
  th, td {{
    padding: 8px 9px; border-bottom: 1px solid var(--line);
    text-align: left; vertical-align: top;
  }}
  th {{
    background: #efe9df; font-weight: 600; font-size: 0.74rem;
    text-transform: uppercase; letter-spacing: 0.03em; color: var(--muted);
  }}
  tr:last-child td {{ border-bottom: 0; }}
  tr.warn, tr.gap-hot {{ background: var(--warn-bg); }}
  .num {{ text-align: right; font-variant-numeric: tabular-nums; white-space: nowrap; }}
  .muted {{ color: var(--muted); font-size: 0.84rem; }}
  .pos {{ color: var(--hot); font-weight: 600; }}
  .neg {{ color: var(--sber); }}
  .flag {{
    display: inline-block;
    padding: 2px 8px;
    border-radius: 6px;
    background: #efe9df;
    font-size: 0.8rem;
  }}
  .legend {{
    display: flex; gap: 14px; flex-wrap: wrap;
    font-size: 0.85rem; color: var(--muted); margin-bottom: 8px;
  }}
  .legend i {{
    display: inline-block; width: 12px; height: 12px;
    border-radius: 2px; margin-right: 5px; vertical-align: -1px;
  }}
  .legend .s {{ background: var(--sber); }}
  .legend .s2 {{ background: var(--sber2); }}
  .legend .m {{ background: var(--smkt); }}
  .caveats {{
    background: var(--card); border: 1px solid var(--line);
    border-radius: 10px; padding: 16px 18px;
  }}
  .caveats ul {{ margin: 8px 0 0; padding-left: 1.2em; }}
  .caveats li {{ margin: 6px 0; color: var(--muted); }}
  footer {{
    margin-top: 40px; padding-top: 14px; border-top: 1px solid var(--line);
    color: var(--muted); font-size: 0.85rem;
  }}
  @media (max-width: 800px) {{
    .pies {{ grid-template-columns: 1fr; }}
    .chart-box {{ height: 360px; }}
    table {{ display: block; overflow-x: auto; }}
  }}
</style>
</head>
<body>
<div class="wrap">

  <header>
    <h1>Кошелёк Сбера vs кошелёк Самоката</h1>
    <p class="lede">
      Город: <strong>{_esc(city)}</strong>. Полный кошелёк клиента Сбера (структура <code>gmv</code>),
      кошелёк аудитории Самоката в Сбере (<code>smkt_gmv</code>), структура сценариев по мега и ml1,
      недоборы и NEW-эталон.
    </p>
    <ol class="steps">
      <li><strong>Кошелёк Сбера целиком</strong> Доли доменов по gmv клиентов в срезе prefs.</li>
      <li><strong>Кошелёк Самоката</strong> Мега-миссии и ml1 из scenario GMV (агрегат, не user-level).</li>
      <li><strong>Сравнение / gap</strong> Полный Сбер − аллокация сценариев через soft-bridge.</li>
      <li><strong>Эталон</strong> Specialty / фуд ml1; аудит миссий без эталона или с пустым составом.</li>
    </ol>
    <div class="callout">
      <h2>Топ-3 недобора · {_esc(city)}</h2>
      <ol>{top3_html if top3_html.strip() else "<li>Нет положительных недоборов</li>"}</ol>
    </div>
  </header>

  <section id="pies">
    <h2>Кошельки рядом · pie</h2>
    <p class="section-note">
      Слева — доли MCC в кошельке Сбера. Справа — доли мега-сценариев Самоката (не домены MCC).
      Наведите: soft-bridge подсветит связанные сегменты на второй диаграмме
      (сценарий ↔ один или несколько MCC и наоборот).
    </p>
    <p id="pieLinkHint"></p>
    <div class="pies">
      <div class="pie-card">
        <h3>Сбер · полный кошелёк</h3>
        <p class="hint">Доли MCC по gmv</p>
        <div class="chart-box"><canvas id="pieSber"></canvas></div>
      </div>
      <div class="pie-card">
        <h3>Самокат · мега-сценарии</h3>
        <p class="hint">Доли GMV по сценариям · связка с MCC через bridge</p>
        <div class="chart-box"><canvas id="pieSmkt"></canvas></div>
      </div>
    </div>
  </section>

  <section id="compare">
    <h2>Сравнение долей (столбцы)</h2>
    <p class="section-note">{_esc(gap_def)}</p>
    <div class="chart-controls" id="cmp-controls">
      <button type="button" class="on" data-series="sber_full">Сбер целиком</button>
      <button type="button" class="on" data-series="sber_smkt">Аудитория СМКТ</button>
      <button type="button" class="on" data-series="samokat">Сценарии → MCC</button>
      <button type="button" data-series="gap">Gap (п.п.)</button>
    </div>
    <div class="legend">
      <span><i class="s"></i>Сбер целиком (gmv)</span>
      <span><i class="s2"></i>аудитория Самоката (smkt_gmv)</span>
      <span><i class="m"></i>сценарии через bridge</span>
    </div>
    <div class="chart-box tall"><canvas id="chartCompare"></canvas></div>
  </section>

  <section id="sber">
    <h2>Кошелёк Сбера · {_esc(city)}</h2>
    <p class="section-note">
      <strong>Сбер целиком</strong> — доля домена в ∑ gmv.
      <strong>Аудитория СМКТ</strong> — доля в ∑ smkt_gmv.
    </p>
    <table>
      <thead>
        <tr>
          <th>MCC</th>
          <th class="num">Сбер целиком</th>
          <th class="num">Ауд. СМКТ</th>
          <th class="num">gmv</th>
          <th class="num">smkt_gmv</th>
          <th class="num">₽ / клиент</th>
        </tr>
      </thead>
      <tbody>{sber_rows}</tbody>
    </table>
  </section>

  <section id="mega">
    <h2>Кошелёк Самоката · мега-миссии</h2>
    <p class="section-note">Доля GMV мега от всего scenario GMV (Mega_Aggregates).</p>
    <div class="chart-box"><canvas id="chartMega"></canvas></div>
    <table>
      <thead>
        <tr><th>Мега</th><th class="num">Доля</th><th class="num">GMV</th></tr>
      </thead>
      <tbody>{mega_rows}</tbody>
    </table>
  </section>

  <section id="ml1">
    <h2>Кошелёк Самоката · ml1</h2>
    <p class="section-note">
      GMV мега делится поровну по сматченным ml4→ml1.
      Строки в скобках — residual. Подсветка — узкий или отсутствующий NEW-эталон.
    </p>
    <div class="chart-box tall"><canvas id="chartMl1"></canvas></div>
    <table>
      <thead>
        <tr>
          <th>ml1</th>
          <th class="num">Доля</th>
          <th class="num">GMV</th>
          <th class="num">NEW-эталон</th>
          <th>Статус</th>
        </tr>
      </thead>
      <tbody>{ml1_rows}</tbody>
    </table>
  </section>

  <section id="gaps">
    <h2>Недоборы</h2>
    <p class="section-note">
      Основной gap — vs <strong>полного</strong> кошелька Сбера.
    </p>
    <table>
      <thead>
        <tr>
          <th>Домен</th>
          <th>Тип</th>
          <th class="num">Сбер</th>
          <th class="num">Ауд. СМКТ</th>
          <th class="num">Сценарии</th>
          <th class="num">Gap</th>
          <th class="num">NEW</th>
          <th>Статус эталона</th>
          <th>Вывод</th>
        </tr>
      </thead>
      <tbody>{gap_rows}</tbody>
    </table>
  </section>

  <section id="audit">
    <h2>Аудит эталонов по миссиям</h2>
    <p class="section-note">
      Канал = н/п на MCC; grocery = food ml1 rollup; узкий specialty; пустой ml4; нулевой матч имён.
    </p>
    <table>
      <thead>
        <tr>
          <th>Мега</th>
          <th class="num">Доля</th>
          <th>MCC (bridge)</th>
          <th>Флаг</th>
          <th>Деталь эталона</th>
          <th class="num">ml4</th>
          <th class="num">mapped</th>
          <th>Состав</th>
        </tr>
      </thead>
      <tbody>{audit_rows}</tbody>
    </table>
  </section>

  <section id="howto">
    <h2>Как читать</h2>
    <div class="caveats">
      <ul>
        <li><strong>Два кошелька Сбера</strong>: gmv (целиком) и smkt_gmv (аудитория Самоката).</li>
        <li><strong>Pie</strong>: Сбер = MCC, Самокат = имена сценариев; hover через scenario_mcc_bridge.</li>
        <li><strong>Gap</strong> = полный Сбер − сценарии→MCC. Soft bridge не user-level.</li>
        <li><strong>ml1</strong> — второй разрез Самоката; grocery MCC = NEW food-lvl1 rollup (FOODZOO/FMCG минус specialty).</li>
        <li><strong>Узкий эталон</strong>: NEW (МАКС+15) &lt; {int(payload.get('etalon_thin_max') or 50)} SKU.</li>
      </ul>
    </div>
  </section>

  <footer>
    budget_gap · {_esc(city)} · prefs (gmv + smkt_gmv), Mega_Aggregates, scenario_mcc_bridge,
    descriptions (ml4), etalons_qnf NEW, mcc_l1_crosswalk.
  </footer>
</div>

<script>
const COMPARE = {_json_embed(compare_payload)};
const PIE = {_json_embed(pie_payload)};
const MEGA = {_json_embed(mega_chart)};
const ML1 = {_json_embed(ml1_chart)};

const colors = {{
  sber_full: '#1a6b4a',
  sber_smkt: '#3d9b72',
  samokat: '#c45c26',
  gap: '#8b2e2e',
}};

const seriesMeta = {{
  sber_full: {{ label: 'Сбер целиком, %', data: COMPARE.sber_full, type: 'bar' }},
  sber_smkt: {{ label: 'Ауд. Самоката, %', data: COMPARE.sber_smkt, type: 'bar' }},
  samokat: {{ label: 'Сценарии→MCC, %', data: COMPARE.samokat, type: 'bar' }},
  gap: {{ label: 'Gap, п.п.', data: COMPARE.gap, type: 'line' }},
}};

let activeSeries = new Set(['sber_full', 'sber_smkt', 'samokat']);
let compareChart, pieSber, pieSmkt;
let linkedHover = false;

function hexToRgba(hex, a) {{
  const h = hex.replace('#', '');
  const n = parseInt(h.length === 3 ? h.split('').map(c => c + c).join('') : h, 16);
  const r = (n >> 16) & 255, g = (n >> 8) & 255, b = n & 255;
  return 'rgba(' + r + ',' + g + ',' + b + ',' + a + ')';
}}

function fmtPct(v) {{
  return String(v).replace('.', ',') + '%';
}}

function pieStylesFor(side, activeSet) {{
  const colors = PIE[side].colors;
  const bg = colors.map((c, i) =>
    !activeSet || activeSet.has(i) ? c : hexToRgba(c, 0.18)
  );
  const border = colors.map((c, i) =>
    activeSet && activeSet.has(i) ? '#1a1916' : '#fffcf6'
  );
  const width = colors.map((_, i) =>
    activeSet && activeSet.has(i) ? 3 : 1
  );
  const offset = colors.map((_, i) =>
    activeSet && activeSet.has(i) ? 10 : 0
  );
  return {{ bg, border, width, offset }};
}}

function applySideStyles(chart, side, activeSet) {{
  if (!chart) return;
  const st = pieStylesFor(side, activeSet);
  const ds = chart.data.datasets[0];
  ds.backgroundColor = st.bg;
  ds.borderColor = st.border;
  ds.borderWidth = st.width;
  ds.offset = st.offset;
  chart.update('none');
}}

function linkedFromSber(idx) {{
  const key = String(idx);
  const smkt = PIE.mcc_to_smkt_idx[key] || [];
  return {{ sber: new Set([idx]), smkt: new Set(smkt) }};
}}

function linkedFromSmkt(idx) {{
  const key = String(idx);
  const sber = PIE.mega_to_sber_idx[key] || [];
  return {{ sber: new Set(sber), smkt: new Set([idx]) }};
}}

function counterpartNames(fromSide, idx) {{
  if (fromSide === 'sber') {{
    const mcc = PIE.sber.labels[idx];
    return (PIE.mcc_to_mega[mcc] || []).filter(n => PIE.samokat.labels.includes(n));
  }}
  const mega = PIE.samokat.labels[idx];
  return (PIE.mega_to_mcc[mega] || []).filter(n => PIE.sber.labels.includes(n));
}}

function applyPieHighlight(source, idx) {{
  const hint = document.getElementById('pieLinkHint');
  if (idx == null || source == null) {{
    applySideStyles(pieSber, 'sber', null);
    applySideStyles(pieSmkt, 'samokat', null);
    if (hint) hint.textContent = '';
    return;
  }}
  const link = source === 'sber' ? linkedFromSber(idx) : linkedFromSmkt(idx);
  applySideStyles(pieSber, 'sber', link.sber.size ? link.sber : null);
  applySideStyles(pieSmkt, 'samokat', link.smkt.size ? link.smkt : null);

  if (!hint) return;
  const counterparts = counterpartNames(source, idx);
  if (source === 'sber') {{
    const mcc = PIE.sber.labels[idx];
    const sShare = fmtPct(PIE.sber.values[idx]);
    if (!counterparts.length) {{
      hint.textContent = 'Сбер: ' + mcc + ' ' + sShare + ' — нет связанного сценария в bridge';
      return;
    }}
    const parts = counterparts.map(name => {{
      const i = PIE.samokat.labels.indexOf(name);
      return name + ' (' + fmtPct(PIE.samokat.values[i]) + ')';
    }});
    hint.textContent = 'Сбер: ' + mcc + ' ' + sShare + ' ↔ Самокат: ' + parts.join(', ');
  }} else {{
    const mega = PIE.samokat.labels[idx];
    const mShare = fmtPct(PIE.samokat.values[idx]);
    if (!counterparts.length) {{
      hint.textContent = 'Самокат: ' + mega + ' ' + mShare + ' — нет связанного MCC в bridge';
      return;
    }}
    const parts = counterparts.map(name => {{
      const i = PIE.sber.labels.indexOf(name);
      return name + ' (' + fmtPct(PIE.sber.values[i]) + ')';
    }});
    hint.textContent = 'Самокат: ' + mega + ' ' + mShare + ' ↔ Сбер: ' + parts.join(', ');
  }}
}}

function makePie(canvasId, side) {{
  const pie = PIE[side];
  const st = pieStylesFor(side, null);
  const prefix = side === 'sber' ? 'Сбер' : 'Самокат';
  return new Chart(document.getElementById(canvasId), {{
    type: 'pie',
    data: {{
      labels: pie.labels,
      datasets: [{{
        data: pie.values,
        backgroundColor: st.bg.slice(),
        borderColor: st.border.slice(),
        borderWidth: st.width.slice(),
        offset: st.offset.slice(),
      }}],
    }},
    options: {{
      responsive: true,
      maintainAspectRatio: false,
      plugins: {{
        legend: {{
          position: 'bottom',
          labels: {{ boxWidth: 12, font: {{ size: 10 }}, padding: 8 }},
        }},
        title: {{ display: false }},
        tooltip: {{
          callbacks: {{
            title: (items) => {{
              if (!items.length) return '';
              return prefix + ': ' + items[0].label;
            }},
            label: (c) => {{
              const share = fmtPct(c.parsed);
              const counterparts = counterpartNames(side, c.dataIndex);
              if (!counterparts.length) {{
                return share + ' · нет пары в bridge';
              }}
              const otherSide = side === 'sber' ? 'Самокат' : 'Сбер';
              const otherPie = side === 'sber' ? PIE.samokat : PIE.sber;
              const parts = counterparts.map(name => {{
                const i = otherPie.labels.indexOf(name);
                return name + ' ' + fmtPct(otherPie.values[i]);
              }});
              return share + ' ↔ ' + otherSide + ': ' + parts.join(', ');
            }},
          }},
        }},
      }},
      onHover: (evt, elements, chart) => {{
        chart.canvas.style.cursor = elements.length ? 'pointer' : 'default';
        if (linkedHover) return;
        if (!elements.length) {{
          applyPieHighlight(null, null);
          return;
        }}
        applyPieHighlight(side, elements[0].index);
      }},
    }},
  }});
}}

function setTwinActive(twin, indices) {{
  if (!twin) return;
  if (!indices.length) {{
    twin.setActiveElements([]);
    twin.tooltip.setActiveElements([], {{ x: 0, y: 0 }});
    twin.update('none');
    return;
  }}
  const meta = twin.getDatasetMeta(0);
  const active = indices
    .filter(i => meta.data[i])
    .map(i => ({{ datasetIndex: 0, index: i }}));
  twin.setActiveElements(active);
  if (active.length) {{
    const pt = meta.data[active[0].index].tooltipPosition();
    twin.tooltip.setActiveElements(active, {{ x: pt.x, y: pt.y }});
  }} else {{
    twin.tooltip.setActiveElements([], {{ x: 0, y: 0 }});
  }}
  twin.update('none');
}}

function wireLinkedPies() {{
  pieSber = makePie('pieSber', 'sber');
  pieSmkt = makePie('pieSmkt', 'samokat');

  function bind(chart, side) {{
    chart.canvas.addEventListener('mouseleave', () => {{
      linkedHover = false;
      applyPieHighlight(null, null);
      const twin = side === 'sber' ? pieSmkt : pieSber;
      setTwinActive(twin, []);
    }});
    const orig = chart.options.onHover;
    chart.options.onHover = (evt, elements, ch) => {{
      orig(evt, elements, ch);
      const twin = side === 'sber' ? pieSmkt : pieSber;
      if (!twin) return;
      linkedHover = true;
      if (!elements.length) {{
        setTwinActive(twin, []);
        linkedHover = false;
        return;
      }}
      const idx = elements[0].index;
      const link = side === 'sber' ? linkedFromSber(idx) : linkedFromSmkt(idx);
      const twinIdx = side === 'sber' ? [...link.smkt] : [...link.sber];
      setTwinActive(twin, twinIdx);
      linkedHover = false;
    }};
  }}
  bind(pieSber, 'sber');
  bind(pieSmkt, 'samokat');
}}

function buildCompareDatasets() {{
  const out = [];
  for (const key of ['sber_full', 'sber_smkt', 'samokat', 'gap']) {{
    if (!activeSeries.has(key)) continue;
    const m = seriesMeta[key];
    if (m.type === 'line') {{
      out.push({{
        type: 'line',
        label: m.label,
        data: m.data,
        borderColor: colors[key],
        backgroundColor: colors[key],
        yAxisID: 'y1',
        tension: 0.25,
        pointRadius: 4,
        borderWidth: 2,
      }});
    }} else {{
      out.push({{
        type: 'bar',
        label: m.label,
        data: m.data,
        backgroundColor: colors[key],
        borderRadius: 4,
        yAxisID: 'y',
      }});
    }}
  }}
  return out;
}}

function renderCompare() {{
  const ctx = document.getElementById('chartCompare');
  if (compareChart) compareChart.destroy();
  compareChart = new Chart(ctx, {{
    data: {{ labels: COMPARE.labels, datasets: buildCompareDatasets() }},
    options: {{
      responsive: true,
      maintainAspectRatio: false,
      interaction: {{ mode: 'index', intersect: false }},
      plugins: {{
        legend: {{ position: 'bottom' }},
        tooltip: {{
          callbacks: {{
            label: (c) => c.dataset.label + ': ' + String(c.parsed.y).replace('.', ',')
          }}
        }}
      }},
      scales: {{
        x: {{
          ticks: {{ maxRotation: 45, minRotation: 30, font: {{ size: 10 }} }},
          grid: {{ display: false }},
        }},
        y: {{
          title: {{ display: true, text: 'Доля, %' }},
          grid: {{ color: '#eee8dc' }},
        }},
        y1: {{
          position: 'right',
          title: {{ display: true, text: 'Gap, п.п.' }},
          grid: {{ drawOnChartArea: false }},
        }},
      }},
    }},
  }});
}}

document.querySelectorAll('#cmp-controls button').forEach(btn => {{
  btn.addEventListener('click', () => {{
    const key = btn.dataset.series;
    if (activeSeries.has(key)) activeSeries.delete(key);
    else activeSeries.add(key);
    if (activeSeries.size === 0) activeSeries.add(key);
    document.querySelectorAll('#cmp-controls button').forEach(b => {{
      b.classList.toggle('on', activeSeries.has(b.dataset.series));
    }});
    renderCompare();
  }});
}});

new Chart(document.getElementById('chartMega'), {{
  type: 'bar',
  data: {{
    labels: MEGA.labels,
    datasets: [{{
      label: 'Доля GMV мега, %',
      data: MEGA.share,
      backgroundColor: '#c45c26',
      borderRadius: 4,
    }}],
  }},
  options: {{
    indexAxis: 'y',
    responsive: true,
    maintainAspectRatio: false,
    plugins: {{ legend: {{ display: false }} }},
    scales: {{
      x: {{ title: {{ display: true, text: '%' }}, grid: {{ color: '#eee8dc' }} }},
      y: {{ ticks: {{ font: {{ size: 11 }} }}, grid: {{ display: false }} }},
    }},
  }},
}});

new Chart(document.getElementById('chartMl1'), {{
  type: 'bar',
  data: {{
    labels: ML1.labels,
    datasets: [
      {{
        label: 'Доля GMV ml1, %',
        data: ML1.share,
        backgroundColor: '#c45c26',
        borderRadius: 4,
        yAxisID: 'y',
      }},
      {{
        type: 'line',
        label: 'NEW-эталон, SKU',
        data: ML1.etalon,
        borderColor: '#2a4a6b',
        backgroundColor: '#2a4a6b',
        yAxisID: 'y1',
        tension: 0.2,
        pointRadius: 3,
      }},
    ],
  }},
  options: {{
    responsive: true,
    maintainAspectRatio: false,
    interaction: {{ mode: 'index', intersect: false }},
    plugins: {{ legend: {{ position: 'bottom' }} }},
    scales: {{
      x: {{ ticks: {{ maxRotation: 50, minRotation: 30, font: {{ size: 10 }} }}, grid: {{ display: false }} }},
      y: {{ title: {{ display: true, text: 'Доля, %' }}, grid: {{ color: '#eee8dc' }} }},
      y1: {{ position: 'right', title: {{ display: true, text: 'SKU' }}, grid: {{ drawOnChartArea: false }} }},
    }},
  }},
}});

wireLinkedPies();
renderCompare();
</script>
</body>
</html>
"""
    html_path.parent.mkdir(parents=True, exist_ok=True)
    html_path.write_text(html, encoding="utf-8")


def main() -> None:
    ap = argparse.ArgumentParser(description="Render budget-gap HTML")
    ap.add_argument("--payload", default=str(DEFAULT_PAYLOAD))
    ap.add_argument("--out", default=str(DEFAULT_HTML))
    args = ap.parse_args()
    render_html(Path(args.payload), Path(args.out))
    print(f"Wrote {args.out}")


if __name__ == "__main__":
    main()
