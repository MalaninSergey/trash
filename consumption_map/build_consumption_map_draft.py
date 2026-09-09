#!/usr/bin/env python3
"""Build consumption-map draft: Sber wallet × эталоны (наш/NEW) × scenario megas.

Designed to run locally or on JupyterHub without a new GP export.
Paths default to this repo layout; override via env or CLI.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent
DEFAULT_DOWNLOADS = Path.home() / "Downloads"


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
            ]
        ),
        "offline": _first_existing(
            [
                inputs / "offline_top_high_income.xlsx",
                inputs / "ТОП offline ритейла у высокодоходных пользователей Сбера (3) (1).xlsx",
                downloads / "offline_top_high_income.xlsx",
                downloads / "ТОП offline ритейла у высокодоходных пользователей Сбера (3) (1).xlsx",
            ]
        ),
        "etalons": _first_existing(
            [
                inputs / "etalons_qnf.xlsx",
                inputs / "Эталоны QNF 3.0 (05.08).xlsx",
                downloads / "Эталоны QNF 3.0 (05.08).xlsx",
                downloads / "etalons_qnf.xlsx",
                downloads / "Эталоны QNF 3.0 (03.08).xlsx",
            ]
        ),
        "scenarios": _first_existing(
            [
                inputs / "scenarios_gmv_report.xlsx",
                repo / "outputs" / "all_extend_da_rooms" / "scenarios_gmv_report.xlsx",
                downloads / "scenarios_gmv_report.xlsx",
            ]
        ),
        "scenarios_desc": _first_existing(
            [
                inputs / "scenarios_descriptions_rooms.xlsx",
                inputs / "Сценарии_описания_ml3_ml4_v9_extend_da_rooms.xlsx",
                repo / ".hub_cache" / "scenaries" / "Сценарии_описания_ml3_ml4_v9_extend_da_rooms.xlsx",
                downloads / "Сценарии_описания_ml3_ml4_v9_extend_da_rooms.xlsx",
                downloads / "Сценарии_описания_ml3_ml4_v9_от Наташи (1).xlsx",
            ]
        ),
        "prefs_magnit_pyaterochka": _first_existing(
            [
                inputs / "prefs_magnit_pyaterochka_audience.xlsx",
                inputs / "Анализ предпочтений основной аудитории Магнита и Пятерочки.xlsx",
                downloads / "prefs_magnit_pyaterochka_audience.xlsx",
                downloads / "Анализ предпочтений основной аудитории Магнита и Пятерочки.xlsx",
            ]
        ),
        "crosswalk": inputs / "mcc_l1_crosswalk.csv",
        "scenario_bridge": inputs / "scenario_mcc_bridge.csv",
        "meta": repo / "outputs" / "all_extend_da_rooms" / "_run_meta.json",
        "out_dir": Path(args.out_dir),
    }


def load_sber_prefs(path: Path) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Return (by_mcc_tag, by_mcc_city, by_city_tag, merchants_raw)."""
    raw = pd.read_excel(path, sheet_name="Без мерчантов")
    raw.columns = [str(c).strip() for c in raw.columns]
    for c in ("gmv", "smkt_gmv", "customers", "smkt_customers", "orders", "smkt_orders"):
        if c in raw.columns:
            raw[c] = pd.to_numeric(raw[c], errors="coerce").fillna(0.0)
    raw["smkt_gmv_share"] = raw["smkt_gmv"] / raw["gmv"].where(raw["gmv"] > 0, pd.NA)
    raw["smkt_cust_share"] = raw["smkt_customers"] / raw["customers"].where(raw["customers"] > 0, pd.NA)

    by_mcc_city = (
        raw.groupby(["city", "mcc_category"], as_index=False)[["gmv", "smkt_gmv", "customers", "smkt_customers"]]
        .sum()
    )
    by_mcc_city["smkt_gmv_share"] = by_mcc_city["smkt_gmv"] / by_mcc_city["gmv"].where(by_mcc_city["gmv"] > 0, pd.NA)

    by_city_tag = pd.read_excel(path, sheet_name="Без МСС")
    by_city_tag.columns = [str(c).strip() for c in by_city_tag.columns]

    merchants = pd.read_excel(path, sheet_name="Все разрезы")
    merchants.columns = [str(c).strip() for c in merchants.columns]
    for c in ("gmv", "smkt_gmv", "customers", "smkt_customers", "orders", "smkt_orders"):
        if c in merchants.columns:
            merchants[c] = pd.to_numeric(merchants[c], errors="coerce").fillna(0.0)
    return raw, by_mcc_city, by_city_tag, merchants


