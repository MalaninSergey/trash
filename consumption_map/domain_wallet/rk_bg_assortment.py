#!/usr/bin/env python3
"""RK × business-group assortment slice for domain_wallet cards."""

from __future__ import annotations

import json
import re
from pathlib import Path

import pandas as pd

UNASSIGNED_RK = "без РК"
FOOD_RK = "food"
ETALON_THIN_MAX = 50


def _norm(s: object) -> str:
    t = str(s or "").strip().lower().replace("ё", "е")
    return re.sub(r"\s+", " ", t)


_SELEKTIV_RE = re.compile(r"\s*[-–—]?\s*селектив\s*$", re.IGNORECASE)


def _strip_selektiv(name: str) -> str:
    """Remove trailing «-селектив» / «селектив» suffix; empty if nothing left."""
    base = _SELEKTIV_RE.sub("", _norm(name)).strip(" -–—")
    return base


def load_ml4_name_aliases(path: Path | None) -> dict[str, str]:
    """from→to map for ML4 fact lookup (both sides `_norm`)."""
    if path is None or not Path(path).exists():
        return {}
    df = pd.read_csv(path)
    cols = {str(c).strip().lower(): c for c in df.columns}
    from_c = cols.get("from") or cols.get("alias_ml4") or cols.get("alias")
    to_c = cols.get("to") or cols.get("canonical_ml4") or cols.get("canonical")
    if from_c is None or to_c is None:
        raise ValueError(f"ml4_name_aliases needs from/to columns, got {list(df.columns)}")
    out: dict[str, str] = {}
    for _, r in df.iterrows():
        fr, to = _norm(r[from_c]), _norm(r[to_c])
        if fr and to and fr != to:
            out[fr] = to
    return out


def load_ml4_global_gmv(path: Path | None) -> dict[str, float]:
    """Global ML4 GMV keyed by `_norm(ml4)` (positive sales signal for dead-leaf check)."""
    if path is None or not Path(path).exists():
        return {}
    p = Path(path)
    if p.suffix.lower() == ".parquet":
        df = pd.read_parquet(p)
    else:
        df = pd.read_csv(p)
    if df.empty:
        return {}
    out: dict[str, float] = {}
    for _, r in df.iterrows():
        ml4_n = _norm(r.get("ml4_n") if "ml4_n" in df.columns else r.get("ml4"))
        if not ml4_n:
            continue
        gmv = float(pd.to_numeric(r.get("gmv"), errors="coerce") or 0.0)
        out[ml4_n] = out.get(ml4_n, 0.0) + gmv
    return out


def _ml4_name_candidates(
    ml4_n: str,
    aliases: dict[str, str],
    global_gmv: dict[str, float] | None = None,
) -> list[str]:
    """Lookup order: exact → CSV alias → strip селектив (not for globally-dead exact names)."""
    n = _norm(ml4_n)
    if not n:
        return []
    out: list[str] = []
    seen: set[str] = set()

    def add(x: str) -> None:
        x = _norm(x)
        if x and x not in seen:
            seen.add(x)
            out.append(x)

    add(n)
    if n in aliases:
        add(aliases[n])
    base = _strip_selektiv(n)
    if base and base != n:
        # Dead selective (0 positions under exact name) must not inherit base GMV.
        if global_gmv is None or float(global_gmv.get(n) or 0.0) > 0.0:
            add(base)
    return out


def lookup_scenario_ml4_fact(
    fact_gmv: dict[tuple[str, str], float],
    mission_n: str,
    ml4_n: str,
    aliases: dict[str, str],
    global_gmv: dict[str, float] | None = None,
) -> float | None:
    """Return scenario×ml4 fact GMV after exact / alias / селектив fallback."""
    m = _norm(mission_n)
    if not m:
        return None
    for key in _ml4_name_candidates(ml4_n, aliases, global_gmv):
        hit = fact_gmv.get((m, key))
        if hit is not None:
            return float(hit)
    return None


def has_global_ml4_sales(
    global_gmv: dict[str, float],
    ml4_n: str,
    aliases: dict[str, str],
) -> bool:
    """True if exact or CSV-alias name has global ml4_gmv > 0 (strip-base not counted for dead)."""
    if not global_gmv:
        return True  # no global file → keep legacy proxy eligibility
    n = _norm(ml4_n)
    if float(global_gmv.get(n) or 0.0) > 0.0:
        return True
    alias = aliases.get(n)
    if alias and float(global_gmv.get(alias) or 0.0) > 0.0:
        return True
    return False


def _is_spec_nutrition(lvl1: str) -> bool:
    t = _norm(lvl1)
    return t == "специальное питание" or ("спец" in t and "пита" in t)


def _is_fmcg_bg(bg: str) -> bool:
    return "fmcg" in _norm(bg)


def _is_qnf_zero(qnf: object) -> bool:
    """True when etalon flag «Категория относится к QNF» is 0 (food shelf)."""
    if qnf is None or (isinstance(qnf, float) and pd.isna(qnf)):
        return False
    t = str(qnf).strip().lower().replace(",", ".")
    if t in ("0", "0.0", "false", "нет", "no"):
        return True
    try:
        return float(t) == 0.0
    except ValueError:
        return False


