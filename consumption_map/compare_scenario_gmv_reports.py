#!/usr/bin/env python3
"""Compare old vs new scenarios_gmv_report.xlsx and write a focused HTML diff.

  python consumption_map/compare_scenario_gmv_reports.py \
    --old outputs/all_extend_da_rooms/scenarios_gmv_report_before_manual_added.xlsx \
    --new outputs/all_extend_da_rooms/scenarios_gmv_report.xlsx \
    --out outputs/all_extend_da_rooms/scenarios_gmv_diff_old_vs_new.html
"""

from __future__ import annotations

import argparse
import html
import json
from pathlib import Path

import pandas as pd

REPO = Path(__file__).resolve().parents[1]


def _fmt_gmv(x: float) -> str:
    ax = abs(x)
    if ax >= 1e9:
        return f"{x / 1e9:,.2f} млрд"
    if ax >= 1e6:
        return f"{x / 1e6:,.1f} млн"
    return f"{x:,.0f}"


def _fmt_pp(x: float) -> str:
    return f"{x:+.2f} п.п."


def _fmt_pct(x: float) -> str:
    return f"{x:+.1%}"


def _load_kpi(path: Path) -> dict[str, float]:
    df = pd.read_excel(path, sheet_name="KPI")
    out: dict[str, float] = {}
    for _, row in df.iterrows():
        k = str(row.iloc[0]).strip()
        try:
            out[k] = float(row.iloc[1])
        except (TypeError, ValueError):
            continue
    return out


def _load_scenario(path: Path) -> pd.DataFrame:
    df = pd.read_excel(path, sheet_name="Scenario_Aggregates")
    df = df.rename(
        columns={
            "Миссия": "mission",
            "GMV_аллоцированный": "gmv",
            "Чеки_аллоцированные": "checks",
            "Чеки_уникальные": "uniq_checks",
            "Пользователи": "users",
        }
    )
    df["mission"] = df["mission"].astype(str).str.strip()
    df["mega"] = df["mission"].str.split("→").str[0].str.strip()
    df["scenario"] = df["mission"].str.split("→").str[-1].str.strip()
    for c in ("gmv", "checks", "uniq_checks", "users"):
        if c in df.columns:
            df[c] = pd.to_numeric(df[c], errors="coerce").fillna(0.0)
    return df


def _load_mega(path: Path) -> pd.DataFrame:
    df = pd.read_excel(path, sheet_name="Mega_Aggregates")
    df = df.rename(columns={"mega": "mega", "GMV": "gmv", "Чеки": "checks"})
    df["mega"] = df["mega"].astype(str).str.strip()
    for c in ("gmv", "checks"):
        df[c] = pd.to_numeric(df[c], errors="coerce").fillna(0.0)
    return df


def _load_unalloc(path: Path) -> pd.DataFrame:
    """Load Unallocated_ML4 if present; empty frame when sheet is missing (aligned builds)."""
    xl = pd.ExcelFile(path)
    if "Unallocated_ML4" not in xl.sheet_names:
        return pd.DataFrame(columns=["ml4", "gmv"])
    df = pd.read_excel(path, sheet_name="Unallocated_ML4")
    df.columns = [str(c).strip() for c in df.columns]
    name_col = "ml4" if "ml4" in df.columns else df.columns[0]
    df = df.rename(columns={name_col: "ml4", "gmv": "gmv", "share_pct": "share_pct"})
    df["ml4"] = df["ml4"].astype(str).str.strip()
    df["gmv"] = pd.to_numeric(df["gmv"], errors="coerce").fillna(0.0)
    if "share_pct" in df.columns:
        df["share_pct"] = pd.to_numeric(df["share_pct"], errors="coerce").fillna(0.0)
    return df[["ml4", "gmv"] + (["share_pct"] if "share_pct" in df.columns else [])]


def _diff_keyed(
    old: pd.DataFrame,
    new: pd.DataFrame,
    key: str,
    value_cols: list[str],
) -> pd.DataFrame:
    o = old.set_index(key)
    n = new.set_index(key)
    keys = sorted(set(o.index) | set(n.index))
    rows = []
    for k in keys:
        row = {key: k}
        for c in value_cols:
            ov = float(o.at[k, c]) if k in o.index and c in o.columns else 0.0
            nv = float(n.at[k, c]) if k in n.index and c in n.columns else 0.0
            row[f"{c}_old"] = ov
            row[f"{c}_new"] = nv
            row[f"{c}_delta"] = nv - ov
            row[f"{c}_pct"] = (nv - ov) / ov if ov else (1.0 if nv else 0.0)
        if k in o.index and k in n.index:
            row["status"] = "changed" if any(abs(row[f"{c}_delta"]) > 1e-6 for c in value_cols) else "same"
        elif k in n.index:
            row["status"] = "added"
        else:
            row["status"] = "removed"
        rows.append(row)
    return pd.DataFrame(rows)