def load_etalons(path: Path) -> pd.DataFrame:
    """Load QNF etalons — only NEW columns (КМ), ignore legacy «Эталон МАКС/15»."""
    df = pd.read_excel(path, sheet_name="Эталоны")
    df.columns = [str(c).strip() for c in df.columns]
    rename = {
        "bg_new": "bg_new",
        "bg": "bg",
        "lvl1": "lvl1",
        "lvl2": "lvl2",
        "lvl3": "lvl3",
        "lvl4": "lvl4",
        "Категория относится к QNF": "qnf",
        "Сезонная": "seasonal",
        "Есть в сценарии": "in_scenario",
        "NEW Эталон МАКСы": "etalon_max",
        "NEW Эталон 15 мин": "etalon_15",
        "NEW Эталон МАКС + 15 мин": "etalon_sum",
    }
    df = df.rename(columns={k: v for k, v in rename.items() if k in df.columns})
    # Drop legacy non-NEW etalon / deviation columns if present
    drop_legacy = [
        c
        for c in df.columns
        if c
        in {
            "Эталон МАКСы",
            "Эталон 15 мин",
            "Эталон МАКС + 15 мин",
            "отклонение МАКСы",
            "отклонение 15 мин",
            "отклонение итого",
            "etalon_max_legacy",
        }
        or (str(c).startswith("отклонение"))
    ]
    # Also drop if someone mapped old names — we only keep NEW→etalon_*
    for c in ("new_max", "new_15", "new_sum", "dev_max", "dev_15", "dev_sum"):
        if c in df.columns:
            drop_legacy.append(c)
    df = df.drop(columns=[c for c in drop_legacy if c in df.columns], errors="ignore")
    for c in ("etalon_max", "etalon_15", "etalon_sum"):
        if c not in df.columns:
            raise ValueError(
                f"В файле эталонов нет NEW-колонок (ожидали NEW Эталон … → {c}): {path}"
            )
        df[c] = pd.to_numeric(df[c], errors="coerce").fillna(0.0)
    if "in_scenario" in df.columns:
        df["in_scenario"] = df["in_scenario"].astype(str).str.strip().str.lower()
    return df


def rollup_etalons(etalons: pd.DataFrame) -> pd.DataFrame:
    g = (
        etalons.groupby("lvl1", as_index=False)
        .agg(
            ml4_count=("lvl4", "count"),
            etalon_max=("etalon_max", "sum"),
            etalon_15=("etalon_15", "sum"),
            etalon_sum=("etalon_sum", "sum"),
            in_scenario_yes=("in_scenario", lambda s: (s == "да").sum()),
            in_scenario_no=("in_scenario", lambda s: (s != "да").sum()),
            qnf_rows=(
                ("qnf", lambda s: (s.astype(str).str.upper() == "QNF").sum())
                if "qnf" in etalons.columns
                else ("lvl4", "count")
            ),
        )
    )
    return g.sort_values("etalon_sum", ascending=False)


def load_crosswalk(path: Path) -> pd.DataFrame:
    cw = pd.read_csv(path)
    cw["lvl1"] = cw["lvl1"].fillna("").astype(str).str.strip()
    cw["weight"] = pd.to_numeric(cw["weight"], errors="coerce").fillna(0.0)
    return cw


