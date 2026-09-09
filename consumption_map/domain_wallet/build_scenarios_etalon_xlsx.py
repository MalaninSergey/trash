#!/usr/bin/env python3
"""Per-scenario NEW etalon from scenario cats_runtime × etalon lvl4 (not MCC rollup).

  python consumption_map/domain_wallet/build_scenarios_etalon_xlsx.py
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

import pandas as pd
from openpyxl import load_workbook
from openpyxl.utils import get_column_letter

PKG = Path(__file__).resolve().parent
ROOT = PKG.parent
REPO = ROOT.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from domain_wallet.build_domain_wallet_report import (  # noqa: E402
    annotate_inseparable_leaves,
    load_mega_mcc_bundles,
)


def _norm(s: object) -> str:
    t = str(s).strip().lower().replace("ё", "е")
    return re.sub(r"\s+", " ", t)


def _first_existing(cands: list[Path]) -> Path:
    for p in cands:
        if p.exists():
            return p
    raise FileNotFoundError("None of:\n" + "\n".join(str(c) for c in cands))


def load_etalon_by_lvl4(path: Path) -> pd.DataFrame:
    et = pd.read_excel(path, sheet_name="Эталоны")
    et.columns = [str(c).strip() for c in et.columns]
    et = et.rename(
        columns={
            "NEW Эталон МАКСы": "etalon_max",
            "NEW Эталон 15 мин": "etalon_15",
            "NEW Эталон МАКС + 15 мин": "etalon_sum",
        }
    )
    for c in ("etalon_max", "etalon_15", "etalon_sum"):
        et[c] = pd.to_numeric(et[c], errors="coerce").fillna(0.0)
    et["lvl4_n"] = et["lvl4"].map(_norm)
    et["lvl3_n"] = et["lvl3"].map(_norm) if "lvl3" in et.columns else ""
    for col in ("lvl1", "lvl2", "lvl3", "lvl4"):
        if col in et.columns:
            et[col] = et[col].astype(str)
        else:
            et[col] = ""
    return et


def build_etalon_indexes(
    et: pd.DataFrame,
) -> tuple[pd.DataFrame, dict[str, list[str]]]:
    by4 = (
        et.groupby("lvl4_n", as_index=False)
        .agg(
            etalon_sum=("etalon_sum", "sum"),
            etalon_max=("etalon_max", "sum"),
            etalon_15=("etalon_15", "sum"),
            lvl4=("lvl4", "first"),
            lvl3=("lvl3", "first"),
            lvl2=("lvl2", "first"),
            lvl1=("lvl1", "first"),
        )
        .set_index("lvl4_n")
    )
    lvl3_to_lvl4: dict[str, list[str]] = {}
    for lvl4_n, row in by4.iterrows():
        l3 = _norm(row.get("lvl3") or "")
        if not l3:
            continue
        lvl3_to_lvl4.setdefault(l3, []).append(str(lvl4_n))
    return by4, lvl3_to_lvl4


def resolve_scenario_lvl4(
    cats: list[str],
    by4: pd.DataFrame,
    lvl3_to_lvl4: dict[str, list[str]],
) -> tuple[set[str], int]:
    """Map scenario category names → set of etalon lvl4 keys. Returns (keys, n_via_lvl3)."""
    keys: set[str] = set()
    via_lvl3 = 0
    for cat_n in cats:
        if cat_n in by4.index:
            keys.add(cat_n)
            continue
        children = lvl3_to_lvl4.get(cat_n) or []
        if children:
            via_lvl3 += 1
            keys.update(children)
    return keys, via_lvl3


def load_scenario_gmv(gmv_path: Path) -> dict[str, float]:
    agg = pd.read_excel(gmv_path, sheet_name="Scenario_Aggregates")
    agg.columns = [str(c).strip() for c in agg.columns]
    gcol = "GMV_аллоцированный" if "GMV_аллоцированный" in agg.columns else "GMV"
    out: dict[str, float] = {}
    for _, r in agg.iterrows():
        mission = str(r["Миссия"]).strip()
        out[mission] = float(pd.to_numeric(r[gcol], errors="coerce") or 0.0)
    return out


def load_additions(path: Path) -> dict[tuple[str, str], list[str]]:
    """Parse manual lvl4 placements from Excel sheet `добавить в сценарии`."""
    raw = pd.read_excel(path, sheet_name="добавить в сценарии")
    raw.columns = [str(c).strip() for c in raw.columns]
    lvl_cols = [c for c in raw.columns if str(c).strip().startswith("Lvl4")]
    out: dict[tuple[str, str], list[str]] = {}
    for _, r in raw.iterrows():
        mega = str(r.get("Мега") or "").strip()
        sub = str(r.get("Сценарий") or "").strip()
        if not mega or not sub:
            continue
        vals: list[str] = []
        for c in lvl_cols:
            v = str(r.get(c) or "").strip()
            if not v or v.lower() == "nan":
                continue
            vals.append(v)
        if not vals:
            continue
        key = (mega, sub)
        out.setdefault(key, [])
        out[key].extend(vals)
    for key, vals in list(out.items()):
        out[key] = list(dict.fromkeys(vals))
    return out


def extend_scenarios_with_additions(
    scenarios: list[dict],
    additions: dict[tuple[str, str], list[str]],
    *,
    coffee_target: tuple[str, str] = ("Готовлю дома", "Завтрак выходного дня"),
    coffee_lvl4: str = "Кофе молотый в дрип-пакетах",
) -> list[dict]:
    """Inject manual lvl4 additions into cats_runtime before etalon allocation."""
    out: list[dict] = []
    matched: set[tuple[str, str]] = set()
    coffee_hit = False
    for s in scenarios:
        row = dict(s)
        mega = str(row.get("mega") or "").strip()
        sub = str(row.get("sub") or row.get("scenario") or "").strip()
        cats = [str(x).strip() for x in (row.get("cats_runtime") or []) if str(x).strip()]
        key = (mega, sub)
        if key in additions:
            matched.add(key)
            cats.extend(additions[key])
        if key == coffee_target:
            cats.append(coffee_lvl4)
            coffee_hit = True
        row["cats_runtime"] = list(dict.fromkeys(cats))
        out.append(row)
    missed = sorted(set(additions) - matched)
    if missed:
        print(
            "WARNING: additions not matched to scenarios: "
            + "; ".join(f"{m} → {s}" for m, s in missed[:10]),
            flush=True,
        )
    if not coffee_hit:
        print(
            f"WARNING: coffee target not found: {coffee_target[0]} → {coffee_target[1]}",
            flush=True,
        )
    return out


def scenario_etalon_rows(
    scenarios: list[dict],
    by4: pd.DataFrame,
    lvl3_to_lvl4: dict[str, list[str]],
    gmv_by_mission: dict[str, float],
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Allocate each etalon lvl4 across scenarios that contain it, weights = scenario GMV."""
    meta: dict[str, dict] = {}
    scen_lvl4: dict[str, set[str]] = {}
    scen_via_lvl3: dict[str, int] = {}
    scen_n_rt: dict[str, int] = {}
    lvl4_owners: dict[str, list[str]] = {}

    for s in scenarios:
        mega = str(s.get("mega") or "").strip()
        sub = str(s.get("sub") or s.get("scenario") or "").strip()
        mission = str(s.get("label") or f"{mega} → {sub}").strip()
        cats = list(
            dict.fromkeys(_norm(x) for x in (s.get("cats_runtime") or []) if str(x).strip())
        )
        keys, via_lvl3 = resolve_scenario_lvl4(cats, by4, lvl3_to_lvl4)
        meta[mission] = {"mega": mega, "sub": sub, "mission": mission}
        scen_lvl4[mission] = keys
        scen_via_lvl3[mission] = via_lvl3
        scen_n_rt[mission] = len(cats)
        for k in keys:
            lvl4_owners.setdefault(k, []).append(mission)

    # Each lvl4 goes wholly to the owning scenario with the largest GMV (no fractions).
    alloc_sum: dict[str, int] = {m: 0 for m in meta}
    alloc_max: dict[str, int] = {m: 0 for m in meta}
    alloc_15: dict[str, int] = {m: 0 for m in meta}
    assigned_keys: dict[str, list[str]] = {m: [] for m in meta}
    shared_cats: dict[str, int] = {m: 0 for m in meta}
    detail_rows: list[dict] = []

    for lvl4_n, owners in lvl4_owners.items():
        row = by4.loc[lvl4_n]
        es = int(round(float(row["etalon_sum"])))
        em = int(round(float(row["etalon_max"])))
        e15 = int(round(float(row["etalon_15"])))
        n_own = len(owners)
        winner = max(
            owners,
            key=lambda m: (float(gmv_by_mission.get(m) or 0.0), m),
        )
        for m in owners:
            if n_own > 1:
                shared_cats[m] += 1
        alloc_sum[winner] += es
        alloc_max[winner] += em
        alloc_15[winner] += e15
        assigned_keys[winner].append(str(lvl4_n))
        others = [meta[m]["sub"] for m in owners if m != winner]
        detail_rows.append(
            {
                "Мега": meta[winner]["mega"],
                "Сценарий": meta[winner]["sub"],
                "Миссия": winner,
                "Категория эталона (lvl4)": str(row["lvl4"]),
                "Lvl1 эталона": row.get("lvl1"),
                "Сценариев с категорией": n_own,
                "Эталон 15 мин": e15,
                "Эталон МАКС": em,
                "Эталон сумма": es,
                "Другие сценарии с категорией": " · ".join(others[:8])
                + ("…" if len(others) > 8 else ""),
            }
        )

    summary_rows: list[dict] = []
    for mission, info in meta.items():
        keys = assigned_keys[mission]
        n_rt = scen_n_rt[mission]
        n_m = len(keys)
        sum_s = alloc_sum[mission]
        names = [
            str(by4.loc[k, "lvl4"])
            for k in sorted(keys, key=lambda x: -float(by4.loc[x, "etalon_sum"]))
        ][:12]
        summary_rows.append(
            {
                "Мега": info["mega"],
                "Сценарий": info["sub"],
                "Миссия": mission,
                "Категорий в сценарии (runtime)": n_rt,
                "Категорий с эталоном": n_m,
                "из них через lvl3": scen_via_lvl3[mission],
                "Категорий с пересечением": shared_cats[mission],
                "Покрытие категорий, %": round(100 * n_m / n_rt, 1) if n_rt else None,
                "Эталон 15 мин": alloc_15[mission],
                "Эталон МАКС": alloc_max[mission],
                "Эталон сумма": sum_s,
                "Статус эталона": (
                    "н/д" if n_m == 0 else ("широкий" if sum_s >= 50 else "узкий")
                ),
                "Категории эталона (фрагмент)": " · ".join(names)
                + ("…" if len(keys) > 12 else ""),
            }
        )

    used_sum = int(sum(int(round(float(by4.loc[k, "etalon_sum"]))) for k in lvl4_owners))
    alloc_total = int(sum(alloc_sum.values()))
    if used_sum != alloc_total:
        print(
            f"WARNING: etalon alloc drift used={used_sum} alloc={alloc_total}",
            flush=True,
        )

    unused_rows = []
    for lvl4_n, row in by4.iterrows():
        if str(lvl4_n) in lvl4_owners:
            continue
        unused_rows.append(
            {
                "Lvl1": row.get("lvl1"),
                "Lvl2": row.get("lvl2"),
                "Lvl3": row.get("lvl3"),
                "Lvl4": row.get("lvl4"),
                "Эталон 15 мин": int(round(float(row["etalon_15"]))),
                "Эталон МАКС": int(round(float(row["etalon_max"]))),
                "Эталон сумма": int(round(float(row["etalon_sum"]))),
            }
        )
    unused = pd.DataFrame(unused_rows)
    if not unused.empty:
        unused = unused.sort_values(
            ["Эталон сумма", "Lvl1", "Lvl4"], ascending=[False, True, True]
        ).reset_index(drop=True)

    return pd.DataFrame(summary_rows), pd.DataFrame(detail_rows), unused


