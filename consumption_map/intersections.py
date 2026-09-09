#!/usr/bin/env python3
"""Scenario × retailer intersections via MCC bridge (Sber merchant shares)."""

from __future__ import annotations

import pandas as pd


def merchant_shares_by_mcc(
    prefs_raw: pd.DataFrame,
    city: str = "Москва",
    top_n: int = 12,
) -> pd.DataFrame:
    """Aggregate merchant smkt_gmv shares inside each MCC for a city."""
    df = prefs_raw.copy()
    df.columns = [str(c).strip() for c in df.columns]
    if city:
        df = df[df["city"] == city]
    for c in ("smkt_gmv", "smkt_customers", "gmv", "customers"):
        if c in df.columns:
            df[c] = pd.to_numeric(df[c], errors="coerce").fillna(0.0)

    g = (
        df.groupby(["city", "mcc_category", "merchant"], as_index=False)
        .agg(
            smkt_gmv=("smkt_gmv", "sum"),
            smkt_customers=("smkt_customers", "sum"),
            gmv=("gmv", "sum"),
            customers=("customers", "sum"),
        )
    )
    g["mcc_smkt_gmv"] = g.groupby(["city", "mcc_category"])["smkt_gmv"].transform("sum")
    g["share_smkt_gmv"] = g["smkt_gmv"] / g["mcc_smkt_gmv"].where(g["mcc_smkt_gmv"] > 0, pd.NA)
    g["rank"] = g.groupby(["city", "mcc_category"])["smkt_gmv"].rank(ascending=False, method="first")
    # Always keep Самокат even outside top_n — иначе доля Самоката в specialty = NaN
    is_smkt = g["merchant"].astype(str).str.lower().str.contains("самокат")
    g = g[(g["rank"] <= top_n) | is_smkt].sort_values(
        ["mcc_category", "smkt_gmv"], ascending=[True, False]
    )
    return g


def build_scenario_retailer_intersections(
    megas: pd.DataFrame,
    bridge: pd.DataFrame,
    merchant_shares: pd.DataFrame,
    city: str = "Москва",
    top_retailers: int = 8,
) -> pd.DataFrame:
    """
    Soft intersection: mega-scenario GMV × MCC competitors from Sber.

    Not user-level overlap — domain bridge. Each row = scenario ↔ retailer via MCC.
    """
    m = megas.copy()
    m.columns = [str(c).strip() for c in m.columns]
    # normalize mega column
    mega_col = "mega" if "mega" in m.columns else m.columns[0]
    gmv_col = "GMV" if "GMV" in m.columns else [c for c in m.columns if "gmv" in c.lower() or c == "GMV"]
    if isinstance(gmv_col, list):
        gmv_col = gmv_col[0] if gmv_col else m.columns[1]
    m = m.rename(columns={mega_col: "mega", gmv_col: "scenario_gmv"})
    m["scenario_gmv"] = pd.to_numeric(m["scenario_gmv"], errors="coerce").fillna(0.0)
    total_scen = m["scenario_gmv"].sum()
    m["scenario_gmv_share"] = m["scenario_gmv"] / total_scen if total_scen else 0.0

    b = bridge.copy()
    b = b[b["role"].astype(str) != "skip"]
    b["weight"] = pd.to_numeric(b["weight"], errors="coerce").fillna(0.0)

    shares = merchant_shares[merchant_shares["city"] == city].copy() if "city" in merchant_shares.columns else merchant_shares.copy()

    rows = []
    for _, sc in m.iterrows():
        mega = str(sc["mega"])
        links = b[b["mega"] == mega]
        if links.empty:
            continue
        for _, link in links.iterrows():
            mcc = link["mcc_group"]
            retailers = shares[shares["mcc_category"] == mcc].nlargest(top_retailers, "smkt_gmv")
            if retailers.empty:
                rows.append(
                    {
                        "city": city,
                        "mega": mega,
                        "scenario_gmv": float(sc["scenario_gmv"]),
                        "scenario_gmv_share": float(sc["scenario_gmv_share"]),
                        "mcc_group": mcc,
                        "bridge_role": link["role"],
                        "bridge_weight": float(link["weight"]),
                        "merchant": "(нет данных в Сбере)",
                        "merchant_smkt_gmv": 0.0,
                        "merchant_share_in_mcc": None,
                        "is_samokat": False,
                    }
                )
                continue
            for _, ret in retailers.iterrows():
                name = str(ret["merchant"])
                rows.append(
                    {
                        "city": city,
                        "mega": mega,
                        "scenario_gmv": float(sc["scenario_gmv"]),
                        "scenario_gmv_share": float(sc["scenario_gmv_share"]),
                        "mcc_group": mcc,
                        "bridge_role": link["role"],
                        "bridge_weight": float(link["weight"]),
                        "merchant": name,
                        "merchant_smkt_gmv": float(ret["smkt_gmv"]),
                        "merchant_share_in_mcc": float(ret["share_smkt_gmv"]) if pd.notna(ret["share_smkt_gmv"]) else None,
                        "is_samokat": "самокат" in name.lower() or name.lower() == "samokat",
                    }
                )
    return pd.DataFrame(rows)