def join_wallet_etalons(
    by_mcc_city: pd.DataFrame,
    etalon_l1: pd.DataFrame,
    crosswalk: pd.DataFrame,
    city: str = "Москва",
) -> pd.DataFrame:
    """Specialty MCC × NEW-etalon rollup for one city."""
    specialty = crosswalk[crosswalk["bridge_type"] == "specialty"].copy()
    wallet = by_mcc_city[by_mcc_city["city"] == city][
        ["mcc_category", "gmv", "smkt_gmv", "smkt_gmv_share", "smkt_customers"]
    ].copy()
    wallet = wallet.rename(columns={"mcc_category": "mcc_group"})

    et = etalon_l1.set_index("lvl1")
    rows = []
    for mcc, grp in specialty.groupby("mcc_group"):
        etalon_sum = 0.0
        etalon_max = 0.0
        etalon_15 = 0.0
        ml4 = 0
        mapped = []
        for _, r in grp.iterrows():
            l1 = r["lvl1"]
            mapped.append(l1)
        uniq = []
        for l1 in mapped:
            if not l1 or str(l1).endswith("(missing)") or l1 not in et.index:
                continue
            if l1 not in uniq:
                uniq.append(l1)
                etalon_sum += float(et.loc[l1, "etalon_sum"])
                etalon_max += float(et.loc[l1, "etalon_max"]) if "etalon_max" in et.columns else 0.0
                etalon_15 += float(et.loc[l1, "etalon_15"]) if "etalon_15" in et.columns else 0.0
                ml4 += int(et.loc[l1, "ml4_count"])
        wrow = wallet[wallet["mcc_group"] == mcc]
        if wrow.empty:
            gmv = smkt = share = cust = None
        else:
            gmv = float(wrow["gmv"].iloc[0])
            smkt = float(wrow["smkt_gmv"].iloc[0])
            share = (
                float(wrow["smkt_gmv_share"].iloc[0])
                if pd.notna(wrow["smkt_gmv_share"].iloc[0])
                else None
            )
            cust = float(wrow["smkt_customers"].iloc[0])
        rows.append(
            {
                "city": city,
                "mcc_group": mcc,
                "mapped_lvl1": "; ".join(uniq),
                "ml4_count": ml4,
                "etalon_sum_new_km": etalon_sum,
                "etalon_max_new": etalon_max,
                "etalon_15_new": etalon_15,
                # aliases kept for older readers
                "etalon_sum_ours": etalon_sum,
                "etalon_dev_new_minus_ours": 0.0,
                "external_gmv": gmv,
                "external_smkt_gmv": smkt,
                "external_smkt_gmv_share": share,
                "external_smkt_customers": cust,
            }
        )

    out = pd.DataFrame(rows)
    if out.empty:
        return out
    out["smkt_gmv_rank"] = out["external_smkt_gmv"].rank(ascending=False, method="dense")
    out["etalon_thin_rank"] = out["etalon_sum_new_km"].rank(ascending=True, method="dense")
    out["gap_score"] = out["smkt_gmv_rank"] + out["etalon_thin_rank"]
    out = out.sort_values(["gap_score", "external_smkt_gmv"], ascending=[False, False])
    return out


def load_scenario_megas(path: Path) -> pd.DataFrame:
    xl = pd.ExcelFile(path)
    sheet = "Mega_Aggregates" if "Mega_Aggregates" in xl.sheet_names else None
    if sheet is None:
        # fallback names
        for s in xl.sheet_names:
            if "mega" in s.lower() or "мега" in s.lower():
                sheet = s
                break
    if sheet is None:
        return pd.DataFrame({"note": ["Mega_Aggregates sheet not found"], "sheets": [", ".join(xl.sheet_names)]})
    df = pd.read_excel(path, sheet_name=sheet)
    df.columns = [str(c).strip() for c in df.columns]
    return df


def load_offline_summary(path: Path) -> pd.DataFrame:
    """Latest-month-ish rollup from Чистый исходник."""
    raw = pd.read_excel(path, sheet_name="Чистый исходник")
    raw.columns = [str(c).strip() for c in raw.columns]
    if "tr_month" in raw.columns:
        raw["tr_month"] = pd.to_datetime(raw["tr_month"], errors="coerce")
    for c in ("amount", "users_number", "cnt_trx"):
        if c in raw.columns:
            raw[c] = pd.to_numeric(raw[c], errors="coerce").fillna(0.0)
    # pivot last available month per tag
    if "tr_month" in raw.columns and raw["tr_month"].notna().any():
        last = raw["tr_month"].max()
        snap = raw[raw["tr_month"] == last].copy()
        snap["period"] = last.strftime("%Y-%m")
    else:
        snap = raw.copy()
        snap["period"] = "unknown"
    agg = (
        snap.groupby(["tag_name", "company"], as_index=False)[["amount", "users_number", "cnt_trx"]]
        .sum()
        .sort_values("amount", ascending=False)
    )
    return agg


