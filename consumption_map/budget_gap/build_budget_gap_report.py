#!/usr/bin/env python3
"""Budget-gap report: full Sber wallet × Samokat scenarios (mega + ml1) × NEW etalon.

Research framing:
  1. Overall Sber client wallet by MCC (gmv shares) + Samokat-audience wallet (smkt_gmv)
  2. Samokat scenario wallet by mega-mission and by ml1 (aggregated, not user-level)
  3. Gaps vs soft bridge mega→MCC
  4. NEW etalon overlay + audit of missions/ml1 without applicable etalon

Run:
  python consumption_map/budget_gap/build_budget_gap_report.py
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import pandas as pd

PKG = Path(__file__).resolve().parent
ROOT = PKG.parent  # consumption_map/
REPO = ROOT.parent
DEFAULT_DOWNLOADS = Path.home() / "Downloads"
DEFAULT_CITY = "Москва"

ETALON_THIN_MAX = 50.0
GAP_MATERIAL_PP = 0.01  # 1 п.п.

sys.path.insert(0, str(ROOT))
from mega_categories import load_mega_category_map  # noqa: E402


def _first_existing(candidates: list[Path]) -> Path:
    for p in candidates:
        if p.exists():
            return p
    raise FileNotFoundError("None of:\n" + "\n".join(str(c) for c in candidates))


def resolve_paths(args: argparse.Namespace) -> dict[str, Path]:
    downloads = Path(args.downloads)
    repo = Path(args.repo)
    inputs = ROOT / "inputs"
    return {
        "prefs": _first_existing(
            [
                inputs / "prefs_samokat_audience.xlsx",
                inputs / "Анализ предпочтений основной аудитории Самоката (1).xlsx",
                downloads / "prefs_samokat_audience.xlsx",
                downloads / "Анализ предпочтений основной аудитории Самоката (1).xlsx",
                downloads / "Анализ предпочтений основной аудитории Самоката (1) (1).xlsx",
            ]
        ),
        "etalons": _first_existing(
            [
                inputs / "etalons_qnf.xlsx",
                inputs / "Эталоны QNF 3.0 (05.08).xlsx",
                downloads / "Эталоны QNF 3.0 (05.08).xlsx",
                downloads / "etalons_qnf.xlsx",
            ]
        ),
        "scenarios": _first_existing(
            [
                inputs / "scenarios_gmv_report.xlsx",
                repo / "outputs" / "all_extend_da_rooms" / "scenarios_gmv_report.xlsx",
                downloads / "scenarios_gmv_report.xlsx",
            ]
        ),
        "descriptions": _first_existing(
            [
                inputs / "scenarios_descriptions_rooms.xlsx",
                downloads / "scenarios_descriptions_rooms.xlsx",
            ]
        ),
        "crosswalk": inputs / "mcc_l1_crosswalk.csv",
        "scenario_bridge": inputs / "scenario_mcc_bridge.csv",
        "meta": repo / "outputs" / "all_extend_da_rooms" / "_run_meta.json",
        "out_dir": Path(args.out_dir),
    }


def load_sber_wallets(prefs_path: Path, city: str = DEFAULT_CITY) -> pd.DataFrame:
    """Two wallets from the same prefs cut (city×MCC):

    - sber_full_share: overall Sber clients in the file (`gmv`)
    - sber_smkt_share: Samokat-audience subset (`smkt_gmv`)
    """
    raw = pd.read_excel(prefs_path, sheet_name="Без мерчантов")
    raw.columns = [str(c).strip() for c in raw.columns]
    for c in ("gmv", "smkt_gmv", "customers", "smkt_customers"):
        raw[c] = pd.to_numeric(raw[c], errors="coerce").fillna(0.0)

    city_df = raw[raw["city"] == city].copy()
    if city_df.empty:
        raise ValueError(f"No rows for city={city!r} in {prefs_path}")

    by_mcc = (
        city_df.groupby("mcc_category", as_index=False)[
            ["gmv", "smkt_gmv", "customers", "smkt_customers"]
        ]
        .sum()
        .rename(columns={"mcc_category": "mcc_group"})
    )
    total_gmv = float(by_mcc["gmv"].sum())
    total_smkt = float(by_mcc["smkt_gmv"].sum())
    by_mcc["sber_full_share"] = by_mcc["gmv"] / total_gmv if total_gmv > 0 else 0.0
    by_mcc["sber_smkt_share"] = by_mcc["smkt_gmv"] / total_smkt if total_smkt > 0 else 0.0
    # Primary research wallet = overall Sber client structure
    by_mcc["sber_share"] = by_mcc["sber_full_share"]
    by_mcc["rub_per_customer"] = by_mcc["gmv"] / by_mcc["customers"].where(
        by_mcc["customers"] > 0, pd.NA
    )
    by_mcc["rub_per_smkt_customer"] = by_mcc["smkt_gmv"] / by_mcc["smkt_customers"].where(
        by_mcc["smkt_customers"] > 0, pd.NA
    )
    by_mcc["city"] = city
    by_mcc["wallet_total_gmv"] = total_gmv
    by_mcc["wallet_total_smkt_gmv"] = total_smkt
    return by_mcc.sort_values("sber_full_share", ascending=False).reset_index(drop=True)


def load_mega_wallet(scenarios_path: Path) -> pd.DataFrame:
    xl = pd.ExcelFile(scenarios_path)
    sheet = "Mega_Aggregates" if "Mega_Aggregates" in xl.sheet_names else None
    if sheet is None:
        for s in xl.sheet_names:
            if "mega" in s.lower() or "мега" in s.lower():
                sheet = s
                break
    if sheet is None:
        raise ValueError(f"Mega_Aggregates not found in {scenarios_path}: {xl.sheet_names}")

    mega = pd.read_excel(scenarios_path, sheet_name=sheet)
    mega.columns = [str(c).strip() for c in mega.columns]
    gmv_col = "GMV" if "GMV" in mega.columns else next(c for c in mega.columns if "gmv" in c.lower())
    mega = mega.rename(columns={gmv_col: "GMV"})
    mega["mega"] = mega["mega"].astype(str).str.strip()
    mega["GMV"] = pd.to_numeric(mega["GMV"], errors="coerce").fillna(0.0)
    total = float(mega["GMV"].sum())
    mega["mega_share"] = mega["GMV"] / total if total > 0 else 0.0
    mega["wallet_total_gmv"] = total
    return mega.sort_values("GMV", ascending=False).reset_index(drop=True)


def allocate_mega_to_mcc(mega: pd.DataFrame, bridge: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    b = bridge.copy()
    b["mega"] = b["mega"].astype(str).str.strip()
    b["mcc_group"] = b["mcc_group"].astype(str).str.strip()
    b["weight"] = pd.to_numeric(b["weight"], errors="coerce").fillna(0.0)
    b["w_norm"] = b.groupby("mega")["weight"].transform(
        lambda s: s / s.sum() if float(s.sum()) > 0 else 0.0
    )

    m = mega[["mega", "mega_share", "GMV"]].copy()
    alloc = b.merge(m, on="mega", how="left")
    alloc["mega_share"] = alloc["mega_share"].fillna(0.0)
    alloc["GMV"] = alloc["GMV"].fillna(0.0)
    alloc["allocated_share"] = alloc["mega_share"] * alloc["w_norm"]
    alloc["allocated_gmv"] = alloc["GMV"] * alloc["w_norm"]

    by_mcc = (
        alloc.groupby("mcc_group", as_index=False)
        .agg(
            samokat_implied_share=("allocated_share", "sum"),
            samokat_implied_gmv=("allocated_gmv", "sum"),
            n_megas=("mega", "nunique"),
            megas=("mega", lambda s: "; ".join(sorted(set(str(x) for x in s)))),
        )
        .sort_values("samokat_implied_share", ascending=False)
        .reset_index(drop=True)
    )
    return by_mcc, alloc


# Non-food lvl1 that may appear under FOODZOO / FMCG markers but must not roll into grocery.
_GROCERY_NON_FOOD_LVL1 = frozenset(
    {
        "Праздничные и сезонные товары",
        "Товары для взрослых",
    }
)
_FOOD_BG_NEW = frozenset({"FOODZOO"})
_FOOD_BG = frozenset({"FMCG DRY", "FMCG FRESH"})


def load_new_etalons(etalons_path: Path) -> pd.DataFrame:
    df = pd.read_excel(etalons_path, sheet_name="Эталоны")
    df.columns = [str(c).strip() for c in df.columns]
    rename = {
        "NEW Эталон МАКСы": "etalon_max",
        "NEW Эталон 15 мин": "etalon_15",
        "NEW Эталон МАКС + 15 мин": "etalon_sum",
    }
    df = df.rename(columns={k: v for k, v in rename.items() if k in df.columns})
    for c in ("etalon_max", "etalon_15", "etalon_sum"):
        if c not in df.columns:
            raise ValueError(f"Missing NEW etalon column → {c} in {etalons_path}")
        df[c] = pd.to_numeric(df[c], errors="coerce").fillna(0.0)
    return df


def etalon_by_lvl1(etalons: pd.DataFrame) -> pd.DataFrame:
    return (
        etalons.groupby("lvl1", as_index=False)
        .agg(
            etalon_sum=("etalon_sum", "sum"),
            etalon_max=("etalon_max", "sum"),
            etalon_15=("etalon_15", "sum"),
            ml4_count=("lvl4", "count") if "lvl4" in etalons.columns else ("lvl1", "count"),
        )
        .sort_values("etalon_sum", ascending=False)
        .reset_index(drop=True)
    )


def specialty_lvl1_set(crosswalk: pd.DataFrame) -> set[str]:
    cw = crosswalk.copy()
    cw["bridge_type"] = cw["bridge_type"].astype(str).str.strip()
    cw["lvl1"] = cw["lvl1"].fillna("").astype(str).str.strip()
    return {l1 for l1 in cw.loc[cw["bridge_type"] == "specialty", "lvl1"] if l1}


def discover_grocery_food_lvl1(etalons: pd.DataFrame, crosswalk: pd.DataFrame) -> list[str]:
    """Food lvl1 for grocery MCC: FOODZOO / FMCG markers, excluding specialty-mapped lvl1.

    Avoids double-counting zoo/chemistry/hygiene etc. that already roll into specialty MCC.
    """
    specialty = specialty_lvl1_set(crosswalk)
    if "lvl1" not in etalons.columns:
        return []
    mask = pd.Series(False, index=etalons.index)
    if "bg_new" in etalons.columns:
        mask = mask | etalons["bg_new"].astype(str).str.strip().isin(_FOOD_BG_NEW)
    if "bg" in etalons.columns:
        mask = mask | etalons["bg"].astype(str).str.strip().isin(_FOOD_BG)
    candidates = {
        str(x).strip()
        for x in etalons.loc[mask, "lvl1"].dropna()
        if str(x).strip()
    }
    food = sorted(candidates - specialty - _GROCERY_NON_FOOD_LVL1)
    return food


def _rollup_lvl1_list(
    et_l1: pd.DataFrame, lvl1_list: list[str]
) -> tuple[list[str], float, float, float, float]:
    uniq: list[str] = []
    etalon_sum = etalon_max = etalon_15 = ml4 = 0.0
    for l1 in lvl1_list:
        if not l1 or l1 not in et_l1.index or l1 in uniq:
            continue
        uniq.append(l1)
        etalon_sum += float(et_l1.loc[l1, "etalon_sum"])
        etalon_max += float(et_l1.loc[l1, "etalon_max"])
        etalon_15 += float(et_l1.loc[l1, "etalon_15"])
        ml4 += float(et_l1.loc[l1, "ml4_count"])
    return uniq, etalon_sum, etalon_max, etalon_15, ml4


def _etalon_status_from_rollup(uniq: list[str], etalon_sum: float, empty_label: str) -> str:
    if not uniq:
        return empty_label
    if etalon_sum < ETALON_THIN_MAX:
        return "узкий"
    return "широкий"


def rollup_etalon_by_mcc(etalons: pd.DataFrame, crosswalk: pd.DataFrame) -> pd.DataFrame:
    et_l1 = etalon_by_lvl1(etalons).set_index("lvl1")
    cw = crosswalk.copy()
    cw["lvl1"] = cw["lvl1"].fillna("").astype(str).str.strip()
    cw["mcc_group"] = cw["mcc_group"].astype(str).str.strip()
    food_auto = discover_grocery_food_lvl1(etalons, crosswalk)

    rows = []
    for mcc, grp in cw.groupby("mcc_group"):
        btypes = sorted(set(str(x) for x in grp["bridge_type"].dropna()))
        bridge_type = btypes[0] if len(btypes) == 1 else ";".join(btypes)

        if "channel" in btypes and "specialty" not in btypes and "grocery" not in btypes:
            rows.append(
                {
                    "mcc_group": mcc,
                    "bridge_type": bridge_type,
                    "mapped_lvl1": "",
                    "etalon_sum_new": None,
                    "etalon_max_new": None,
                    "etalon_15_new": None,
                    "ml4_count": None,
                    "etalon_applicable": False,
                    "etalon_status": "н/п (канал)",
                }
            )
            continue

        if "grocery" in btypes and "specialty" not in btypes:
            cw_lvl1 = [l1 for l1 in grp["lvl1"] if l1]
            lvl1_list = cw_lvl1 if cw_lvl1 else food_auto
            uniq, etalon_sum, etalon_max, etalon_15, ml4 = _rollup_lvl1_list(et_l1, lvl1_list)
            status = _etalon_status_from_rollup(uniq, etalon_sum, "grocery без food lvl1 в эталоне")
            rows.append(
                {
                    "mcc_group": mcc,
                    "bridge_type": "grocery",
                    "mapped_lvl1": "; ".join(uniq),
                    "etalon_sum_new": etalon_sum if uniq else None,
                    "etalon_max_new": etalon_max if uniq else None,
                    "etalon_15_new": etalon_15 if uniq else None,
                    "ml4_count": int(ml4) if uniq else None,
                    "etalon_applicable": bool(uniq),
                    "etalon_status": status,
                }
            )
            continue

        if "specialty" not in btypes:
            rows.append(
                {
                    "mcc_group": mcc,
                    "bridge_type": bridge_type,
                    "mapped_lvl1": "",
                    "etalon_sum_new": None,
                    "etalon_max_new": None,
                    "etalon_15_new": None,
                    "ml4_count": None,
                    "etalon_applicable": False,
                    "etalon_status": "н/п (не specialty/grocery MCC)",
                }
            )
            continue

        uniq, etalon_sum, etalon_max, etalon_15, ml4 = _rollup_lvl1_list(
            et_l1, list(grp["lvl1"])
        )
        status = _etalon_status_from_rollup(uniq, etalon_sum, "specialty без lvl1 в кроссвоке")
        rows.append(
            {
                "mcc_group": mcc,
                "bridge_type": "specialty",
                "mapped_lvl1": "; ".join(uniq),
                "etalon_sum_new": etalon_sum,
                "etalon_max_new": etalon_max,
                "etalon_15_new": etalon_15,
                "ml4_count": int(ml4),
                "etalon_applicable": True,
                "etalon_status": status,
            }
        )
    return pd.DataFrame(rows)


def load_ml4_to_ml1(descriptions_path: Path, etalons: pd.DataFrame) -> dict[str, str]:
    mapping: dict[str, str] = {}
    if "lvl4" in etalons.columns:
        for _, r in etalons.iterrows():
            if pd.notna(r.get("lvl4")) and pd.notna(r.get("lvl1")):
                mapping[str(r["lvl4"]).strip().lower()] = str(r["lvl1"]).strip()
    ml = pd.read_excel(descriptions_path, sheet_name="Список МЛ")
    ml.columns = [str(c).strip() for c in ml.columns]
    for _, r in ml.iterrows():
        if pd.notna(r.get("new_ml4")) and pd.notna(r.get("new_ml1")):
            mapping[str(r["new_ml4"]).strip().lower()] = str(r["new_ml1"]).strip()
    return mapping


def build_ml1_wallet(
    mega: pd.DataFrame,
    descriptions_path: Path,
    etalons: pd.DataFrame,
    ml4_to_ml1: dict[str, str],
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Allocate mega GMV → ml4 (equal split of mapped) → ml1; join NEW etalon."""
    mega_cats = load_mega_category_map(descriptions_path)
    et_l1 = etalon_by_lvl1(etalons).set_index("lvl1")
    mega_gmv = mega.set_index("mega")["GMV"].to_dict()
    mega_share = mega.set_index("mega")["mega_share"].to_dict()

    detail_rows: list[dict] = []
    gmv_by_ml1: dict[str, float] = {}
    mapped_gmv = 0.0
    unmapped_gmv = 0.0
    empty_ml4_gmv = 0.0

    all_megas = sorted(set(mega["mega"].astype(str)) | set(mega_cats["mega"].astype(str)))
    cats_by_mega = mega_cats.set_index("mega") if not mega_cats.empty else pd.DataFrame()

    for mega_name in all_megas:
        gmv = float(mega_gmv.get(mega_name, 0.0) or 0.0)
        share = float(mega_share.get(mega_name, 0.0) or 0.0)
        if mega_name in cats_by_mega.index:
            raw = str(cats_by_mega.loc[mega_name, "ml4_categories"] or "")
            ml4s = [x.strip() for x in raw.split("·") if x.strip()]
            n_ml4 = int(cats_by_mega.loc[mega_name, "n_ml4"] or len(ml4s))
        else:
            ml4s, n_ml4 = [], 0

        if n_ml4 == 0 or not ml4s:
            empty_ml4_gmv += gmv
            detail_rows.append(
                {
                    "mega": mega_name,
                    "n_ml4": 0,
                    "n_ml4_mapped": 0,
                    "map_rate": None,
                    "GMV": gmv,
                    "mega_share": share,
                    "status": "состав ml4 пуст — кошелёк ml1 через MCC/bridge",
                }
            )
            continue

        mapped = [(m4, ml4_to_ml1[m4.lower()]) for m4 in ml4s if m4.lower() in ml4_to_ml1]
        n_mapped = len(mapped)
        map_rate = n_mapped / len(ml4s) if ml4s else 0.0
        if n_mapped == 0:
            unmapped_gmv += gmv
            detail_rows.append(
                {
                    "mega": mega_name,
                    "n_ml4": len(ml4s),
                    "n_ml4_mapped": 0,
                    "map_rate": 0.0,
                    "GMV": gmv,
                    "mega_share": share,
                    "status": "ml4 есть, но 0 сматчено с ml1 (имена)",
                }
            )
            continue

        # Equal split of mega GMV across mapped ml4 only; residual = unmapped share of GMV
        piece = gmv / n_mapped
        mapped_gmv += gmv * map_rate
        unmapped_gmv += gmv * (1.0 - map_rate)
        for _m4, l1 in mapped:
            gmv_by_ml1[l1] = gmv_by_ml1.get(l1, 0.0) + piece

        detail_rows.append(
            {
                "mega": mega_name,
                "n_ml4": len(ml4s),
                "n_ml4_mapped": n_mapped,
                "map_rate": map_rate,
                "GMV": gmv,
                "mega_share": share,
                "status": "ок" if map_rate >= 0.5 else "слабый матч ml4→ml1",
            }
        )

    total = float(mega["GMV"].sum())
    rows = []
    for l1, g in sorted(gmv_by_ml1.items(), key=lambda x: -x[1]):
        et_sum = float(et_l1.loc[l1, "etalon_sum"]) if l1 in et_l1.index else None
        et_max = float(et_l1.loc[l1, "etalon_max"]) if l1 in et_l1.index else None
        et_15 = float(et_l1.loc[l1, "etalon_15"]) if l1 in et_l1.index else None
        if et_sum is None:
            et_status = "нет в NEW-эталоне"
        elif et_sum <= 0:
            et_status = "эталон = 0"
        elif et_sum < ETALON_THIN_MAX:
            et_status = "узкий"
        else:
            et_status = "широкий"
        rows.append(
            {
                "lvl1": l1,
                "GMV": g,
                "ml1_share": g / total if total > 0 else 0.0,
                "etalon_sum_new": et_sum,
                "etalon_max_new": et_max,
                "etalon_15_new": et_15,
                "etalon_status": et_status,
            }
        )

    # Residual buckets for transparency
    for label, g in (
        ("(не сматчено ml4→ml1)", unmapped_gmv),
        ("(мега без состава ml4)", empty_ml4_gmv),
    ):
        if g > 0:
            rows.append(
                {
                    "lvl1": label,
                    "GMV": g,
                    "ml1_share": g / total if total > 0 else 0.0,
                    "etalon_sum_new": None,
                    "etalon_max_new": None,
                    "etalon_15_new": None,
                    "etalon_status": "н/п",
                }
            )

    ml1_wallet = pd.DataFrame(rows).sort_values("GMV", ascending=False).reset_index(drop=True)
    mega_ml4_audit = pd.DataFrame(detail_rows).sort_values("GMV", ascending=False).reset_index(drop=True)
    return ml1_wallet, mega_ml4_audit


