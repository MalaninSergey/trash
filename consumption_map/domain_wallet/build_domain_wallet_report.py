#!/usr/bin/env python3
"""Domain wallet report — greenfield leaf scenario → one Sber MCC.

Raw inputs only: prefs, Scenario_Aggregates, scenario_leaf_mcc_bridge,
etalons NEW, mcc_l1_crosswalk, Magnit/Pyaterochka audience prefs.
Does not use budget_gap / mega-bridge.

  python consumption_map/domain_wallet/build_domain_wallet_report.py
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import pandas as pd

PKG = Path(__file__).resolve().parent
ROOT = PKG.parent
REPO = ROOT.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from magnit_pyaterochka import load_mp_sources  # noqa: E402
try:
    from domain_wallet.export_domain_wallet_excel import export_domain_wallet_excel  # noqa: E402
    from domain_wallet.rk_bg_assortment import build_assortment_payload  # noqa: E402
except ImportError:
    from export_domain_wallet_excel import export_domain_wallet_excel  # noqa: E402
    from rk_bg_assortment import build_assortment_payload  # noqa: E402

DEFAULT_DOWNLOADS = Path.home() / "Downloads"
DEFAULT_CITY = "Москва"
DEFAULT_CITIES = ("Москва",)
ETALON_THIN_MAX = 50.0
GAP_MATERIAL_PP = 0.01
GROCERY_MCC = "Продуктовые магазины"
MP_OFFLINE = ("Магнит Оффлайн", "Пятерочка Оффлайн")
# Prefs Сбера (ТЗ): метрики merchant/MCC за последние 12 мес.
SBER_PERIOD_MONTHS = 12
# Окно сценариев Самоката (period_from…period_to в _run_meta): обычно 6 мес.
SMKT_PERIOD_MONTHS = 6
PERIOD_MONTHS = SBER_PERIOD_MONTHS  # backward-compat alias in payload

_GROCERY_NON_FOOD = frozenset({"Праздничные и сезонные товары", "Товары для взрослых"})
_FOOD_BG_NEW = frozenset({"FOODZOO"})
_FOOD_BG = frozenset({"FMCG DRY", "FMCG FRESH"})


def _first_existing(candidates: list[Path]) -> Path:
    for p in candidates:
        if p.exists():
            return p
    raise FileNotFoundError("None of:\n" + "\n".join(str(c) for c in candidates))


def _optional_existing(candidates: list[Path]) -> Path | None:
    for p in candidates:
        if p.exists():
            return p
    return None


def resolve_paths(args: argparse.Namespace) -> dict[str, Path | None]:
    downloads = Path(args.downloads)
    repo = Path(args.repo)
    inputs = ROOT / "inputs"
    return {
        "prefs": _first_existing(
            [
                inputs / "prefs_samokat_audience.xlsx",
                downloads / "Анализ предпочтений основной аудитории Самоката (1).xlsx",
                downloads / "Анализ предпочтений основной аудитории Самоката (1) (1).xlsx",
            ]
        ),
        "etalons": _first_existing(
            [
                inputs / "etalons_qnf.xlsx",
                downloads / "Эталоны QNF 3.0 (05.08).xlsx",
            ]
        ),
        "scenarios": _first_existing(
            [
                inputs / "scenarios_gmv_report.xlsx",
                repo / "outputs" / "all_extend_da_rooms" / "scenarios_gmv_report.xlsx",
            ]
        ),
        "leaf_bridge": inputs / "scenario_leaf_mcc_bridge.csv",
        "mega_bridge": inputs / "scenario_mcc_bridge.csv",
        "crosswalk": inputs / "mcc_l1_crosswalk.csv",
        "prefs_mp": _first_existing(
            [
                inputs / "prefs_magnit_pyaterochka_audience.xlsx",
                downloads / "Анализ предпочтений основной аудитории Магнита и Пятерочки.xlsx",
                downloads / "Анализ предпочтений основной аудитории Магнита и Пятерочки (3).xlsx",
            ]
        ),
        "meta": repo / "outputs" / "all_extend_da_rooms" / "_run_meta.json",
        "scenario_etalons": _first_existing(
            [
                ROOT / "outputs" / "scenarios_with_etalon.xlsx",
                downloads / "scenarios_with_etalon.xlsx",
            ]
        ),
        "rk_bg": _first_existing(
            [
                inputs / "rk_bg.xlsx",
                downloads / "РК - БГ.xlsx",
            ]
        ),
        "catalog": _first_existing(
            [
                repo / "outputs" / "all_extend_da_rooms" / "scenarios_catalog_full.json",
                ROOT / "inputs" / "scenarios_catalog_full.json",
            ]
        ),
        "scenario_ml4_fact": _optional_existing(
            [
                ROOT / "outputs" / "ml4_fact" / "scenario_ml4_gmv_fact.parquet",
                inputs / "scenario_ml4_gmv_fact.parquet",
                ROOT / "outputs" / "ml4_fact" / "scenario_ml4_gmv_fact.csv",
                inputs / "scenario_ml4_gmv_fact.csv",
            ]
        ),
        "ml4_gmv_fact": _optional_existing(
            [
                ROOT / "outputs" / "ml4_fact" / "ml4_gmv_fact.parquet",
                inputs / "ml4_gmv_fact.parquet",
                ROOT / "outputs" / "ml4_fact" / "ml4_gmv_fact.csv",
                inputs / "ml4_gmv_fact.csv",
            ]
        ),
        "ml4_name_aliases": _optional_existing(
            [
                inputs / "ml4_name_aliases.csv",
            ]
        ),
        "out_dir": Path(args.out_dir),
    }


MARKETPLACE_MCC = "Маркетплейсы"


def load_sber_wallet(
    prefs_path: Path,
    city: str,
    *,
    exclude_mccs: frozenset[str] | set[str] | None = None,
) -> pd.DataFrame:
    raw = pd.read_excel(prefs_path, sheet_name="Без мерчантов")
    raw.columns = [str(c).strip() for c in raw.columns]
    for c in ("gmv", "smkt_gmv", "customers", "smkt_customers"):
        raw[c] = pd.to_numeric(raw[c], errors="coerce").fillna(0.0)
    city_df = raw[raw["city"] == city].copy()
    if city_df.empty:
        raise ValueError(f"No rows for city={city!r}")
    by = (
        city_df.groupby("mcc_category", as_index=False)[["gmv", "smkt_gmv", "customers", "smkt_customers"]]
        .sum()
        .rename(columns={"mcc_category": "mcc_group"})
    )
    if exclude_mccs:
        by = by[~by["mcc_group"].astype(str).isin(exclude_mccs)].copy()
    total = float(by["gmv"].sum())
    total_smkt = float(by["smkt_gmv"].sum())
    by["sber_full_share"] = by["gmv"] / total if total else 0.0
    by["sber_smkt_share"] = by["smkt_gmv"] / total_smkt if total_smkt else 0.0
    # domain-only ARPPU (clients overlap across MCC) — kept for reference
    by["rub_per_customer_domain"] = by["gmv"] / by["customers"].where(by["customers"] > 0, pd.NA)
    by["city"] = city
    return by.sort_values("sber_full_share", ascending=False).reset_index(drop=True)


def load_city_client_totals(prefs_path: Path, city: str) -> dict[str, float]:
    """Unique city clients from prefs sheet «Без МСС» (not sum of MCC)."""
    raw = pd.read_excel(prefs_path, sheet_name="Без МСС")
    raw.columns = [str(c).strip() for c in raw.columns]
    for c in ("customers", "smkt_customers", "gmv", "smkt_gmv"):
        if c in raw.columns:
            raw[c] = pd.to_numeric(raw[c], errors="coerce").fillna(0.0)
    sub = raw[raw["city"] == city]
    if sub.empty:
        raise ValueError(f"No Без МСС rows for city={city!r}")
    return {
        "sber_customers_total": float(sub["customers"].sum()),
        "smkt_customers_total": float(sub["smkt_customers"].sum()),
        "sber_gmv_total": float(sub["gmv"].sum()) if "gmv" in sub.columns else 0.0,
        "smkt_gmv_total": float(sub["smkt_gmv"].sum()) if "smkt_gmv" in sub.columns else 0.0,
    }


def load_scenario_national_users(meta_path: Path) -> int | None:
    """National distinct Samokat customers for the scenario period (_run_meta)."""
    if not meta_path.exists():
        return None
    try:
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
    except Exception:
        return None
    n = meta.get("national_users")
    if n is None:
        return None
    try:
        n_int = int(n)
    except (TypeError, ValueError):
        return None
    return n_int if n_int > 0 else None


def load_leaf_gmv(scenarios_path: Path) -> pd.DataFrame:
    agg = pd.read_excel(scenarios_path, sheet_name="Scenario_Aggregates")
    agg.columns = [str(c).strip() for c in agg.columns]
    gmv_col = "GMV_аллоцированный" if "GMV_аллоцированный" in agg.columns else "GMV"
    out = pd.DataFrame(
        {
            "mission": agg["Миссия"].astype(str).str.strip(),
            "GMV": pd.to_numeric(agg[gmv_col], errors="coerce").fillna(0.0),
        }
    )
    out["mega"] = out["mission"].str.split("→").str[0].str.strip()
    out["scenario"] = out["mission"].str.split("→").str[-1].str.strip()
    total = float(out["GMV"].sum())
    out["leaf_share"] = out["GMV"] / total if total else 0.0
    out["wallet_total_gmv"] = total
    return out.sort_values("GMV", ascending=False).reset_index(drop=True)


def allocate_leaf_to_mcc(
    leaves: pd.DataFrame, bridge: pd.DataFrame
) -> tuple[pd.DataFrame, pd.DataFrame, dict]:
    b = bridge.copy()
    b["mission"] = b["mission"].astype(str).str.strip()
    b["mcc_group"] = b["mcc_group"].fillna("").astype(str).str.strip()
    dup = b.groupby("mission")["mcc_group"].nunique()
    bad = dup[dup > 1]
    if len(bad):
        raise ValueError(f"Bridge violates 1:1 for missions: {bad.index.tolist()[:10]}")

    merged = leaves.merge(
        b[["mission", "mcc_group", "seed_source", "needs_review"]], on="mission", how="left"
    )
    merged["mcc_group"] = merged["mcc_group"].fillna("")
    total = float(leaves["GMV"].sum())
    mapped = merged[merged["mcc_group"] != ""].copy()
    unmapped = merged[merged["mcc_group"] == ""].copy()

    by_mcc = (
        mapped.groupby("mcc_group", as_index=False)
        .agg(
            samokat_implied_gmv=("GMV", "sum"),
            n_leaves=("mission", "nunique"),
            leaves_preview=("scenario", lambda s: " · ".join(list(s)[:5])),
        )
        .sort_values("samokat_implied_gmv", ascending=False)
        .reset_index(drop=True)
    )
    by_mcc["samokat_implied_share"] = by_mcc["samokat_implied_gmv"] / total if total else 0.0

    coverage = {
        "total_gmv": total,
        "mapped_gmv": float(mapped["GMV"].sum()),
        "unmapped_gmv": float(unmapped["GMV"].sum()),
        "mapped_share": float(mapped["GMV"].sum()) / total if total else 0.0,
        "n_leaves": int(len(leaves)),
        "n_mapped": int(len(mapped)),
        "n_unmapped": int(len(unmapped)),
        "n_needs_review": int((merged["needs_review"].astype(str).str.lower() == "true").sum()),
    }
    return by_mcc, merged, coverage


def load_mega_mcc_bundles(mega_bridge_path: Path) -> dict[str, list[str]]:
    """Megas that historically span >1 MCC (candidates for leaf «слияние»)."""
    if not mega_bridge_path.exists():
        return {}
    raw = pd.read_csv(mega_bridge_path)
    raw["mega"] = raw["mega"].astype(str).str.strip()
    raw["mcc_group"] = raw["mcc_group"].astype(str).str.strip()
    raw = raw[(raw["mega"] != "") & (raw["mcc_group"] != "") & (raw["mcc_group"] != "Маркетплейсы")]
    out: dict[str, list[str]] = {}
    for mega, grp in raw.groupby("mega"):
        mccs = sorted({str(x) for x in grp["mcc_group"] if str(x)})
        if len(mccs) > 1:
            out[str(mega)] = mccs
    return out


# Name → other MCC: only clear cross-domain wording (avoid «стол»→мебель etc.).
_MERGE_NAME_HINTS: tuple[tuple[str, str], ...] = (
    (r"обув", "Обувь"),
    (r"мебел", "Мебель"),
    (r"кинотеатр", "Бытовая техника и электроника"),
    (r"стиральн|водонагрев", "Бытовая техника и электроника"),
    (r"монитор|ноутбук|ПК\b|перифери", "Бытовая техника и электроника"),
    (r"\bкниг", "Книжные магазины"),
    (r"канцеляр", "Канцтовары"),
)


def _name_merge_hints(text: str) -> list[str]:
    import re

    t = text.lower()
    found: list[str] = []
    for pat, mcc in _MERGE_NAME_HINTS:
        if re.search(pat, t, flags=re.IGNORECASE) and mcc not in found:
            found.append(mcc)
    if re.search(r"обустройств\w*\s+.+\s+с нуля", t, flags=re.IGNORECASE):
        # room fit-outs historically split tech / home / furniture
        for mcc in (
            "Бытовая техника и электроника",
            "Товары для дома",
            "Мебель",
        ):
            if mcc not in found:
                found.append(mcc)
    return found


def annotate_inseparable_leaves(
    leaf_detail: pd.DataFrame, mega_bundles: dict[str, list[str]]
) -> pd.DataFrame:
    """Every leaf is tagged: «слияние» if mixed domains, else «неразделимо» (1:1)."""
    df = leaf_detail.copy()
    is_merge: list[bool] = []
    tags: list[str] = []
    siblings: list[str] = []
    notes: list[str] = []
    for _, r in df.iterrows():
        mcc = str(r.get("mcc_group") or "").strip()
        mission = str(r.get("mission") or "")
        scenario = str(r.get("scenario") or "")
        text = f"{mission} {scenario}"
        hints = [h for h in _name_merge_hints(text) if h != mcc]
        cross = sorted(set(hints))
        if cross:
            is_merge.append(True)
            tags.append("слияние")
            siblings.append(" · ".join(cross))
            notes.append(
                f"Слияние: сценарий тянет несколько доменов "
                f"({mcc} + {' / '.join(cross)}); при 1:1 GMV целиком в «{mcc}»."
            )
        else:
            is_merge.append(False)
            tags.append("неразделимо")
            siblings.append("")
            notes.append(
                "Неразделимо: 1 сценарий → 1 MCC, доли между доменами не режем."
            )
    df["is_merge"] = is_merge
    df["split_tag"] = tags
    df["inseparable"] = True  # backward-compat: any tagged leaf
    df["inseparable_with"] = siblings
    df["inseparable_note"] = notes
    return df


def build_mcc_inseparable_notes(
    leaf_detail: pd.DataFrame, mega_bundles: dict[str, list[str]], mccs: list[str]
) -> pd.DataFrame:
    """Domain tags: «слияние» if mixed leaves / empty victim, else «неразделимо»."""
    rows = []
    leaves = leaf_detail.copy()
    leaves["mega"] = leaves["mega"].astype(str).str.strip()
    leaves["mcc_group"] = leaves["mcc_group"].fillna("").astype(str).str.strip()
    if "is_merge" not in leaves.columns:
        leaves["is_merge"] = False
    leaves["is_merge"] = leaves["is_merge"].fillna(False).astype(bool)
    merge_leaves = leaves[leaves["is_merge"]].copy()

    for mcc in mccs:
        megas_touching = sorted(m for m, bundle in mega_bundles.items() if mcc in bundle)
        sibling: set[str] = set()

        here = leaves[leaves["mcc_group"] == mcc]
        n_here = int(len(here))
        merge_here = merge_leaves[merge_leaves["mcc_group"] == mcc]
        n_merge_here = int(len(merge_here))

        elsewhere = (
            leaves[
                leaves["mega"].isin(megas_touching)
                & (leaves["mcc_group"] != "")
                & (leaves["mcc_group"] != mcc)
            ]
            if megas_touching
            else leaves.iloc[0:0]
        )

        hinted_elsewhere_mccs: set[str] = set()
        for _, r in merge_leaves.iterrows():
            if str(r.get("mcc_group") or "") == mcc:
                continue
            with_parts = [x.strip() for x in str(r.get("inseparable_with") or "").split("·") if x.strip()]
            if mcc in with_parts:
                hinted_elsewhere_mccs.add(str(r.get("mcc_group") or ""))
                sibling.update(x for x in with_parts if x != mcc)
                sibling.add(str(r.get("mcc_group") or ""))

        empty = n_here == 0 and (len(elsewhere) > 0 or bool(hinted_elsewhere_mccs))
        is_merge_domain = empty or n_merge_here > 0 or bool(hinted_elsewhere_mccs)

        for _, r in merge_here.iterrows():
            sibling.update(
                x.strip()
                for x in str(r.get("inseparable_with") or "").split("·")
                if x.strip() and x.strip() != mcc
            )

        if is_merge_domain:
            tag = "слияние"
            if empty:
                hosts = sorted({str(x) for x in elsewhere["mcc_group"].unique()}) if len(elsewhere) else sorted(
                    hinted_elsewhere_mccs
                )
                if mcc == "Обувь":
                    note = (
                        "Слияние: в сценариях гардероба обувь и одежда вместе; "
                        "1 сценарий → 1 MCC — GMV в «Одежда для взрослых», не в «Обувь»."
                    )
                    sibling = {"Одежда для взрослых"}
                else:
                    note = (
                        f"Слияние: домен без листьев; смешанные сценарии "
                        f"ушли в {' / '.join(hosts) or 'соседний MCC'}."
                    )
            elif n_merge_here:
                sample = " · ".join(merge_here["scenario"].astype(str).head(3))
                note = (
                    f"Слияние: {n_merge_here} лист(а) смешивают домены "
                    f"({sample}{'…' if n_merge_here > 3 else ''}); "
                    "при 1:1 GMV целиком здесь, смежный домен может быть пустым."
                )
            else:
                note = (
                    f"Слияние: сценарии в {' / '.join(sorted(hinted_elsewhere_mccs))} "
                    f"по названию тянут «{mcc}»."
                )
        else:
            tag = "неразделимо"
            note = "Неразделимо: сценарии домена целиком в одном MCC (правило 1:1)."

        rows.append(
            {
                "mcc_group": mcc,
                "split_tag": tag,
                "is_merge": is_merge_domain,
                "inseparable": True,
                "inseparable_with": " · ".join(sorted(x for x in sibling if x)),
                "inseparable_note": note,
                "inseparable_empty": empty,
            }
        )
    return pd.DataFrame(rows)


def load_etalons(path: Path) -> pd.DataFrame:
    df = pd.read_excel(path, sheet_name="Эталоны")
    df.columns = [str(c).strip() for c in df.columns]
    rename = {
        "NEW Эталон МАКСы": "etalon_max",
        "NEW Эталон 15 мин": "etalon_15",
        "NEW Эталон МАКС + 15 мин": "etalon_sum",
    }
    df = df.rename(columns={k: v for k, v in rename.items() if k in df.columns})
    for c in ("etalon_max", "etalon_15", "etalon_sum"):
        df[c] = pd.to_numeric(df[c], errors="coerce").fillna(0.0)
    return df


def etalon_by_lvl1(etalons: pd.DataFrame) -> pd.DataFrame:
    return etalons.groupby("lvl1", as_index=False).agg(
        etalon_sum=("etalon_sum", "sum"),
        etalon_max=("etalon_max", "sum"),
        etalon_15=("etalon_15", "sum"),
        ml4_count=("lvl4", "count") if "lvl4" in etalons.columns else ("lvl1", "count"),
    )


def rollup_etalon_by_mcc(etalons: pd.DataFrame, crosswalk: pd.DataFrame) -> pd.DataFrame:
    et_l1 = etalon_by_lvl1(etalons).set_index("lvl1")
    cw = crosswalk.copy()
    cw["lvl1"] = cw["lvl1"].fillna("").astype(str).str.strip()
    cw["mcc_group"] = cw["mcc_group"].astype(str).str.strip()
    specialty_l1 = {
        str(x).strip()
        for x in cw.loc[cw["bridge_type"].astype(str) == "specialty", "lvl1"]
        if str(x).strip()
    }
    mask = pd.Series(False, index=etalons.index)
    if "bg_new" in etalons.columns:
        mask |= etalons["bg_new"].astype(str).str.strip().isin(_FOOD_BG_NEW)
    if "bg" in etalons.columns:
        mask |= etalons["bg"].astype(str).str.strip().isin(_FOOD_BG)
    food_l1 = sorted(
        {str(x).strip() for x in etalons.loc[mask, "lvl1"].dropna() if str(x).strip()}
        - specialty_l1
        - _GROCERY_NON_FOOD
    )

    rows = []
    # Full NEW catalog (all lvl1) — reference width for marketplace / channel.
    all_lvl1 = sorted({str(x).strip() for x in etalons["lvl1"].dropna() if str(x).strip()})

    for mcc, grp in cw.groupby("mcc_group"):
        btypes = sorted(set(str(x) for x in grp["bridge_type"].dropna()))
        btype = btypes[0] if len(btypes) == 1 else ";".join(btypes)
        if "channel" in btypes:
            lvl1s = all_lvl1
            label = "channel full NEW"
            out_type = "channel"
        elif "grocery" in btypes:
            lvl1s = food_l1
            label = "grocery food ml1"
            out_type = "grocery"
        elif "specialty" in btypes:
            lvl1s = [str(x).strip() for x in grp["lvl1"] if str(x).strip()]
            label = "specialty"
            out_type = "specialty"
        else:
            rows.append(
                {
                    "mcc_group": mcc,
                    "bridge_type": btype,
                    "mapped_lvl1": "",
                    "etalon_sum_new": None,
                    "etalon_max_new": None,
                    "etalon_15_new": None,
                    "etalon_applicable": False,
                    "etalon_status": "н/п",
                }
            )
            continue

        uniq: list[str] = []
        es = em = e15 = ml4 = 0.0
        for l1 in lvl1s:
            if not l1 or l1 not in et_l1.index or l1 in uniq:
                continue
            uniq.append(l1)
            es += float(et_l1.loc[l1, "etalon_sum"])
            em += float(et_l1.loc[l1, "etalon_max"])
            e15 += float(et_l1.loc[l1, "etalon_15"])
            ml4 += float(et_l1.loc[l1, "ml4_count"])
        if not uniq:
            status = f"{label}: нет lvl1"
            applicable = False
            es = em = e15 = None  # type: ignore
        elif float(es) < ETALON_THIN_MAX:
            status = "узкий"
            applicable = True
        else:
            status = "широкий"
            applicable = True
        rows.append(
            {
                "mcc_group": mcc,
                "bridge_type": out_type,
                "mapped_lvl1": "; ".join(uniq) if out_type != "channel" else f"все NEW lvl1 ({len(uniq)})",
                "etalon_sum_new": es,
                "etalon_max_new": em,
                "etalon_15_new": e15,
                "ml4_count": int(ml4) if uniq else None,
                "etalon_applicable": applicable,
                "etalon_status": status,
            }
        )
    return pd.DataFrame(rows)


def load_exclusive_scenario_etalons(path: Path) -> pd.DataFrame:
    """Per-scenario exclusive NEW etalon (each lvl4 in exactly one scenario)."""
    raw = pd.read_excel(path, sheet_name="Сценарии")
    raw.columns = [str(c).strip() for c in raw.columns]
    rename = {
        "Мега": "mega",
        "Сценарий": "scenario",
        "Миссия": "mission",
        "Домен (MCC)": "mcc_group",
        "Эталон 15 мин": "etalon_15",
        "Эталон МАКС": "etalon_max",
        "Эталон сумма": "etalon_sum",
        "Статус эталона": "etalon_status_src",
    }
    df = raw.rename(columns={k: v for k, v in rename.items() if k in raw.columns})
    for c in ("etalon_15", "etalon_max", "etalon_sum"):
        if c in df.columns:
            df[c] = pd.to_numeric(df[c], errors="coerce").fillna(0).round().astype(int)
        else:
            df[c] = 0
    df["mega"] = df.get("mega", pd.Series(dtype=str)).astype(str).str.strip()
    df["scenario"] = df.get("scenario", pd.Series(dtype=str)).astype(str).str.strip()
    if "mission" not in df.columns or df["mission"].isna().all():
        df["mission"] = df["mega"] + " → " + df["scenario"]
    else:
        df["mission"] = df["mission"].astype(str).str.strip()
        df.loc[df["mission"].isin(["", "nan", "None"]), "mission"] = (
            df["mega"] + " → " + df["scenario"]
        )
    if "mcc_group" in df.columns:
        df["mcc_group"] = df["mcc_group"].fillna("").astype(str).str.strip()
        df.loc[df["mcc_group"].isin(["nan", "None"]), "mcc_group"] = ""
    else:
        df["mcc_group"] = ""
    return df


def load_unused_etalon_pool(path: Path) -> dict:
    """SKU from sheet «Вне_сценариев» (not in any scenario)."""
    try:
        unused = pd.read_excel(path, sheet_name="Вне_сценариев")
    except ValueError:
        return {"etalon_15": 0, "etalon_max": 0, "etalon_sum": 0, "n_cats": 0}
    unused.columns = [str(c).strip() for c in unused.columns]
    rename = {
        "Эталон 15 мин": "etalon_15",
        "Эталон МАКС": "etalon_max",
        "Эталон сумма": "etalon_sum",
    }
    unused = unused.rename(columns={k: v for k, v in rename.items() if k in unused.columns})
    for c in ("etalon_15", "etalon_max", "etalon_sum"):
        if c in unused.columns:
            unused[c] = pd.to_numeric(unused[c], errors="coerce").fillna(0)
        else:
            unused[c] = 0
    return {
        "etalon_15": int(round(float(unused["etalon_15"].sum()))),
        "etalon_max": int(round(float(unused["etalon_max"].sum()))),
        "etalon_sum": int(round(float(unused["etalon_sum"].sum()))),
        "n_cats": int(len(unused)),
    }


def load_mega_primary_mcc(path: Path) -> dict[str, str]:
    """One MCC per mega: primary role, then highest weight."""
    if not path.exists():
        return {}
    raw = pd.read_csv(path)
    raw["mega"] = raw["mega"].astype(str).str.strip()
    raw["mcc_group"] = raw["mcc_group"].astype(str).str.strip()
    raw = raw[(raw["mega"] != "") & (raw["mcc_group"] != "") & (raw["mcc_group"] != "Маркетплейсы")]
    if raw.empty:
        return {}
    raw["weight"] = pd.to_numeric(raw["weight"], errors="coerce").fillna(0.0) if "weight" in raw.columns else 1.0
    raw["pri"] = (
        raw["role"].astype(str).str.strip().eq("primary").astype(int) if "role" in raw.columns else 0
    )
    raw = raw.sort_values(["mega", "pri", "weight"], ascending=[True, False, False])
    return raw.drop_duplicates("mega", keep="first").set_index("mega")["mcc_group"].to_dict()


def fill_scenario_mcc(scen_et: pd.DataFrame, primary_mcc: dict[str, str]) -> pd.DataFrame:
    """Catalog scenarios without GMV have empty MCC in xlsx — put them on mega primary."""
    df = scen_et.copy()
    miss = df["mcc_group"].fillna("").astype(str).str.strip() == ""
    if miss.any():
        df.loc[miss, "mcc_group"] = df.loc[miss, "mega"].map(primary_mcc).fillna("")
        n = int((miss & (df["etalon_sum"] > 0)).sum())
        sku = int(df.loc[miss, "etalon_sum"].sum())
        if sku:
            print(
                f"Exclusive etalon: {n} catalog-only scenarios without GMV "
                f"mapped via mega → {sku} SKU (xlsx 3115 vs GMV leaves)",
                flush=True,
            )
    return df


def apply_exclusive_etalon_to_mcc(etalon_mcc: pd.DataFrame, scen_et: pd.DataFrame) -> pd.DataFrame:
    """Replace MCC etalon SKUs with exclusive scenario rollup (each lvl4 in one scenario)."""
    out = etalon_mcc.copy()
    leaves = scen_et[scen_et["mcc_group"].astype(str).str.strip() != ""].copy()
    by = (
        leaves.groupby("mcc_group", as_index=False)
        .agg(
            etalon_15_new=("etalon_15", "sum"),
            etalon_max_new=("etalon_max", "sum"),
            etalon_sum_new=("etalon_sum", "sum"),
        )
    )
    out = out.drop(columns=["etalon_15_new", "etalon_max_new", "etalon_sum_new"], errors="ignore")
    out = out.merge(by, on="mcc_group", how="left")
    for c in ("etalon_15_new", "etalon_max_new", "etalon_sum_new"):
        out[c] = pd.to_numeric(out[c], errors="coerce").fillna(0).astype(int)
    status = []
    for v in out["etalon_sum_new"]:
        if int(v) <= 0:
            status.append("н/д")
        elif int(v) < ETALON_THIN_MAX:
            status.append("узкий")
        else:
            status.append("широкий")
    out["etalon_status"] = status
    out["etalon_applicable"] = out["etalon_sum_new"] > 0
    return out


def attach_leaf_etalons(leaf_detail: pd.DataFrame, scen_et: pd.DataFrame) -> pd.DataFrame:
    df = leaf_detail.copy()
    df = df.drop(columns=["etalon_15", "etalon_max", "etalon_sum"], errors="ignore")
    df["mega"] = df["mega"].astype(str).str.strip()
    df["scenario"] = df["scenario"].astype(str).str.strip()
    alt = scen_et[["mega", "scenario", "etalon_15", "etalon_max", "etalon_sum"]].copy()
    alt["mega"] = alt["mega"].astype(str).str.strip()
    alt["scenario"] = alt["scenario"].astype(str).str.strip()
    alt = alt.drop_duplicates(["mega", "scenario"], keep="first")
    df = df.merge(alt, on=["mega", "scenario"], how="left")
    miss = df["etalon_sum"].isna()
    if miss.any() and "mission" in scen_et.columns:
        keys = scen_et[["mission", "etalon_15", "etalon_max", "etalon_sum"]].drop_duplicates(
            "mission", keep="first"
        )
        extra = df.loc[miss, ["mission"]].merge(keys, on="mission", how="left")
        for c in ("etalon_15", "etalon_max", "etalon_sum"):
            df.loc[miss, c] = extra[c].values
    n_miss = int(df["etalon_sum"].isna().sum())
    if n_miss:
        print(f"WARNING: {n_miss} scenarios without exclusive etalon match", flush=True)
    for c in ("etalon_15", "etalon_max", "etalon_sum"):
        df[c] = pd.to_numeric(df[c], errors="coerce").fillna(0).astype(int)
    return df


def append_catalog_only_etalon_leaves(leaf_detail: pd.DataFrame, scen_et: pd.DataFrame) -> pd.DataFrame:
    """Keep xlsx catalog-only scenarios (no GMV) so their exclusive SKU stay visible."""
    have = set(zip(leaf_detail["mega"].astype(str), leaf_detail["scenario"].astype(str)))
    extra = scen_et.copy()
    extra = extra[~extra.apply(lambda r: (str(r["mega"]), str(r["scenario"])) in have, axis=1)]
    extra = extra[extra["etalon_sum"] > 0].copy()
    if extra.empty:
        return leaf_detail
    total = (
        float(leaf_detail["wallet_total_gmv"].iloc[0])
        if "wallet_total_gmv" in leaf_detail.columns and len(leaf_detail)
        else 0.0
    )
    extra["GMV"] = 0.0
    extra["leaf_share"] = 0.0
    extra["wallet_total_gmv"] = total
    extra["seed_source"] = "catalog_only_etalon"
    extra["needs_review"] = False
    extra["is_merge"] = False
    extra["split_tag"] = "неразделимо"
    extra["inseparable"] = True
    extra["inseparable_with"] = ""
    extra["inseparable_note"] = "Нет в Scenario_Aggregates (GMV=0); эталон из каталога сценариев."
    for c in leaf_detail.columns:
        if c not in extra.columns:
            extra[c] = None
    return pd.concat([leaf_detail, extra[leaf_detail.columns]], ignore_index=True)


def _conclusion(row: pd.Series) -> str:
    gap = float(row["gap_pp"]) if pd.notna(row.get("gap_pp")) else 0.0
    btype = str(row.get("bridge_type") or "")
    et = row.get("etalon_sum_new")
    status = str(row.get("etalon_status") or "")
    et_txt = "н/д" if pd.isna(et) else f"{int(float(et))} SKU"
    thin = pd.isna(et) or float(et) < ETALON_THIN_MAX
    if bool(row.get("inseparable_empty")):
        base = str(row.get("inseparable_note") or "").strip()
        if gap >= GAP_MATERIAL_PP:
            return f"Недобор {100 * gap:.1f} п.п. — артефакт слияния. {base}"
        return base or "Слияние сценариев с соседним доменом."
    if "channel" in btype:
        if gap >= GAP_MATERIAL_PP:
            return (
                f"Канал (маркетплейсы): недобор {100 * gap:.1f} п.п.; "
                f"эталон сценариев {et_txt} (категория только в одном сценарии)."
            )
        return f"Канал; эталон сценариев {et_txt}."
    if gap >= GAP_MATERIAL_PP and thin and "н/п" not in status:
        msg = f"Недобор {100 * gap:.1f} п.п.; NEW-эталон узкий ({et_txt}) → гипотеза расширить ширину."
    elif gap >= GAP_MATERIAL_PP:
        msg = f"Недобор {100 * gap:.1f} п.п.; эталон {et_txt} ({status}) — смотреть миссии/спрос."
    elif gap <= -GAP_MATERIAL_PP:
        msg = f"Самокат перевешивает ({100 * gap:.1f} п.п.); эталон {et_txt}."
    else:
        msg = f"Доли сопоставимы; эталон {et_txt}."
    if bool(row.get("is_merge")) and str(row.get("inseparable_note") or "").strip():
        msg += " " + str(row["inseparable_note"]).strip()
    return msg


def build_mp_wallet_by_mcc(categories: pd.DataFrame, city: str) -> pd.DataFrame:
    """MCC share inside Magnit/5ka offline cohort wallets (never sum cohorts)."""
    rows: dict[str, dict] = {}
    for merch, prefix in (
        ("Магнит Оффлайн", "magnit_off"),
        ("Пятерочка Оффлайн", "pyat_off"),
    ):
        sub = categories[
            (categories["city"] == city) & (categories["retail_merch"] == merch)
        ].copy()
        total = float(sub["retail_gmv"].sum())
        for _, r in sub.iterrows():
            mcc = str(r["mcc_category"])
            d = rows.setdefault(mcc, {"mcc_group": mcc})
            gmv = float(r["retail_gmv"])
            d[f"{prefix}_retail_gmv"] = gmv
            d[f"{prefix}_wallet_share"] = (gmv / total) if total else 0.0
            d[f"{prefix}_share_of_mcc"] = (
                float(r["retail_gmv_share_of_category"])
                if pd.notna(r.get("retail_gmv_share_of_category"))
                else None
            )
    return pd.DataFrame(list(rows.values())) if rows else pd.DataFrame({"mcc_group": []})


def _samokat_share_in_cohort_grocery(merchants: pd.DataFrame, city: str, retail_merch: str) -> float | None:
    df = merchants[
        (merchants["city"] == city)
        & (merchants["retail_merch"] == retail_merch)
        & (merchants["mcc_category"] == GROCERY_MCC)
    ]
    if df.empty:
        return None
    mask = df["merchant"].astype(str).str.lower().str.contains("самокат", na=False)
    hit = df.loc[mask]
    if hit.empty:
        return 0.0
    return float(hit["share_in_mcc_cohort"].sum())


def build_mp_grocery_context(
    categories: pd.DataFrame,
    merchants: pd.DataFrame,
    sber: pd.DataFrame,
    city: str,
) -> dict:
    """Grocery-only context: Magnit/5ka cohort size vs Samokat audience + Samokat inside cohort."""
    sk = sber[sber["mcc_group"] == GROCERY_MCC]
    smkt_gmv = float(sk["smkt_gmv"].iloc[0]) if not sk.empty else 0.0
    smkt_cust = float(sk["smkt_customers"].iloc[0]) if not sk.empty and "smkt_customers" in sk else None

    cohorts = []
    for merch, key in (
        ("Магнит Оффлайн", "magnit_off"),
        ("Пятерочка Оффлайн", "pyat_off"),
    ):
        sub = categories[
            (categories["city"] == city)
            & (categories["retail_merch"] == merch)
            & (categories["mcc_category"] == GROCERY_MCC)
        ]
        gmv = float(sub["retail_gmv"].iloc[0]) if not sub.empty else 0.0
        cust = float(sub["retail_customers"].iloc[0]) if not sub.empty else 0.0
        smkt_in = _samokat_share_in_cohort_grocery(merchants, city, merch)
        ratio = (gmv / smkt_gmv) if smkt_gmv > 0 else None
        cohorts.append(
            {
                "key": key,
                "retail_merch": merch,
                "grocery_retail_gmv": gmv,
                "grocery_retail_customers": cust,
                "vs_samokat_aud_gmv": ratio,
                "samokat_share_in_cohort_grocery": smkt_in,
            }
        )

    mag = next(c for c in cohorts if c["key"] == "magnit_off")
    pyat = next(c for c in cohorts if c["key"] == "pyat_off")
    note = (
        f"Grocery · Магнит Оффлайн {mag['grocery_retail_gmv']/1e9:.1f} млрд ₽"
        f" ({mag['vs_samokat_aud_gmv']:.1f}× к аудитории Самоката)"
        if mag.get("vs_samokat_aud_gmv")
        else f"Grocery · Магнит Оффлайн {mag['grocery_retail_gmv']/1e9:.1f} млрд ₽"
    )
    if pyat.get("vs_samokat_aud_gmv"):
        note += (
            f"; Пятёрочка Оффлайн {pyat['grocery_retail_gmv']/1e9:.1f} млрд ₽"
            f" ({pyat['vs_samokat_aud_gmv']:.1f}×)."
        )
    else:
        note += f"; Пятёрочка Оффлайн {pyat['grocery_retail_gmv']/1e9:.1f} млрд ₽."
    for c in (mag, pyat):
        sh = c.get("samokat_share_in_cohort_grocery")
        if sh is not None:
            note += f" Внутри {c['retail_merch']} grocery Самокат ≈ {100 * sh:.0f}%."
    note += " Когорты не суммировать; эталон grocery — не по их структуре."

    return {
        "city": city,
        "mcc_group": GROCERY_MCC,
        "samokat_aud_grocery_smkt_gmv": smkt_gmv,
        "samokat_aud_grocery_customers": smkt_cust,
        "cohorts": cohorts,
        "note": note,
    }


def build_master(
    sber: pd.DataFrame,
    samokat: pd.DataFrame,
    etalon: pd.DataFrame,
    leaf_detail: pd.DataFrame,
    city: str,
    mp_wallet: pd.DataFrame | None = None,
    city_totals: dict[str, float] | None = None,
    inseparable: pd.DataFrame | None = None,
) -> pd.DataFrame:
    mccs = sorted(
        set(sber["mcc_group"].astype(str))
        | set(samokat["mcc_group"].astype(str))
        | set(etalon["mcc_group"].astype(str))
        | (set(mp_wallet["mcc_group"].astype(str)) if mp_wallet is not None and not mp_wallet.empty else set())
    )
    df = (
        pd.DataFrame({"mcc_group": mccs})
        .merge(sber, on="mcc_group", how="left")
        .merge(samokat, on="mcc_group", how="left")
        .merge(etalon, on="mcc_group", how="left")
    )
    if mp_wallet is not None and not mp_wallet.empty:
        df = df.merge(mp_wallet, on="mcc_group", how="left")
    if inseparable is not None and not inseparable.empty:
        df = df.merge(inseparable, on="mcc_group", how="left")
    df["city"] = city
    df["sber_full_share"] = df["sber_full_share"].fillna(0.0)
    df["sber_smkt_share"] = df["sber_smkt_share"].fillna(0.0)
    df["samokat_implied_share"] = df["samokat_implied_share"].fillna(0.0)
    df["samokat_implied_gmv"] = df["samokat_implied_gmv"].fillna(0.0)
    df["gmv"] = pd.to_numeric(df.get("gmv"), errors="coerce").fillna(0.0)
    df["inseparable"] = df.get("inseparable", False)
    df["inseparable"] = df["inseparable"].fillna(False).astype(bool)
    df["is_merge"] = df.get("is_merge", False)
    df["is_merge"] = df["is_merge"].fillna(False).astype(bool)
    df["inseparable_empty"] = df.get("inseparable_empty", False)
    df["inseparable_empty"] = df["inseparable_empty"].fillna(False).astype(bool)
    df["inseparable_with"] = df.get("inseparable_with", "").fillna("").astype(str)
    df["inseparable_note"] = df.get("inseparable_note", "").fillna("").astype(str)
    if "split_tag" not in df.columns:
        df["split_tag"] = ""
    df["split_tag"] = df["split_tag"].fillna("").astype(str)
    df.loc[df["split_tag"] == "", "split_tag"] = df["is_merge"].map(
        lambda x: "слияние" if x else "неразделимо"
    )
    df["gap_pp"] = df["sber_full_share"] - df["samokat_implied_share"]
    df["bridge_type"] = df["bridge_type"].fillna("unknown")
    df["n_leaves"] = df["n_leaves"].fillna(0).astype(int)

    totals = city_totals or {}
    sber_all_n = float(totals.get("sber_customers_total") or 0.0)
    # Sber ₽/client: аудитория Самоката в Сбере (город, Без МСС)
    sber_smkt_n = float(totals.get("sber_smkt_customers_total") or 0.0)
    # Samokat scenarios ₽/client: national_users периода
    scenario_n = float(totals.get("smkt_customers_total") or 0.0)
    df["sber_customers_total"] = sber_all_n
    df["sber_smkt_customers_total"] = sber_smkt_n
    df["smkt_customers_total"] = scenario_n
    df["smkt_customers_scope"] = totals.get("smkt_customers_scope") or "city_prefs"
    df["smkt_gmv"] = pd.to_numeric(df.get("smkt_gmv"), errors="coerce").fillna(0.0)
    sber_12m = df["smkt_gmv"] / sber_smkt_n if sber_smkt_n else pd.NA
    # 12м prefs → /2, чтобы период был сопоставим с 6м окном сценариев
    df["rub_per_customer_sber"] = sber_12m / 2.0 if sber_smkt_n else pd.NA
    df["rub_per_customer_smkt"] = df["samokat_implied_gmv"] / scenario_n if scenario_n else pd.NA
    df["rub_per_customer_sber_month"] = sber_12m / SBER_PERIOD_MONTHS if sber_smkt_n else pd.NA
    df["rub_per_customer_smkt_month"] = df["rub_per_customer_smkt"] / SMKT_PERIOD_MONTHS
    df["rub_per_customer_gap"] = df["rub_per_customer_sber"] - df["rub_per_customer_smkt"]
    df["rub_per_customer_gap_month"] = (
        df["rub_per_customer_sber_month"] - df["rub_per_customer_smkt_month"]
    )
    # backward-compat alias used in older HTML
    df["rub_per_customer"] = df["rub_per_customer_sber"]

    et_sum = pd.to_numeric(df["etalon_sum_new"], errors="coerce")
    et_total = float(et_sum.fillna(0).sum())
    df["etalon_sku_share"] = et_sum / et_total if et_total else pd.NA

    mask_sp = ~df["bridge_type"].astype(str).isin(["grocery", "channel"])
    sber_sp = float(df.loc[mask_sp, "sber_full_share"].sum())
    smkt_sp = float(df.loc[mask_sp, "samokat_implied_share"].sum())
    df["sber_specialty_share"] = df["sber_full_share"] / sber_sp if sber_sp else pd.NA
    df["samokat_specialty_share"] = df["samokat_implied_share"] / smkt_sp if smkt_sp else pd.NA
    df.loc[~mask_sp, ["sber_specialty_share", "samokat_specialty_share"]] = pd.NA
    df["gap_specialty_pp"] = df["sber_specialty_share"] - df["samokat_specialty_share"]
    df["conclusion"] = df.apply(_conclusion, axis=1)

    leaf_lists = (
        leaf_detail[leaf_detail["mcc_group"] != ""]
        .groupby("mcc_group")["mission"]
        .apply(lambda s: " · ".join(sorted(s)))
        .rename("missions")
    )
    df = df.merge(leaf_lists, on="mcc_group", how="left")
    return df.sort_values("gap_pp", ascending=False).reset_index(drop=True)



def build_coverage_table(leaf_detail: pd.DataFrame, sber: pd.DataFrame, coverage: dict) -> pd.DataFrame:
    rows = [
        {"раздел": "coverage", "ключ": k, "значение": str(v), "комментарий": ""}
        for k, v in coverage.items()
    ]
    mapped_mcc = set(leaf_detail.loc[leaf_detail["mcc_group"] != "", "mcc_group"])
    for mcc in sber["mcc_group"]:
        if mcc not in mapped_mcc:
            sh = float(sber.loc[sber.mcc_group == mcc, "sber_full_share"].iloc[0])
            rows.append(
                {
                    "раздел": "mcc_without_leaves",
                    "ключ": mcc,
                    "значение": f"sber_share={100 * sh:.2f}%",
                    "комментарий": "ложный недобор возможен",
                }
            )
    for _, r in leaf_detail[leaf_detail["mcc_group"] == ""].iterrows():
        rows.append(
            {
                "раздел": "unmapped_leaf",
                "ключ": r["mission"],
                "значение": f"GMV={float(r['GMV']):.0f}",
                "комментарий": "",
            }
        )
    return pd.DataFrame(rows)


def build_comparison_sheet(master: pd.DataFrame) -> pd.DataFrame:
    """Manager-facing comparison table (Sber vs Samokat implied vs etalon)."""
    df = master.copy()
    out = pd.DataFrame(
        {
            "Домен (MCC)": df["mcc_group"],
            "Доля Сбер, %": (df["sber_full_share"] * 100).round(2),
            "Доля Самокат (сценарии), %": (df["samokat_implied_share"] * 100).round(2),
            "Gap, п.п.": (df["gap_pp"] * 100).round(2),
            "₽/клиент Сбер (период), аудитория Самоката": df["rub_per_customer_sber"],
            "₽/клиент Сбер / мес, аудитория Самоката": df["rub_per_customer_sber_month"],
            "₽/клиент Самокат (сценарии, период)": df["rub_per_customer_smkt"],
            "₽/клиент Самокат (сценарии) / мес": df["rub_per_customer_smkt_month"],
            "Отклонение ₽/клиент (Сбер−Самокат)": df["rub_per_customer_gap"],
            "Отклонение ₽/клиент / мес": df["rub_per_customer_gap_month"],
            "Клиенты Сбер всего (город)": df["sber_customers_total"],
            "Клиенты Самоката в Сбере (город)": df["sber_smkt_customers_total"],
            "Клиенты Самокат (нац., период сценариев)": df["smkt_customers_total"],
            "Знаменатель Самокат сценарии": df["smkt_customers_scope"],
            "Доля Сбер specialty, %": (pd.to_numeric(df["sber_specialty_share"], errors="coerce") * 100).round(2),
            "Доля Самокат specialty, %": (
                pd.to_numeric(df["samokat_specialty_share"], errors="coerce") * 100
            ).round(2),
            "Gap specialty, п.п.": (pd.to_numeric(df["gap_specialty_pp"], errors="coerce") * 100).round(2),
            "GMV Сбер (полный), ₽": df["gmv"],
            "GMV Самоката в Сбере, ₽": df["smkt_gmv"],
            "GMV Самокат (сценарии), ₽": df["samokat_implied_gmv"],
            "Количество сценариев": df["n_leaves"],
            "Тег разметки": df["split_tag"],
            "Смежные домены (слияние)": df["inseparable_with"],
            "Пустой из‑за слияния": df["inseparable_empty"].map(lambda x: "да" if x else ""),
            "Заметка": df["inseparable_note"],
            "Эталон 15 мин": df["etalon_15_new"],
            "Эталон МАКС": df["etalon_max_new"],
            "Эталон сумма": df["etalon_sum_new"],
            "Доля SKU в эталоне, %": (pd.to_numeric(df["etalon_sku_share"], errors="coerce") * 100).round(2),
            "Статус эталона": df["etalon_status"],
            "Сценарии (список)": df.get("missions"),
            "Вывод": df["conclusion"],
        }
    )
    if "magnit_off_wallet_share" in df.columns:
        out["Доля в кошельке Магнит офф, %"] = (
            pd.to_numeric(df["magnit_off_wallet_share"], errors="coerce") * 100
        ).round(2)
        out["Доля в кошельке Пятёрочка офф, %"] = (
            pd.to_numeric(df["pyat_off_wallet_share"], errors="coerce") * 100
        ).round(2)
    return out.sort_values("Gap, п.п.", ascending=False).reset_index(drop=True)



def build_specialty_sheet(master: pd.DataFrame) -> pd.DataFrame:
    df = master[~master["bridge_type"].astype(str).isin(["grocery", "channel"])].copy()
    if df.empty:
        return pd.DataFrame()
    # renormalize specialty shares already on master
    out = pd.DataFrame(
        {
            "Домен (MCC)": df["mcc_group"],
            "Доля Сбер specialty, %": (pd.to_numeric(df["sber_specialty_share"], errors="coerce") * 100).round(2),
            "Доля Самокат specialty, %": (
                pd.to_numeric(df["samokat_specialty_share"], errors="coerce") * 100
            ).round(2),
            "Gap specialty, п.п.": (pd.to_numeric(df["gap_specialty_pp"], errors="coerce") * 100).round(2),
            "₽/клиент Сбер / мес, аудитория Самоката": df["rub_per_customer_sber_month"],
            "₽/клиент Самокат (сценарии) / мес": df["rub_per_customer_smkt_month"],
            "Отклонение ₽/клиент / мес": df["rub_per_customer_gap_month"],
            "Эталон 15 мин": df["etalon_15_new"],
            "Эталон МАКС": df["etalon_max_new"],
            "Эталон сумма": df["etalon_sum_new"],
            "Доля SKU в эталоне, %": (pd.to_numeric(df["etalon_sku_share"], errors="coerce") * 100).round(2),
            "Статус эталона": df["etalon_status"],
            "Количество сценариев": df["n_leaves"],
            "Вывод": df["conclusion"],
        }
    )
    return out.sort_values("Gap specialty, п.п.", ascending=False).reset_index(drop=True)


def build_mp_sheet(master: pd.DataFrame) -> pd.DataFrame:
    """Manager sheet: Sber / Samokat implied vs Magnit & Pyaterochka offline wallet shares."""
    df = master.copy()
    if "magnit_off_wallet_share" not in df.columns:
        return pd.DataFrame()
    return pd.DataFrame(
        {
            "Домен (MCC)": df["mcc_group"],
            "Доля Сбер, %": (df["sber_full_share"] * 100).round(2),
            "Доля Самокат (сценарии), %": (df["samokat_implied_share"] * 100).round(2),
            "Доля Магнит офф, %": (pd.to_numeric(df["magnit_off_wallet_share"], errors="coerce") * 100).round(2),
            "Доля Пятёрочка офф, %": (pd.to_numeric(df["pyat_off_wallet_share"], errors="coerce") * 100).round(2),
            "GMV Магнит офф, ₽": df.get("magnit_off_retail_gmv"),
            "GMV Пятёрочка офф, ₽": df.get("pyat_off_retail_gmv"),
            "Магнит доля от MCC, %": (
                pd.to_numeric(df.get("magnit_off_share_of_mcc"), errors="coerce") * 100
            ).round(2),
            "Пятёрочка доля от MCC, %": (
                pd.to_numeric(df.get("pyat_off_share_of_mcc"), errors="coerce") * 100
            ).round(2),
        }
    ).sort_values("Доля Сбер, %", ascending=False).reset_index(drop=True)


def build_mp_grocery_sheet(ctx: dict) -> pd.DataFrame:
    rows = []
    for c in ctx.get("cohorts") or []:
        rows.append(
            {
                "Город": ctx.get("city"),
                "Домен": ctx.get("mcc_group"),
                "Когорта": c["retail_merch"],
                "Grocery GMV когорты, ₽": c["grocery_retail_gmv"],
                "Клиенты когорты grocery": c["grocery_retail_customers"],
                "× к smkt_gmv аудитории Самоката": (
                    round(c["vs_samokat_aud_gmv"], 2) if c.get("vs_samokat_aud_gmv") is not None else None
                ),
                "Доля Самоката внутри grocery когорты, %": (
                    round(100 * c["samokat_share_in_cohort_grocery"], 2)
                    if c.get("samokat_share_in_cohort_grocery") is not None
                    else None
                ),
                "smkt_gmv аудитории Самоката grocery, ₽": ctx.get("samokat_aud_grocery_smkt_gmv"),
                "Заметка": ctx.get("note"),
            }
        )
    return pd.DataFrame(rows)


def build_leaves_sheet(leaf_detail: pd.DataFrame) -> pd.DataFrame:
    df = leaf_detail.copy()
    return pd.DataFrame(
        {
            "Сценарий (миссия)": df["mission"],
            "Мега": df["mega"],
            "Сценарий": df["scenario"],
            "Домен (MCC)": df["mcc_group"],
            "GMV, ₽": df["GMV"],
            "Доля в кошельке Самоката (сценарии), %": (df["leaf_share"] * 100).round(3),
            "Тег разметки": df.get("split_tag"),
            "Смежные домены": df.get("inseparable_with"),
            "Заметка": df.get("inseparable_note"),
            "Источник разметки": df.get("seed_source"),
            "Эталон 15 мин": df.get("etalon_15"),
            "Эталон МАКС": df.get("etalon_max"),
            "Эталон сумма": df.get("etalon_sum"),
        }
    ).sort_values(
        ["Доля в кошельке Самоката (сценарии), %", "GMV, ₽"], ascending=[False, False]
    ).reset_index(drop=True)



def compute_all(
    paths: dict[str, Path],
    city: str,
    *,
    exclude_mccs: frozenset[str] | set[str] | None = None,
    variant: str = "default",
) -> dict:
    if not paths["leaf_bridge"].exists():
        raise FileNotFoundError(paths["leaf_bridge"])
    bridge = pd.read_csv(paths["leaf_bridge"])
    if exclude_mccs:
        stuck = bridge[bridge["mcc_group"].astype(str).isin(exclude_mccs)]
        if not stuck.empty:
            raise ValueError(
                f"Bridge still maps {len(stuck)} leaves to excluded MCC: "
                + ", ".join(stuck["mission"].head(5).astype(str))
            )
    crosswalk = pd.read_csv(paths["crosswalk"])
    if exclude_mccs:
        crosswalk = crosswalk[~crosswalk["mcc_group"].astype(str).isin(exclude_mccs)].copy()
    sber = load_sber_wallet(paths["prefs"], city, exclude_mccs=exclude_mccs)
    city_totals = load_city_client_totals(paths["prefs"], city)
    # Sber ARPPU denominator: Samokat audience in Sber (city prefs), not all Sber clients
    city_totals["sber_smkt_customers_total"] = float(city_totals.get("smkt_customers_total") or 0.0)
    national_users = load_scenario_national_users(paths["meta"])
    if national_users is not None:
        city_totals["smkt_customers_total"] = float(national_users)
        city_totals["smkt_customers_scope"] = "national_scenario_period"
    else:
        city_totals["smkt_customers_scope"] = "city_prefs_smkt_customers"
        print(
            "WARNING: national_users missing in _run_meta.json — "
            "Samokat ₽/client falls back to city smkt_customers from prefs",
            flush=True,
        )
    leaves = load_leaf_gmv(paths["scenarios"])
    samokat, leaf_detail, coverage = allocate_leaf_to_mcc(leaves, bridge)
    mega_bundles = load_mega_mcc_bundles(paths["mega_bridge"])
    leaf_detail = annotate_inseparable_leaves(leaf_detail, mega_bundles)
    if exclude_mccs:
        samokat = samokat[~samokat["mcc_group"].astype(str).isin(exclude_mccs)].copy()
        total = float(leaves["GMV"].sum())
        samokat["samokat_implied_share"] = (
            samokat["samokat_implied_gmv"] / total if total else 0.0
        )
    etalons = load_etalons(paths["etalons"])
    etalon_mcc = rollup_etalon_by_mcc(etalons, crosswalk)
    if exclude_mccs:
        etalon_mcc = etalon_mcc[~etalon_mcc["mcc_group"].astype(str).isin(exclude_mccs)].copy()
    scen_et = load_exclusive_scenario_etalons(paths["scenario_etalons"])
    unused_pool = load_unused_etalon_pool(paths["scenario_etalons"])
    primary_mcc = load_mega_primary_mcc(paths["mega_bridge"])
    scen_et = fill_scenario_mcc(scen_et, primary_mcc)
    if exclude_mccs:
        scen_et = scen_et[~scen_et["mcc_group"].astype(str).isin(exclude_mccs)].copy()
    leaf_detail = attach_leaf_etalons(leaf_detail, scen_et)
    leaf_detail = append_catalog_only_etalon_leaves(leaf_detail, scen_et)
    etalon_mcc = apply_exclusive_etalon_to_mcc(etalon_mcc, scen_et)
    etalon_pool = {
        "in_scenarios_15": int(scen_et["etalon_15"].sum()),
        "in_scenarios_max": int(scen_et["etalon_max"].sum()),
        "in_scenarios_sum": int(scen_et["etalon_sum"].sum()),
        "unused_15": unused_pool["etalon_15"],
        "unused_max": unused_pool["etalon_max"],
        "unused_sum": unused_pool["etalon_sum"],
        "unused_n_cats": unused_pool["n_cats"],
    }
    print(
        f"Exclusive etalon from {paths['scenario_etalons'].name}: "
        f"15={etalon_pool['in_scenarios_15']} "
        f"MAX={etalon_pool['in_scenarios_max']} "
        f"sum={etalon_pool['in_scenarios_sum']} "
        f"(unused {etalon_pool['unused_sum']} SKU / {etalon_pool['unused_n_cats']} cats)",
        flush=True,
    )

    mp_src = load_mp_sources(paths["prefs_mp"])
    mp_wallet = build_mp_wallet_by_mcc(mp_src["categories"], city)
    if exclude_mccs:
        mp_wallet = mp_wallet[~mp_wallet["mcc_group"].astype(str).isin(exclude_mccs)].copy()
        for prefix in ("magnit_off", "pyat_off"):
            gcol = f"{prefix}_retail_gmv"
            scol = f"{prefix}_wallet_share"
            if gcol in mp_wallet.columns:
                tot = float(mp_wallet[gcol].fillna(0).sum())
                mp_wallet[scol] = mp_wallet[gcol] / tot if tot else 0.0
    mp_grocery = build_mp_grocery_context(mp_src["categories"], mp_src["merchants"], sber, city)

    mcc_universe = sorted(
        set(sber["mcc_group"].astype(str))
        | set(samokat["mcc_group"].astype(str))
        | set(etalon_mcc["mcc_group"].astype(str))
    )
    if exclude_mccs:
        mcc_universe = [m for m in mcc_universe if m not in exclude_mccs]
    inseparable = build_mcc_inseparable_notes(leaf_detail, mega_bundles, mcc_universe)

    master = build_master(
        sber, samokat, etalon_mcc, leaf_detail, city,
        mp_wallet=mp_wallet, city_totals=city_totals, inseparable=inseparable,
    )
    if exclude_mccs:
        master = master[~master["mcc_group"].astype(str).isin(exclude_mccs)].copy()
        mask_sp = ~master["bridge_type"].astype(str).isin(["grocery", "channel"])
        sber_sp = float(master.loc[mask_sp, "sber_full_share"].sum())
        smkt_sp = float(master.loc[mask_sp, "samokat_implied_share"].sum())
        master["sber_specialty_share"] = master["sber_full_share"] / sber_sp if sber_sp else pd.NA
        master["samokat_specialty_share"] = (
            master["samokat_implied_share"] / smkt_sp if smkt_sp else pd.NA
        )
        master.loc[~mask_sp, ["sber_specialty_share", "samokat_specialty_share"]] = pd.NA
        master["gap_specialty_pp"] = master["sber_specialty_share"] - master["samokat_specialty_share"]
        et_sum = pd.to_numeric(master["etalon_sum_new"], errors="coerce")
        et_total = float(et_sum.fillna(0).sum())
        master["etalon_sku_share"] = et_sum / et_total if et_total else pd.NA
        master["conclusion"] = master.apply(_conclusion, axis=1)
        master = master.sort_values("gap_pp", ascending=False).reset_index(drop=True)

    coverage_df = build_coverage_table(leaf_detail, sber, coverage)

    period = "н/д"
    meta: dict = {}
    if paths["meta"].exists():
        try:
            meta = json.loads(paths["meta"].read_text(encoding="utf-8"))
            if meta.get("period_from") and meta.get("period_to"):
                period = f"{meta['period_from']} — {meta['period_to']}"
            elif meta.get("date_from") and meta.get("date_to"):
                period = f"{meta['date_from']} — {meta['date_to']}"
        except Exception:
            meta = {}

    smkt_scope = city_totals.get("smkt_customers_scope")
    smkt_n = city_totals.get("smkt_customers_total")
    sber_smkt_n = city_totals.get("sber_smkt_customers_total")
    spravka_rows = [
        {
            "раздел": "метод",
            "ключ": "rule",
            "значение": "1 листовой сценарий → 1 MCC; implied wallet Самоката = сумма GMV листьев в домене",
            "комментарий": "",
        },
        {
            "раздел": "метод",
            "ключ": "gap",
            "значение": "sber_full_share (gmv) − samokat_implied_share (leaf GMV / ∑ all leaves)",
            "комментарий": "Положительный = недобор",
        },
        {
            "раздел": "метод",
            "ключ": "etalon",
            "значение": (
                "Эталон сценариев: каждая lvl4 NEW только в одном сценарии "
                "(пересечение → сценарий с наибольшим GMV); "
                "домен = сумма эталонов его сценариев (15 / МАКС / сумма), "
                f"Σ сценариев = {etalon_pool['in_scenarios_sum']} SKU; "
                f"вне сценариев {etalon_pool['unused_sum']} SKU "
                f"({etalon_pool['unused_n_cats']} категорий). "
                + (
                    "Маркетплейсы — только SKU gift-сценариев, не весь каталог."
                    if variant == "default"
                    else "Домен Маркетплейсы исключён."
                )
            ),
            "комментарий": "",
        },
        {
            "раздел": "метод",
            "ключ": "magnit_pyaterochka",
            "значение": (
                "Отдельные когорты оффлайн; доля MCC = retail_gmv / ∑ когорты. "
                "Не суммировать Магнит и Пятёрочку. Не gap vs Сбер."
            ),
            "комментарий": "контекст в карточке домена + блок grocery",
        },
        {
            "раздел": "метод",
            "ключ": "period",
            "значение": period,
            "комментарий": city,
        },
        {
            "раздел": "метод",
            "ключ": "mapped_gmv_share",
            "значение": f"{100 * coverage['mapped_share']:.2f}%",
            "комментарий": "",
        },
        {
            "раздел": "метод",
            "ключ": "variant",
            "значение": variant,
            "комментарий": "",
        },
        {
            "раздел": "метод",
            "ключ": "rub_per_customer",
            "значение": (
                f"Сбер: smkt_gmv домена / smkt_customers города (аудитория Самоката в Сбере, Без МСС"
                f", n={sber_smkt_n:.0f}); месяц = ÷{SBER_PERIOD_MONTHS} (prefs, 12 мес). "
                f"Самокат: GMV сценариев / national_users={smkt_n:.0f} ({smkt_scope}); "
                f"месяц = ÷{SMKT_PERIOD_MONTHS} (окно сценариев)."
            ),
            "комментарий": "не ARPPU внутри MCC (клиенты пересекаются)",
        },
        {
            "раздел": "метод",
            "ключ": "inseparable",
            "значение": (
                "Тег «слияние» — сценарий/домен смешивает 2+ MCC (обувь+одежда, мебель+дом, "
                "обустройство с нуля); «неразделимо» — обычный 1:1 без смешения доменов."
            ),
            "комментарий": "теги в HTML",
        },
    ]
    if variant == "no_marketplace":
        spravka_rows.append(
            {
                "раздел": "метод",
                "ключ": "no_marketplace",
                "значение": (
                    "Домен Маркетплейсы убран из кошелька Сбера (доли перенормированы). "
                    "6 gift-сценариев: срочный/last-minute/коллеге → продукты; "
                    "учителю → канцтовары; мужчине → электроника; родителям → товары для дома."
                ),
                "комментарий": str(paths["leaf_bridge"].name),
            }
        )

    spravka = pd.DataFrame(spravka_rows)

    return {
        "Master": master,
        "Сравнение": build_comparison_sheet(master),
        "Specialty": build_specialty_sheet(master),
        "Магнит_5ка": build_mp_sheet(master),
        "Grocery_MP": build_mp_grocery_sheet(mp_grocery),
        "Справка": spravka,
        "sber_wallet": sber,
        "samokat_leaves": leaf_detail.sort_values("GMV", ascending=False).reset_index(drop=True),
        "Leaves_view": build_leaves_sheet(leaf_detail),
        "samokat_mcc": samokat,
        "coverage": coverage_df,
        "coverage_meta": coverage,
        "leaf_bridge": bridge,
        "mp_grocery": mp_grocery,
        "variant": variant,
        "etalon_pool": etalon_pool,
    }



def city_payload_slice(tables: dict) -> dict:
    bridge_map = {
        str(r["mission"]): str(r["mcc_group"])
        for _, r in tables["leaf_bridge"].iterrows()
        if str(r.get("mcc_group") or "")
    }
    mcc_to_missions: dict[str, list[str]] = {}
    for mission, mcc in bridge_map.items():
        mcc_to_missions.setdefault(mcc, []).append(mission)
    return {
        "coverage": tables["coverage_meta"],
        "master": tables["Master"].to_dict(orient="records"),
        "sber_wallet": tables["sber_wallet"].to_dict(orient="records"),
        "samokat_leaves": tables["samokat_leaves"].to_dict(orient="records"),
        "mp_grocery": tables.get("mp_grocery") or {},
        "bridge_mission_to_mcc": bridge_map,
        "bridge_mcc_to_missions": mcc_to_missions,
    }


def write_xlsx(tables: dict, out_path: Path, city_tables: dict[str, dict] | None = None) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with pd.ExcelWriter(out_path, engine="openpyxl") as xl:
        tables["Сравнение"].to_excel(xl, sheet_name="Сравнение", index=False)
        tables["Specialty"].to_excel(xl, sheet_name="Specialty", index=False)
        if "Магнит_5ка" in tables and tables["Магнит_5ка"] is not None and not tables["Магнит_5ка"].empty:
            tables["Магнит_5ка"].to_excel(xl, sheet_name="Магнит_5ка", index=False)
        if "Grocery_MP" in tables and tables["Grocery_MP"] is not None and not tables["Grocery_MP"].empty:
            tables["Grocery_MP"].to_excel(xl, sheet_name="Grocery_MP", index=False)
        tables["Leaves_view"].to_excel(xl, sheet_name="Сценарии_доли", index=False)
        tables["Master"].to_excel(xl, sheet_name="Master", index=False)
        tables["Справка"].to_excel(xl, sheet_name="Справка", index=False)
        tables["coverage"].to_excel(xl, sheet_name="Coverage", index=False)
        tables["leaf_bridge"].to_excel(xl, sheet_name="Leaf_bridge", index=False)
        if city_tables:
            for city, ct in city_tables.items():
                if city == tables["Master"]["city"].iloc[0]:
                    continue
                sheet = "Сравнение_" + (
                    "SPB" if "Петербург" in city else ("KRD" if "Краснодар" in city else city[:8])
                )
                ct["Сравнение"].to_excel(xl, sheet_name=sheet[:31], index=False)


def write_payload(
    tables: dict,
    out_path: Path,
    city: str,
    cities_data: dict[str, dict],
    *,
    variant: str = "default",
    assortment: dict | None = None,
) -> None:
    gap_def = (
        "Gap = доля MCC в полном кошельке Сбера (gmv) минус доля MCC "
        "по сумме GMV листовых сценариев (1 сценарий → 1 домен)."
    )
    if variant == "no_marketplace":
        gap_def += (
            " Вариант без домена Маркетплейсы: доли Сбера перенормированы; "
            "gift-сценарии перенесены в другие MCC."
        )
    payload = {
        "city": city,
        "cities": list(cities_data.keys()),
        "variant": variant,
        "gap_definition": gap_def,
        "etalon_thin_max": ETALON_THIN_MAX,
        "period_months": PERIOD_MONTHS,
        "period_months_sber": SBER_PERIOD_MONTHS,
        "period_months_smkt": SMKT_PERIOD_MONTHS,
        "etalon_pool": tables.get("etalon_pool") or {},
        "assortment": assortment or {},
        "smkt_customers_scope": cities_data[city]["master"][0].get("smkt_customers_scope")
        if cities_data[city].get("master")
        else None,
        "smkt_customers_total": cities_data[city]["master"][0].get("smkt_customers_total")
        if cities_data[city].get("master")
        else None,
        "sber_smkt_customers_total": cities_data[city]["master"][0].get("sber_smkt_customers_total")
        if cities_data[city].get("master")
        else None,
        "by_city": cities_data,
        **cities_data[city],
    }
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(
        json.dumps(payload, ensure_ascii=False, default=str, indent=2), encoding="utf-8"
    )


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--downloads", default=str(DEFAULT_DOWNLOADS))
    ap.add_argument("--repo", default=str(REPO))
    ap.add_argument("--out-dir", default=str(ROOT / "outputs"))
    ap.add_argument("--city", default=DEFAULT_CITY, help="Primary city for xlsx default sheets")
    ap.add_argument(
        "--cities",
        default=",".join(DEFAULT_CITIES),
        help="Comma-separated cities (default: Москва only; HTML has no city switcher)",
    )
    ap.add_argument(
        "--with-marketplace",
        action="store_true",
        help="Keep Маркетплейсы MCC (default: exclude and remap gift scenarios)",
    )
    ap.add_argument("--skip-html", action="store_true")
    args = ap.parse_args()

    paths = resolve_paths(args)
    # Default report is without marketplaces (gift scenarios remapped).
    variant = "default"
    exclude_mccs: frozenset[str] | None = None
    suffix = ""
    if not args.with_marketplace:
        variant = "no_marketplace"
        exclude_mccs = frozenset({MARKETPLACE_MCC})
        paths["leaf_bridge"] = ROOT / "inputs" / "scenario_leaf_mcc_bridge_no_marketplace.csv"
        suffix = ""
    else:
        suffix = "_with_marketplace"

    cities = [c.strip() for c in args.cities.split(",") if c.strip()]
    if args.city not in cities:
        cities = [args.city] + cities

    city_tables: dict[str, dict] = {}
    cities_data: dict[str, dict] = {}
    for city in cities:
        print(f"Computing {city}…")
        city_tables[city] = compute_all(
            paths, city=city, exclude_mccs=exclude_mccs, variant=variant
        )
        cities_data[city] = city_payload_slice(city_tables[city])

    tables = city_tables[args.city]
    print("Building RK/BG assortment cards…")
    master = tables["Master"]
    mcc_gap = {
        str(r["mcc_group"]).strip(): float(r["gap_pp"] or 0.0)
        for _, r in master.iterrows()
        if str(r.get("mcc_group") or "").strip()
    }
    from datetime import datetime, timezone

    fact_path = paths.get("scenario_ml4_fact")
    ml4_gmv_path = paths.get("ml4_gmv_fact")
    aliases_path = paths.get("ml4_name_aliases")
    if fact_path:
        print(f"Scenario×ML4 fact GMV: {fact_path}")
    else:
        print("WARNING: scenario_ml4_gmv_fact not found — assortment ML4 GMV uses etalon proxy")
    if ml4_gmv_path:
        print(f"Global ML4 GMV (dead-leaf check): {ml4_gmv_path}")
    if aliases_path:
        print(f"ML4 name aliases: {aliases_path}")
    assortment = build_assortment_payload(
        rk_bg_path=paths["rk_bg"],
        etalons_path=paths["etalons"],
        scenario_etalons_path=paths["scenario_etalons"],
        catalog_path=paths["catalog"],
        leaf_gmv=tables["samokat_leaves"],
        mcc_gap=mcc_gap,
        scenario_ml4_fact_path=fact_path,
        ml4_gmv_fact_path=ml4_gmv_path,
        ml4_name_aliases_path=aliases_path,
        snapshot_meta={
            "as_of": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "city": args.city,
            "variant": variant,
            "etalon_file": str(paths["etalons"]),
            "gmv_file": str(paths["scenarios"]),
            "scenario_etalons_file": str(paths["scenario_etalons"]),
            "catalog_file": str(paths["catalog"]),
            "rk_bg_file": str(paths["rk_bg"]),
            "period_months_smkt": SMKT_PERIOD_MONTHS,
            "period_months_sber": SBER_PERIOD_MONTHS,
        },
    )
    n_cards = len((assortment.get("cards") or {}))
    n_scen = sum(int(c.get("n_scenarios") or 0) for c in (assortment.get("cards") or {}).values())
    n_prio = sum(len(c.get("priority_rows") or []) for c in (assortment.get("cards") or {}).values())
    ameta = assortment.get("snapshot_meta") or {}
    print(
        f"Assortment cards: {n_cards}; scenario rows: {n_scen}; priority rows: {n_prio}; "
        f"fact hits={ameta.get('scenario_ml4_fact_hits', 0)} "
        f"proxy fallback={ameta.get('scenario_ml4_proxy_fallback', 0)} "
        f"none={ameta.get('scenario_ml4_none', 0)} "
        f"aliases={ameta.get('ml4_name_aliases', 0)}"
    )

    out = paths["out_dir"]
    xlsx = out / f"domain_wallet_report{suffix}.xlsx"
    consolidated_xlsx = out / f"domain_wallet_consolidated{suffix}.xlsx"
    payload = out / f"domain_wallet_payload{suffix}.json"
    html = out / f"domain_wallet_report{suffix}.html" if suffix else out / "domain_wallet_report.html"
    write_xlsx(tables, xlsx, city_tables=city_tables)
    write_payload(
        tables, payload, args.city, cities_data, variant=variant, assortment=assortment
    )
    export_domain_wallet_excel(
        assortment,
        consolidated_xlsx,
        city=args.city,
        variant=variant,
        mcc_gap=mcc_gap,
    )
    print(f"Wrote {xlsx} · variant={variant}")
    print(f"Wrote {consolidated_xlsx} (RK cards consolidated, навигация РК×БГ)")
    print(f"Coverage mapped GMV: {100 * tables['coverage_meta']['mapped_share']:.1f}%")
    print(f"Top gaps ({args.city}):")
    for _, r in tables["Master"].head(6).iterrows():
        print(
            f"  {r['mcc_group']}: gap={100 * float(r['gap_pp']):+.1f} п.п. "
            f"Sber {100 * float(r['sber_full_share']):.1f}% vs "
            f"Smkt {100 * float(r['samokat_implied_share']):.1f}% "
            f"leaves={int(r['n_leaves'])} et={r.get('etalon_status')}"
        )
    if not args.skip_html:
        from render_domain_wallet_html import render_html

        render_html(payload, html, include_mp=False)
        render_html(payload, out / "domain_wallet_report_core.html", include_mp=False)
        html_mp = out / (
            "domain_wallet_report_with_marketplace_with_mp.html"
            if suffix
            else "domain_wallet_report_with_mp.html"
        )
        if suffix:
            html_mp = out / "domain_wallet_report_with_marketplace_mp.html"
        else:
            html_mp = out / "domain_wallet_report_with_mp.html"
        render_html(payload, html_mp, include_mp=True)
        print(f"Wrote {html}")
        print(f"Wrote {out / 'domain_wallet_report_core.html'}")
        print(f"Wrote {html_mp} (с Магнит/Пятёрочка)")


if __name__ == "__main__":
    main()