def score_external_demand(join_df: pd.DataFrame) -> pd.DataFrame:
    """
    Оцениваем «спрос снаружи» по данным Сбера (аудитория Самоката в MCC).

    Сигналы:
    1) absolute smkt_gmv — сколько аудитория СМКТ тратит в домене у внешних мерчантов
    2) percentile rank среди specialty-MCC города — насколько домен горячий относительно других
    3) smkt_gmv_share — какая доля всего GMV категории приходится на самокатовцев (вовлечённость)

    Уровни по percentile smkt_gmv внутри города:
    - очень активный: top 25%
    - активный: 50–75%
    - умеренный: 25–50%
    - слабый: bottom 25%
    Плюс абсолютный пол: < 300 млн ₽ smkt_gmv всегда не выше «умеренный».
    """
    df = join_df.copy()
    if df.empty:
        return df
    df["external_smkt_gmv"] = pd.to_numeric(df["external_smkt_gmv"], errors="coerce")
    if "external_smkt_gmv_share" in df.columns:
        df["external_smkt_gmv_share"] = pd.to_numeric(df["external_smkt_gmv_share"], errors="coerce")
    else:
        df["external_smkt_gmv_share"] = pd.NA

    # percentile 0..1 among rows with non-null smkt
    valid = df["external_smkt_gmv"].notna() & (df["external_smkt_gmv"] > 0)
    df["demand_percentile"] = pd.NA
    if valid.any():
        df.loc[valid, "demand_percentile"] = df.loc[valid, "external_smkt_gmv"].rank(pct=True)

    def tier_row(r) -> tuple[str, str, float]:
        smkt = r["external_smkt_gmv"]
        pct = r["demand_percentile"]
        share = r["external_smkt_gmv_share"]
        if pd.isna(smkt) or smkt <= 0:
            return "нет данных", "Нет smkt_gmv аудитории Самоката в MCC", 0.0
        # absolute floor
        if smkt < 3e8:  # < 300 млн
            base = "слабый"
        elif pd.isna(pct):
            base = "умеренный"
        elif pct >= 0.75:
            base = "очень активный"
        elif pct >= 0.50:
            base = "активный"
        elif pct >= 0.25:
            base = "умеренный"
        else:
            base = "слабый"
        # bump if Samokat audience owns large share of category
        share_note = ""
        if pd.notna(share) and share >= 0.30:
            share_note = f"; самокатовцы = {100*share:.0f}% GMV категории"
            if base == "умеренный":
                base = "активный"
            elif base == "слабый" and smkt >= 3e8:
                base = "умеренный"
        score = float(pct) if pd.notna(pct) else 0.0
        explain = (
            f"smkt_gmv аудитории СМКТ = {smkt/1e9:.1f} млрд "
            f"(перцентиль {100*score:.0f}% среди доменов города){share_note}"
        )
        return base, explain, score

    tiers, explains, scores = [], [], []
    for _, r in df.iterrows():
        t, e, s = tier_row(r)
        tiers.append(t)
        explains.append(e)
        scores.append(s)
    df["demand_tier"] = tiers
    df["demand_explain"] = explains
    df["demand_score"] = scores
    return df


def build_hypotheses(
    join_df: pd.DataFrame,
    n: int = 12,
    merchant_shares: pd.DataFrame | None = None,
    city: str = "Москва",
) -> pd.DataFrame:
    if join_df.empty:
        return pd.DataFrame()
    from synthesis import market_etalon_advice, market_snapshot

    scored = score_external_demand(join_df)
    scored = scored.sort_values(
        ["demand_score", "external_smkt_gmv"], ascending=[False, False]
    )
    top = scored.head(n).copy()
    hyp = []
    shares = merchant_shares if merchant_shares is not None else pd.DataFrame()
    for _, r in top.iterrows():
        etalon = float(r.get("etalon_sum_new_km") or r.get("etalon_sum_ours") or 0)
        etalon_max = float(r.get("etalon_max_new") or 0)
        etalon_15 = float(r.get("etalon_15_new") or 0)
        smkt = r["external_smkt_gmv"]
        tier = r["demand_tier"]
        explain = r["demand_explain"]
        mcc = str(r["mcc_group"])
        market = market_snapshot(shares, city, mcc)
        market_line = market["line"]
        if pd.isna(smkt):
            continue
        thin = etalon <= 0 or etalon < 50
        if tier in ("нет данных", "слабый"):
            action = (
                f"Спрос снаружи {tier} — низкий приоритет ширины ({explain}). "
                f"NEW-эталон {etalon:.0f} SKU (МАКС {etalon_max:.0f} / 15 мин {etalon_15:.0f}). "
                f"Рынок MCC: {market_line}."
            )
        elif etalon <= 0:
            action = (
                f"Спрос {tier}: NEW-эталон пустой — растить ширину vs рынок. {explain}. "
                f"Рынок: {market_line}. {market_etalon_advice(market, cutting=False)}"
            )
        elif thin and tier in ("очень активный", "активный"):
            action = (
                f"Спрос {tier}: NEW-эталон узкий ({etalon:.0f} SKU: МАКС {etalon_max:.0f} / "
                f"15 мин {etalon_15:.0f}) при сильном внешнем кошельке. {explain}. "
                f"Рынок: {market_line}. {market_etalon_advice(market, cutting=False)}"
            )
        else:
            action = (
                f"Спрос {tier}: NEW-эталон {etalon:.0f} SKU (МАКС {etalon_max:.0f} / "
                f"15 мин {etalon_15:.0f}) — сверить покрытие с лидерами рынка. {explain}. "
                f"Рынок: {market_line}. {market_etalon_advice(market, cutting=False)}"
            )
        hyp.append(
            {
                "city": r["city"],
                "mcc_group": r["mcc_group"],
                "external_smkt_gmv": smkt,
                "external_smkt_gmv_share": r.get("external_smkt_gmv_share"),
                "demand_tier": tier,
                "demand_score": r["demand_score"],
                "demand_explain": explain,
                "etalon_new_km": etalon,
                "etalon_new_max": etalon_max,
                "etalon_new_15": etalon_15,
                # legacy aliases for HTML that still reads etalon_ours
                "etalon_ours": etalon,
                "dev": 0.0,
                "mapped_lvl1": r["mapped_lvl1"],
                "market_top_retailers": market_line,
                "market_top1": market.get("top1_name"),
                "market_top1_share": market.get("top1_share"),
                "hypothesis": action,
            }
        )
    return pd.DataFrame(hyp)