def build_mission_etalon_audit(
    mega: pd.DataFrame,
    bridge: pd.DataFrame,
    etalon_mcc: pd.DataFrame,
    mega_ml4_audit: pd.DataFrame,
) -> pd.DataFrame:
    """Per mega: bridge MCCs, etalon applicability, ml4 composition flags."""
    b = bridge.copy()
    b["mega"] = b["mega"].astype(str).str.strip()
    et = etalon_mcc.set_index("mcc_group")
    ml4 = mega_ml4_audit.set_index("mega") if not mega_ml4_audit.empty else pd.DataFrame()

    rows = []
    for _, m in mega.iterrows():
        mega_name = str(m["mega"])
        links = b[b["mega"] == mega_name]
        if links.empty:
            rows.append(
                {
                    "mega": mega_name,
                    "GMV": float(m["GMV"]),
                    "mega_share": float(m["mega_share"]),
                    "mcc_links": "",
                    "etalon_note": "нет в scenario_mcc_bridge",
                    "etalon_flag": "нет моста",
                    "n_ml4": None,
                    "n_ml4_mapped": None,
                    "ml4_status": "—",
                }
            )
            continue

        notes = []
        flags = []
        mcc_parts = []
        for _, link in links.iterrows():
            mcc = str(link["mcc_group"])
            role = str(link.get("role") or "")
            mcc_parts.append(f"{mcc} ({role})" if role else mcc)
            if mcc not in et.index:
                notes.append(f"{mcc}: нет в кроссвоке")
                flags.append("нет кроссвока")
                continue
            er = et.loc[mcc]
            btype = str(er.get("bridge_type") or "")
            if not bool(er.get("etalon_applicable")):
                if "channel" in btype:
                    notes.append(f"{mcc}: эталон н/п (канал)")
                    flags.append("канал н/п")
                elif "grocery" in btype:
                    notes.append(f"{mcc}: grocery без food ml1 в NEW-эталоне")
                    flags.append("grocery без etalon")
                else:
                    notes.append(f"{mcc}: эталон н/п")
                    flags.append("н/п")
            else:
                status = str(er.get("etalon_status") or "")
                sku = er.get("etalon_sum_new")
                sku_txt = "н/д" if pd.isna(sku) else f"{int(float(sku))} SKU"
                if "grocery" in btype:
                    notes.append(f"{mcc}: food ml1 rollup — {status} ({sku_txt})")
                else:
                    notes.append(f"{mcc}: {status} ({sku_txt})")
                flags.append(status)

        ml4_n = ml4_map = None
        ml4_status = "—"
        if mega_name in ml4.index:
            ml4_n = int(ml4.loc[mega_name, "n_ml4"] or 0)
            ml4_map = ml4.loc[mega_name, "n_ml4_mapped"]
            ml4_status = str(ml4.loc[mega_name, "status"] or "")

        # Primary flag for filtering
        primary_flag = flags[0] if flags else "—"
        if any(f in ("узкий", "specialty без lvl1 в кроссвоке", "нет кроссвока") for f in flags):
            primary_flag = next(
                f for f in flags if f in ("узкий", "specialty без lvl1 в кроссвоке", "нет кроссвока")
            )
        elif all(f in ("grocery без etalon", "канал н/п", "н/п") for f in flags):
            primary_flag = flags[0]

        rows.append(
            {
                "mega": mega_name,
                "GMV": float(m["GMV"]),
                "mega_share": float(m["mega_share"]),
                "mcc_links": "; ".join(mcc_parts),
                "etalon_note": " · ".join(notes),
                "etalon_flag": primary_flag,
                "n_ml4": ml4_n,
                "n_ml4_mapped": ml4_map,
                "ml4_status": ml4_status,
            }
        )
    return pd.DataFrame(rows).sort_values("GMV", ascending=False).reset_index(drop=True)