def _ml1_matches(ml1_raw: str, lvl1: str) -> bool:
    rule = _norm(ml1_raw)
    if not rule or rule == "все":
        return True
    if "кроме" in rule:
        return not _is_spec_nutrition(lvl1)
    if "пита" in rule:
        return _is_spec_nutrition(lvl1)
    return _norm(lvl1) == rule


def load_rk_bg_rules(path: Path) -> pd.DataFrame:
    raw = pd.read_excel(path)
    raw.columns = [str(c).strip() for c in raw.columns]
    rename = {"РК": "rk", "мл1": "ml1", "ml1": "ml1"}
    raw = raw.rename(columns={k: v for k, v in rename.items() if k in raw.columns})
    if "bg" not in raw.columns or "rk" not in raw.columns:
        raise ValueError(f"rk_bg sheet needs РК/bg columns, got {list(raw.columns)}")
    if "ml1" not in raw.columns:
        raw["ml1"] = "все"
    out = pd.DataFrame(
        {
            "rk": raw["rk"].astype(str).str.strip(),
            "bg": raw["bg"].astype(str).str.strip(),
            "ml1": raw["ml1"].astype(str).str.strip(),
        }
    )
    out = out[(out["rk"] != "") & (out["bg"] != "") & (out["rk"] != "nan")]
    return out.reset_index(drop=True)


def load_etalon_lvl4(path: Path) -> pd.DataFrame:
    et = pd.read_excel(path, sheet_name="Эталоны")
    et.columns = [str(c).strip() for c in et.columns]
    et = et.rename(
        columns={
            "NEW Эталон МАКСы": "etalon_max",
            "NEW Эталон 15 мин": "etalon_15",
            "NEW Эталон МАКС + 15 мин": "etalon_sum",
            "Категория относится к QNF": "qnf",
            "Сезонная": "seasonal",
        }
    )
    for c in ("etalon_max", "etalon_15", "etalon_sum"):
        et[c] = pd.to_numeric(et[c], errors="coerce").fillna(0.0)
    for col in ("bg", "bg_new", "lvl1", "lvl2", "lvl3", "lvl4"):
        if col not in et.columns:
            et[col] = ""
        et[col] = et[col].map(lambda x: "" if pd.isna(x) else str(x).strip())
    et["lvl4_n"] = et["lvl4"].map(_norm)
    et["lvl3_n"] = et["lvl3"].map(_norm)
    et["lvl1_n"] = et["lvl1"].map(_norm)
    et = et[et["lvl4_n"] != ""].copy()
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
            bg=("bg", "first"),
            qnf=("qnf", "first"),
            seasonal=("seasonal", "first"),
        )
    )
    return by4.set_index("lvl4_n", drop=False)


def _lvl3_index(by4: pd.DataFrame) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    for lvl4_n, row in by4.iterrows():
        l3 = _norm(row.get("lvl3") or "")
        if not l3:
            continue
        out.setdefault(l3, []).append(str(lvl4_n))
    return out


def assign_owners(by4: pd.DataFrame, rules: pd.DataFrame) -> pd.DataFrame:
    """Each etalon lvl4 → (rk, bg). Unmapped BGs go to без РК.

    FMCG + QNF=0 → synthetic RK «food» (overrides dictionary owners).
    """
    rows = []
    for lvl4_n, row in by4.iterrows():
        bg = str(row.get("bg") or "").strip()
        lvl1 = str(row.get("lvl1") or "").strip()
        if _is_fmcg_bg(bg) and _is_qnf_zero(row.get("qnf")):
            matched = [(FOOD_RK, bg or "—")]
        else:
            hits = rules[rules["bg"] == bg]
            matched = []
            for _, rule in hits.iterrows():
                if _ml1_matches(str(rule["ml1"]), lvl1):
                    matched.append((str(rule["rk"]), bg))
            if not matched:
                matched = [(UNASSIGNED_RK, bg or "—")]
        seen: set[tuple[str, str]] = set()
        for rk, bg_name in matched:
            key = (rk, bg_name)
            if key in seen:
                continue
            seen.add(key)
            rec = row.to_dict()
            rec["rk"] = rk
            rec["bg"] = bg_name
            rec["lvl4_n"] = str(lvl4_n)
            rows.append(rec)
    return pd.DataFrame(rows)


def load_exclusive_winners(path: Path) -> dict[str, str]:
    try:
        det = pd.read_excel(path, sheet_name="Категории_эталона")
    except ValueError:
        return {}
    det.columns = [str(c).strip() for c in det.columns]
    if "Категория эталона (lvl4)" not in det.columns or "Миссия" not in det.columns:
        return {}
    out: dict[str, str] = {}
    for _, r in det.iterrows():
        key = _norm(r["Категория эталона (lvl4)"])
        if not key:
            continue
        out[key] = str(r["Миссия"]).strip()
    return out