def build_competitive_sets(
    merchant_shares: pd.DataFrame,
    city: str = "Москва",
    mccs: list[str] | None = None,
) -> pd.DataFrame:
    """Compact competitive set per MCC with Samokat flag and share rank."""
    s = merchant_shares[merchant_shares["city"] == city].copy()
    if mccs:
        s = s[s["mcc_category"].isin(mccs)]
    s["is_samokat"] = s["merchant"].astype(str).str.lower().str.contains("самокат") | (
        s["merchant"].astype(str).str.lower() == "samokat"
    )
    return s.sort_values(["mcc_category", "smkt_gmv"], ascending=[True, False])


def build_mission_dictionary(
    megas: pd.DataFrame,
    bridge: pd.DataFrame,
    merchant_shares: pd.DataFrame,
    city: str = "Москва",
    top_retailers: int = 6,
) -> pd.DataFrame:
    """One row per mission×MCC: domains + retailer list (словарь/карта)."""
    m = megas.copy()
    m.columns = [str(c).strip() for c in m.columns]
    mega_col = "mega" if "mega" in m.columns else m.columns[0]
    gmv_col = "GMV" if "GMV" in m.columns else m.columns[1]
    m = m.rename(columns={mega_col: "mega", gmv_col: "scenario_gmv"})
    m["scenario_gmv"] = pd.to_numeric(m["scenario_gmv"], errors="coerce").fillna(0.0)
    total = m["scenario_gmv"].sum()
    m["scenario_gmv_share"] = m["scenario_gmv"] / total if total else 0.0

    b = bridge.copy()
    b["weight"] = pd.to_numeric(b["weight"], errors="coerce").fillna(0.0)
    shares = merchant_shares[merchant_shares["city"] == city] if "city" in merchant_shares.columns else merchant_shares

    rows = []
    for _, sc in m.sort_values("scenario_gmv", ascending=False).iterrows():
        mega = str(sc["mega"])
        links = b[b["mega"] == mega]
        if links.empty:
            rows.append(
                {
                    "mega": mega,
                    "scenario_gmv": float(sc["scenario_gmv"]),
                    "scenario_gmv_share": float(sc["scenario_gmv_share"]),
                    "mcc_group": "—",
                    "bridge_role": "не сопоставлено",
                    "bridge_weight": 0.0,
                    "top_retailers": "",
                    "retailer_shares_pct": "",
                    "samokat_share_in_mcc": None,
                }
            )
            continue
        for _, link in links.iterrows():
            mcc = link["mcc_group"]
            ret = shares[shares["mcc_category"] == mcc].nlargest(top_retailers, "smkt_gmv")
            names = []
            shares_s = []
            smkt_share = None
            for _, r in ret.iterrows():
                name = str(r["merchant"])
                sh = float(r["share_smkt_gmv"]) if pd.notna(r["share_smkt_gmv"]) else 0.0
                names.append(name)
                shares_s.append(f"{name} {100*sh:.0f}%")
                if "самокат" in name.lower():
                    smkt_share = sh
            rows.append(
                {
                    "mega": mega,
                    "scenario_gmv": float(sc["scenario_gmv"]),
                    "scenario_gmv_share": float(sc["scenario_gmv_share"]),
                    "mcc_group": mcc,
                    "bridge_role": str(link["role"]),
                    "bridge_weight": float(link["weight"]),
                    "top_retailers": ", ".join(names),
                    "retailer_shares_pct": " · ".join(shares_s),
                    "samokat_share_in_mcc": smkt_share,
                }
            )
    return pd.DataFrame(rows)