def _conclusion(row: pd.Series) -> str:
    gap = float(row["gap_pp"]) if pd.notna(row["gap_pp"]) else 0.0
    btype = str(row.get("bridge_type") or "")
    etalon = row.get("etalon_sum_new")

    if "channel" in btype:
        if gap >= GAP_MATERIAL_PP:
            return "Канал (маркетплейсы) силён в Сбере, слабо в сценариях — не эталон, а ось Where."
        return "Канал; эталон н/п."

    thin = pd.isna(etalon) or float(etalon) < ETALON_THIN_MAX
    wide = pd.notna(etalon) and float(etalon) >= ETALON_THIN_MAX
    et_txt = "н/д" if pd.isna(etalon) else f"{int(etalon)} SKU"
    grocery_prefix = "Grocery food-ml1 rollup: " if "grocery" in btype else ""

    if gap >= GAP_MATERIAL_PP and thin:
        return (
            f"{grocery_prefix}Недобор {100 * gap:.1f} п.п.; NEW-эталон узкий ({et_txt}) → "
            "гипотеза: расширить ширину."
        )
    if gap >= GAP_MATERIAL_PP and wide:
        return (
            f"{grocery_prefix}Недобор {100 * gap:.1f} п.п.; NEW-эталон уже широкий ({et_txt}) → "
            "причина не в узком эталоне (миссии / спрос / канал)."
        )
    if gap <= -GAP_MATERIAL_PP:
        return (
            f"{grocery_prefix}Самокат перевешивает vs Сбер ({100 * gap:.1f} п.п.); "
            f"эталон {et_txt}."
        )
    return f"{grocery_prefix}Доли сопоставимы; NEW-эталон {et_txt}."