def load_unused_rows(path: Path) -> pd.DataFrame:
    try:
        unused = pd.read_excel(path, sheet_name="Вне_сценариев")
    except ValueError:
        return pd.DataFrame()
    unused.columns = [str(c).strip() for c in unused.columns]
    unused = unused.rename(
        columns={
            "Lvl1": "lvl1",
            "Lvl2": "lvl2",
            "Lvl3": "lvl3",
            "Lvl4": "lvl4",
            "Эталон 15 мин": "etalon_15",
            "Эталон МАКС": "etalon_max",
            "Эталон сумма": "etalon_sum",
        }
    )
    if "lvl4" not in unused.columns:
        return pd.DataFrame()
    unused["lvl4_n"] = unused["lvl4"].map(_norm)
    for c in ("etalon_15", "etalon_max", "etalon_sum"):
        unused[c] = pd.to_numeric(unused.get(c), errors="coerce").fillna(0)
    return unused


def load_catalog_scenarios(path: Path) -> list[dict]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    scenarios = raw.get("scenarios") or []
    out = []
    for s in scenarios:
        mega = str(s.get("mega") or "").strip()
        sub = str(s.get("sub") or s.get("scenario") or "").strip()
        mission = str(s.get("label") or f"{mega} → {sub}").strip()
        cats = [str(x).strip() for x in (s.get("cats_runtime") or []) if str(x).strip()]
        out.append({"mega": mega, "scenario": sub, "mission": mission, "cats": cats})
    return out


def resolve_scenario_lvl4(
    cats: list[str],
    by4: pd.DataFrame,
    lvl3_to_lvl4: dict[str, list[str]],
) -> tuple[list[str], int]:
    keys: list[str] = []
    seen: set[str] = set()
    unmatched = 0
    for cat in cats:
        n = _norm(cat)
        if n in by4.index:
            if n not in seen:
                keys.append(n)
                seen.add(n)
            continue
        children = lvl3_to_lvl4.get(n) or []
        if children:
            for c in children:
                if c not in seen:
                    keys.append(c)
                    seen.add(c)
        else:
            unmatched += 1
    return keys, unmatched


def _etalon_status(sum_sku: float, n_ml4: int) -> str:
    if n_ml4 <= 0:
        return "н/д"
    if sum_sku >= ETALON_THIN_MAX:
        return "широкий"
    return "узкий"


def _ml4_record(
    row: pd.Series,
    *,
    exclusive: bool,
    owner: str,
    rk: str = "",
    bg_owner: str = "",
    in_this_bg: bool = True,
) -> dict:
    qnf = row.get("qnf")
    seasonal = row.get("seasonal")
    bg = str(bg_owner or row.get("bg") or "")
    return {
        "lvl1": str(row.get("lvl1") or ""),
        "lvl2": str(row.get("lvl2") or ""),
        "lvl3": str(row.get("lvl3") or ""),
        "lvl4": str(row.get("lvl4") or ""),
        "rk": str(rk or ""),
        "bg": bg,
        "in_this_bg": bool(in_this_bg),
        "etalon_15": int(round(float(row.get("etalon_15") or 0))),
        "etalon_max": int(round(float(row.get("etalon_max") or 0))),
        "etalon_sum": int(round(float(row.get("etalon_sum") or 0))),
        "exclusive": bool(exclusive),
        "owner": owner if not exclusive else "",
        "qnf": "" if qnf is None or (isinstance(qnf, float) and pd.isna(qnf)) else str(qnf),
        "seasonal": (
            ""
            if seasonal is None or (isinstance(seasonal, float) and pd.isna(seasonal))
            else str(seasonal)
        ),
    }


def _primary_owner(owned_map: dict[str, list[tuple[str, str]]], kn: str) -> tuple[str, str]:
    pairs = owned_map.get(kn) or []
    if not pairs:
        return "", ""
    return pairs[0][0], pairs[0][1]


def _build_scenario_ml4_rows(
    kns: list[str],
    *,
    by4: pd.DataFrame,
    winners: dict[str, str],
    owned_map: dict[str, list[tuple[str, str]]],
    fact_gmv: dict[tuple[str, str], float],
    mission: str,
    mission_n: str,
    aliases: dict[str, str] | None = None,
    global_gmv: dict[str, float] | None = None,
    card_keys: set[str] | None = None,
) -> tuple[list[dict], int]:
    """Build ML4 rows. If card_keys set, mark in_this_bg; else all True."""
    alias_map = aliases or {}
    glob = global_gmv if global_gmv is not None else {}
    rows: list[dict] = []
    n_lost = 0
    for kn in kns:
        if kn not in by4.index:
            continue
        row = by4.loc[kn]
        winner = winners.get(kn) or ""
        exclusive = bool(winner) and winner == mission
        if winner and not exclusive:
            n_lost += 1
        rk, bg_owner = _primary_owner(owned_map, kn)
        in_bg = True if card_keys is None else kn in card_keys
        rec = _ml4_record(
            row,
            exclusive=exclusive,
            owner=winner,
            rk=rk,
            bg_owner=bg_owner or str(row.get("bg") or ""),
            in_this_bg=in_bg,
        )
        fact = lookup_scenario_ml4_fact(
            fact_gmv, mission_n, kn, alias_map, global_gmv=glob
        )
        if fact is not None:
            rec["gmv_ml4"] = float(fact)
            rec["gmv_source"] = "fact"
        elif fact_gmv:
            # Hard rule: no (mission, ml4) fact → GMV=0 / none.
            # Do not spread scenario GMV by etalon weight (inflates UI vs real sales).
            rec["gmv_ml4"] = 0.0
            rec["gmv_source"] = "none"
        elif not has_global_ml4_sales(glob, kn, alias_map):
            # Legacy (no fact file): dead leaf → none.
            rec["gmv_ml4"] = 0.0
            rec["gmv_source"] = "none"
        else:
            # Legacy (no fact file): etalon-weight proxy eligibility.
            rec["gmv_ml4"] = None
            rec["gmv_source"] = "proxy"
        rows.append(rec)
    rows.sort(key=lambda x: (-int(x.get("in_this_bg") or 0), -x["etalon_sum"], x["lvl4"]))
    return rows, n_lost