def build_unified_master(
    megas: pd.DataFrame,
    bridge: pd.DataFrame,
    by_mcc_city: pd.DataFrame,
    etalon_l1: pd.DataFrame,
    crosswalk: pd.DataFrame,
    merchant_shares: pd.DataFrame,
    city: str = "Москва",
    top_retailers: int = 5,
) -> pd.DataFrame:
    """
    Единая таблица: миссия × MCC × Сбер × эталоны × топ-ритейлеры.

    Grain: mega × mcc_group (city fixed).
    Эталоны: только NEW (МАКС / 15 мин / сумма) — rollup через lvl1 кроссвок.
    """
    m = megas.copy()
    m.columns = [str(c).strip() for c in m.columns]
    mega_col = "mega" if "mega" in m.columns else m.columns[0]
    gmv_col = "GMV" if "GMV" in m.columns else m.columns[1]
    checks_col = "Чеки" if "Чеки" in m.columns else None
    m = m.rename(columns={mega_col: "mega", gmv_col: "scenario_gmv"})
    m["scenario_gmv"] = pd.to_numeric(m["scenario_gmv"], errors="coerce").fillna(0.0)
    if checks_col:
        m["scenario_checks"] = pd.to_numeric(m[checks_col], errors="coerce").fillna(0.0)
    else:
        m["scenario_checks"] = 0.0
    total = m["scenario_gmv"].sum()
    m["scenario_gmv_share"] = m["scenario_gmv"] / total if total else 0.0

    # NEW-etalon by MCC via crosswalk (sum unique lvl1 once per MCC)
    et = etalon_l1.set_index("lvl1")
    cw = crosswalk[crosswalk["bridge_type"] == "specialty"].copy()
    etalon_by_mcc = {}
    for mcc, grp in cw.groupby("mcc_group"):
        uniq = []
        e_sum = 0.0
        ml4 = 0
        for l1 in grp["lvl1"].dropna().astype(str):
            l1 = l1.strip()
            if not l1 or l1 in uniq or l1 not in et.index:
                continue
            uniq.append(l1)
            row = et.loc[l1]
            e_sum += float(row.get("etalon_sum", 0) or 0)
            ml4 += int(row.get("ml4_count", 0) or 0)
        etalon_by_mcc[mcc] = {
            "mapped_lvl1": "; ".join(uniq),
            "etalon_new_km": e_sum,
            "ml4_count": ml4,
        }
    wallet = by_mcc_city[by_mcc_city["city"] == city].copy() if "city" in by_mcc_city.columns else by_mcc_city.copy()
    wallet = wallet.rename(columns={"mcc_category": "mcc_group"})
    shares = merchant_shares[merchant_shares["city"] == city] if "city" in merchant_shares.columns else merchant_shares

    b = bridge.copy()
    b["weight"] = pd.to_numeric(b["weight"], errors="coerce").fillna(0.0)

    rows = []
    for _, sc in m.sort_values("scenario_gmv", ascending=False).iterrows():
        mega = str(sc["mega"])
        links = b[b["mega"] == mega]
        if links.empty:
            rows.append(
                {
                    "city": city,
                    "mega": mega,
                    "scenario_gmv": float(sc["scenario_gmv"]),
                    "scenario_gmv_share": float(sc["scenario_gmv_share"]),
                    "scenario_checks": float(sc["scenario_checks"]),
                    "mcc_group": None,
                    "bridge_role": "не сопоставлено",
                    "bridge_weight": None,
                    "sber_smkt_gmv": None,
                    "sber_smkt_gmv_share_in_mcc_total": None,
                    "sber_smkt_customers": None,
                    "mapped_lvl1": None,
                    "etalon_new_km_sku": None,
                    "etalon_max_sku": None,
                    "etalon_15min_sku": None,
                    "top_retailers": None,
                    "retailer_shares_pct": None,
                    "samokat_share_in_mcc": None,
                }
            )
            continue
        for _, link in links.iterrows():
            mcc = link["mcc_group"]
            wrow = wallet[wallet["mcc_group"] == mcc]
            sber_smkt = float(wrow["smkt_gmv"].iloc[0]) if len(wrow) else None
            sber_share = float(wrow["smkt_gmv_share"].iloc[0]) if len(wrow) and pd.notna(wrow["smkt_gmv_share"].iloc[0]) else None
            sber_cust = float(wrow["smkt_customers"].iloc[0]) if len(wrow) else None

            et_info = etalon_by_mcc.get(mcc, {})
            mapped = et_info.get("mapped_lvl1")
            e_new = et_info.get("etalon_new_km")

            ret = shares[shares["mcc_category"] == mcc].nlargest(top_retailers, "smkt_gmv")
            # Samokat share from full MCC list (may be outside top_retailers)
            all_mcc = shares[shares["mcc_category"] == mcc]
            sm_rows = all_mcc[all_mcc["merchant"].astype(str).str.lower().str.contains("самокат")]
            smkt_share = float(sm_rows["share_smkt_gmv"].iloc[0]) if len(sm_rows) else None
            names, shares_s = [], []
            for _, rr in ret.iterrows():
                name = str(rr["merchant"])
                sh = float(rr["share_smkt_gmv"]) if pd.notna(rr["share_smkt_gmv"]) else 0.0
                names.append(name)
                shares_s.append(f"{name} {100*sh:.0f}%")
                if "самокат" in name.lower() and smkt_share is None:
                    smkt_share = sh

            rows.append(
                {
                    "city": city,
                    "mega": mega,
                    "scenario_gmv": float(sc["scenario_gmv"]),
                    "scenario_gmv_share": float(sc["scenario_gmv_share"]),
                    "scenario_checks": float(sc["scenario_checks"]),
                    "mcc_group": mcc,
                    "bridge_role": str(link["role"]),
                    "bridge_weight": float(link["weight"]),
                    "sber_smkt_gmv": sber_smkt,
                    "sber_smkt_share_of_category_gmv": sber_share,
                    "sber_smkt_customers": sber_cust,
                    "mapped_lvl1": mapped,
                    "etalon_new_km_sku": e_new,
                    "etalon_max_sku": None,
                    "etalon_15min_sku": None,
                    "top_retailers": ", ".join(names),
                    "retailer_shares_pct": " · ".join(shares_s),
                    "samokat_share_in_mcc": smkt_share,
                }
            )
    return pd.DataFrame(rows)