def build_master(
    sber: pd.DataFrame,
    samokat_mcc: pd.DataFrame,
    etalon_mcc: pd.DataFrame,
    city: str,
) -> pd.DataFrame:
    mccs = sorted(
        set(sber["mcc_group"].astype(str))
        | set(samokat_mcc["mcc_group"].astype(str))
        | set(etalon_mcc["mcc_group"].astype(str))
    )
    base = pd.DataFrame({"mcc_group": mccs})
    df = (
        base.merge(sber, on="mcc_group", how="left")
        .merge(samokat_mcc, on="mcc_group", how="left")
        .merge(etalon_mcc, on="mcc_group", how="left")
    )
    df["city"] = city
    df["sber_full_share"] = df["sber_full_share"].fillna(0.0)
    df["sber_smkt_share"] = df["sber_smkt_share"].fillna(0.0)
    df["sber_share"] = df["sber_full_share"]  # primary gap vs overall Sber wallet
    df["samokat_implied_share"] = df["samokat_implied_share"].fillna(0.0)
    df["gap_pp"] = df["sber_full_share"] - df["samokat_implied_share"]
    df["gap_pp_vs_smkt_aud"] = df["sber_smkt_share"] - df["samokat_implied_share"]
    df["gap_ratio"] = df["samokat_implied_share"] / df["sber_full_share"].where(
        df["sber_full_share"] > 1e-12, pd.NA
    )
    df["bridge_type"] = df["bridge_type"].fillna("unknown")
    df["conclusion"] = df.apply(_conclusion, axis=1)

    cols = [
        "city",
        "mcc_group",
        "bridge_type",
        "sber_full_share",
        "sber_smkt_share",
        "gmv",
        "smkt_gmv",
        "rub_per_customer",
        "rub_per_smkt_customer",
        "samokat_implied_share",
        "samokat_implied_gmv",
        "gap_pp",
        "gap_pp_vs_smkt_aud",
        "gap_ratio",
        "etalon_sum_new",
        "etalon_max_new",
        "etalon_15_new",
        "etalon_status",
        "ml4_count",
        "mapped_lvl1",
        "n_megas",
        "megas",
        "conclusion",
    ]
    for c in cols:
        if c not in df.columns:
            df[c] = pd.NA
    return df[cols].sort_values("gap_pp", ascending=False).reset_index(drop=True)