def build_method_sheet(paths: dict[str, Path], meta: dict | None) -> pd.DataFrame:
    rows = [
        ("prefs_file", str(paths["prefs"])),
        ("offline_file", str(paths["offline"])),
        ("etalons_file", str(paths["etalons"])),
        ("scenarios_file", str(paths["scenarios"])),
        ("scenarios_desc_file", str(paths["scenarios_desc"])),
        ("prefs_magnit_pyaterochka_file", str(paths["prefs_magnit_pyaterochka"])),
        ("crosswalk_file", str(paths["crosswalk"])),
        ("etalon_source", "Только NEW Эталон МАКСы / 15 мин / МАКС+15 из файла QNF (колонки с припиской NEW)."),
        ("etalon_ours", "deprecated — не используем старый эталон без NEW"),
        ("etalon_new", "NEW Эталон — целевая ширина (единственный эталон в отчёте)"),
        ("bridge_specialty", "MCC ↔ lvl1 (NEW-эталоны) для wallet×width"),
        ("bridge_grocery", "Продуктовые → мегасценарии + offline сети"),
        ("bridge_channel", "Маркетплейсы → канал Where"),
        ("bridge_role_primary", "primary — основной MCC домена миссии (главный кошелёк / эталон)"),
        ("bridge_role_secondary", "secondary — смежный MCC (канал или соседний домен), вес обычно <1"),
        ("demand_def", "Спрос снаружи = smkt_gmv аудитории Самоката в MCC (Сбер). Уровни по перцентилю среди доменов города: очень активный top25%, активный 50-75%, умеренный 25-50%, слабый bottom25%; пол <300 млн ≤ умеренный. Доп. сигнал: smkt_share категории ≥30%."),
        (
            "etalon_decision",
            "Ширину = NEW-эталон × рынок домена (топ-ритейлеры smkt_gmv в MCC). Старый эталон без NEW не используем.",
        ),
        ("share_def", "retailer_shares_pct / samokat_share_in_mcc — доля smkt_gmv мерчанта внутри MCC у аудитории Самоката (Сбер), не доля рынка РФ."),
        ("ml4_note", "Сценарии и GMV назначены на ml4. n_ml4 / ml4_preview — состав миссии из файла описаний; полный список — лист Mega_ml4."),
        ("bridge_scenario_retailer", "Мегасценарий ↔ MCC ↔ топ-ритейлеры Сбера (мягкое пересечение по домену)"),
        (
            "magnit_pyaterochka_note",
            "Фильтр retail_merch = когорта уникальных клиентов. Метрики retail_* — внутри когорты; "
            "customers/gmv категории — тотал категории (одинаковы по мерчам). "
            "НЕ суммировать несколько retail_merch — обороты задваиваются.",
        ),
        ("note", "Нет user-level join; срезы город×бакет×домен. Capture ml1 GMV — следующий шаг (GP)."),
        ("xlsx_layout", "consumption_map_draft.xlsx — Master + Справка + Mega_ml4 для менеджеров; consumption_map_draft_full.xlsx — полный кэш для HTML."),
    ]
    if meta:
        rows.append(("scenario_period_from", str(meta.get("period_from"))))
        rows.append(("scenario_period_to", str(meta.get("period_to"))))
        rows.append(("scenario_allocated_gmv", str(meta.get("allocated_gmv"))))
    return pd.DataFrame(rows, columns=["key", "value"])