def enrich_unified_etalon_split(
    unified: pd.DataFrame,
    etalons_ml4: pd.DataFrame,
    crosswalk: pd.DataFrame,
) -> pd.DataFrame:
    """Fill NEW-only etalon split: МАКС / 15 мин / сумма from ml4 via crosswalk."""
    df = etalons_ml4.copy()
    df.columns = [str(c).strip() for c in df.columns]
    if "etalon_max" not in df.columns or "etalon_sum" not in df.columns:
        return unified

    cw = crosswalk[crosswalk["bridge_type"] == "specialty"].copy()
    mcc_to_l1: dict[str, list[str]] = {}
    for mcc, grp in cw.groupby("mcc_group"):
        mcc_to_l1[mcc] = sorted({str(x).strip() for x in grp["lvl1"].dropna() if str(x).strip()})

    agg = (
        df.groupby("lvl1", as_index=False)
        .agg(
            etalon_max=("etalon_max", "sum"),
            etalon_15=("etalon_15", "sum"),
            etalon_sum=("etalon_sum", "sum"),
        )
    )
    by_l1 = agg.set_index("lvl1")

    maxs, mins, sums, mapped = [], [], [], []
    for _, r in unified.iterrows():
        mcc = r.get("mcc_group")
        l1s = mcc_to_l1.get(mcc, []) if pd.notna(mcc) else []
        e_max = e_15 = e_sum = 0.0
        used = []
        for l1 in l1s:
            if l1 not in by_l1.index:
                continue
            used.append(l1)
            e_max += float(by_l1.loc[l1, "etalon_max"] or 0)
            e_15 += float(by_l1.loc[l1, "etalon_15"] or 0)
            e_sum += float(by_l1.loc[l1, "etalon_sum"] or 0)
        if used:
            maxs.append(e_max)
            mins.append(e_15)
            sums.append(e_sum)
            mapped.append("; ".join(used))
        else:
            maxs.append(r.get("etalon_max_sku"))
            mins.append(r.get("etalon_15min_sku"))
            sums.append(r.get("etalon_new_km_sku"))
            mapped.append(r.get("mapped_lvl1"))
    out = unified.copy()
    out["etalon_max_sku"] = maxs  # NEW МАКСы
    out["etalon_15min_sku"] = mins  # NEW 15 мин
    out["etalon_new_km_sku"] = sums  # NEW МАКС+15
    out["mapped_lvl1"] = mapped
    return out


_MASTER_COL_ORDER = [
    "city",
    "mega",
    "n_scenarios",
    "n_ml4",
    "scenarios_preview",
    "ml4_preview",
    "scenario_gmv",
    "scenario_gmv_share",
    "scenario_checks",
    "mcc_group",
    "bridge_role",
    "bridge_weight",
    "sber_smkt_gmv",
    "sber_smkt_share_of_category_gmv",
    "sber_smkt_customers",
    "demand_tier",
    "demand_score",
    "demand_explain",
    "mapped_lvl1",
    "etalon_max_sku",
    "etalon_15min_sku",
    "etalon_new_km_sku",
    "top_retailers",
    "retailer_shares_pct",
    "samokat_share_in_mcc",
    "market_top1",
    "market_top1_share",
    "market_top_retailers",
    "hypothesis",
]