def build_spravka(
    paths: dict[str, Path],
    city: str,
    sber: pd.DataFrame,
    mega: pd.DataFrame,
    master: pd.DataFrame,
    mission_audit: pd.DataFrame,
) -> pd.DataFrame:
    period = "н/д"
    meta_path = paths.get("meta")
    if meta_path and meta_path.exists():
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
            if "date_from" in meta and "date_to" in meta:
                period = f"{meta['date_from']} — {meta['date_to']}"
            else:
                period = str(meta.get("period") or period)
        except Exception:
            pass

    rows: list[dict] = [
        {
            "раздел": "метод",
            "ключ": "gap_definition",
            "значение": (
                "Gap = доля MCC в полном кошельке Сбера (gmv / ∑ gmv по MCC города) "
                "минус доля MCC после аллокации mega GMV через soft-bridge. "
                "Дополнительно: gap_pp_vs_smkt_aud — то же vs кошелька аудитории Самоката (smkt_gmv)."
            ),
            "комментарий": "Положительный gap = недобор Самоката vs Сбер",
        },
        {
            "раздел": "метод",
            "ключ": "sber_wallets",
            "значение": (
                "В prefs два кошелька: gmv = клиенты Сбера в срезе; "
                "smkt_gmv = подмножество «самокатовцы». Исследование — про полный кошелёк."
            ),
            "комментарий": "",
        },
        {
            "раздел": "метод",
            "ключ": "ml1_wallet",
            "значение": (
                "Кошелёк ml1: GMV мега делится поровну по сматченным ml4→ml1 "
                "(Список МЛ + эталоны). Мега без ml4 / без матча — residual-строки."
            ),
            "комментарий": "",
        },
        {
            "раздел": "метод",
            "ключ": "etalon",
            "значение": (
                f"NEW-колонки QNF; specialty MCC через mcc_l1_crosswalk; "
                f"grocery MCC = rollup food lvl1 (FOODZOO / FMCG, минус specialty); "
                f"канал н/п; узкий < {int(ETALON_THIN_MAX)} SKU"
            ),
            "комментарий": "Маркетплейсы на MCC: н/п; grocery — food ml1 из эталонов",
        },
        {
            "раздел": "метод",
            "ключ": "city",
            "значение": city,
            "комментарий": "",
        },
        {
            "раздел": "метод",
            "ключ": "scenarios_period",
            "значение": period,
            "комментарий": "",
        },
    ]
    for key in ("prefs", "scenarios", "etalons", "scenario_bridge", "crosswalk", "descriptions"):
        if key in paths:
            rows.append(
                {
                    "раздел": "источники",
                    "ключ": key,
                    "значение": str(paths[key]),
                    "комментарий": "",
                }
            )

    for _, r in sber.iterrows():
        rows.append(
            {
                "раздел": "sber_full_wallet",
                "ключ": str(r["mcc_group"]),
                "значение": f"{100 * float(r['sber_full_share']):.2f}%",
                "комментарий": f"gmv={float(r['gmv']):.0f}",
            }
        )
    for _, r in mega.iterrows():
        rows.append(
            {
                "раздел": "samokat_mega",
                "ключ": str(r["mega"]),
                "значение": f"{100 * float(r['mega_share']):.2f}%",
                "комментарий": f"GMV={float(r['GMV']):.0f}",
            }
        )
    for i, (_, r) in enumerate(master.head(5).iterrows(), 1):
        rows.append(
            {
                "раздел": "top_gaps",
                "ключ": f"#{i} {r['mcc_group']}",
                "значение": f"{100 * float(r['gap_pp']):+.2f} п.п.",
                "комментарий": str(r["conclusion"]),
            }
        )
    # Highlight mission etalon issues
    hot = mission_audit[
        mission_audit["etalon_flag"].isin(
            ["узкий", "нет моста", "нет кроссвока", "specialty без lvl1 в кроссвоке"]
        )
        | mission_audit["ml4_status"].astype(str).str.contains("пуст|0 сматчено|слабый", na=False)
    ]
    for _, r in hot.iterrows():
        rows.append(
            {
                "раздел": "etalon_audit",
                "ключ": str(r["mega"]),
                "значение": str(r["etalon_flag"]),
                "комментарий": f"{r['etalon_note']} | ml4: {r['ml4_status']}",
            }
        )
    return pd.DataFrame(rows)


