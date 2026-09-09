#!/usr/bin/env python3
"""Load mega-mission → ml4 categories (+ leaf scenarios) from scenario description xlsx.

Scenarios / GMV assignment are defined on ml4. Sheet «Сценарии» has ml4 value columns;
«Сценарии по комнатам» is mostly ml3-only and is used only as a fallback for scenario names.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd


def _is_pct_col(name: str) -> bool:
    cl = name.lower()
    return name.startswith("%") or "доля" in cl


def _ml4_value_cols(columns: list[str]) -> list[str]:
    out = []
    for c in columns:
        if _is_pct_col(c):
            continue
        cl = c.lower()
        if "мл-4" in cl or "ml-4" in cl or "ml4" in cl:
            out.append(c)
    return out


def _collect_from_sheet(df: pd.DataFrame) -> dict[str, dict[str, set[str]]]:
    df = df.copy()
    df.columns = [str(c).strip() for c in df.columns]
    mega_col = next((c for c in df.columns if "егасценарий" in c.lower() or c == "mega"), None)
    scen_col = next((c for c in df.columns if str(c).strip() in ("Сценарий", "scenario")), None)
    if not mega_col:
        return {}
    ml4_cols = _ml4_value_cols(list(df.columns))
    out: dict[str, dict[str, set[str]]] = {}
    for mega, grp in df.groupby(mega_col, dropna=True):
        mega_s = str(mega).strip()
        if not mega_s or mega_s.lower() == "nan":
            continue
        bucket = out.setdefault(mega_s, {"ml4": set(), "scenarios": set()})
        for _, row in grp.iterrows():
            if scen_col and pd.notna(row.get(scen_col)):
                sc = str(row[scen_col]).strip()
                if sc and sc.lower() != "nan":
                    bucket["scenarios"].add(sc)
            for c in ml4_cols:
                v = row.get(c)
                if pd.isna(v):
                    continue
                name = str(v).strip()
                if name and name.lower() != "nan":
                    bucket["ml4"].add(name)
    return out


def _preferred_sheets(sheet_names: list[str]) -> list[str]:
    """Prefer «Сценарии» (has ml4 cols) over rooms sheet (mostly ml3)."""
    preferred: list[str] = []
    for name in sheet_names:
        if name.strip() == "Сценарии":
            preferred.append(name)
    for name in sheet_names:
        if "комнат" in name.lower() and name not in preferred:
            preferred.append(name)
    if not preferred:
        preferred = [s for s in sheet_names if "ценари" in s.lower()][:2]
    return preferred


def load_mega_category_map(path: Path) -> pd.DataFrame:
    """
    Return one row per mega with:
      mega, n_scenarios, n_ml4, scenarios_list, ml4_categories, ml4_preview
    """
    xl = pd.ExcelFile(path)
    preferred = _preferred_sheets(xl.sheet_names)

    merged: dict[str, dict[str, set[str]]] = {}
    for sheet in preferred:
        part = _collect_from_sheet(pd.read_excel(path, sheet_name=sheet))
        for mega, payload in part.items():
            bucket = merged.setdefault(mega, {"ml4": set(), "scenarios": set()})
            bucket["ml4"].update(payload["ml4"])
            bucket["scenarios"].update(payload["scenarios"])

    rows = []
    for mega, payload in sorted(merged.items(), key=lambda x: x[0]):
        ml4 = sorted(payload["ml4"])
        scenarios = sorted(payload["scenarios"])
        preview = " · ".join(ml4[:12])
        if len(ml4) > 12:
            preview += f" · … (+{len(ml4) - 12})"
        rows.append(
            {
                "mega": mega,
                "n_scenarios": len(scenarios),
                "n_ml4": len(ml4),
                "scenarios_list": " · ".join(scenarios),
                "ml4_categories": " · ".join(ml4),
                "ml4_preview": preview,
            }
        )
    return pd.DataFrame(rows)


def enrich_dictionary_with_categories(
    dictionary: pd.DataFrame,
    mega_cats: pd.DataFrame,
) -> pd.DataFrame:
    if dictionary.empty or mega_cats is None or mega_cats.empty:
        out = dictionary.copy()
        for c in ("n_ml4", "n_scenarios", "ml4_preview", "ml4_categories", "scenarios_list"):
            if c not in out.columns:
                out[c] = None
        return out
    cols = ["mega", "n_ml4", "n_scenarios", "ml4_preview", "ml4_categories", "scenarios_list"]
    return dictionary.merge(mega_cats[cols], on="mega", how="left")