def _autofit(path: Path) -> None:
    wb = load_workbook(path)
    for ws in wb.worksheets:
        for i, col in enumerate(ws.columns, 1):
            maxlen = 0
            for cell in col[:100]:
                maxlen = max(maxlen, len(str(cell.value)) if cell.value is not None else 0)
            ws.column_dimensions[get_column_letter(i)].width = min(52, max(12, maxlen + 2))
        ws.auto_filter.ref = ws.dimensions
        ws.freeze_panes = "A2"
    wb.save(path)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(ROOT / "outputs" / "scenarios_with_etalon.xlsx"))
    ap.add_argument(
        "--catalog",
        default=str(REPO / "outputs" / "all_extend_da_rooms" / "scenarios_catalog_full.json"),
    )
    ap.add_argument(
        "--etalons",
        default="",
        help="Path to etalons xlsx (default: inputs/etalons_qnf.xlsx or Downloads)",
    )
    ap.add_argument(
        "--leaf-bridge",
        default=str(ROOT / "inputs" / "scenario_leaf_mcc_bridge_no_marketplace.csv"),
    )
    ap.add_argument(
        "--add-scenarios-xlsx",
        default=str(Path.home() / "Downloads" / "Добавить в сценарии.xlsx"),
        help="Manual lvl4 -> scenario placements for currently unused categories",
    )
    args = ap.parse_args()

    catalog_path = Path(args.catalog)
    etalon_path = Path(args.etalons) if args.etalons else _first_existing(
        [
            ROOT / "inputs" / "etalons_qnf.xlsx",
            Path.home() / "Downloads" / "Эталоны QNF 3.0 (05.08).xlsx",
        ]
    )
    catalog = json.loads(catalog_path.read_text(encoding="utf-8"))
    scenarios = catalog["scenarios"]
    et = load_etalon_by_lvl4(etalon_path)
    by4, lvl3_to_lvl4 = build_etalon_indexes(et)
    add_path = Path(args.add_scenarios_xlsx)
    additions = load_additions(add_path) if add_path.exists() else {}
    if additions:
        scenarios = extend_scenarios_with_additions(scenarios, additions)
        print(
            f"Manual scenario additions from {add_path.name}: "
            f"{len(additions)} scenario rows, "
            f"{sum(len(v) for v in additions.values()) + 1} lvl4 incl. coffee drips",
            flush=True,
        )
    else:
        scenarios = extend_scenarios_with_additions(scenarios, {})

    gmv_path = _first_existing(
        [
            REPO / "outputs" / "all_extend_da_rooms" / "scenarios_gmv_report.xlsx",
            ROOT / "inputs" / "scenarios_gmv_report.xlsx",
        ]
    )
    gmv_by_mission = load_scenario_gmv(gmv_path)
    summary, detail, unused = scenario_etalon_rows(
        scenarios, by4, lvl3_to_lvl4, gmv_by_mission
    )

    # MCC + split tags from leaf bridge
    bridge = pd.read_csv(args.leaf_bridge)
    bridge["mission"] = bridge["mission"].astype(str).str.strip()
    mega_bundles = load_mega_mcc_bundles(ROOT / "inputs" / "scenario_mcc_bridge.csv")
    leaf = summary.rename(columns={"Миссия": "mission"})[["mission"]].copy()
    leaf = leaf.merge(
        bridge[["mission", "mcc_group", "seed_source", "needs_review"]],
        on="mission",
        how="left",
    )
    leaf["mega"] = leaf["mission"].str.split("→").str[0].str.strip()
    leaf["scenario"] = leaf["mission"].str.split("→").str[-1].str.strip()
    leaf["GMV"] = 0.0
    leaf = annotate_inseparable_leaves(leaf, mega_bundles)
    summary = summary.merge(
        leaf[
            [
                "mission",
                "mcc_group",
                "split_tag",
                "inseparable_with",
            ]
        ].rename(
            columns={
                "mission": "Миссия",
                "mcc_group": "Домен (MCC)",
                "split_tag": "Тег",
                "inseparable_with": "Пересечение с доменами",
            }
        ),
        on="Миссия",
        how="left",
    )

    gmv = pd.DataFrame(
        {
            "Миссия": list(gmv_by_mission.keys()),
            "GMV сценария, ₽": list(gmv_by_mission.values()),
        }
    )
    total = float(gmv["GMV сценария, ₽"].sum())
    gmv["Доля в кошельке сценариев, %"] = (
        gmv["GMV сценария, ₽"] / total * 100 if total else 0.0
    ).round(3)
    summary = summary.merge(gmv, on="Миссия", how="left")

    col_order = [
        "Мега",
        "Сценарий",
        "Миссия",
        "Домен (MCC)",
        "Тег",
        "Пересечение с доменами",
        "GMV сценария, ₽",
        "Доля в кошельке сценариев, %",
        "Категорий в сценарии (runtime)",
        "Категорий с эталоном",
        "из них через lvl3",
        "Категорий с пересечением",
        "Покрытие категорий, %",
        "Эталон 15 мин",
        "Эталон МАКС",
        "Эталон сумма",
        "Статус эталона",
        "Категории эталона (фрагмент)",
    ]
    summary = summary[[c for c in col_order if c in summary.columns]]
    summary = summary.sort_values(
        ["Домен (MCC)", "Эталон сумма", "GMV сценария, ₽"],
        ascending=[True, False, False],
    ).reset_index(drop=True)

    if not detail.empty:
        uniq_pool = float(detail["Эталон сумма"].sum())
        alloc_pool = float(summary["Эталон сумма"].sum())
        alloc_15 = float(summary["Эталон 15 мин"].sum())
        alloc_max = float(summary["Эталон МАКС"].sum())
    else:
        uniq_pool = alloc_pool = alloc_15 = alloc_max = 0.0
    unused_sum = float(unused["Эталон сумма"].sum()) if not unused.empty else 0.0
    file_sum = float(by4["etalon_sum"].sum())

    spravka = pd.DataFrame(
        [
            {
                "поле": "метод",
                "значение": (
                    "Эталон на сценарий: cats_runtime → lvl4 NEW; "
                    "пересекающаяся категория целиком уходит в сценарий с наибольшим GMV (без долей)."
                ),
            },
            {
                "поле": "колонки эталона",
                "значение": "Эталон 15 мин / Эталон МАКС / Эталон сумма — целые SKU; каждая lvl4 ровно в одном сценарии.",
            },
            {
                "поле": "инвариант",
                "значение": (
                    f"Σ долей по сценариям = Σ уникальных lvl4 в сценариях "
                    f"({alloc_pool:.1f} ≈ {uniq_pool:.1f}); "
                    f"файл эталонов {file_sum:.0f}; вне сценариев {unused_sum:.0f}."
                ),
            },
            {
                "поле": "источник категорий",
                "значение": str(catalog_path),
            },
            {
                "поле": "источник эталона",
                "значение": str(etalon_path),
            },
            {
                "поле": "источник ручных добавлений",
                "значение": str(add_path) if add_path.exists() else "нет",
            },
            {
                "поле": "источник GMV",
                "значение": str(gmv_path),
            },
            {
                "поле": "покрытие",
                "значение": (
                    f"Среднее покрытие категорий: "
                    f"{summary['Покрытие категорий, %'].mean():.1f}% "
                    f"(old catalog vs NEW etalon)."
                ),
            },
        ]
    )

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    with pd.ExcelWriter(out, engine="openpyxl") as xl:
        summary.to_excel(xl, sheet_name="Сценарии", index=False)
        unused.to_excel(xl, sheet_name="Вне_сценариев", index=False)
        detail.sort_values(
            ["Миссия", "Эталон сумма"], ascending=[True, False]
        ).to_excel(xl, sheet_name="Категории_эталона", index=False)
        spravka.to_excel(xl, sheet_name="Справка", index=False)
    _autofit(out)

    auto = summary[summary["Мега"] == "Авто"][
        ["Сценарий", "Эталон 15 мин", "Эталон МАКС", "Эталон сумма", "GMV сценария, ₽"]
    ]
    print(f"Wrote {out}")
    print(auto.to_string(index=False))
    print(
        f"All scenarios: {len(summary)}; "
        f"sum 15={alloc_15:.1f} max={alloc_max:.1f} total={alloc_pool:.1f} "
        f"(unique pool≈{uniq_pool:.1f}); unused cats={len(unused)} SKU={unused_sum:.0f}; "
        f"file total={file_sum:.0f}"
    )


if __name__ == "__main__":
    main()