def _fill_proxy_gmv(ml4_rows: list[dict], scenario_gmv: float) -> None:
    """Fact keep; none stay 0 / excluded from weights.

    Legacy only: remaining rows get etalon-weight share of scenario GMV as proxy
    (used when scenario×ml4 fact file is absent). With fact file loaded, no proxy rows.
    """
    if not ml4_rows:
        return
    weights: list[float] = []
    for m in ml4_rows:
        if m.get("gmv_source") == "none":
            weights.append(0.0)
        else:
            weights.append(float(m.get("etalon_sum") or 0))
    allocs = _allocate_gmv(scenario_gmv, weights)
    for m, alloc in zip(ml4_rows, allocs):
        src = m.get("gmv_source")
        if src == "fact" and m.get("gmv_ml4") is not None:
            continue
        if src == "none":
            m["gmv_ml4"] = 0.0
            continue
        m["gmv_ml4"] = float(alloc)
        m["gmv_source"] = "proxy"


def _allocate_gmv(gmv: float, weights: list[float]) -> list[float]:
    """Proxy split of scenario GMV across ML4 (by etalon_sum; equal if all zero)."""
    if not weights:
        return []
    positive = [max(float(w or 0.0), 0.0) for w in weights]
    total = float(sum(positive))
    if total <= 0:
        share = float(gmv) / len(weights)
        return [share] * len(weights)
    return [float(gmv) * (w / total) for w in positive]


def _allocate_ints(total: int, weights: list[float]) -> list[int]:
    """Largest-remainder integer split; parts sum exactly to total."""
    n = len(weights)
    if n == 0:
        return []
    total_i = int(total)
    if total_i <= 0:
        return [0] * n
    positive = [max(float(w or 0.0), 0.0) for w in weights]
    wsum = float(sum(positive))
    if wsum <= 0:
        base, rem = divmod(total_i, n)
        out = [base] * n
        for i in range(rem):
            out[i] += 1
        return out
    raw = [total_i * (w / wsum) for w in positive]
    floors = [int(x) for x in raw]  # truncate toward 0 for non-negative
    rem = total_i - sum(floors)
    order = sorted(
        range(n),
        key=lambda i: (raw[i] - floors[i], positive[i], -i),
        reverse=True,
    )
    for i in order[: max(rem, 0)]:
        floors[i] += 1
    return floors


def _apply_gmv_proportional_etalon_shares(cards: dict[str, dict], by4: pd.DataFrame) -> None:
    """Overwrite scenario ML4 etalon_* with GMV-proportional shares of the lvl4 total.

    Card-level ML4 index rows keep full BG totals. Scenario-row aggregates
    (exclusive winner-take-all) stay as computed earlier. Display on scenario
    expand / ML4→scenarios uses shares so Σ across missions = ML4 etalon total.

    Only etalon_15 and etalon_max are split by largest remainder; per mission
    etalon_sum = etalon_15 + etalon_max (never allocated independently).

    Weight per mission: gmv_ml4 (fact) if > 0, else scenario GMV.
    """
    kn_mission_w: dict[str, dict[str, float]] = {}
    for card in cards.values():
        for s in card.get("scenarios") or []:
            mission = str(s.get("mission") or "")
            if not mission:
                continue
            scen_gmv = float(s.get("gmv") or 0.0)
            seen_kn: set[str] = set()
            for lst_name in ("ml4", "ml4_all"):
                for m in s.get(lst_name) or []:
                    kn = _norm(m.get("lvl4"))
                    if not kn or kn in seen_kn:
                        continue
                    seen_kn.add(kn)
                    try:
                        gmv_ml4 = float(m["gmv_ml4"]) if m.get("gmv_ml4") is not None else 0.0
                    except (TypeError, ValueError):
                        gmv_ml4 = 0.0
                    w = gmv_ml4 if gmv_ml4 > 0 else scen_gmv
                    slot = kn_mission_w.setdefault(kn, {})
                    prev = slot.get(mission)
                    if prev is None or w > prev:
                        slot[mission] = w

    kn_shares: dict[str, dict[str, tuple[int, int, int]]] = {}
    for kn, mission_w in kn_mission_w.items():
        if kn not in by4.index:
            continue
        row = by4.loc[kn]
        e15 = int(round(float(row.get("etalon_15") or 0)))
        emax = int(round(float(row.get("etalon_max") or 0)))
        missions = list(mission_w.keys())
        weights = [mission_w[m] for m in missions]
        a15 = _allocate_ints(e15, weights)
        amax = _allocate_ints(emax, weights)
        kn_shares[kn] = {
            missions[i]: (a15[i], amax[i], a15[i] + amax[i]) for i in range(len(missions))
        }

    for card in cards.values():
        for s in card.get("scenarios") or []:
            mission = str(s.get("mission") or "")
            for lst_name in ("ml4", "ml4_all"):
                for m in s.get(lst_name) or []:
                    kn = _norm(m.get("lvl4"))
                    m["etalon_full_15"] = int(m.get("etalon_15") or 0)
                    m["etalon_full_max"] = int(m.get("etalon_max") or 0)
                    m["etalon_full_sum"] = int(m.get("etalon_sum") or 0)
                    share = kn_shares.get(kn, {}).get(mission)
                    if share is not None:
                        m["etalon_15"], m["etalon_max"], m["etalon_sum"] = share