def build_manager_method_sheet(method: pd.DataFrame) -> pd.DataFrame:
    """Short keys for the slim workbook (no file paths)."""
    keep = {
        "scenario_period_from",
        "scenario_period_to",
        "scenario_allocated_gmv",
        "etalon_new",
        "etalon_source",
        "demand_def",
        "share_def",
        "bridge_role_primary",
        "bridge_role_secondary",
        "bridge_specialty",
        "bridge_grocery",
        "bridge_channel",
        "bridge_scenario_retailer",
        "etalon_decision",
        "ml4_note",
        "magnit_pyaterochka_note",
        "note",
        "xlsx_layout",
    }
    m = method.copy()
    m["key"] = m["key"].astype(str)
    return m[m["key"].isin(keep)].reset_index(drop=True)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--downloads", default=str(DEFAULT_DOWNLOADS))
    ap.add_argument("--repo", default=str(ROOT.parent))
    ap.add_argument("--out-dir", default=str(ROOT / "outputs"))
    ap.add_argument("--city", default="Москва")
    args = ap.parse_args()

    paths = resolve_paths(args)
    out_dir = paths["out_dir"]
    out_dir.mkdir(parents=True, exist_ok=True)

    meta = None
    if paths["meta"].exists():
        meta = json.loads(paths["meta"].read_text(encoding="utf-8"))

    prefs_raw, by_mcc_city, by_city_tag, merchants = load_sber_prefs(paths["prefs"])
    etalons = load_etalons(paths["etalons"])
    etalon_l1 = rollup_etalons(etalons)
    crosswalk = load_crosswalk(paths["crosswalk"])
    join_msk = join_wallet_etalons(by_mcc_city, etalon_l1, crosswalk, city=args.city)
    cities = sorted(by_mcc_city["city"].dropna().unique())
    joins = [join_wallet_etalons(by_mcc_city, etalon_l1, crosswalk, city=c) for c in cities]
    join_all = pd.concat(joins, ignore_index=True) if joins else join_msk

    megas = load_scenario_megas(paths["scenarios"])
    offline = load_offline_summary(paths["offline"])
    method = build_method_sheet(paths, meta)

    from intersections import (
        build_mission_dictionary,
        build_scenario_retailer_intersections,
        build_unified_master,
        enrich_unified_etalon_split,
        enrich_unified_extras,
        merchant_shares_by_mcc,
        scenario_cards_payload,
    )

    scenario_bridge = pd.read_csv(paths["scenario_bridge"])
    merchant_shares = merchant_shares_by_mcc(merchants, city=args.city, top_n=12)
    merchant_shares_all = pd.concat(
        [merchant_shares_by_mcc(merchants, city=c, top_n=12) for c in cities],
        ignore_index=True,
    )
    hyp = build_hypotheses(
        join_msk, merchant_shares=merchant_shares_all, city=args.city
    )
    intersections = build_scenario_retailer_intersections(
        megas, scenario_bridge, merchant_shares_all, city=args.city, top_retailers=8
    )
    cards = scenario_cards_payload(intersections, megas, top_scenarios=14)
    dictionary = build_mission_dictionary(
        megas, scenario_bridge, merchant_shares_all, city=args.city, top_retailers=6
    )
    from mega_categories import enrich_dictionary_with_categories, load_mega_category_map

    mega_cats = load_mega_category_map(paths["scenarios_desc"])
    dictionary = enrich_dictionary_with_categories(dictionary, mega_cats)
    unified = build_unified_master(
        megas,
        scenario_bridge,
        by_mcc_city,
        etalon_l1,
        crosswalk,
        merchant_shares_all,
        city=args.city,
        top_retailers=5,
    )
    unified = enrich_unified_etalon_split(unified, etalons, crosswalk)
    demand_by_mcc = score_external_demand(join_msk)
    if not demand_by_mcc.empty and "mcc_group" not in demand_by_mcc.columns and "mcc_category" in demand_by_mcc.columns:
        demand_by_mcc = demand_by_mcc.rename(columns={"mcc_category": "mcc_group"})
    unified = enrich_unified_extras(unified, mega_cats=mega_cats, demand=demand_by_mcc, hyp=hyp)

    grocery_wallet = by_mcc_city[by_mcc_city["mcc_category"] == "Продуктовые магазины"].copy()
    mp_wallet = by_mcc_city[by_mcc_city["mcc_category"] == "Маркетплейсы"].copy()
    grocery_merchants = merchant_shares_all[
        merchant_shares_all["mcc_category"] == "Продуктовые магазины"
    ].copy()

    from magnit_pyaterochka import (
        RETAIL_MERCH_ORDER,
        compare_audiences_by_mcc,
        grocery_overlap_note,
        load_mp_sources,
        merchant_shares_one_cohort,
    )

    mp_src = load_mp_sources(paths["prefs_magnit_pyaterochka"])
    mp_totals = mp_src["totals"].copy()
    mp_categories = mp_src["categories"].copy()
    mp_merchants = mp_src["merchants"].copy()
    # Side-by-side vs Samokat audience — one row per (MCC × retail_merch), never sum merches
    mp_compare = pd.concat(
        [
            compare_audiences_by_mcc(
                by_mcc_city,
                mp_categories,
                city=c,
                retail_merches=("Магнит Оффлайн", "Пятерочка Оффлайн"),
            )
            for c in cities
            if c in set(mp_categories["city"].astype(str))
        ],
        ignore_index=True,
    )
    mp_grocery_overlap = grocery_overlap_note(mp_merchants, city=args.city)
    mp_top_merchants = pd.concat(
        [
            merchant_shares_one_cohort(mp_merchants, city=args.city, retail_merch=m, top_n=8)
            for m in RETAIL_MERCH_ORDER
            if m in set(mp_merchants["retail_merch"].astype(str))
        ],
        ignore_index=True,
    )
    # Focus-city totals for KPI (still one merch at a time)
    mp_totals_focus = mp_totals[mp_totals["city"] == args.city].copy()

    # Full workbook: HTML + analytics cache (unchanged sheet names)
    out_full = out_dir / "consumption_map_draft_full.xlsx"
    with pd.ExcelWriter(out_full, engine="openpyxl") as xl:
        method.to_excel(xl, sheet_name="00_Method", index=False)
        dictionary.to_excel(xl, sheet_name="00b_Dictionary", index=False)
        unified.to_excel(xl, sheet_name="00c_Unified_Master", index=False)
        by_mcc_city.sort_values("smkt_gmv", ascending=False).to_excel(xl, sheet_name="01_Sber_MCC_city", index=False)
        prefs_raw.sort_values("smkt_gmv", ascending=False).to_excel(xl, sheet_name="01b_Sber_MCC_tag", index=False)
        by_city_tag.to_excel(xl, sheet_name="01c_Sber_city_tag", index=False)
        etalon_l1.to_excel(xl, sheet_name="02_Etalon_by_lvl1", index=False)
        etalons.to_excel(xl, sheet_name="02b_Etalon_ml4", index=False)
        crosswalk.to_excel(xl, sheet_name="03_Crosswalk", index=False)
        scenario_bridge.to_excel(xl, sheet_name="03b_Scenario_MCC", index=False)
        join_all.to_excel(xl, sheet_name="04_Wallet_x_Etalon", index=False)
        join_msk.to_excel(xl, sheet_name="04b_Wallet_x_Etalon_MSK", index=False)
        hyp.to_excel(xl, sheet_name="05_Hypotheses", index=False)
        megas.to_excel(xl, sheet_name="06_Scenario_Megas", index=False)
        mega_cats.to_excel(xl, sheet_name="06b_Mega_Categories", index=False)
        grocery_wallet.to_excel(xl, sheet_name="07_Grocery_wallet", index=False)
        offline.head(200).to_excel(xl, sheet_name="07b_Offline_TOP", index=False)
        grocery_merchants.to_excel(xl, sheet_name="07c_Grocery_merchants", index=False)
        mp_wallet.to_excel(xl, sheet_name="08_Marketplace_wallet", index=False)
        merchant_shares_all.to_excel(xl, sheet_name="09_Merchant_shares", index=False)
        intersections.to_excel(xl, sheet_name="09b_Scenario_x_Retailer", index=False)
        mp_totals.to_excel(xl, sheet_name="10_MP_Totals", index=False)
        mp_categories.to_excel(xl, sheet_name="10b_MP_MCC", index=False)
        mp_compare.to_excel(xl, sheet_name="10c_MP_vs_Samokat", index=False)
        mp_grocery_overlap.to_excel(xl, sheet_name="10d_MP_Grocery_overlap", index=False)
        mp_top_merchants.to_excel(xl, sheet_name="10e_MP_Top_merchants", index=False)
        mp_totals_focus.to_excel(xl, sheet_name="10f_MP_Totals_focus", index=False)

    # Slim workbook for managers: one Master + at most two helper sheets
    manager_method = build_manager_method_sheet(method)
    mega_ml4 = mega_cats.copy() if mega_cats is not None else pd.DataFrame()
    out_xlsx = out_dir / "consumption_map_draft.xlsx"
    with pd.ExcelWriter(out_xlsx, engine="openpyxl") as xl:
        unified.to_excel(xl, sheet_name="Master", index=False)
        manager_method.to_excel(xl, sheet_name="Справка", index=False)
        mega_ml4.to_excel(xl, sheet_name="Mega_ml4", index=False)

    cards_path = out_dir / "scenario_retailer_cards.json"
    cards_path.write_text(json.dumps(cards, ensure_ascii=False, indent=2), encoding="utf-8")

    brief = out_dir / "consumption_map_draft_brief.md"
    lines = [
        "# Карта потребления — черновик",
        "",
        f"Город фокуса: **{args.city}**",
        "",
        "## Excel",
        f"- **Для менеджеров:** `consumption_map_draft.xlsx` — листы `Master` ({len(unified)}×{unified.shape[1]}), `Справка`, `Mega_ml4`.",
        "- **Полный кэш (HTML):** `consumption_map_draft_full.xlsx` — все аналитические листы; рендер читает его.",
        "",
        "## Пересечения миссий и ритейлеров",
        "- Мягкий мост: мегасценарий → MCC → топ-мерчанты Сбера (доли smkt_gmv внутри MCC)",
        "- В grocery Самокат виден как мерчант рядом с ВкусВилл/Перекрёсток/…",
        "",
        "## Топ гипотез по эталонам",
        "",
    ]
    if not hyp.empty:
        for _, r in hyp.iterrows():
            lines.append(
                f"- **{r['mcc_group']}**: smkt_gmv={r['external_smkt_gmv']:,.0f}; "
                f"NEW-эталон={r['etalon_new_km']:.0f} "
                f"(МАКС {r.get('etalon_new_max', 0):.0f} / 15мин {r.get('etalon_new_15', 0):.0f}) "
                f"→ {r['hypothesis']}"
            )
    # sample intersection for grocery missions
    if not intersections.empty:
        lines += ["", "## Пример: Готовлю дома ↔ ритейлеры", ""]
        sample = intersections[intersections["mega"] == "Готовлю дома"].head(8)
        for _, r in sample.iterrows():
            sh = f"{100*r['merchant_share_in_mcc']:.0f}%" if pd.notna(r["merchant_share_in_mcc"]) else "—"
            lines.append(f"- {r['merchant']}: доля в MCC {sh}")
    lines += [
        "",
        "## Магнит / Пятёрочка (отдельные когорты)",
        "- `retail_merch` = уникальные клиенты когорты; **не суммировать** несколько мерчей.",
        f"- Сравнение с аудиторией Самоката: лист `10c_MP_vs_Samokat` в full-xlsx ({len(mp_compare)} строк).",
        "",
        f"HTML: `consumption_map_report.html` (из `consumption_map_draft_full.xlsx`)",
        "",
    ]
    brief.write_text("\n".join(lines), encoding="utf-8")

    from render_consumption_map_html import render_html

    out_html = out_dir / "consumption_map_report.html"
    render_html(out_full, out_html, city=args.city, cards_path=cards_path)

    print(f"Wrote {out_xlsx} (slim: {list(pd.ExcelFile(out_xlsx).sheet_names)})")
    print(f"Wrote {out_full} (full HTML cache)")
    print(f"Wrote {brief}")
    print(f"Wrote {out_html}")
    print(f"Wrote {cards_path}")
    print(f"Master columns: {unified.shape[1]}; Hypotheses: {len(hyp)}; intersections: {len(intersections)}; cards: {len(cards)}")


if __name__ == "__main__":
    main()