def compute_all(paths: dict[str, Path], city: str = DEFAULT_CITY) -> dict[str, pd.DataFrame]:
    bridge = pd.read_csv(paths["scenario_bridge"])
    crosswalk = pd.read_csv(paths["crosswalk"])

    sber = load_sber_wallets(paths["prefs"], city=city)
    mega = load_mega_wallet(paths["scenarios"])
    samokat_mcc, alloc = allocate_mega_to_mcc(mega, bridge)
    etalons = load_new_etalons(paths["etalons"])
    etalon_mcc = rollup_etalon_by_mcc(etalons, crosswalk)
    ml4_to_ml1 = load_ml4_to_ml1(paths["descriptions"], etalons)
    ml1_wallet, mega_ml4_audit = build_ml1_wallet(
        mega, paths["descriptions"], etalons, ml4_to_ml1
    )
    mission_audit = build_mission_etalon_audit(mega, bridge, etalon_mcc, mega_ml4_audit)
    master = build_master(sber, samokat_mcc, etalon_mcc, city=city)
    spravka = build_spravka(paths, city, sber, mega, master, mission_audit)

    return {
        "Master": master,
        "Справка": spravka,
        "sber_wallet": sber,
        "samokat_mega": mega,
        "samokat_ml1": ml1_wallet,
        "samokat_mcc": samokat_mcc,
        "mission_etalon_audit": mission_audit,
        "mega_ml4_audit": mega_ml4_audit,
        "alloc_detail": alloc,
        "scenario_bridge": bridge,
    }


