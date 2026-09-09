#!/usr/bin/env python3
"""Plain-language synthesis: how all report sources connect + actionable takeaways."""

from __future__ import annotations

from typing import Any

import pandas as pd


def _money(x) -> str:
    try:
        v = float(x)
    except (TypeError, ValueError):
        return "—"
    if abs(v) >= 1e9:
        return f"{v/1e9:.1f} млрд ₽".replace(".", ",")
    if abs(v) >= 1e6:
        return f"{v/1e6:.0f} млн ₽"
    return f"{v:,.0f} ₽".replace(",", " ")


def _pct(x) -> str:
    try:
        v = float(x)
    except (TypeError, ValueError):
        return "—"
    if pd.isna(v):
        return "—"
    return f"{100 * v:.0f}%"


def _is_grocery_or_channel(mcc) -> bool:
    s = str(mcc or "")
    return s in ("Продуктовые магазины", "Маркетплейсы") or "родукт" in s or "аркетплейс" in s


def _fmt_int(x) -> str:
    try:
        if pd.isna(x):
            return "—"
        return str(int(float(x)))
    except (TypeError, ValueError):
        return "—"


def market_snapshot(
    merchant_shares: pd.DataFrame,
    city: str,
    mcc: str,
    top_n: int = 5,
) -> dict[str, Any]:
    """Top retailers in MCC for Samokat audience (Sber) — market, not own GMV only."""
    empty: dict[str, Any] = {
        "line": "—",
        "top1_name": None,
        "top1_share": None,
        "top3_share": None,
        "samokat_share": None,
        "players": [],
    }
    if merchant_shares is None or merchant_shares.empty:
        return empty
    df = merchant_shares[
        (merchant_shares["city"] == city)
        & (merchant_shares["mcc_category"].astype(str) == str(mcc))
    ].copy()
    if df.empty:
        return empty
    df = df.sort_values("smkt_gmv", ascending=False)
    rows: list[dict[str, Any]] = []
    for _, r in df.iterrows():
        name = str(r["merchant"]).strip()
        share = float(r["share_smkt_gmv"]) if pd.notna(r.get("share_smkt_gmv")) else 0.0
        gmv = float(r["smkt_gmv"]) if pd.notna(r.get("smkt_gmv")) else 0.0
        key = name.casefold()
        hit = next((x for x in rows if x["key"] == key), None)
        if hit:
            hit["share"] += share
            hit["gmv"] += gmv
        else:
            rows.append({"name": name, "key": key, "share": share, "gmv": gmv})
    rows.sort(key=lambda x: x["share"], reverse=True)
    top = rows[:top_n]
    samokat_share = next(
        (x["share"] for x in rows if "самокат" in x["key"] or x["key"] == "samokat"),
        None,
    )
    top1 = top[0] if top else None
    top3_share = sum(x["share"] for x in top[:3]) if top else None
    line = " · ".join(f"{x['name']} {_pct(x['share'])}" for x in top) if top else "—"
    return {
        "line": line,
        "top1_name": top1["name"] if top1 else None,
        "top1_share": top1["share"] if top1 else None,
        "top3_share": top3_share,
        "samokat_share": samokat_share,
        "players": top,
    }


def market_etalon_advice(market: dict[str, Any], *, cutting: bool) -> str:
    """Recommendation that leans on market structure, not only own smkt_gmv."""
    if not market.get("top1_name"):
        return "Рыночный разрез по ритейлерам в MCC пока пуст — добрать доли Сбера."
    top1 = market["top1_name"]
    t1s = market.get("top1_share") or 0
    t3 = market.get("top3_share") or 0
    sm = market.get("samokat_share")
    sm_bit = (
        f"доля Самоката в MCC у аудитории {_pct(sm)}"
        if sm is not None
        else "Самоката почти нет в топе MCC у аудитории"
    )
    if cutting:
        if t1s >= 0.4:
            return (
                f"Рынок концентрирован: {top1} ~{_pct(t1s)} трат аудитории в домене. "
                f"Ширину эталона сверять с лидером рынка ({top1}), а не только с нашим оборотом; "
                f"{sm_bit}. Урезание NEW без оглядки на ассортимент лидера — риск отстать от рыночного стандарта."
            )
        if t3 >= 0.55:
            return (
                f"Топ-3 сети держат {_pct(t3)} домена ({market['line']}). "
                f"Решение наш/NEW — против их покрытия категорий; {sm_bit}."
            )
        return (
            f"Рынок фрагментирован ({market['line']}). "
            f"При урезании NEW зафиксировать, какие куски рынка (у каких сетей) сознательно отдаём; {sm_bit}."
        )
    if t1s >= 0.4:
        return (
            f"Лидер рынка {top1} ({_pct(t1s)}). Расширение NEW оправдано, если закрываем пробелы "
            f"относительно {top1} / топа; {sm_bit}."
        )
    return (
        f"Рынок: {market['line']}. Расширение NEW — под доли игроков, у которых аудитория уже тратит; {sm_bit}."
    )