def _table(rows: list[dict], cols: list[tuple[str, str]], empty: str = "Нет отличий") -> str:
    if not rows:
        return f'<p class="muted">{html.escape(empty)}</p>'
    th = "".join(f"<th>{html.escape(h)}</th>" for h, _ in cols)
    body = []
    for r in rows:
        tds = []
        for _, key in cols:
            val = r.get(key, "")
            cls = ""
            if isinstance(val, float) and key.endswith(("_delta", "_pct", "_pp")):
                cls = "pos" if val > 0 else ("neg" if val < 0 else "")
            if key == "status":
                cls = f"st-{val}"
            tds.append(f'<td class="{cls}">{val if isinstance(val, str) else html.escape(str(val))}</td>')
        body.append("<tr>" + "".join(tds) + "</tr>")
    return f"<table><thead><tr>{th}</tr></thead><tbody>{''.join(body)}</tbody></table>"


def render_html(
    *,
    old_path: Path,
    new_path: Path,
    kpi_old: dict[str, float],
    kpi_new: dict[str, float],
    mega_diff: pd.DataFrame,
    scen_diff: pd.DataFrame,
    unalloc_diff: pd.DataFrame,
    meta_note: str,
) -> str:
    def kpi(name: str) -> tuple[float, float, float]:
        o = float(kpi_old.get(name, 0.0) or 0.0)
        n = float(kpi_new.get(name, 0.0) or 0.0)
        return o, n, n - o

    # Prefer common KPI names; fall back gracefully
    kpi_keys = []
    for k in (
        "allocated_gmv",
        "unallocated_gmv",
        "total_line_gmv",
        "checks",
        "covered_checks",
        "GMV_аллоцированный",
        "allocated_gmv_rub",
    ):
        if k in kpi_old or k in kpi_new:
            kpi_keys.append(k)
    # Also include all keys that differ
    for k in sorted(set(kpi_old) | set(kpi_new)):
        if k not in kpi_keys:
            o, n, d = kpi(k)
            if abs(d) > 1e-6:
                kpi_keys.append(k)

    kpi_rows = []
    for k in kpi_keys:
        o, n, d = kpi(k)
        pct = (d / o) if o else (1.0 if n else 0.0)
        kpi_rows.append(
            {
                "metric": html.escape(k),
                "old": _fmt_gmv(o) if "gmv" in k.lower() or "GMV" in k else f"{o:,.0f}",
                "new": _fmt_gmv(n) if "gmv" in k.lower() or "GMV" in k else f"{n:,.0f}",
                "delta": _fmt_gmv(d) if "gmv" in k.lower() or "GMV" in k else f"{d:+,.0f}",
                "pct": _fmt_pct(pct),
                "_delta": d,
            }
        )

    total_new_gmv = float(scen_diff["gmv_new"].sum()) if len(scen_diff) else 0.0
    total_old_gmv = float(scen_diff["gmv_old"].sum()) if len(scen_diff) else 0.0

    mega = mega_diff.copy()
    mega["share_old"] = mega["gmv_old"] / total_old_gmv if total_old_gmv else 0.0
    mega["share_new"] = mega["gmv_new"] / total_new_gmv if total_new_gmv else 0.0
    mega["share_pp"] = (mega["share_new"] - mega["share_old"]) * 100.0
    mega = mega.sort_values("gmv_delta", key=lambda s: s.abs(), ascending=False)

    scen = scen_diff.copy()
    scen["share_old"] = scen["gmv_old"] / total_old_gmv if total_old_gmv else 0.0
    scen["share_new"] = scen["gmv_new"] / total_new_gmv if total_new_gmv else 0.0
    scen["share_pp"] = (scen["share_new"] - scen["share_old"]) * 100.0

    added = scen[scen["status"] == "added"].sort_values("gmv_new", ascending=False)
    removed = scen[scen["status"] == "removed"].sort_values("gmv_old", ascending=False)
    changed = scen[scen["status"] == "changed"].copy()
    changed = changed[changed["gmv_delta"].abs() > 1.0]  # ignore noise
    changed = changed.sort_values("gmv_delta", key=lambda s: s.abs(), ascending=False)

    un = unalloc_diff.copy()
    un = un[un["gmv_delta"].abs() > 1.0].sort_values("gmv_delta", key=lambda s: s.abs(), ascending=False)

    def mega_rows(df: pd.DataFrame) -> list[dict]:
        out = []
        for _, r in df.iterrows():
            out.append(
                {
                    "mega": html.escape(str(r["mega"])),
                    "old": _fmt_gmv(r["gmv_old"]),
                    "new": _fmt_gmv(r["gmv_new"]),
                    "delta": _fmt_gmv(r["gmv_delta"]),
                    "pct": _fmt_pct(r["gmv_pct"]),
                    "pp": _fmt_pp(r["share_pp"]),
                    "status": r["status"],
                    "_delta": r["gmv_delta"],
                }
            )
        return out

    def scen_rows(df: pd.DataFrame, limit: int = 80) -> list[dict]:
        out = []
        for _, r in df.head(limit).iterrows():
            out.append(
                {
                    "mission": html.escape(str(r["mission"])),
                    "old": _fmt_gmv(r["gmv_old"]),
                    "new": _fmt_gmv(r["gmv_new"]),
                    "delta": _fmt_gmv(r["gmv_delta"]),
                    "pct": _fmt_pct(r["gmv_pct"]),
                    "pp": _fmt_pp(r["share_pp"]),
                    "status": r["status"],
                    "_delta": r["gmv_delta"],
                }
            )
        return out

    def un_rows(df: pd.DataFrame, limit: int = 60) -> list[dict]:
        out = []
        for _, r in df.head(limit).iterrows():
            out.append(
                {
                    "ml4": html.escape(str(r["ml4"])),
                    "old": _fmt_gmv(r["gmv_old"]),
                    "new": _fmt_gmv(r["gmv_new"]),
                    "delta": _fmt_gmv(r["gmv_delta"]),
                    "pct": _fmt_pct(r["gmv_pct"]),
                    "status": r["status"],
                    "_delta": r["gmv_delta"],
                }
            )
        return out

    # highlight class via string replace after — keep numeric in class via pos/neg from _delta
    def with_signed(rows: list[dict], fields: list[str]) -> list[dict]:
        for r in rows:
            for f in fields:
                # already formatted strings; mark via sibling
                pass
            # inject class hints already handled in _table via float keys — convert:
            r["delta_f"] = r.pop("_delta", 0.0)
        return rows

    # Rebuild tables with float delta for coloring
    def table_gmv(rows: list[dict], name_key: str, name_label: str) -> str:
        if not rows:
            return '<p class="muted">Нет отличий</p>'
        th = f"<th>{html.escape(name_label)}</th><th>Старый GMV</th><th>Новый GMV</th><th>Δ GMV</th><th>Δ %</th>"
        if any("pp" in r for r in rows):
            th += "<th>Δ доля</th>"
        th += "<th>Статус</th>"
        body = []
        for r in rows:
            d = float(r.get("_delta", 0.0))
            cls = "pos" if d > 0 else ("neg" if d < 0 else "")
            cells = [
                f"<td>{r[name_key]}</td>",
                f"<td>{r['old']}</td>",
                f"<td>{r['new']}</td>",
                f'<td class="{cls}">{r["delta"]}</td>',
                f'<td class="{cls}">{r["pct"]}</td>',
            ]
            if "pp" in r:
                cells.append(f'<td class="{cls}">{r["pp"]}</td>')
            cells.append(f'<td class="st-{r["status"]}">{r["status"]}</td>')
            body.append("<tr>" + "".join(cells) + "</tr>")
        return f"<table><thead><tr>{th}</tr></thead><tbody>{''.join(body)}</tbody></table>"

    kpi_html_rows = []
    for r in kpi_rows:
        d = float(r["_delta"])
        cls = "pos" if d > 0 else ("neg" if d < 0 else "")
        kpi_html_rows.append(
            "<tr>"
            f"<td>{r['metric']}</td><td>{r['old']}</td><td>{r['new']}</td>"
            f'<td class="{cls}">{r["delta"]}</td><td class="{cls}">{r["pct"]}</td>'
            "</tr>"
        )
    kpi_table = (
        "<table><thead><tr><th>KPI</th><th>Старый</th><th>Новый</th><th>Δ</th><th>Δ %</th></tr></thead>"
        f"<tbody>{''.join(kpi_html_rows)}</tbody></table>"
        if kpi_html_rows
        else '<p class="muted">Нет KPI для сравнения</p>'
    )

    summary = {
        "missions_added": int((scen["status"] == "added").sum()),
        "missions_removed": int((scen["status"] == "removed").sum()),
        "missions_changed": int((changed["status"] == "changed").sum()) if len(changed) else int((scen["status"] == "changed").sum()),
        "gmv_total_old": total_old_gmv,
        "gmv_total_new": total_new_gmv,
        "gmv_total_delta": total_new_gmv - total_old_gmv,
        "top_up": [
            {"mission": str(r.mission), "delta": float(r.gmv_delta)}
            for _, r in changed.head(5).iterrows()
        ]
        if len(changed)
        else [],
        "top_down": [
            {"mission": str(r.mission), "delta": float(r.gmv_delta)}
            for _, r in changed.sort_values("gmv_delta").head(5).iterrows()
        ]
        if len(changed)
        else [],
    }

    return f"""<!DOCTYPE html>
<html lang="ru">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>Diff: старые vs новые сценарии GMV</title>
<style>
:root {{
  --bg: #f6f3ee;
  --ink: #1c1917;
  --muted: #78716c;
  --line: #e7e5e4;
  --card: #fffdf9;
  --pos: #166534;
  --neg: #9f1239;
  --accent: #0f766e;
}}
* {{ box-sizing: border-box; }}
body {{
  margin: 0; font-family: "IBM Plex Sans", "Segoe UI", sans-serif;
  background: radial-gradient(1200px 600px at 10% -10%, #dff7f3 0%, transparent 55%),
              radial-gradient(900px 500px at 100% 0%, #fde68a55 0%, transparent 50%),
              var(--bg);
  color: var(--ink); line-height: 1.45;
}}
main {{ max-width: 1180px; margin: 0 auto; padding: 32px 20px 64px; }}
h1 {{ font-size: 1.7rem; margin: 0 0 8px; letter-spacing: -0.02em; }}
h2 {{ font-size: 1.15rem; margin: 28px 0 10px; }}
.lead {{ color: var(--muted); margin: 0 0 18px; max-width: 70ch; }}
.meta {{ font-size: 0.9rem; color: var(--muted); margin-bottom: 22px; }}
.meta code {{ background: #fff; border: 1px solid var(--line); padding: 1px 6px; border-radius: 4px; }}
.cards {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(160px, 1fr)); gap: 12px; margin: 16px 0 8px; }}
.card {{ background: var(--card); border: 1px solid var(--line); border-radius: 12px; padding: 14px 16px; }}
.card .lbl {{ font-size: 0.75rem; color: var(--muted); text-transform: uppercase; letter-spacing: 0.04em; }}
.card .val {{ font-size: 1.25rem; font-weight: 650; margin-top: 4px; }}
table {{ width: 100%; border-collapse: collapse; background: var(--card); border: 1px solid var(--line); border-radius: 12px; overflow: hidden; font-size: 0.9rem; }}
th, td {{ padding: 8px 10px; border-bottom: 1px solid var(--line); text-align: left; vertical-align: top; }}
th {{ background: #fafaf9; font-size: 0.75rem; text-transform: uppercase; letter-spacing: 0.03em; color: var(--muted); }}
tr:last-child td {{ border-bottom: 0; }}
.pos {{ color: var(--pos); font-weight: 600; }}
.neg {{ color: var(--neg); font-weight: 600; }}
.st-added {{ color: var(--pos); }}
.st-removed {{ color: var(--neg); }}
.st-changed {{ color: var(--accent); }}
.st-same {{ color: var(--muted); }}
.muted {{ color: var(--muted); }}
footer {{ margin-top: 36px; color: var(--muted); font-size: 0.85rem; }}
</style>
</head>
<body>
<main>
  <h1>Разница GMV: старые vs новые сценарии</h1>
  <p class="lead">Сравнение отчётов до и после расширения каталога сценариев (manual_added). Показаны места, где изменились GMV/доли на уровне KPI, мегасценариев, миссий и unallocated ML4.</p>
  <div class="meta">
    <div>Старый: <code>{html.escape(str(old_path))}</code></div>
    <div>Новый: <code>{html.escape(str(new_path))}</code></div>
    <div>{html.escape(meta_note)}</div>
  </div>

  <div class="cards">
    <div class="card"><div class="lbl">GMV сценариев (old)</div><div class="val">{_fmt_gmv(total_old_gmv)}</div></div>
    <div class="card"><div class="lbl">GMV сценариев (new)</div><div class="val">{_fmt_gmv(total_new_gmv)}</div></div>
    <div class="card"><div class="lbl">Δ total GMV</div><div class="val">{_fmt_gmv(total_new_gmv - total_old_gmv)}</div></div>
    <div class="card"><div class="lbl">Миссий + / − / Δ</div><div class="val">{summary['missions_added']} / {summary['missions_removed']} / {int((scen['status']=='changed').sum())}</div></div>
  </div>

  <h2>KPI</h2>
  {kpi_table}

  <h2>Мегасценарии</h2>
  {table_gmv(mega_rows(mega[mega['status'] != 'same']), 'mega', 'Мега')}

  <h2>Новые миссии</h2>
  {table_gmv(scen_rows(added), 'mission', 'Миссия')}

  <h2>Удалённые миссии</h2>
  {table_gmv(scen_rows(removed), 'mission', 'Миссия')}

  <h2>Миссии с наибольшим |Δ GMV|</h2>
  {table_gmv(scen_rows(changed, 100), 'mission', 'Миссия')}

  <h2>Unallocated ML4 — крупнейшие сдвиги</h2>
  {table_gmv(un_rows(un), 'ml4', 'ML4')}

  <footer>generated by compare_scenario_gmv_reports.py · summary={html.escape(json.dumps(summary, ensure_ascii=False))}</footer>
</main>
</body>
</html>
"""


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--old",
        type=Path,
        default=REPO / "outputs/all_extend_da_rooms/scenarios_gmv_report_before_manual_added.xlsx",
    )
    ap.add_argument(
        "--new",
        type=Path,
        default=REPO / "outputs/all_extend_da_rooms/scenarios_gmv_report.xlsx",
    )
    ap.add_argument(
        "--out",
        type=Path,
        default=REPO / "outputs/all_extend_da_rooms/scenarios_gmv_diff_old_vs_new.html",
    )
    ap.add_argument("--meta-note", default="")
    args = ap.parse_args()

    kpi_old = _load_kpi(args.old)
    kpi_new = _load_kpi(args.new)
    scen_old = _load_scenario(args.old)
    scen_new = _load_scenario(args.new)
    mega_old = _load_mega(args.old)
    mega_new = _load_mega(args.new)
    un_old = _load_unalloc(args.old)
    un_new = _load_unalloc(args.new)

    scen_diff = _diff_keyed(scen_old, scen_new, "mission", ["gmv", "checks"])
    # preserve mega/scenario labels
    label = pd.concat(
        [
            scen_old[["mission", "mega", "scenario"]],
            scen_new[["mission", "mega", "scenario"]],
        ]
    ).drop_duplicates("mission")
    scen_diff = scen_diff.merge(label, on="mission", how="left")

    mega_diff = _diff_keyed(mega_old, mega_new, "mega", ["gmv", "checks"])
    if un_old.empty or un_new.empty:
        unalloc_diff = pd.DataFrame(columns=["ml4", "gmv_old", "gmv_new", "gmv_delta", "gmv_pct", "status"])
        missing = []
        if un_old.empty:
            missing.append("old")
        if un_new.empty:
            missing.append("new")
        unalloc_skip_note = (
            f"Unallocated_ML4 отсутствует в {'/'.join(missing)} — блок ML4 пропущен."
        )
    else:
        unalloc_diff = _diff_keyed(un_old, un_new, "ml4", ["gmv"])
        unalloc_skip_note = ""

    note = args.meta_note or (
        "Старый отчёт — до manual_added; новый — после assign+report на расширенном каталоге сценариев."
    )
    if unalloc_skip_note:
        note = f"{note} {unalloc_skip_note}".strip()
    html_out = render_html(
        old_path=args.old,
        new_path=args.new,
        kpi_old=kpi_old,
        kpi_new=kpi_new,
        mega_diff=mega_diff,
        scen_diff=scen_diff,
        unalloc_diff=unalloc_diff,
        meta_note=note,
    )
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(html_out, encoding="utf-8")
    print(f"Wrote {args.out}")
    print(
        f"missions added={(scen_diff.status=='added').sum()} "
        f"removed={(scen_diff.status=='removed').sum()} "
        f"changed={(scen_diff.status=='changed').sum()} "
        f"gmv_delta={scen_diff.gmv_delta.sum():,.0f}"
    )


if __name__ == "__main__":
    main()