def write_xlsx(tables: dict[str, pd.DataFrame], out_path: Path) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with pd.ExcelWriter(out_path, engine="openpyxl") as xl:
        tables["Master"].to_excel(xl, sheet_name="Master", index=False)
        tables["Справка"].to_excel(xl, sheet_name="Справка", index=False)
        tables["samokat_ml1"].to_excel(xl, sheet_name="Samokat_ml1", index=False)
        tables["mission_etalon_audit"].to_excel(xl, sheet_name="Etalon_audit", index=False)


def write_payload(tables: dict[str, pd.DataFrame], out_path: Path, city: str) -> None:
    bridge_df = tables.get("scenario_bridge")
    bridge_records = (
        bridge_df.to_dict(orient="records") if bridge_df is not None else []
    )
    payload = {
        "city": city,
        "gap_definition": (
            "Gap = доля MCC в полном кошельке Сбера (gmv) минус доля MCC, "
            "имплицитно выделенная сценариям Самоката через soft-bridge."
        ),
        "etalon_thin_max": ETALON_THIN_MAX,
        "master": tables["Master"].to_dict(orient="records"),
        "sber_wallet": tables["sber_wallet"].to_dict(orient="records"),
        "samokat_mega": tables["samokat_mega"].to_dict(orient="records"),
        "samokat_ml1": tables["samokat_ml1"].to_dict(orient="records"),
        "mission_etalon_audit": tables["mission_etalon_audit"].to_dict(orient="records"),
        "scenario_bridge": bridge_records,
        "spravka": tables["Справка"].to_dict(orient="records"),
    }
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(
        json.dumps(payload, ensure_ascii=False, default=str, indent=2), encoding="utf-8"
    )