def _mission_so_what(links: list[dict]) -> str:
    if not links:
        return "Нет моста к MCC — проверить scenario_mcc_bridge."
    grocery = [l for l in links if "родукт" in l["mcc"]]
    specialty = [l for l in links if "родукт" not in l["mcc"]]
    parts = []
    if grocery:
        parts.append(
            f"Grocery-нога: доля Самоката в MCC {grocery[0]['smkt_share']}; "
            f"соседи — {grocery[0]['retailers'][:120]}."
        )
    if specialty:
        s = specialty[0]
        mkt = s.get("market") or s.get("retailers") or "—"
        parts.append(
            f"Specialty: {s['mcc']} — внешний кошелёк {s['sber']}, "
            f"эталоны NEW МАКС/15/сумма = {s['etalon_max']}/{s['etalon_15']}/{s['etalon_new']}. "
            f"Рынок: {mkt}."
        )
    return " ".join(parts) if parts else "Смотри связанные домены ниже."


def build_synthesis(
    *,
    city: str,
    megas: pd.DataFrame,
    hyp: pd.DataFrame,
    grocery_merchants: pd.DataFrame,
    mp_compare: pd.DataFrame,
    mp_grocery: pd.DataFrame,
    unified: pd.DataFrame,
    merchant_shares: pd.DataFrame | None = None,
    period: str = "",
) -> dict[str, Any]:
    """Return payload for HTML: flow, conclusions, story lenses."""

    if merchant_shares is None:
        merchant_shares = pd.DataFrame()

    flow = [
        {
            "id": "scenarios",
            "title": "Миссии Самоката",
            "what": "Что покупают внутри Самоката (мегасценарии / GMV)",
            "role": "спрос внутри",
        },
        {
            "id": "sber_smkt",
            "title": "Сбер · аудитория Самоката",
            "what": "Куда ещё тратят самокатовцы (MCC и сети рынка)",
            "role": "кошелёк + рынок",
        },
        {
            "id": "etalons",
            "title": "NEW-эталоны QNF",
            "what": "Только NEW: МАКС / 15 мин / сумма — целевая ширина",
            "role": "решение по витрине",
        },
        {
            "id": "mp",
            "title": "Магнит / Пятёрочка",
            "what": "Отдельные когорты: пересечение с масс-маркетом",
            "role": "конкурентный контекст",
        },
    ]
    join_logic = (
        "Жёсткого user-level join нет. Связка: "
        "миссия → MCC → доли ритейлеров рынка (Сбер) → NEW-эталон. "
        "В отчёте только колонки NEW из QNF; старый эталон без NEW не используем. "
        "Магнит/Пятёрочка — отдельные аудитории (не суммировать)."
    )

    conclusions: list[dict[str, Any]] = []

    groc = grocery_merchants[grocery_merchants["city"] == city].sort_values(
        "smkt_gmv", ascending=False
    )
    sm = groc[groc["merchant"].astype(str).str.lower().str.contains("самокат")]
    if len(sm) and len(groc):
        share = float(sm["share_smkt_gmv"].iloc[0])
        g2 = groc.reset_index(drop=True)
        mask = g2["merchant"].astype(str).str.lower().str.contains("самокат")
        rank = int(g2.index[mask][0]) + 1 if mask.any() else 0
        top2 = groc.head(2)
        conclusions.append(
            {
                "id": "grocery_share",
                "tag": "Grocery",
                "title": f"В grocery Самокат — №{rank} у своей аудитории ({_pct(share)})",
                "body": (
                    f"Рынок grocery у аудитории Самоката ({city}): "
                    f"{top2.iloc[0]['merchant']} {_pct(top2.iloc[0]['share_smkt_gmv'])}, "
                    f"{top2.iloc[1]['merchant']} {_pct(top2.iloc[1]['share_smkt_gmv'])}, "
                    f"Самокат {_pct(share)} ({_money(sm['smkt_gmv'].iloc[0])}). "
                    "Ориентир ширины/корзины — лидеры рынка (ВВ/Перекрёсток), не только свой GMV."
                ),
                "sources": ["scenarios", "sber_smkt"],
                "action": "Сравнивать эталон grocery с корзиной топ-сетей рынка, не с внутренним оборотом в вакууме.",
            }
        )

    if not megas.empty and "GMV" in megas.columns:
        top_mega = megas.sort_values("GMV", ascending=False).iloc[0]
        conclusions.append(
            {
                "id": "top_mission",
                "tag": "Миссии",
                "title": f"Крупнейшая миссия — «{top_mega['mega']}» ({_money(top_mega['GMV'])})",
                "body": (
                    "Она почти целиком сидит на MCC «Продуктовые». "
                    "Эталоны specialty сюда не переносятся — решения по ширине grocery идут через сети рынка и миссии."
                ),
                "sources": ["scenarios", "sber_smkt", "etalons"],
                "action": "Не смешивать grocery-миссии с эталонами specialty; считать отдельно.",
            }
        )

    if not hyp.empty:
        hot = hyp[hyp["demand_tier"].isin(["очень активный", "активный"])].copy()
        # thin NEW etalon under strong demand
        hot["etalon_new_km"] = pd.to_numeric(hot.get("etalon_new_km"), errors="coerce").fillna(0)
        thin = hot[hot["etalon_new_km"] < 80].sort_values(
            ["etalon_new_km", "external_smkt_gmv"], ascending=[True, False]
        )
        wide = hot[hot["etalon_new_km"] >= 80].sort_values("external_smkt_gmv", ascending=False)
        if len(thin):
            r = thin.iloc[0]
            mcc = str(r["mcc_group"])
            market = market_snapshot(merchant_shares, city, mcc)
            advice = market_etalon_advice(market, cutting=False)
            conclusions.append(
                {
                    "id": "etalon_thin",
                    "tag": "NEW-эталон × рынок",
                    "title": f"Узкий NEW-эталон при сильном спросе: {mcc}",
                    "body": (
                        f"Спрос {r['demand_tier']}, smkt_gmv аудитории = {_money(r['external_smkt_gmv'])}. "
                        f"NEW-эталон {int(r['etalon_new_km'])} SKU "
                        f"(МАКС {int(r.get('etalon_new_max') or 0)} / 15 мин {int(r.get('etalon_new_15') or 0)}). "
                        f"Рынок домена (Сбер): {market['line']}. {advice}"
                    ),
                    "sources": ["sber_smkt", "etalons"],
                    "action": (
                        f"По «{mcc}»: наращивать NEW-ширину относительно лидеров "
                        f"({market['top1_name'] or 'топ MCC'}), не от внутреннего оборота в вакууме."
                    ),
                }
            )
        if len(wide):
            r = wide.iloc[0]
            mcc = str(r["mcc_group"])
            market = market_snapshot(merchant_shares, city, mcc)
            advice = market_etalon_advice(market, cutting=False)
            conclusions.append(
                {
                    "id": "etalon_check",
                    "tag": "NEW-эталон × рынок",
                    "title": f"Сильный спрос + NEW-эталон есть: {mcc} ({int(r['etalon_new_km'])} SKU)",
                    "body": (
                        f"Спрос {r['demand_tier']}, {_money(r['external_smkt_gmv'])} smkt_gmv. "
                        f"NEW {int(r['etalon_new_km'])} (МАКС {int(r.get('etalon_new_max') or 0)} / "
                        f"15 мин {int(r.get('etalon_new_15') or 0)}). "
                        f"Рынок домена: {market['line']}. {advice}"
                    ),
                    "sources": ["sber_smkt", "etalons", "scenarios"],
                    "action": (
                        f"Сверить покрытие «{mcc}» с {market['top1_name'] or 'топ рынка'}: "
                        "эталон уже задан — вопрос в составе vs лидеры."
                    ),
                }
            )

    if not mp_compare.empty:
        sub = mp_compare[
            (mp_compare["city"] == city)
            & (mp_compare["mcc_category"] == "Продуктовые магазины")
            & (mp_compare["retail_merch"].isin(["Магнит Оффлайн", "Пятерочка Оффлайн"]))
        ]
        sm_in = (
            mp_grocery[
                mp_grocery["merchant"].astype(str).str.lower().str.contains("самокат")
            ]
            if not mp_grocery.empty
            else pd.DataFrame()
        )
        if len(sub):
            bits = []
            for _, r in sub.iterrows():
                bits.append(
                    f"{r['retail_merch']}: grocery {_money(r['cohort_gmv'])} "
                    f"({float(r['cohort_vs_samokat_aud_gmv']):.1f}× к аудитории Самоката)"
                )
            cross = ""
            if len(sm_in):
                parts = [
                    f"{r['retail_merch']}: Самокат {_money(r['retail_gmv'])} "
                    f"({_pct(r['share_in_mcc_cohort'])})"
                    for _, r in sm_in.iterrows()
                ]
                cross = " Пересечение: " + "; ".join(parts) + "."
            conclusions.append(
                {
                    "id": "mp_context",
                    "tag": "Магнит/5ка",
                    "title": "У масс-маркета grocery больше; Самокат внутри когорты — мал",
                    "body": (
                        " ".join(bits) + "." + cross + " "
                        "Клиенты Магнита/Пятёрочки почти не «живут» в Самокате — другой объём и частота."
                    ),
                    "sources": ["mp", "sber_smkt"],
                    "action": "Эталон grocery ориентировать на аудиторию Самоката и ВВ/Перекрёсток, не на доли внутри Магнита/5ки.",
                }
            )

    n_uni = len(unified) if unified is not None else 0
    conclusions.append(
        {
            "id": "how_to_decide",
            "tag": "Как решать",
            "title": "Эталон = миссия × спрос × рынок × NEW-ширина",
            "body": (
                f"В единой таблице {n_uni} строк ({city}"
                + (f", сценарии {period}" if period else "")
                + "). "
                "Specialty: NEW-эталон (МАКС/15/сумма) + доли лидеров MCC в Сбере. "
                "Старый эталон без NEW не участвует."
            ),
            "sources": ["scenarios", "sber_smkt", "etalons", "mp"],
            "action": "По домену: рынок (топ сетей) → NEW-эталон → миссия.",
        }
    )

    lenses: list[dict[str, Any]] = []

    if not megas.empty and "GMV" in megas.columns and not unified.empty:
        for _, m in megas.sort_values("GMV", ascending=False).head(5).iterrows():
            mega = str(m["mega"])
            rows = unified[unified["mega"].astype(str) == mega]
            links = []
            for _, r in rows.iterrows():
                mcc = str(r.get("mcc_group", ""))
                market = market_snapshot(merchant_shares, city, mcc)
                links.append(
                    {
                        "mcc": mcc,
                        "role": str(r.get("bridge_role", "")),
                        "sber": _money(r.get("sber_smkt_gmv")),
                        "etalon_max": (
                            "н/п"
                            if _is_grocery_or_channel(mcc)
                            else _fmt_int(r.get("etalon_max_sku"))
                        ),
                        "etalon_15": (
                            "н/п"
                            if _is_grocery_or_channel(mcc)
                            else _fmt_int(r.get("etalon_15min_sku"))
                        ),
                        "etalon_new": (
                            "н/п"
                            if _is_grocery_or_channel(mcc)
                            else _fmt_int(r.get("etalon_new_km_sku"))
                        ),
                        "retailers": market["line"]
                        if market["line"] != "—"
                        else str(r.get("retailer_shares_pct") or "—"),
                        "market": market["line"],
                        "smkt_share": _pct(r.get("samokat_share_in_mcc")),
                    }
                )
            lenses.append(
                {
                    "key": f"mission:{mega}",
                    "kind": "Миссия",
                    "label": f"{mega} · {_money(m['GMV'])}",
                    "headline": f"Миссия «{mega}» — {_money(m['GMV'])} внутри Самоката",
                    "so_what": _mission_so_what(links),
                    "links": links,
                    "missions": [],
                }
            )

    if not hyp.empty:
        for _, r in hyp.head(6).iterrows():
            mcc = str(r["mcc_group"])
            market = market_snapshot(merchant_shares, city, mcc)
            mission_hits: list[str] = []
            if not unified.empty:
                hits = unified[unified["mcc_group"].astype(str) == mcc]
                mission_hits = sorted(hits["mega"].astype(str).unique().tolist())[:5]
            advice = market_etalon_advice(market, cutting=False)
            etalon = int(r.get("etalon_new_km") or 0)
            lenses.append(
                {
                    "key": f"mcc:{mcc}",
                    "kind": "Домен",
                    "label": f"{mcc} · спрос {r['demand_tier']}",
                    "headline": (
                        f"{mcc}: спрос {r['demand_tier']}, "
                        f"smkt {_money(r['external_smkt_gmv'])}, "
                        f"NEW-эталон {etalon} "
                        f"(МАКС {int(r.get('etalon_new_max') or 0)} / 15 мин {int(r.get('etalon_new_15') or 0)})"
                    ),
                    "so_what": f"{r.get('hypothesis', '')} {advice}",
                    "links": [
                        {
                            "mcc": mcc,
                            "role": "specialty",
                            "sber": _money(r["external_smkt_gmv"]),
                            "etalon_max": str(int(r.get("etalon_new_max") or 0)),
                            "etalon_15": str(int(r.get("etalon_new_15") or 0)),
                            "etalon_new": str(etalon),
                            "retailers": market["line"],
                            "market": market["line"],
                            "smkt_share": _pct(r.get("external_smkt_gmv_share")),
                        }
                    ],
                    "missions": mission_hits,
                }
            )

    return {
        "city": city,
        "period": period,
        "flow": flow,
        "join_logic": join_logic,
        "conclusions": conclusions,
        "lenses": lenses,
    }