def load_scenario_ml4_fact(path: Path | None) -> dict[tuple[str, str], float]:
    """mission×ml4 factual GMV keyed by (_norm(mission), _norm(ml4))."""
    if path is None or not Path(path).exists():
        return {}
    p = Path(path)
    if p.suffix.lower() == ".parquet":
        df = pd.read_parquet(p)
    else:
        df = pd.read_csv(p)
    if df.empty:
        return {}
    out: dict[tuple[str, str], float] = {}
    for _, r in df.iterrows():
        mission_n = _norm(r.get("mission"))
        ml4_n = _norm(r.get("ml4_n") if "ml4_n" in df.columns else r.get("ml4"))
        if not mission_n or not ml4_n:
            continue
        gmv = float(pd.to_numeric(r.get("gmv"), errors="coerce") or 0.0)
        # Sum if duplicates (shouldn't happen)
        out[(mission_n, ml4_n)] = out.get((mission_n, ml4_n), 0.0) + gmv
    return out


def build_assortment_payload(
    *,
    rk_bg_path: Path,
    etalons_path: Path,
    scenario_etalons_path: Path,
    catalog_path: Path,
    leaf_gmv: pd.DataFrame | None,
    mcc_gap: dict[str, float] | None = None,
    snapshot_meta: dict | None = None,
    scenario_ml4_fact_path: Path | None = None,
    ml4_gmv_fact_path: Path | None = None,
    ml4_name_aliases_path: Path | None = None,
) -> dict:
    rules = load_rk_bg_rules(rk_bg_path)
    by4 = load_etalon_lvl4(etalons_path)
    lvl3_to_lvl4 = _lvl3_index(by4)
    owned = assign_owners(by4, rules)
    winners = load_exclusive_winners(scenario_etalons_path)
    unused = load_unused_rows(scenario_etalons_path)
    scenarios = load_catalog_scenarios(catalog_path)
    fact_gmv = load_scenario_ml4_fact(scenario_ml4_fact_path)
    aliases = load_ml4_name_aliases(ml4_name_aliases_path)
    global_gmv = load_ml4_global_gmv(ml4_gmv_fact_path)
    gap_map = {str(k).strip(): float(v) for k, v in (mcc_gap or {}).items() if str(k).strip()}
    n_fact_hits = 0
    n_proxy_fallback = 0
    n_none = 0
    gmv_by_mission: dict[str, float] = {}
    mcc_by_mission: dict[str, str] = {}
    if leaf_gmv is not None and not leaf_gmv.empty:
        for _, r in leaf_gmv.iterrows():
            mission = str(r.get("mission") or "").strip()
            if not mission:
                continue
            gmv_by_mission[mission] = float(pd.to_numeric(r.get("GMV"), errors="coerce") or 0.0)
            mcc = str(r.get("mcc_group") or "").strip()
            if mcc and mcc not in ("nan", "None"):
                mcc_by_mission[mission] = mcc
    total_gmv = float(sum(gmv_by_mission.values())) or 0.0

    owner_to_lvl4: dict[tuple[str, str], set[str]] = {}
    owned_map: dict[str, list[tuple[str, str]]] = {}
    for _, r in owned.iterrows():
        kn = str(r["lvl4_n"])
        rk = str(r["rk"])
        bg = str(r["bg"])
        owner_to_lvl4.setdefault((rk, bg), set()).add(kn)
        pair = (rk, bg)
        owned_map.setdefault(kn, [])
        if pair not in owned_map[kn]:
            owned_map[kn].append(pair)

    lvl4_lookup = owned.drop_duplicates("lvl4_n").set_index("lvl4_n")

    cards: dict[str, dict] = {}
    for (rk, bg), keys in sorted(owner_to_lvl4.items(), key=lambda x: (x[0][0] != UNASSIGNED_RK, x[0][0], x[0][1])):
        card_key = f"{rk}||{bg}"
        unused_rows = []
        if not unused.empty:
            for _, u in unused.iterrows():
                kn = str(u["lvl4_n"])
                if kn not in keys:
                    continue
                src = lvl4_lookup.loc[kn] if kn in lvl4_lookup.index else None
                unused_rows.append(
                    {
                        "lvl1": str(u.get("lvl1") or (src["lvl1"] if src is not None else "")),
                        "lvl2": str(u.get("lvl2") or (src["lvl2"] if src is not None else "")),
                        "lvl3": str(u.get("lvl3") or (src["lvl3"] if src is not None else "")),
                        "lvl4": str(u.get("lvl4") or ""),
                        "etalon_15": int(round(float(u.get("etalon_15") or 0))),
                        "etalon_max": int(round(float(u.get("etalon_max") or 0))),
                        "etalon_sum": int(round(float(u.get("etalon_sum") or 0))),
                    }
                )
        unused_rows.sort(key=lambda x: (-x["etalon_sum"], x["lvl4"]))
        cards[card_key] = {
            "rk": rk,
            "bg": bg,
            "scenarios": [],
            "ml4s": [],
            "priority_rows": [],
            "unused": unused_rows,
            "unused_n": len(unused_rows),
            "unused_15": int(sum(x["etalon_15"] for x in unused_rows)),
            "unused_max": int(sum(x["etalon_max"] for x in unused_rows)),
            "unused_sum": int(sum(x["etalon_sum"] for x in unused_rows)),
        }

    for scen in scenarios:
        mission = scen["mission"]
        keys, unmatched = resolve_scenario_lvl4(scen["cats"], by4, lvl3_to_lvl4)
        if not keys:
            continue
        by_card: dict[str, list[str]] = {}
        for kn in keys:
            for rk, bg in owned_map.get(kn) or []:
                ck = f"{rk}||{bg}"
                by_card.setdefault(ck, []).append(kn)
        gmv = float(gmv_by_mission.get(mission) or 0.0)
        share = (gmv / total_gmv) if total_gmv else 0.0
        mcc_group = mcc_by_mission.get(mission) or ""
        mission_n = _norm(mission)
        # Full scenario composition (all etalon-matched ML4) — shared across cards.
        ml4_all_base, n_lost_all = _build_scenario_ml4_rows(
            list(dict.fromkeys(keys)),
            by4=by4,
            winners=winners,
            owned_map=owned_map,
            fact_gmv=fact_gmv,
            mission=mission,
            mission_n=mission_n,
            aliases=aliases,
            global_gmv=global_gmv,
            card_keys=None,
        )
        _fill_proxy_gmv(ml4_all_base, gmv)
        for ck, kns in by_card.items():
            if ck not in cards:
                continue
            unique_kns = list(dict.fromkeys(kns))
            card_key_set = set(unique_kns)
            # BG-scoped rows for card metrics / mega pie / ML4 index (KM by BG).
            # Leave proxy gmv_ml4 as None — filled later by card-scoped etalon split.
            ml4_bg, n_lost_bg = _build_scenario_ml4_rows(
                unique_kns,
                by4=by4,
                winners=winners,
                owned_map=owned_map,
                fact_gmv=fact_gmv,
                mission=mission,
                mission_n=mission_n,
                aliases=aliases,
                global_gmv=global_gmv,
                card_keys=card_key_set,
            )
            e15 = emax = esum = 0
            for rec in ml4_bg:
                if rec.get("exclusive"):
                    e15 += rec["etalon_15"]
                    emax += rec["etalon_max"]
                    esum += rec["etalon_sum"]
            # Expand list: full scenario ML4 with current-BG highlight + full-list GMV.
            ml4_all = []
            for base in ml4_all_base:
                rec = dict(base)
                kn = _norm(rec.get("lvl4"))
                rec["in_this_bg"] = kn in card_key_set
                ml4_all.append(rec)
            ml4_all.sort(
                key=lambda x: (-int(x.get("in_this_bg") or 0), -x["etalon_sum"], x["lvl4"])
            )
            cards[ck]["scenarios"].append(
                {
                    "mission": mission,
                    "mega": scen["mega"],
                    "scenario": scen["scenario"],
                    "mcc_group": mcc_group,
                    "gmv": gmv,
                    "leaf_share": round(share, 6),
                    "n_ml4": len(ml4_bg),
                    "n_ml4_all": len(ml4_all),
                    "n_unmatched": unmatched,
                    "n_lost": n_lost_bg,
                    "n_lost_all": n_lost_all,
                    "etalon_15": e15,
                    "etalon_max": emax,
                    "etalon_sum": esum,
                    "etalon_status": _etalon_status(esum, len(ml4_bg)),
                    "ml4": ml4_bg,
                    "ml4_all": ml4_all,
                }
            )

    rk_bgs: dict[str, list[str]] = {}
    unused_keys_by_card = {
        ck: {_norm(u.get("lvl4")) for u in (card.get("unused") or []) if u.get("lvl4")}
        for ck, card in cards.items()
    }
    for ck, card in cards.items():
        card["scenarios"].sort(
            key=lambda s: (-float(s["gmv"]), -int(s["etalon_sum"]), s["mission"])
        )
        card["n_scenarios"] = len(card["scenarios"])
        card["etalon_15"] = int(sum(s["etalon_15"] for s in card["scenarios"]))
        card["etalon_max"] = int(sum(s["etalon_max"] for s in card["scenarios"]))
        card["etalon_sum"] = int(sum(s["etalon_sum"] for s in card["scenarios"]))
        rk_bgs.setdefault(card["rk"], [])
        if card["bg"] not in rk_bgs[card["rk"]]:
            rk_bgs[card["rk"]].append(card["bg"])
        owned_keys = owner_to_lvl4.get((card["rk"], card["bg"]), set())
        card["n_ml4"] = len(owned_keys)
        in_scen = set()
        # Invert: ML4 → scenarios (+ GMV proxy weights within BG slice)
        ml4_acc: dict[str, dict] = {}
        for kn in owned_keys:
            if kn not in by4.index:
                continue
            row = by4.loc[kn]
            winner = winners.get(kn) or ""
            ml4_acc[kn] = {
                "lvl1": str(row.get("lvl1") or ""),
                "lvl2": str(row.get("lvl2") or ""),
                "lvl3": str(row.get("lvl3") or ""),
                "lvl4": str(row.get("lvl4") or ""),
                "bg": str(row.get("bg") or card["bg"]),
                "etalon_15": int(round(float(row.get("etalon_15") or 0))),
                "etalon_max": int(round(float(row.get("etalon_max") or 0))),
                "etalon_sum": int(round(float(row.get("etalon_sum") or 0))),
                "qnf": (
                    ""
                    if row.get("qnf") is None
                    or (isinstance(row.get("qnf"), float) and pd.isna(row.get("qnf")))
                    else str(row.get("qnf"))
                ),
                "seasonal": (
                    ""
                    if row.get("seasonal") is None
                    or (
                        isinstance(row.get("seasonal"), float)
                        and pd.isna(row.get("seasonal"))
                    )
                    else str(row.get("seasonal"))
                ),
                "exclusive_owner": winner,
                "in_unused": kn in unused_keys_by_card.get(ck, set()),
                "missions": [],
                "gmv_touch": 0.0,
                "gmv_proxy": 0.0,
                "n_fact": 0,
                "n_proxy": 0,
                "n_none": 0,
            }
        priority_rows: list[dict] = []
        for s in card["scenarios"]:
            demand = float(s.get("gmv") or 0.0)
            mcc = str(s.get("mcc_group") or "")
            gap = float(gap_map.get(mcc) or 0.0) if mcc else 0.0
            ml4_list = list(s.get("ml4") or [])
            weights = [
                0.0
                if m.get("gmv_source") == "none"
                else float(m.get("etalon_sum") or 0)
                for m in ml4_list
            ]
            allocs = _allocate_gmv(demand, weights)
            for m, alloc in zip(ml4_list, allocs):
                kn = _norm(m.get("lvl4"))
                src0 = str(m.get("gmv_source") or "")
                # Prefer factual mission×ml4 GMV; no fact → none (0).
                # Legacy etalon-weight proxy only when explicitly marked (no fact file).
                if src0 == "fact" and m.get("gmv_ml4") is not None:
                    gmv_ml4 = float(m["gmv_ml4"])
                    src = "fact"
                    n_fact_hits += 1
                elif src0 == "proxy":
                    gmv_ml4 = float(alloc)
                    m["gmv_ml4"] = gmv_ml4
                    m["gmv_source"] = "proxy"
                    src = "proxy"
                    n_proxy_fallback += 1
                else:
                    gmv_ml4 = 0.0
                    m["gmv_ml4"] = 0.0
                    m["gmv_source"] = "none"
                    src = "none"
                    n_none += 1
                in_scen.add(kn)
                if kn in ml4_acc:
                    acc = ml4_acc[kn]
                    if s["mission"] not in acc["missions"]:
                        acc["missions"].append(s["mission"])
                    acc["gmv_touch"] += demand
                    acc["gmv_proxy"] += gmv_ml4
                    if src == "fact":
                        acc["n_fact"] += 1
                    elif src == "none":
                        acc["n_none"] += 1
                    else:
                        acc["n_proxy"] += 1
                if not m.get("exclusive"):
                    continue
                et_sum = int(m.get("etalon_sum") or 0)
                score = demand * max(et_sum, 1)
                priority_rows.append(
                    {
                        "mission": s["mission"],
                        "mega": s.get("mega") or "",
                        "scenario": s.get("scenario") or "",
                        "mcc_group": mcc,
                        "lvl1": m.get("lvl1") or "",
                        "lvl2": m.get("lvl2") or "",
                        "lvl3": m.get("lvl3") or "",
                        "lvl4": m.get("lvl4") or "",
                        "demand_gmv": demand,
                        "etalon_15": int(m.get("etalon_15") or 0),
                        "etalon_max": int(m.get("etalon_max") or 0),
                        "etalon_sum": et_sum,
                        "sber_gap_pp": gap,
                        "priority_score": score,
                    }
                )
        priority_rows.sort(
            key=lambda r: (-float(r["priority_score"]), -float(r["demand_gmv"]), r["lvl4"])
        )
        card["priority_rows"] = priority_rows
        card["n_ml4_in_scenarios"] = len(in_scen)
        ml4_rows = []
        for kn, acc in ml4_acc.items():
            missions = list(acc["missions"])
            n_f = int(acc["n_fact"])
            n_p = int(acc["n_proxy"])
            n_n = int(acc["n_none"])
            kinds = sum(1 for x in (n_f, n_p, n_n) if x)
            if kinds > 1:
                gmv_source = "mixed"
            elif n_f:
                gmv_source = "fact"
            elif n_p:
                gmv_source = "proxy"
            elif n_n:
                gmv_source = "none"
            else:
                gmv_source = ""
            ml4_rows.append(
                {
                    "lvl1": acc["lvl1"],
                    "lvl2": acc["lvl2"],
                    "lvl3": acc["lvl3"],
                    "lvl4": acc["lvl4"],
                    "bg": acc["bg"],
                    "etalon_15": acc["etalon_15"],
                    "etalon_max": acc["etalon_max"],
                    "etalon_sum": acc["etalon_sum"],
                    "qnf": acc["qnf"],
                    "seasonal": acc["seasonal"],
                    "exclusive_owner": acc["exclusive_owner"],
                    "in_unused": bool(acc["in_unused"]),
                    "n_scenarios": len(missions),
                    "missions": missions,
                    "gmv_touch": float(acc["gmv_touch"]),
                    "gmv_proxy": float(acc["gmv_proxy"]),
                    "gmv_source": gmv_source,
                }
            )
        ml4_rows.sort(
            key=lambda r: (
                -float(r["gmv_proxy"]),
                -int(r["etalon_sum"]),
                -int(r["n_scenarios"]),
                r["lvl4"],
            )
        )
        card["ml4s"] = ml4_rows

    # After exclusive aggregates / card ML4 totals are fixed: rewrite scenario ML4
    # etalon_* as GMV-proportional shares (display); keep etalon_full_* for exclusive UI.
    _apply_gmv_proportional_etalon_shares(cards, by4)

    rk_index = []
    food_bgs = rk_bgs.pop(FOOD_RK, [])
    unassigned_bgs = rk_bgs.pop(UNASSIGNED_RK, [])
    for rk in sorted(rk_bgs, key=lambda x: x):
        rk_index.append({"rk": rk, "bgs": sorted(rk_bgs[rk])})
    if food_bgs:
        rk_index.append({"rk": FOOD_RK, "bgs": sorted(food_bgs)})
    if unassigned_bgs:
        rk_index.append({"rk": UNASSIGNED_RK, "bgs": sorted(unassigned_bgs)})

    meta = dict(snapshot_meta or {})
    meta["scenario_ml4_fact_pairs"] = len(fact_gmv)
    meta["scenario_ml4_fact_hits"] = n_fact_hits
    meta["scenario_ml4_proxy_fallback"] = n_proxy_fallback
    meta["scenario_ml4_none"] = n_none
    meta["ml4_name_aliases"] = len(aliases)
    meta["etalon_scenario_split"] = "gmv_ml4_proportional"
    if scenario_ml4_fact_path is not None:
        meta["scenario_ml4_fact_file"] = str(scenario_ml4_fact_path)
    if ml4_gmv_fact_path is not None:
        meta["ml4_gmv_fact_file"] = str(ml4_gmv_fact_path)
    if ml4_name_aliases_path is not None:
        meta["ml4_name_aliases_file"] = str(ml4_name_aliases_path)
    fact_note = (
        "GMV по ML4 — сумма GMV категории по сценариям карточки. "
        "В раскрытии сценария — полный состав ML4 сценария (все БГ); "
        "pie / индекс ML4 карточки — только ML4 этой БГ. "
        "Эталон на ML4 в составе сценария — доли 15 и МАКС полного эталона категории, "
        "пропорционально GMV этой ML4 в сценарии (иначе GMV сценария); "
        "Σ доли = 15 + МАКС; сумма долей по сценариям = эталон ML4 в индексе. "
    )
    return {
        "unassigned_rk": UNASSIGNED_RK,
        "food_rk": FOOD_RK,
        "note": (
            "Сценарий может быть в нескольких БГ, если в нём категории разных групп. "
            "Эталон в строке сценария (колонки таблицы) — SKU 15 мин / МАКС, "
            "эксклюзивно закреплённые за этим сценарием внутри выбранной БГ. "
            "В раскрытии сценария / ML4→сценарии эталон на строках ML4 — доли по GMV "
            "(не полный эталон на каждый сценарий). "
            "РК «food» — FMCG (DRY/FRESH) с QNF=0; QNF-категории FMCG остаются у РК из словаря. "
            "Таблица ML4 — обратный разрез: категория → сценарии. "
            + fact_note
        ),
        "rk_index": rk_index,
        "cards": cards,
        "snapshot_meta": meta,
    }