def main() -> None:
    ap = argparse.ArgumentParser(description="Build budget-gap report tables")
    ap.add_argument("--downloads", default=str(DEFAULT_DOWNLOADS))
    ap.add_argument("--repo", default=str(REPO))
    ap.add_argument("--out-dir", default=str(ROOT / "outputs"))
    ap.add_argument("--city", default=DEFAULT_CITY)
    ap.add_argument("--skip-html", action="store_true")
    args = ap.parse_args()

    paths = resolve_paths(args)
    out_dir = paths["out_dir"]
    tables = compute_all(paths, city=args.city)

    xlsx_path = out_dir / "budget_gap_report.xlsx"
    payload_path = out_dir / "budget_gap_payload.json"
    html_path = out_dir / "budget_gap_report.html"

    write_xlsx(tables, xlsx_path)
    write_payload(tables, payload_path, city=args.city)

    print(f"Wrote {xlsx_path}")
    print(f"Wrote {payload_path}")
    g = tables["Master"][tables["Master"]["mcc_group"].astype(str) == "Продуктовые магазины"]
    if not g.empty:
        gr = g.iloc[0]
        print(
            f"Grocery etalon ({args.city}): sum={gr.get('etalon_sum_new')} "
            f"status={gr.get('etalon_status')} lvl1={gr.get('mapped_lvl1')}"
        )
    print(f"Top gaps vs full Sber wallet ({args.city}):")
    for _, r in tables["Master"].head(5).iterrows():
        print(
            f"  {r['mcc_group']}: gap={100 * float(r['gap_pp']):+.1f} п.п. "
            f"(Sber full {100 * float(r['sber_full_share']):.1f}% / "
            f"smkt-aud {100 * float(r['sber_smkt_share']):.1f}% vs "
            f"Smkt {100 * float(r['samokat_implied_share']):.1f}%) "
            f"etalon={r.get('etalon_status')}"
        )
    print("Mission etalon flags:")
    for _, r in tables["mission_etalon_audit"].iterrows():
        if r["etalon_flag"] not in ("широкий", "есть") or "пуст" in str(r["ml4_status"]):
            print(f"  {r['mega']}: {r['etalon_flag']} | {r['ml4_status']}")

    if not args.skip_html:
        from render_budget_gap_html import render_html

        render_html(payload_path, html_path)
        print(f"Wrote {html_path}")


if __name__ == "__main__":
    main()
