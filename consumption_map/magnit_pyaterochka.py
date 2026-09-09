#!/usr/bin/env python3
"""Magnit / Pyaterochka audience prefs (Sber) — load without double-counting."""

from __future__ import annotations

import pandas as pd


RETAIL_MERCH_ORDER = (
    "Магнит Оффлайн",
    "Пятерочка Оффлайн",
    "Магнит Онлайн",
    "Пятерочка Онлайн",
)


def load_mp_sources(path) -> dict[str, pd.DataFrame]:
    """Load flat source sheets (not pivot previews)."""
    cats = pd.read_excel(path, sheet_name="источник категории")
    tots = pd.read_excel(path, sheet_name="источник тотал")
    mers = pd.read_excel(path, sheet_name="источник мерчанты")
    for df in (cats, tots, mers):
        df.columns = [str(c).strip() for c in df.columns]
    for df, cols in (
        (cats, ("customers", "retail_customers", "orders", "retail_orders", "gmv", "retail_gmv")),
        (tots, ("customers", "retail_customers", "orders", "retail_orders", "gmv", "retail_gmv")),
        (mers, ("customers", "retail_customers", "orders", "retail_orders", "gmv", "retail_gmv")),
    ):
        for c in cols:
            if c in df.columns:
                df[c] = pd.to_numeric(df[c], errors="coerce").fillna(0.0)
    # shares within cohort
    cats["retail_gmv_share_of_category"] = cats["retail_gmv"] / cats["gmv"].where(cats["gmv"] > 0, pd.NA)
    cats["retail_cust_share"] = cats["retail_customers"] / cats["customers"].where(cats["customers"] > 0, pd.NA)
    tots["retail_gmv_share"] = tots["retail_gmv"] / tots["gmv"].where(tots["gmv"] > 0, pd.NA)
    mers["mcc_retail_gmv"] = mers.groupby(["city", "mcc_category", "retail_merch"])["retail_gmv"].transform("sum")
    mers["share_in_mcc_cohort"] = mers["retail_gmv"] / mers["mcc_retail_gmv"].where(mers["mcc_retail_gmv"] > 0, pd.NA)
    return {"categories": cats, "totals": tots, "merchants": mers}


def merchant_shares_one_cohort(
    merchants: pd.DataFrame,
    city: str,
    retail_merch: str,
    top_n: int = 10,
) -> pd.DataFrame:
    """Top merchants per MCC for a SINGLE retail_merch (no cross-merch sum)."""
    df = merchants[(merchants["city"] == city) & (merchants["retail_merch"] == retail_merch)].copy()
    df["rank"] = df.groupby("mcc_category")["retail_gmv"].rank(ascending=False, method="first")
    return df[df["rank"] <= top_n].sort_values(["mcc_category", "retail_gmv"], ascending=[True, False])


def compare_audiences_by_mcc(
    samokat_by_mcc: pd.DataFrame,
    mp_categories: pd.DataFrame,
    city: str = "Москва",
    retail_merches: tuple[str, ...] = ("Магнит Оффлайн", "Пятерочка Оффлайн"),
) -> pd.DataFrame:
    """
    Side-by-side: Samokat audience smkt_gmv vs Magnit/Pyaterochka cohort retail_gmv by MCC.

    Important: each retail_merch is a separate unique-client cohort — do NOT sum them.
    """
    sk = samokat_by_mcc[samokat_by_mcc["city"] == city][
        ["mcc_category", "smkt_gmv", "smkt_customers", "smkt_gmv_share"]
    ].copy()
    sk = sk.rename(
        columns={
            "smkt_gmv": "samokat_aud_gmv",
            "smkt_customers": "samokat_aud_customers",
            "smkt_gmv_share": "samokat_aud_share_of_cat",
        }
    )

    rows = []
    for merch in retail_merches:
        sub = mp_categories[(mp_categories["city"] == city) & (mp_categories["retail_merch"] == merch)][
            ["mcc_category", "retail_gmv", "retail_customers", "retail_gmv_share_of_category"]
        ].copy()
        sub = sub.rename(
            columns={
                "retail_gmv": "cohort_gmv",
                "retail_customers": "cohort_customers",
                "retail_gmv_share_of_category": "cohort_share_of_cat",
            }
        )
        sub["retail_merch"] = merch
        merged = sub.merge(sk, on="mcc_category", how="outer")
        merged["city"] = city
        rows.append(merged)
    out = pd.concat(rows, ignore_index=True)
    # ratio: how large is Magnit/5ka cohort spend vs Samokat audience in same MCC
    out["cohort_vs_samokat_aud_gmv"] = out["cohort_gmv"] / out["samokat_aud_gmv"].where(
        out["samokat_aud_gmv"] > 0, pd.NA
    )
    return out.sort_values(["retail_merch", "cohort_gmv"], ascending=[True, False])


def grocery_overlap_note(merchants: pd.DataFrame, city: str = "Москва") -> pd.DataFrame:
    """In grocery MCC, share of Samokat / VkusVill etc. inside Magnit Offline and Pyaterochka Offline cohorts."""
    focus = {"Самокат", "Вкусвилл", "ВкусВилл", "Перекресток", "Перекрёсток", "Магнит", "Пятерочка", "Азбука"}
    df = merchants[
        (merchants["city"] == city)
        & (merchants["mcc_category"] == "Продуктовые магазины")
        & (merchants["retail_merch"].isin(["Магнит Оффлайн", "Пятерочка Оффлайн"]))
    ].copy()
    df["is_key"] = df["merchant"].astype(str).apply(
        lambda x: any(k.lower() in x.lower() for k in focus)
    )
    key = df[df["is_key"]].copy()
    # also keep top 8 overall per cohort
    tops = []
    for merch, grp in df.groupby("retail_merch"):
        tops.append(grp.nlargest(8, "retail_gmv"))
    top = pd.concat(tops, ignore_index=True)
    out = pd.concat([key, top], ignore_index=True).drop_duplicates(
        subset=["retail_merch", "merchant"]
    )
    return out.sort_values(["retail_merch", "retail_gmv"], ascending=[True, False])