def enrich_unified_extras(
    unified: pd.DataFrame,
    mega_cats: pd.DataFrame | None = None,
    demand: pd.DataFrame | None = None,
    hyp: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """
    Pull ml4/leaf composition, external demand tiers, and MCC hypotheses onto Master.

    Full ml4_categories stay on Mega_ml4 (too wide for the manager table).
    """
    out = unified.copy()

    if mega_cats is not None and not mega_cats.empty and "mega" in mega_cats.columns:
        cat_cols = [c for c in ("mega", "n_ml4", "n_scenarios", "ml4_preview", "scenarios_list") if c in mega_cats.columns]
        cats = mega_cats[cat_cols].drop_duplicates("mega")
        out = out.drop(columns=[c for c in ("n_ml4", "n_scenarios", "ml4_preview", "scenarios_preview") if c in out.columns], errors="ignore")
        out = out.merge(cats, on="mega", how="left")
        if "scenarios_list" in out.columns:
            def _scen_preview(v) -> str | None:
                if pd.isna(v) or not str(v).strip():
                    return None
                parts = [p.strip() for p in str(v).split(" · ") if p.strip()]
                if len(parts) <= 8:
                    return " · ".join(parts)
                return " · ".join(parts[:8]) + f" · … (+{len(parts) - 8})"

            out["scenarios_preview"] = out["scenarios_list"].map(_scen_preview)
            out = out.drop(columns=["scenarios_list"])

    if demand is not None and not demand.empty and "mcc_group" in demand.columns:
        dcols = [c for c in ("mcc_group", "demand_tier", "demand_score", "demand_explain") if c in demand.columns]
        d = demand[dcols].drop_duplicates("mcc_group")
        out = out.drop(columns=[c for c in dcols if c != "mcc_group" and c in out.columns], errors="ignore")
        out = out.merge(d, on="mcc_group", how="left")

    if hyp is not None and not hyp.empty and "mcc_group" in hyp.columns:
        hcols = [
            c
            for c in ("mcc_group", "market_top1", "market_top1_share", "market_top_retailers", "hypothesis")
            if c in hyp.columns
        ]
        h = hyp[hcols].drop_duplicates("mcc_group")
        out = out.drop(columns=[c for c in hcols if c != "mcc_group" and c in out.columns], errors="ignore")
        out = out.merge(h, on="mcc_group", how="left")

    ordered = [c for c in _MASTER_COL_ORDER if c in out.columns]
    rest = [c for c in out.columns if c not in ordered]
    return out[ordered + rest]


def scenario_cards_payload(
    intersections: pd.DataFrame,
    megas: pd.DataFrame,
    top_scenarios: int = 12,
) -> list[dict]:
    """JSON-serializable cards: scenario → MCC competitors."""
    if intersections.empty:
        return []
    mega_order = (
        megas.rename(columns={megas.columns[0]: "mega", "GMV": "scenario_gmv"})
        if "mega" not in megas.columns
        else megas
    )
    if "GMV" in mega_order.columns and "scenario_gmv" not in mega_order.columns:
        mega_order = mega_order.rename(columns={"GMV": "scenario_gmv"})
    mega_order["scenario_gmv"] = pd.to_numeric(mega_order["scenario_gmv"], errors="coerce").fillna(0.0)
    top = mega_order.nlargest(top_scenarios, "scenario_gmv")["mega"].astype(str).tolist()

    cards = []
    for mega in top:
        sub = intersections[intersections["mega"] == mega]
        if sub.empty:
            continue
        mccs = []
        for mcc, grp in sub.groupby("mcc_group", sort=False):
            retailers = []
            for _, r in grp.drop_duplicates("merchant").nlargest(8, "merchant_smkt_gmv").iterrows():
                retailers.append(
                    {
                        "merchant": r["merchant"],
                        "share": r["merchant_share_in_mcc"],
                        "smkt_gmv": r["merchant_smkt_gmv"],
                        "is_samokat": bool(r["is_samokat"]),
                    }
                )
            role = str(grp["bridge_role"].iloc[0])
            mccs.append({"mcc": mcc, "role": role, "retailers": retailers})
        cards.append(
            {
                "mega": mega,
                "scenario_gmv": float(sub["scenario_gmv"].iloc[0]),
                "scenario_gmv_share": float(sub["scenario_gmv_share"].iloc[0]),
                "mccs": mccs,
            }
        )
    return cards
