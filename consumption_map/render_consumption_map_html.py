#!/usr/bin/env python3
"""Render consumption map HTML with scenario ↔ retailer intersections."""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from synthesis import build_synthesis


def _fmt_money(x) -> str:
    try:
        v = float(x)
    except (TypeError, ValueError):
        return "—"
    if pd.isna(v):
        return "—"
    if abs(v) >= 1e9:
        return f"{v/1e9:.1f} млрд".replace(".", ",")
    if abs(v) >= 1e6:
        return f"{v/1e6:.0f} млн"
    return f"{v:,.0f}".replace(",", " ")


def _fmt_int(x) -> str:
    try:
        v = float(x)
    except (TypeError, ValueError):
        return "—"
    if pd.isna(v):
        return "—"
    return f"{int(v):,}".replace(",", " ")


def _fmt_pct(x) -> str:
    try:
        v = float(x)
    except (TypeError, ValueError):
        return "—"
    if pd.isna(v):
        return "—"
    return f"{100 * v:.0f}%"


def _fmt_etalon_cell(x, *, grocery_or_channel: bool = False) -> str:
    """Dash for missing; explicit note for domains without QNF specialty etalon."""
    try:
        v = float(x)
        if pd.isna(v):
            return "н/п" if grocery_or_channel else "—"
        return f"{int(v):,}".replace(",", " ")
    except (TypeError, ValueError):
        return "н/п" if grocery_or_channel else "—"


def _bridge_role_ru(role) -> str:
    r = str(role or "").strip().lower()
    return {
        "primary": "основной",
        "secondary": "смежный",
        "channel": "канал",
    }.get(r, str(role or "—"))


def _bridge_role_hint(role) -> str:
    r = str(role or "").strip().lower()
    return {
        "primary": "главный MCC-домен миссии",
        "secondary": "доп. домен, куда ещё ходит аудитория",
        "channel": "канал покупки (маркетплейс и т.п.)",
    }.get(r, "")


def _is_grocery_or_channel(mcc) -> bool:
    s = str(mcc or "")
    return s in ("Продуктовые магазины", "Маркетплейсы") or "родукт" in s or "аркетплейс" in s

def _esc(s) -> str:
    return (
        str(s)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def _num_class(v) -> str:
    try:
        return "neg" if float(v) < 0 else "pos"
    except (TypeError, ValueError):
        return ""


def _badge_for_hyp(text: str) -> str:
    t = str(text)
    if "Спор" in t or "режут" in t:
        return "badge-warn"
    if "пустые" in t or "Растить" in t:
        return "badge-danger"
    return "badge-ok"


def render_html(
    xlsx: Path,
    out_html: Path,
    city: str = "Москва",
    cards_path: Path | None = None,
) -> Path:
    hyp = pd.read_excel(xlsx, "05_Hypotheses")
    megas = pd.read_excel(xlsx, "06_Scenario_Megas")
    wallet_msk = pd.read_excel(xlsx, "04b_Wallet_x_Etalon_MSK")
    merchant_shares = pd.read_excel(xlsx, "09_Merchant_shares")
    intersections = pd.read_excel(xlsx, "09b_Scenario_x_Retailer")
    grocery_merchants = pd.read_excel(xlsx, "07c_Grocery_merchants")
    offline = pd.read_excel(xlsx, "07b_Offline_TOP")
    method = pd.read_excel(xlsx, "00_Method")
    etalon_l1 = pd.read_excel(xlsx, "02_Etalon_by_lvl1")
    xl_sheets = pd.ExcelFile(xlsx).sheet_names
    sber_mcc = pd.read_excel(xlsx, "01_Sber_MCC_city") if "01_Sber_MCC_city" in xl_sheets else pd.DataFrame()
    dictionary = pd.read_excel(xlsx, "00b_Dictionary") if "00b_Dictionary" in xl_sheets else pd.DataFrame()
    unified = pd.read_excel(xlsx, "00c_Unified_Master") if "00c_Unified_Master" in xl_sheets else pd.DataFrame()
    mp_compare = pd.read_excel(xlsx, "10c_MP_vs_Samokat") if "10c_MP_vs_Samokat" in xl_sheets else pd.DataFrame()
    mp_totals = pd.read_excel(xlsx, "10f_MP_Totals_focus") if "10f_MP_Totals_focus" in xl_sheets else pd.DataFrame()
    if mp_totals.empty and "10_MP_Totals" in xl_sheets:
        mp_totals = pd.read_excel(xlsx, "10_MP_Totals")
        if not mp_totals.empty and "city" in mp_totals.columns:
            mp_totals = mp_totals[mp_totals["city"] == city]
    mp_grocery = (
        pd.read_excel(xlsx, "10d_MP_Grocery_overlap") if "10d_MP_Grocery_overlap" in xl_sheets else pd.DataFrame()
    )
    mp_top = pd.read_excel(xlsx, "10e_MP_Top_merchants") if "10e_MP_Top_merchants" in xl_sheets else pd.DataFrame()

    method_map = dict(zip(method["key"].astype(str), method["value"].astype(str)))
    mp_note = method_map.get(
        "magnit_pyaterochka_note",
        "Фильтр retail_merch = когорта уникальных клиентов. Не суммировать несколько мерчей — обороты задваиваются.",
    )
    period = ""
    if method_map.get("scenario_period_from"):
        period = f"{str(method_map['scenario_period_from'])[:10]} — {str(method_map['scenario_period_to'])[:10]}"

    if cards_path and cards_path.exists():
        cards = json.loads(cards_path.read_text(encoding="utf-8"))
    else:
        cards = []

    # Grocery shares for focus city
    groc = grocery_merchants[grocery_merchants["city"] == city].sort_values("smkt_gmv", ascending=False).head(12)
    grocery_chart = {
        "labels": groc["merchant"].astype(str).tolist(),
        "shares": [float(x) * 100 if pd.notna(x) else 0 for x in groc["share_smkt_gmv"]],
        "smkt": [float(x) / 1e9 for x in groc["smkt_gmv"]],
        "is_smkt": [
            ("самокат" in str(m).lower()) for m in groc["merchant"]
        ],
    }

    # MCC list for competitive explorer
    mcc_list = sorted(merchant_shares[merchant_shares["city"] == city]["mcc_category"].dropna().unique().tolist())
    mcc_payload = {}
    for mcc in mcc_list:
        sub = merchant_shares[(merchant_shares["city"] == city) & (merchant_shares["mcc_category"] == mcc)]
        sub = sub.sort_values("smkt_gmv", ascending=False).head(10)
        mcc_payload[mcc] = [
            {
                "merchant": str(r["merchant"]),
                "share": float(r["share_smkt_gmv"]) if pd.notna(r["share_smkt_gmv"]) else 0,
                "smkt_gmv": float(r["smkt_gmv"]),
                "is_samokat": bool(
                    "самокат" in str(r["merchant"]).lower() or str(r["merchant"]).lower() == "samokat"
                ),
            }
            for _, r in sub.iterrows()
        ]

    # Hypothesis rows
    hyp_rows = []
    for _, r in hyp.iterrows():
        badge = _badge_for_hyp(r.get("hypothesis", ""))
        cls = _num_class(r["dev"])
        tier = r.get("demand_tier", "")
        tier_cls = {
            "очень активный": "tier-hot",
            "активный": "tier-high",
            "умеренный": "tier-mid",
            "слабый": "tier-low",
        }.get(str(tier), "tier-mid")
        hyp_rows.append(
            "<tr>"
            f"<td><b>{_esc(r['mcc_group'])}</b></td>"
            f"<td><span class='tier {tier_cls}'>{_esc(tier)}</span></td>"
            f"<td class='num'>{_fmt_money(r['external_smkt_gmv'])}</td>"
            f"<td class='muted'>{_esc(r.get('market_top_retailers', '—'))}</td>"
            f"<td class='num'>{_fmt_int(r.get('etalon_new_km', r.get('etalon_ours')))}</td>"
            f"<td class='num'>{_fmt_int(r.get('etalon_new_max'))}</td>"
            f"<td class='num'>{_fmt_int(r.get('etalon_new_15'))}</td>"
            "</tr>"
        )

    # Mind-map graph payload from dictionary (mission → mcc → top retailers)
    # Volumes: mission = scenario GMV; domain = Sber smkt_gmv of Samokat audience in MCC
    domain_gmv = {}
    if not sber_mcc.empty:
        for _, wr in sber_mcc[sber_mcc["city"] == city].iterrows():
            domain_gmv[str(wr["mcc_category"])] = float(wr.get("smkt_gmv") or 0)
    if not wallet_msk.empty and "mcc_group" in wallet_msk.columns:
        for _, wr in wallet_msk.iterrows():
            key = str(wr["mcc_group"])
            if key not in domain_gmv or domain_gmv[key] <= 0:
                domain_gmv[key] = float(wr.get("external_smkt_gmv") or 0)
    if not merchant_shares.empty:
        ms_city = merchant_shares[merchant_shares["city"] == city]
        if "mcc_smkt_gmv" in ms_city.columns:
            for mcc_name, grp in ms_city.groupby("mcc_category"):
                key = str(mcc_name)
                if key not in domain_gmv or domain_gmv[key] <= 0:
                    domain_gmv[key] = float(grp["mcc_smkt_gmv"].iloc[0] or 0)
        else:
            for mcc_name, grp in ms_city.groupby("mcc_category"):
                key = str(mcc_name)
                if key not in domain_gmv or domain_gmv[key] <= 0:
                    domain_gmv[key] = float(grp["smkt_gmv"].sum())

    mission_gmv = {}
    if not megas.empty and "GMV" in megas.columns:
        for _, mr in megas.iterrows():
            mission_gmv[str(mr["mega"])] = float(mr["GMV"] or 0)

    graph_nodes = []
    graph_edges = []
    seen = set()
    for _, r in dictionary.iterrows():
        mega = str(r.get("mega", ""))
        mcc = str(r.get("mcc_group", ""))
        if not mega or mega == "nan":
            continue
        mid = f"m:{mega}"
        if mid not in seen:
            seen.add(mid)
            gmv = float(mission_gmv.get(mega) or r.get("scenario_gmv") or 0)
            gmv_label = _fmt_money(gmv)
            n_ml4 = r.get("n_ml4")
            n_scen = r.get("n_scenarios")
            ml4_prev = str(r.get("ml4_preview") or "")
            scen_list = str(r.get("scenarios_list") or "")
            cat_bits = []
            if pd.notna(n_scen):
                cat_bits.append(f"сценариев: {int(n_scen)}")
            if pd.notna(n_ml4):
                cat_bits.append(f"ml4: {int(n_ml4)}")
            cat_head = ", ".join(cat_bits)
            title = f"{mega}\nGMV миссии: {gmv_label}"
            if cat_head:
                title += f"\n{cat_head}"
            if ml4_prev and ml4_prev != "nan":
                title += f"\nКатегории ml4: {ml4_prev}"
            graph_nodes.append(
                {
                    "id": mid,
                    "label": f"{mega}\n{gmv_label}",
                    "group": "mission",
                    "kind": "mission",
                    "name": mega,
                    "volume": gmv,
                    "volume_fmt": gmv_label,
                    "volume_metric": "GMV миссии (Самокат)",
                    "n_ml4": int(n_ml4) if pd.notna(n_ml4) else None,
                    "n_scenarios": int(n_scen) if pd.notna(n_scen) else None,
                    "ml4_preview": ml4_prev if ml4_prev and ml4_prev != "nan" else "",
                    "scenarios_list": scen_list if scen_list and scen_list != "nan" else "",
                    "title": title,
                    "value": max(18, min(70, (gmv / 1e9) * 1.6)) if gmv else 18,
                }
            )
        if not mcc or mcc in ("—", "nan", "None"):
            continue
        did = f"d:{mcc}"
        if did not in seen:
            seen.add(did)
            dgmv = float(domain_gmv.get(mcc) or 0)
            # fallback from unified row
            if dgmv <= 0 and not unified.empty:
                urow = unified[unified["mcc_group"].astype(str) == mcc]
                if len(urow) and pd.notna(urow.iloc[0].get("sber_smkt_gmv")):
                    dgmv = float(urow.iloc[0]["sber_smkt_gmv"])
            dgmv_label = _fmt_money(dgmv) if dgmv else "—"
            graph_nodes.append(
                {
                    "id": did,
                    "label": f"{mcc}\n{dgmv_label}",
                    "group": "domain",
                    "kind": "domain",
                    "name": mcc,
                    "volume": dgmv,
                    "volume_fmt": dgmv_label,
                    "volume_metric": "smkt_gmv аудитории Самоката в MCC",
                    "title": f"{mcc}\nДомен (Sber smkt): {dgmv_label}",
                    "value": max(16, min(65, (dgmv / 1e9) * 0.45)) if dgmv else 16,
                }
            )
        role = str(r.get("bridge_role", ""))
        graph_edges.append(
            {
                "from": mid,
                "to": did,
                "title": f"{role} · миссия {_fmt_money(mission_gmv.get(mega) or r.get('scenario_gmv') or 0)}",
            }
        )
        retailers = str(r.get("retailer_shares_pct") or "")
        parts = [p.strip() for p in retailers.split("·") if p.strip()][:4]
        for p in parts:
            name = p.rsplit(" ", 1)[0].strip() if " " in p else p
            if not name:
                continue
            rid = f"r:{mcc}:{name}"
            if rid not in seen:
                seen.add(rid)
                is_sm = "самокат" in name.lower()
                graph_nodes.append(
                    {
                        "id": rid,
                        "label": name,
                        "group": "samokat" if is_sm else "retailer",
                        "kind": "retailer",
                        "name": name,
                        "volume": None,
                        "volume_fmt": p,
                        "volume_metric": "доля в MCC",
                        "title": f"{name}\n{p} в «{mcc}»",
                        "value": 14 if is_sm else 10,
                    }
                )
            graph_edges.append({"from": did, "to": rid, "title": p})

    # Ranked volume lists for the mind-map sidebar
    mission_rank = sorted(
        [
            {"name": n["name"], "volume": n["volume"], "fmt": n["volume_fmt"]}
            for n in graph_nodes
            if n.get("kind") == "mission"
        ],
        key=lambda x: x["volume"] or 0,
        reverse=True,
    )
    domain_rank = sorted(
        [
            {"name": n["name"], "volume": n["volume"], "fmt": n["volume_fmt"]}
            for n in graph_nodes
            if n.get("kind") == "domain"
        ],
        key=lambda x: x["volume"] or 0,
        reverse=True,
    )
    mission_rank_html = "".join(
        f"<tr data-node='m:{_esc(r['name'])}'><td>{i+1}. {_esc(r['name'])}</td>"
        f"<td class='num'>{_esc(r['fmt'])}</td></tr>"
        for i, r in enumerate(mission_rank[:12])
    )
    domain_rank_html = "".join(
        f"<tr data-node='d:{_esc(r['name'])}'><td>{i+1}. {_esc(r['name'])}</td>"
        f"<td class='num'>{_esc(r['fmt'])}</td></tr>"
        for i, r in enumerate(domain_rank[:12])
    )

    # Mega table
    mega_rows = []
    if "GMV" in megas.columns:
        for _, r in megas.head(12).iterrows():
            mega_rows.append(
                "<tr>"
                f"<td>{_esc(r['mega'])}</td>"
                f"<td class='num'>{_fmt_money(r['GMV'])}</td>"
                f"<td class='num'>{_fmt_int(r.get('Чеки', ''))}</td>"
                "</tr>"
            )

    # Offline top without ПРОЧИЕ
    off = offline.copy()
    if "company" in off.columns:
        off = off[off["company"].astype(str).str.upper() != "ПРОЧИЕ"]
    off_top = off.nlargest(12, "amount") if "amount" in off.columns else off.head(12)
    off_rows = []
    for _, r in off_top.iterrows():
        off_rows.append(
            "<tr>"
            f"<td>{_esc(r.get('tag_name', ''))}</td>"
            f"<td>{_esc(r.get('company', ''))}</td>"
            f"<td class='num'>{_fmt_money(r.get('amount', ''))}</td>"
            f"<td class='num'>{_fmt_int(r.get('users_number', ''))}</td>"
            "</tr>"
        )

    # Dictionary + unified rows for HTML
    unified_rows = []
    for _, r in unified.iterrows():
        mcc = r.get("mcc_group", "")
        groc_ch = _is_grocery_or_channel(mcc)
        unified_rows.append(
            "<tr>"
            f"<td><b>{_esc(r.get('mega',''))}</b></td>"
            f"<td>{_esc(mcc)}</td>"
            f"<td>{_esc(_bridge_role_ru(r.get('bridge_role')))}</td>"
            f"<td class='num'>{_fmt_money(r.get('scenario_gmv'))}</td>"
            f"<td class='num'>{_fmt_pct(r.get('scenario_gmv_share'))}</td>"
            f"<td class='num'>{_fmt_money(r.get('sber_smkt_gmv'))}</td>"
            f"<td class='num'>{_fmt_pct(r.get('sber_smkt_share_of_category_gmv'))}</td>"
            f"<td class='num'>{_fmt_etalon_cell(r.get('etalon_max_sku'), grocery_or_channel=groc_ch)}</td>"
            f"<td class='num'>{_fmt_etalon_cell(r.get('etalon_15min_sku'), grocery_or_channel=groc_ch)}</td>"
            f"<td class='num'>{_fmt_etalon_cell(r.get('etalon_new_km_sku'), grocery_or_channel=groc_ch)}</td>"
            f"<td class='muted'>{_esc(r.get('retailer_shares_pct',''))}</td>"
            f"<td class='num'>{_fmt_pct(r.get('samokat_share_in_mcc'))}</td>"
            "</tr>"
        )

    dict_rows = []
    for _, r in dictionary.iterrows():
        n_ml4 = r.get("n_ml4")
        n_scen = r.get("n_scenarios")
        ml4_cell = _esc(r.get("ml4_preview") or "—")
        meta = []
        if pd.notna(n_scen):
            meta.append(f"{int(n_scen)} сцен.")
        if pd.notna(n_ml4):
            meta.append(f"{int(n_ml4)} ml4")
        meta_s = " · ".join(meta)
        dict_rows.append(
            "<tr>"
            f"<td><b>{_esc(r.get('mega',''))}</b>"
            f"{('<div class=\"hint\">' + _esc(meta_s) + '</div>') if meta_s else ''}</td>"
            f"<td>{_esc(r.get('mcc_group',''))}</td>"
            f"<td>{_esc(_bridge_role_ru(r.get('bridge_role')))}"
            f"<div class='hint'>{_esc(_bridge_role_hint(r.get('bridge_role')))}</div></td>"
            f"<td class='num'>{_fmt_money(r.get('scenario_gmv'))}</td>"
            f"<td class='muted' title='{_esc(r.get('ml4_categories') or '')}'>{ml4_cell}</td>"
            f"<td>{_esc(r.get('retailer_shares_pct',''))}</td>"
            f"<td class='num'>{_fmt_pct(r.get('samokat_share_in_mcc'))}</td>"
            "</tr>"
        )

    # JSON for client-side filter of unified
    unified_json = []
    for _, r in unified.iterrows():
        unified_json.append({k: (None if pd.isna(v) else v) for k, v in r.items()})
    dict_json = []
    for _, r in dictionary.iterrows():
        dict_json.append({k: (None if pd.isna(v) else v) for k, v in r.items()})

    smkt_groc = groc[groc["merchant"].astype(str).str.lower().str.contains("самокат")]
    smkt_share = float(smkt_groc["share_smkt_gmv"].iloc[0]) if len(smkt_groc) else None
    vkus = groc[groc["merchant"].astype(str).str.lower().str.contains("вкус")]
    perek = groc[groc["merchant"].astype(str).str.lower().str.contains("перекр")]
    lead_line = ""
    if smkt_share is not None and len(vkus) and len(perek):
        lead_line = (
            f"Среди grocery-трат аудитории Самоката в {city}: "
            f"<b>Самокат {_fmt_pct(smkt_share)}</b>, "
            f"ВкусВилл {_fmt_pct(vkus['share_smkt_gmv'].iloc[0])}, "
            f"Перекрёсток {_fmt_pct(perek['share_smkt_gmv'].iloc[0])} "
            f"(доли внутри MCC «Продуктовые» по smkt_gmv)."
        )

    n_cards = len(cards)
    n_mcc = len(mcc_list)
    total_smkt_specialty = float(wallet_msk["external_smkt_gmv"].sum()) if len(wallet_msk) else 0
    n_unified = len(unified)
    n_dict = len(dictionary)

    synth = build_synthesis(
        city=city,
        megas=megas,
        hyp=hyp,
        grocery_merchants=grocery_merchants,
        mp_compare=mp_compare,
        mp_grocery=mp_grocery,
        unified=unified,
        merchant_shares=merchant_shares,
        period=period,
    )
    flow_html = "".join(
        f'<div class="flow-card"><div class="flow-role">{_esc(n["role"])}</div>'
        f'<div class="flow-title">{_esc(n["title"])}</div>'
        f'<div class="flow-what">{_esc(n["what"])}</div></div>'
        + ('<div class="flow-arrow">→</div>' if i < len(synth["flow"]) - 1 else "")
        for i, n in enumerate(synth["flow"])
    )
    # conclusions HTML removed from report — written to md beside HTML
    _ = synth["conclusions"]
    lens_opts = "".join(
        f'<option value="{_esc(L["key"])}">{_esc(L["kind"])}: {_esc(L["label"])}</option>'
        for L in synth["lenses"]
    )

    # Magnit / Pyaterochka audience block
    mp_has = not mp_compare.empty
    mp_compare_city = mp_compare[mp_compare["city"] == city] if mp_has and "city" in mp_compare.columns else mp_compare
    mp_merch_opts = (
        sorted(mp_compare_city["retail_merch"].dropna().unique().tolist())
        if mp_has and "retail_merch" in mp_compare_city.columns
        else []
    )
    # Prefer offline cohorts first in select
    pref_order = ["Магнит Оффлайн", "Пятерочка Оффлайн", "Магнит Онлайн", "Пятерочка Онлайн"]
    mp_merch_opts = [m for m in pref_order if m in mp_merch_opts] + [
        m for m in mp_merch_opts if m not in pref_order
    ]
    default_merch = mp_merch_opts[0] if mp_merch_opts else ""

    mp_kpi_rows = []
    for _, r in mp_totals.iterrows():
        mp_kpi_rows.append(
            "<tr>"
            f"<td>{_esc(r.get('retail_merch',''))}</td>"
            f"<td class='num'>{_fmt_int(r.get('retail_customers'))}</td>"
            f"<td class='num'>{_fmt_money(r.get('retail_gmv'))}</td>"
            f"<td class='num'>{_fmt_pct(r.get('retail_gmv_share'))}</td>"
            "</tr>"
        )

    mp_compare_json = []
    for _, r in mp_compare_city.iterrows():
        mp_compare_json.append({k: (None if pd.isna(v) else v) for k, v in r.items()})

    mp_top_json = []
    for _, r in mp_top.iterrows():
        mp_top_json.append({k: (None if pd.isna(v) else v) for k, v in r.items()})

    mp_groc_rows = []
    for _, r in mp_grocery.iterrows():
        mer = str(r.get("merchant", ""))
        is_sm = "самокат" in mer.lower()
        mp_groc_rows.append(
            "<tr>"
            f"<td>{_esc(r.get('retail_merch',''))}</td>"
            f"<td>{'<span class=badge-smkt>Самокат</span> ' if is_sm else ''}{_esc(mer)}</td>"
            f"<td class='num'>{_fmt_money(r.get('retail_gmv'))}</td>"
            f"<td class='num'>{_fmt_pct(r.get('share_in_mcc_cohort'))}</td>"
            "</tr>"
        )

    # Highlight: Samokat inside Magnit Offline grocery
    mp_cross_line = ""
    if not mp_grocery.empty:
        mag = mp_grocery[
            (mp_grocery["retail_merch"].astype(str) == "Магнит Оффлайн")
            & (mp_grocery["merchant"].astype(str).str.lower().str.contains("самокат"))
        ]
        pyat = mp_grocery[
            (mp_grocery["retail_merch"].astype(str) == "Пятерочка Оффлайн")
            & (mp_grocery["merchant"].astype(str).str.lower().str.contains("самокат"))
        ]
        bits = []
        if len(mag):
            bits.append(
                f"у аудитории <b>Магнит Оффлайн</b> Самокат = {_fmt_money(mag['retail_gmv'].iloc[0])} "
                f"({_fmt_pct(mag['share_in_mcc_cohort'].iloc[0])} их grocery)"
            )
        if len(pyat):
            bits.append(
                f"у аудитории <b>Пятёрочка Оффлайн</b> Самокат = {_fmt_money(pyat['retail_gmv'].iloc[0])} "
                f"({_fmt_pct(pyat['share_in_mcc_cohort'].iloc[0])} их grocery)"
            )
        if bits:
            mp_cross_line = (
                "Сколько grocery-трат аудитории Магнита/Пятёрочки уходит в Самокат: "
                + "; ".join(bits)
                + "."
            )

    html = f"""<!doctype html>
<html lang="ru">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width,initial-scale=1" />
  <title>Карта потребления — миссии × ритейлеры</title>
  <script src="https://cdn.plot.ly/plotly-2.35.2.min.js" charset="utf-8"></script>
  <script src="https://unpkg.com/vis-network@9.1.9/standalone/umd/vis-network.min.js"></script>
  <style>
    :root {{
      --bg:#f3f5f7; --card:#fff; --ink:#15202b; --muted:#5c6b7a; --line:#e3e8ee;
      --accent:#0f6e56; --accent-soft:#e7f5f0; --warn:#9a6700; --warn-bg:#fff8e6;
      --danger:#b42318; --ok:#027a48; --ok-bg:#ecfdf3; --samokat:#0f6e56; --other:#94a3b8;
    }}
    * {{ box-sizing:border-box; }}
    body {{ margin:0; background:var(--bg); color:var(--ink); font-family:"Segoe UI",system-ui,sans-serif; line-height:1.45; }}
    .wrap {{ max-width:1200px; margin:0 auto; padding:18px 14px 56px; }}
    .hero {{
      background:linear-gradient(135deg,#0b3d2e 0%,#0f6e56 60%,#1a8f6e 100%);
      color:#fff; border-radius:16px; padding:26px 26px 20px; margin-bottom:14px;
    }}
    .hero h1 {{ margin:0 0 8px; font-size:26px; letter-spacing:-.02em; }}
    .hero p {{ margin:0; opacity:.93; max-width:900px; font-size:15px; }}
    .meta {{ margin-top:12px; display:flex; flex-wrap:wrap; gap:8px; }}
    .pill {{ background:rgba(255,255,255,.14); border:1px solid rgba(255,255,255,.22); border-radius:999px; padding:4px 11px; font-size:12px; }}
    .toc {{ display:flex; flex-wrap:wrap; gap:8px; margin-top:12px; }}
    .toc a {{ color:#fff; text-decoration:none; font-size:12px; background:rgba(255,255,255,.12); border:1px solid rgba(255,255,255,.2); padding:5px 10px; border-radius:8px; }}
    .box {{ background:var(--card); border:1px solid var(--line); border-radius:14px; padding:16px 18px; margin-bottom:12px; box-shadow:0 1px 2px rgba(16,24,40,.04); }}
    .box h2 {{ margin:0 0 6px; font-size:18px; }}
    .box h3 {{ margin:0 0 8px; font-size:14px; }}
    .lead {{ margin:0 0 12px; color:var(--muted); font-size:14px; }}
    .callout {{ background:var(--accent-soft); border:1px solid #b7e0d0; border-radius:12px; padding:12px 14px; font-size:14px; margin:10px 0; }}
    .warnbox {{ background:var(--warn-bg); border:1px solid #f5d98b; border-radius:12px; padding:12px 14px; font-size:13px; color:#7a5b00; margin:10px 0; }}
    .flow {{ display:flex; flex-wrap:wrap; align-items:stretch; gap:8px; margin:12px 0 4px; }}
    .flow-card {{ flex:1 1 160px; background:#f8fafc; border:1px solid var(--line); border-radius:12px; padding:12px; min-width:140px; }}
    .flow-role {{ font-size:11px; text-transform:uppercase; letter-spacing:.04em; color:var(--accent); margin-bottom:4px; }}
    .flow-title {{ font-weight:700; font-size:14px; margin-bottom:4px; }}
    .flow-what {{ font-size:12px; color:var(--muted); }}
    .flow-arrow {{ display:flex; align-items:center; color:var(--muted); font-size:20px; padding:0 2px; }}
    @media (max-width:700px) {{ .flow-arrow {{ display:none; }} }}
    .lens-card {{ background:#f8fafc; border:1px solid var(--line); border-radius:12px; padding:14px; margin-top:10px; min-height:120px; }}
    .lens-card h3 {{ margin:0 0 6px; font-size:16px; }}
    .lens-meta {{ font-size:13px; color:var(--muted); margin-bottom:10px; }}
    .lens-links {{ display:grid; gap:8px; }}
    .lens-link {{ background:#fff; border:1px solid var(--line); border-radius:10px; padding:10px 12px; font-size:13px; }}
    .lens-link > b:first-child {{ display:block; margin-bottom:4px; }}
    .kpi {{ display:grid; grid-template-columns:repeat(4,minmax(0,1fr)); gap:10px; }}
    @media (max-width:900px) {{ .kpi {{ grid-template-columns:1fr 1fr; }} }}
    .k {{ background:#f8fafc; border:1px solid var(--line); border-radius:12px; padding:12px; }}
    .k b {{ display:block; font-size:12px; color:var(--muted); margin-bottom:6px; }}
    .k span {{ font-size:22px; font-weight:700; }}
    .grid2 {{ display:grid; grid-template-columns:1fr 1fr; gap:12px; }}
    @media (max-width:900px) {{ .grid2 {{ grid-template-columns:1fr; }} }}
    table {{ width:100%; border-collapse:collapse; font-size:13px; }}
    th,td {{ padding:8px 10px; border-bottom:1px solid var(--line); text-align:left; vertical-align:top; }}
    th {{ font-size:11px; text-transform:uppercase; letter-spacing:.04em; color:var(--muted); background:#f8fafc; position:sticky; top:0; }}
    .num {{ text-align:right; font-variant-numeric:tabular-nums; white-space:nowrap; }}
    .neg {{ color:var(--danger); }} .pos {{ color:var(--ok); }}
    .scroll {{ max-height:420px; overflow:auto; border:1px solid var(--line); border-radius:10px; }}
    .badge {{ display:inline-block; padding:3px 8px; border-radius:8px; font-size:12px; }}
    .badge-warn {{ background:var(--warn-bg); color:var(--warn); }}
    .badge-danger {{ background:#fef3f2; color:var(--danger); }}
    .badge-ok {{ background:var(--ok-bg); color:var(--ok); }}
    .badge-smkt {{ background:#d1fae5; color:#065f46; font-weight:700; }}
    .flt {{ display:flex; flex-wrap:wrap; gap:10px; align-items:flex-end; margin-bottom:12px; }}
    .flt label {{ display:block; font-size:12px; color:var(--muted); margin-bottom:4px; }}
    .flt select {{ height:36px; min-width:220px; border-radius:8px; border:1px solid var(--line); padding:0 10px; background:#fff; font-size:13px; }}
    .plot {{ width:100%; height:400px; }}
    .plot-sm {{ width:100%; height:340px; }}
    .card-grid {{ display:grid; grid-template-columns:1fr; gap:10px; }}
    .scard {{ border:1px solid var(--line); border-radius:12px; padding:12px 14px; background:#fbfdff; }}
    .scard .head {{ display:flex; justify-content:space-between; gap:10px; flex-wrap:wrap; margin-bottom:8px; }}
    .scard .title {{ font-weight:700; font-size:15px; }}
    .scard .sub {{ color:var(--muted); font-size:12px; }}
    .mcc-block {{ margin-top:8px; padding-top:8px; border-top:1px dashed var(--line); }}
    .mcc-block .mcc-name {{ font-size:12px; font-weight:700; color:var(--accent); margin-bottom:6px; }}
    .bars {{ display:flex; flex-direction:column; gap:6px; }}
    .bar-row {{ display:grid; grid-template-columns:140px 1fr 64px; gap:8px; align-items:center; font-size:12px; }}
    .bar-track {{ height:10px; background:#eef2f6; border-radius:999px; overflow:hidden; }}
    .bar-fill {{ height:100%; border-radius:999px; background:var(--other); }}
    .bar-fill.smkt {{ background:var(--samokat); }}
    .bar-name.smkt {{ font-weight:700; color:var(--accent); }}
    .steps {{ display:grid; grid-template-columns:repeat(3,1fr); gap:10px; }}
    @media (max-width:900px) {{ .steps {{ grid-template-columns:1fr; }} }}
    .step {{ border:1px solid var(--line); border-radius:12px; padding:12px; background:#fbfdff; }}
    .step .n {{ width:22px; height:22px; border-radius:50%; background:var(--accent-soft); color:var(--accent); display:inline-flex; align-items:center; justify-content:center; font-size:12px; font-weight:700; margin-bottom:6px; }}
    .tier {{ display:inline-block; padding:2px 8px; border-radius:999px; font-size:11px; font-weight:700; }}
    .tier-hot {{ background:#fef3f2; color:#b42318; }}
    .tier-high {{ background:#fff8e6; color:#9a6700; }}
    .tier-mid {{ background:#eff8ff; color:#175cd3; }}
    .tier-low {{ background:#f2f4f7; color:#667085; }}
    #mindmap {{
      height:560px; border:1px solid var(--line); border-radius:12px; background:#fafcfb;
    }}
    .mind-legend {{ display:flex; flex-wrap:wrap; gap:12px; margin:8px 0 10px; font-size:12px; color:var(--muted); }}
    .mind-legend i {{ display:inline-block; width:10px; height:10px; border-radius:50%; margin-right:5px; }}
    .mind-layout {{ display:grid; grid-template-columns:1fr 280px; gap:12px; align-items:start; }}
    @media (max-width:980px) {{ .mind-layout {{ grid-template-columns:1fr; }} }}
    .mind-side h3 {{ margin:0 0 6px; font-size:13px; }}
    .mind-side .scroll {{ max-height:200px; margin-bottom:12px; }}
    .mind-side tr {{ cursor:pointer; }}
    .mind-side tr:hover td {{ background:#e7f5f0; }}
    .mind-side tr.active td {{ background:#d1fae5; }}
    #mind-info {{ background:#f8fafc; border:1px solid var(--line); border-radius:10px; padding:10px 12px; font-size:13px; min-height:72px; }}
    #mind-info b {{ display:block; margin-bottom:4px; font-size:14px; }}
    .muted {{ color:var(--muted); font-size:12px; }}
    .hint {{ font-size:11px; color:var(--muted); font-weight:400; margin-top:2px; }}
    th .hint {{ text-transform:none; letter-spacing:0; font-weight:400; display:block; margin-top:2px; max-width:150px; white-space:normal; }}
  </style>
</head>
<body>
<div class="wrap">
  <div class="hero">
    <h1>Карта потребления: миссии × кошелёк × эталоны</h1>
    <p>
      Начните с блока <b>«Как всё связано»</b> — там схема источников и выводы.
      Дальше: единая таблица, доли ритейлеров, Магнит/Пятёрочка, эталоны.
    </p>
    <div class="meta">
      <span class="pill">Город: {_esc(city)}</span>
      <span class="pill">Сценарии: {_esc(period) or "6 мес"}</span>
      <span class="pill">Мост: миссия → MCC → мерчанты</span>
      <span class="pill">Мягкое пересечение (не user-level)</span>
    </div>
    <div class="toc">
      <a href="#synthesis">Связь данных</a>
      <a href="#unified">Единая таблица</a>
      <a href="#dictionary">Словарь миссий</a>
      <a href="#mindmap-box">Mind-map</a>
      <a href="#demand">Как считаем спрос</a>
      <a href="#grocery">Grocery-доли</a>
      <a href="#mp-aud">Магнит / Пятёрочка</a>
      <a href="#missions">Миссия → конкуренты</a>
      <a href="#mcc">Доли внутри MCC</a>
      <a href="#etalon">NEW-эталоны</a>
    </div>
  </div>

  <div class="box" id="synthesis">
    <h2>Как связаны источники</h2>
    <p class="lead">
      Миссии Самоката → внешний кошелёк аудитории (Сбер) → NEW-эталоны QNF → сравнение с аудиториями Магнита/Пятёрочки.
      Авто-выводы вынесены в отдельный файл <code>consumption_map_conclusions.md</code>.
    </p>
    <div class="flow">{flow_html}</div>
    <div class="warnbox" style="margin-top:12px">{_esc(synth["join_logic"])}</div>
    <h3 style="margin:18px 0 6px;font-size:15px">Разбор одной оси</h3>
    <p class="lead" style="margin-bottom:8px">Выберите мегамиссию или specialty-домен.</p>
    <div class="flt">
      <div>
        <label>Ось</label>
        <select id="lens-select">{lens_opts}</select>
      </div>
    </div>
    <div class="lens-card" id="lens-panel"></div>
  </div>

  <div class="box" id="unified">
    <h2>Единая таблица: мегамиссии × Сбер × NEW-эталоны</h2>
    <p class="lead">
      Одна строка = мегамиссия из scenario-отчёта × домен MCC.
      Доли ритейлеров и доля Самоката — <b>внутри MCC</b>, от smkt_gmv аудитории Самоката (Сбер), сумма по сетям в домене ≈ 100%.
      NEW-эталон есть только у specialty-доменов (через кроссвок MCC↔ml1); для grocery/маркетплейсов — <b>н/п</b> (эталон QNF туда не клеится).
      Кроссвок приближённый: в сценарии ml4 могут относиться к разным ml1 — в таблице суммируются unique ml1, привязанные к MCC.
    </p>
    <div class="flt">
      <div><label>Поиск</label><input id="unified-search" type="search" placeholder="миссия / MCC / ритейлер…" style="height:36px;min-width:260px;border:1px solid var(--line);border-radius:8px;padding:0 10px" /></div>
      <div><label>Строк</label><div id="unified-count" style="font-size:13px;color:var(--muted);padding-top:8px">{n_unified}</div></div>
    </div>
    <div class="scroll" style="max-height:520px">
      <table id="unified-table">
        <thead>
          <tr>
            <th>Мегамиссия</th>
            <th>Домен MCC</th>
            <th>Роль моста<div class="hint">основной / смежный</div></th>
            <th class="num">GMV миссии<div class="hint">внутри Самоката</div></th>
            <th class="num">Доля миссий<div class="hint">от суммы мега</div></th>
            <th class="num">Sber smkt GMV<div class="hint">траты аудитории СМКТ в MCC</div></th>
            <th class="num">Доля аудитории в кат.<div class="hint">smkt_gmv / gmv категории</div></th>
            <th class="num">NEW МАКС</th>
            <th class="num">NEW 15 мин</th>
            <th class="num">NEW сумма</th>
            <th>Ритейлеры<div class="hint">% от smkt_gmv в MCC</div></th>
            <th class="num">Доля Самоката<div class="hint">% от smkt_gmv в MCC</div></th>
          </tr>
        </thead>
        <tbody id="unified-tbody">{''.join(unified_rows)}</tbody>
      </table>
    </div>
  </div>

  <div class="box" id="dictionary">
    <h2>Словарь: мегамиссия → категории → домен → ритейлеры</h2>
    <p class="lead">
      <b>Категории ml4</b> — что входит в мегамиссию по описанию сценариев (уникальные ml4 из состава leaf-сценариев; GMV тоже считается по ml4).
      <b>Основной</b> мост — главный MCC-домен; <b>смежный</b> — доп. домен. Доли ритейлеров — % от smkt_gmv аудитории Самоката внутри MCC.
    </p>
    <div class="flt">
      <div><label>Поиск</label><input id="dict-search" type="search" placeholder="Готовлю дома / Соль / Вкусвилл…" style="height:36px;min-width:260px;border:1px solid var(--line);border-radius:8px;padding:0 10px" /></div>
      <div><label>Строк</label><div id="dict-count" style="font-size:13px;color:var(--muted);padding-top:8px">{n_dict}</div></div>
    </div>
    <div class="scroll" style="max-height:420px">
      <table id="dict-table">
        <thead>
          <tr>
            <th>Мегамиссия</th>
            <th>Домен MCC</th>
            <th>Роль моста</th>
            <th class="num">GMV миссии</th>
            <th>Категории ml4 в миссии<div class="hint">уникальные; hover — полный список</div></th>
            <th>Ритейлеры (% в MCC)</th>
            <th class="num">Доля Самоката в MCC</th>
          </tr>
        </thead>
        <tbody id="dict-tbody">{''.join(dict_rows)}</tbody>
      </table>
    </div>
  </div>

  <div class="box" id="mindmap-box">
    <h2>Интерактивная карта словаря</h2>
    <p class="lead">
      Миссия → домен MCC → ритейлеры. На узле миссии — GMV; в подсказке / панели справа — <b>категории ml4</b> и leaf-сценарии.
      У домена — smkt_gmv аудитории Самоката в MCC. Размер узла ≈ объём.
    </p>
    <div class="mind-legend">
      <span><i style="background:#0f6e56"></i>Миссия + GMV</span>
      <span><i style="background:#175cd3"></i>Домен + smkt_gmv</span>
      <span><i style="background:#94a3b8"></i>Ритейлер (доля)</span>
      <span><i style="background:#027a48"></i>Самокат</span>
    </div>
    <div class="flt">
      <div>
        <label>Фокус на миссию</label>
        <select id="mind-focus">
          <option value="">Все миссии</option>
        </select>
      </div>
      <div style="padding-top:18px">
        <button id="mind-reset" type="button" style="height:36px;padding:0 12px;border-radius:8px;border:1px solid var(--line);background:#fff;cursor:pointer">Сбросить вид</button>
      </div>
    </div>
    <div class="mind-layout">
      <div id="mindmap"></div>
      <div class="mind-side">
        <div id="mind-info">Клик по узлу или строке рейтинга — объём и связи.</div>
        <h3>Миссии по GMV</h3>
        <div class="scroll">
          <table>
            <thead><tr><th>Миссия</th><th class="num">GMV</th></tr></thead>
            <tbody id="mind-mission-rank">{mission_rank_html}</tbody>
          </table>
        </div>
        <h3>Домены по smkt_gmv</h3>
        <div class="scroll">
          <table>
            <thead><tr><th>Домен MCC</th><th class="num">Sber</th></tr></thead>
            <tbody id="mind-domain-rank">{domain_rank_html}</tbody>
          </table>
        </div>
      </div>
    </div>
  </div>

  <div class="box" id="demand">
    <h2>Как определяем «спрос снаружи»</h2>
    <p class="lead">Сила домена среди других на данных Сбера (траты аудитории Самоката в MCC).</p>
    <div class="steps">
      <div class="step"><div class="n">1</div><b>smkt_gmv</b><span style="color:var(--muted);font-size:13px">Сколько аудитория Самоката тратит в MCC у внешних мерчантов (₽).</span></div>
      <div class="step"><div class="n">2</div><b>Перцентиль среди доменов</b><span style="color:var(--muted);font-size:13px">Очень активный = top 25%; активный 50–75%; умеренный 25–50%; слабый = bottom 25%.</span></div>
      <div class="step"><div class="n">3</div><b>Доля аудитории в категории</b><span style="color:var(--muted);font-size:13px">Если smkt_gmv ≥30% от всего GMV категории — усиливаем уровень спроса.</span></div>
    </div>
  </div>

  <div class="box" id="logic">
    <h2>Как устроено пересечение</h2>
    <div class="steps">
      <div class="step"><div class="n">1</div><b>Миссия Самоката</b><span style="color:var(--muted);font-size:13px">Напр. «Готовлю дома», «Питомцы», «Красота» — GMV внутри СМКТ.</span></div>
      <div class="step"><div class="n">2</div><b>Домен MCC в Сбере</b><span style="color:var(--muted);font-size:13px">Продуктовые / Зоо / Косметика… — куда та же аудитория платит картой.</span></div>
      <div class="step"><div class="n">3</div><b>Ритейлеры и доли</b><span style="color:var(--muted);font-size:13px">ВкусВилл, Перекрёсток, Четыре лапы… + доля Самоката, если он есть в MCC.</span></div>
    </div>
    <div class="warnbox">
      Это <b>не</b> «одни и те же чеки». Это согласованное пересечение по домену:
      сильная миссия внутри + сильные сети снаружи в связанном MCC = зона конкуренции / недобора.
    </div>
    <div class="kpi" style="margin-top:12px">
      <div class="k"><b>Миссий в карточках</b><span>{n_cards}</span></div>
      <div class="k"><b>MCC с долями ритейлеров</b><span>{n_mcc}</span></div>
      <div class="k"><b>Specialty smkt GMV</b><span>{_fmt_money(total_smkt_specialty)}</span></div>
      <div class="k"><b>Доля Самоката в grocery*</b><span>{_fmt_pct(smkt_share) if smkt_share is not None else "—"}</span></div>
    </div>
    <p class="lead" style="margin-top:8px">* доля smkt_gmv внутри MCC «Продуктовые магазины» у аудитории Самоката ({_esc(city)}).</p>
  </div>

  <div class="box" id="grocery">
    <h2>Grocery: с кем делим кошелёк</h2>
    <p class="lead">Доли ритейлеров внутри продуктового MCC по тратам аудитории Самоката (данные Сбера). Самокат здесь — один из игроков.</p>
    <div class="callout">{lead_line or "Нет данных по Самокату в grocery MCC."}</div>
    <div class="grid2">
      <div>
        <h3>Доли сетей, % smkt_gmv</h3>
        <div id="chart-grocery" class="plot"></div>
      </div>
      <div>
        <h3>Таблица</h3>
        <div class="scroll">
          <table>
            <thead><tr><th>Ритейлер</th><th class="num">Smkt GMV</th><th class="num">Доля</th></tr></thead>
            <tbody>
              {''.join(
                f"<tr><td>{'<span class=badge-smkt>Самокат</span> ' if 'самокат' in str(r['merchant']).lower() else ''}{_esc(r['merchant'])}</td>"
                f"<td class='num'>{_fmt_money(r['smkt_gmv'])}</td>"
                f"<td class='num'>{_fmt_pct(r['share_smkt_gmv'])}</td></tr>"
                for _, r in groc.iterrows()
              )}
            </tbody>
          </table>
        </div>
        <h3 style="margin-top:14px">Offline high-income (Сбер)</h3>
        <div class="scroll" style="max-height:220px">
          <table>
            <thead><tr><th>Бакет</th><th>Сеть</th><th class="num">Оборот</th><th class="num">Клиенты</th></tr></thead>
            <tbody>{''.join(off_rows)}</tbody>
          </table>
        </div>
      </div>
    </div>
  </div>

  <div class="box" id="mp-aud">
    <h2>Аудитории Магнита и Пятёрочки (Сбер)</h2>
    <p class="lead">
      Отдельный срез: берём клиентов, которые ходят в Магнит или в Пятёрочку (онлайн/оффлайн — <b>по одному</b>),
      и смотрим, куда ещё они тратят картой Сбера. Это <b>не</b> аудитория Самоката.
      Нельзя складывать Магнит+Пятёрочка в одну цифру — клиенты и обороты пересекаются и задвоятся.
    </p>
    <div class="warnbox">Выбирайте один ритейлер в фильтре ниже. Сравнение — с кошельком аудитории Самоката в тех же MCC.</div>
    {"<div class='callout'>" + mp_cross_line + "</div>" if mp_cross_line else ""}
    <div class="grid2">
      <div>
        <h3>Размер аудитории — {_esc(city)}</h3>
        <div class="scroll" style="max-height:260px">
          <table>
            <thead>
              <tr>
                <th>Аудитория</th>
                <th class="num">Клиенты</th>
                <th class="num">Их GMV (все MCC)</th>
                <th class="num">Доля в тотале города</th>
              </tr>
            </thead>
            <tbody>{''.join(mp_kpi_rows) if mp_kpi_rows else "<tr><td colspan=4>Нет данных</td></tr>"}</tbody>
          </table>
        </div>
      </div>
      <div>
        <h3>Где у них Самокат в grocery</h3>
        <p class="lead" style="margin:0 0 8px">Доля = % grocery-трат <b>этой</b> аудитории, ушедших в Самокат.</p>
        <div class="scroll" style="max-height:260px">
          <table>
            <thead>
              <tr>
                <th>Аудитория</th>
                <th>Мерчант</th>
                <th class="num">GMV</th>
                <th class="num">Доля в их grocery</th>
              </tr>
            </thead>
            <tbody>{''.join(mp_groc_rows) if mp_groc_rows else "<tr><td colspan=4>Нет данных</td></tr>"}</tbody>
          </table>
        </div>
      </div>
    </div>
    <div class="flt" style="margin-top:14px">
      <div>
        <label>Какую аудиторию смотрим (один ритейлер)</label>
        <select id="mp-merch-select">
          {''.join(f'<option value="{_esc(m)}"{" selected" if m == default_merch else ""}>{_esc(m)}</option>' for m in mp_merch_opts)}
        </select>
      </div>
    </div>
    <div class="grid2">
      <div>
        <h3>MCC: эта аудитория vs аудитория Самоката</h3>
        <div id="chart-mp-mcc" class="plot"></div>
      </div>
      <div>
        <h3>Таблица сравнения</h3>
        <div class="scroll" style="max-height:360px">
          <table>
            <thead>
              <tr>
                <th>MCC</th>
                <th class="num">GMV аудитории</th>
                <th class="num">Их доля в кат.</th>
                <th class="num">GMV ауд. Самоката</th>
                <th class="num">Отношение</th>
              </tr>
            </thead>
            <tbody id="mp-compare-tbody"></tbody>
          </table>
        </div>
      </div>
    </div>
    <h3 style="margin-top:12px">Топ мерчантов у выбранной аудитории</h3>
    <p class="lead">Доля — % от smkt/retail_gmv этой аудитории внутри MCC.</p>
    <div class="scroll" style="max-height:280px">
      <table>
        <thead>
          <tr>
            <th>MCC</th>
            <th>Мерчант</th>
            <th class="num">GMV</th>
            <th class="num">Доля в MCC</th>
          </tr>
        </thead>
        <tbody id="mp-top-tbody"></tbody>
      </table>
    </div>
  </div>

  <div class="box" id="missions">
    <h2>Миссия Самоката → с какими ритейлерами пересекается</h2>
    <p class="lead">Выберите мегасценарий — справа увидите связанные MCC и доли конкурентов (и Самоката, если он в MCC).</p>
    <div class="flt">
      <div>
        <label>Мегасценарий</label>
        <select id="mega-select"></select>
      </div>
    </div>
    <div id="mission-card" class="card-grid"></div>
  </div>

  <div class="box" id="mcc">
    <h2>Доли ритейлеров внутри MCC</h2>
    <p class="lead">Независимо от миссий: как аудитория Самоката распределяет деньги между сетями в категории.</p>
    <div class="flt">
      <div>
        <label>Категория MCC</label>
        <select id="mcc-select">
          {''.join(f'<option value="{_esc(m)}">{_esc(m)}</option>' for m in mcc_list)}
        </select>
      </div>
    </div>
    <div class="grid2">
      <div id="chart-mcc" class="plot-sm"></div>
      <div id="mcc-bars" class="bars"></div>
    </div>
  </div>

  <div class="box">
    <h2>Мегамиссии из scenario-отчёта</h2>
    <p class="lead">Топ мегасценариев Самоката по GMV (тот же файл scenarios_gmv_report) — контекст объёмов миссий.</p>
    <div class="scroll" style="max-height:280px">
      <table>
        <thead><tr><th>Мегамиссия</th><th class="num">GMV</th><th class="num">Чеки</th></tr></thead>
        <tbody>{''.join(mega_rows)}</tbody>
      </table>
    </div>
  </div>

  <div class="box" id="etalon">
    <h2>NEW-эталон + спрос + рынок домена</h2>
    <p class="lead">
      Ширина = NEW из QNF (МАКС / 15 мин / сумма) по specialty MCC через кроссвок ml1.
      Рынок — топ сетей по smkt_gmv аудитории Самоката в том же MCC.
    </p>
    <div class="scroll">
      <table>
        <thead>
          <tr>
            <th>Домен</th>
            <th>Спрос</th>
            <th class="num">Smkt GMV</th>
            <th>Рынок (% в MCC)</th>
            <th class="num">NEW сумма</th>
            <th class="num">NEW МАКС</th>
            <th class="num">NEW 15</th>
          </tr>
        </thead>
        <tbody>{''.join(hyp_rows)}</tbody>
      </table>
    </div>
  </div>

  <div class="box">
    <h2>Ограничения</h2>
    <ul style="margin:0;padding-left:18px;color:var(--muted);font-size:14px">
      <li>Пересечение мегамиссия↔ритейлер — через MCC-мост, не через общих клиентов.</li>
      <li>Все доли ритейлеров / Самоката в таблицах — % от smkt_gmv аудитории Самоката <b>внутри MCC</b> (не от GMV миссии).</li>
      <li>NEW-эталон через кроссвок MCC↔ml1: сценарийные ml4 могут сидеть в разных ml1 — сумма unique ml1 по MCC приближённая.</li>
      <li>Grocery / маркетплейсы: NEW-эталон QNF не применяется (н/п).</li>
      <li>Магнит/Пятёрочка: смотреть по одной аудитории; суммировать нельзя.</li>
    </ul>
  </div>
</div>

<script>
  const cards = {json.dumps(cards, ensure_ascii=False)};
  const groceryChart = {json.dumps(grocery_chart, ensure_ascii=False)};
  const mccPayload = {json.dumps(mcc_payload, ensure_ascii=False)};
  const graphNodes = {json.dumps(graph_nodes, ensure_ascii=False)};
  const graphEdges = {json.dumps(graph_edges, ensure_ascii=False)};
  const mpCompare = {json.dumps(mp_compare_json, ensure_ascii=False)};
  const mpTop = {json.dumps(mp_top_json, ensure_ascii=False)};
  const lenses = {json.dumps(synth["lenses"], ensure_ascii=False)};

  function renderLens(key) {{
    const L = (lenses || []).find(x => x.key === key);
    const panel = document.getElementById('lens-panel');
    if (!panel || !L) return;
    let html = `<h3>${{L.headline}}</h3><div class="lens-meta">${{L.so_what || ''}}</div>`;
    if (L.missions && L.missions.length) {{
      html += `<div class="lens-meta">Связанные мегамиссии: <b>${{L.missions.join(', ')}}</b></div>`;
    }}
    html += `<div class="lens-links">`;
    (L.links || []).forEach(link => {{
      const role = ({{primary:'основной', secondary:'смежный', channel:'канал'}})[link.role] || link.role || '';
      const etMax = link.etalon_max;
      const et15 = link.etalon_15;
      const etSum = link.etalon_new;
      const isEmpty = (!etMax || etMax === '—' || etMax === 'н/п') && (!etSum || etSum === '—' || etSum === 'н/п');
      const etalonLine = isEmpty
        ? `NEW-эталон: <b>н/п</b> <span style="color:#5c6b7a">(grocery/канал или нет кроссвока MCC↔ml1)</span>`
        : `NEW-эталон МАКС / 15 мин / сумма: <b>${{etMax}}</b> / <b>${{et15}}</b> / <b>${{etSum}}</b>`;
      html += `<div class="lens-link">
        <b>${{link.mcc}} <span style="font-weight:400;color:#5c6b7a">· ${{role}}</span></b>
        Sber smkt: ${{link.sber}} · доля Самоката в MCC: ${{link.smkt_share}}<br/>
        ${{etalonLine}}<br/>
        Ритейлеры (% от smkt_gmv в MCC): ${{link.retailers}}
      </div>`;
    }});
    html += `</div>`;
    panel.innerHTML = html;
  }}
  const lensSelect = document.getElementById('lens-select');
  if (lensSelect) {{
    lensSelect.addEventListener('change', e => renderLens(e.target.value));
    if (lensSelect.value) renderLens(lensSelect.value);
  }}

  function pct(v) {{ return (v == null || isNaN(v)) ? '—' : Math.round(100*v) + '%'; }}
  function moneyB(v) {{ return (v == null || isNaN(v)) ? '—' : v.toFixed(2).replace('.', ',') + ' млрд'; }}
  function money(v) {{
    if (v == null || isNaN(v)) return '—';
    if (Math.abs(v) >= 1e9) return (v/1e9).toFixed(1).replace('.', ',') + ' млрд';
    if (Math.abs(v) >= 1e6) return Math.round(v/1e6) + ' млн';
    return Math.round(v).toLocaleString('ru-RU');
  }}
  function filtTable(inputId, tbodyId, countId) {{
    const q = (document.getElementById(inputId).value || '').toLowerCase().trim();
    const rows = document.querySelectorAll('#' + tbodyId + ' tr');
    let n = 0;
    rows.forEach(tr => {{
      const ok = !q || tr.innerText.toLowerCase().includes(q);
      tr.style.display = ok ? '' : 'none';
      if (ok) n++;
    }});
    const c = document.getElementById(countId);
    if (c) c.textContent = n;
  }}
  document.getElementById('unified-search')?.addEventListener('input', () => filtTable('unified-search','unified-tbody','unified-count'));
  document.getElementById('dict-search')?.addEventListener('input', () => filtTable('dict-search','dict-tbody','dict-count'));

  // ---- Mind-map (vis-network) ----
  const mindEl = document.getElementById('mindmap');
  let mindNet = null;
  const allNodes = new vis.DataSet(graphNodes);
  const allEdges = new vis.DataSet(graphEdges);
  const mindFocus = document.getElementById('mind-focus');
  const nodeById = Object.fromEntries(graphNodes.map(n => [n.id, n]));
  graphNodes.filter(n => n.kind === 'mission')
    .sort((a,b) => (b.volume||0) - (a.volume||0))
    .forEach(n => {{
      const o = document.createElement('option');
      o.value = n.id;
      o.textContent = (n.name || n.label) + ' · ' + (n.volume_fmt || '');
      mindFocus.appendChild(o);
    }});

  function showMindInfo(nodeId) {{
    const info = document.getElementById('mind-info');
    const n = nodeById[nodeId];
    if (!info || !n) return;
    let html = `<b>${{n.name || n.label}}</b>`;
    if (n.kind === 'mission') {{
      html += `${{n.volume_metric}}: <b>${{n.volume_fmt}}</b>`;
      if (n.n_scenarios != null || n.n_ml4 != null) {{
        html += `<div style="margin-top:6px;color:#5c6b7a">Leaf-сценариев: <b>${{n.n_scenarios ?? '—'}}</b> · категорий ml4: <b>${{n.n_ml4 ?? '—'}}</b></div>`;
      }}
      if (n.scenarios_list) {{
        html += `<div style="margin-top:6px;font-size:12px"><b>Сценарии:</b> ${{n.scenarios_list}}</div>`;
      }}
      if (n.ml4_preview) {{
        html += `<div style="margin-top:6px;font-size:12px"><b>Категории ml4:</b> ${{n.ml4_preview}}</div>`;
      }}
    }} else if (n.kind === 'domain') {{
      html += `${{n.volume_metric}}: <b>${{n.volume_fmt}}</b>`;
    }} else {{
      html += `${{n.volume_metric}}: ${{n.volume_fmt}}`;
    }}
    info.innerHTML = html;
    document.querySelectorAll('.mind-side tr').forEach(tr => {{
      tr.classList.toggle('active', tr.getAttribute('data-node') === nodeId);
    }});
  }}

  function buildMind(filterMissionId) {{
    let nodes = graphNodes;
    let edges = graphEdges;
    if (filterMissionId) {{
      const keep = new Set([filterMissionId]);
      edges = graphEdges.filter(e => {{
        if (e.from === filterMissionId) {{ keep.add(e.to); return true; }}
        return false;
      }});
      const domains = [...keep].filter(id => id.startsWith('d:'));
      const hop2 = graphEdges.filter(e => domains.includes(e.from));
      hop2.forEach(e => keep.add(e.to));
      edges = edges.concat(hop2);
      nodes = graphNodes.filter(n => keep.has(n.id));
    }}
    const data = {{ nodes: new vis.DataSet(nodes), edges: new vis.DataSet(edges) }};
    const options = {{
      nodes: {{
        shape: 'dot',
        scaling: {{ min: 14, max: 56, label: {{ enabled: true, min: 11, max: 16 }} }},
        font: {{ face: 'Segoe UI', size: 12, color: '#15202b', multi: true, align: 'center' }},
        borderWidth: 1,
        shadow: false,
      }},
      groups: {{
        mission: {{
          color: {{ background:'#0f6e56', border:'#0b3d2e', highlight: {{ background:'#1a8f6e', border:'#0b3d2e' }} }},
          font: {{ color:'#fff', multi: true, size: 12 }},
          shape:'box', margin: 10,
        }},
        domain: {{
          color: {{ background:'#dbeafe', border:'#175cd3' }},
          shape:'box', margin: 8,
          font: {{ multi: true, size: 12 }},
        }},
        retailer: {{ color: {{ background:'#e2e8f0', border:'#94a3b8' }} }},
        samokat: {{ color: {{ background:'#bbf7d0', border:'#027a48' }}, shape:'box', margin:6 }},
      }},
      edges: {{
        color: {{ color:'#cbd5e1', highlight:'#0f6e56' }},
        smooth: {{ type: 'continuous' }},
        arrows: {{ to: {{ enabled: true, scaleFactor: 0.6 }} }},
      }},
      physics: {{
        enabled: true,
        forceAtlas2Based: {{ gravitationalConstant: -45, springLength: 110, springConstant: 0.05 }},
        solver: 'forceAtlas2Based',
        stabilization: {{ iterations: 140 }},
      }},
      interaction: {{ hover: true, tooltipDelay: 60, navigationButtons: true, keyboard: true }},
    }};
    if (mindNet) mindNet.destroy();
    mindNet = new vis.Network(mindEl, data, options);
    mindNet.once('stabilizationIterationsDone', () => {{
      mindNet.setOptions({{ physics: false }});
    }});
    mindNet.on('click', params => {{
      if (params.nodes && params.nodes.length) showMindInfo(params.nodes[0]);
    }});
  }}
  if (mindEl && typeof vis !== 'undefined') {{
    buildMind('');
    mindFocus.addEventListener('change', e => {{
      buildMind(e.target.value);
      if (e.target.value) showMindInfo(e.target.value);
    }});
    document.getElementById('mind-reset').addEventListener('click', () => {{
      mindFocus.value = '';
      buildMind('');
      mindNet.fit({{ animation: true }});
      document.getElementById('mind-info').innerHTML = 'Клик по узлу или строке рейтинга — объём и связи.';
      document.querySelectorAll('.mind-side tr').forEach(tr => tr.classList.remove('active'));
    }});
    document.querySelectorAll('.mind-side tr[data-node]').forEach(tr => {{
      tr.addEventListener('click', () => {{
        const id = tr.getAttribute('data-node');
        showMindInfo(id);
        if (mindNet) {{
          mindNet.selectNodes([id]);
          mindNet.focus(id, {{ scale: 1.15, animation: true }});
        }}
      }});
    }});
  }}

  // Grocery chart
  const gColors = groceryChart.labels.map((l,i) => groceryChart.is_smkt[i] ? '#0f6e56' : '#94a3b8');
  Plotly.newPlot('chart-grocery', [{{
    type:'bar', orientation:'h',
    y: groceryChart.labels.slice().reverse(),
    x: groceryChart.shares.slice().reverse(),
    marker: {{ color: gColors.slice().reverse() }},
    hovertemplate: '%{{y}}<br>%{{x:.1f}}%<extra></extra>'
  }}], {{
    margin:{{l:120,r:16,t:8,b:40}},
    paper_bgcolor:'rgba(0,0,0,0)', plot_bgcolor:'rgba(0,0,0,0)',
    xaxis:{{ title:'% smkt_gmv в продуктовом MCC', gridcolor:'#eef2f6' }},
    yaxis:{{ automargin:true }},
    font:{{ family:'Segoe UI,sans-serif', size:12, color:'#15202b' }}
  }}, {{responsive:true, displayModeBar:false}});

  // Mission cards
  const megaSelect = document.getElementById('mega-select');
  cards.forEach((c,i) => {{
    const opt = document.createElement('option');
    opt.value = i;
    opt.textContent = c.mega + ' (' + moneyB(c.scenario_gmv/1e9) + ')';
    megaSelect.appendChild(opt);
  }});

  function renderMission(idx) {{
    const c = cards[idx];
    if (!c) return;
    let html = `<div class="scard"><div class="head">
      <div><div class="title">${{c.mega}}</div>
      <div class="sub">GMV миссии внутри Самоката: ${{moneyB(c.scenario_gmv/1e9)}} · доля среди мега: ${{pct(c.scenario_gmv_share)}}</div></div>
    </div>`;
    (c.mccs || []).forEach(block => {{
      html += `<div class="mcc-block"><div class="mcc-name">${{block.mcc}} · ${{block.role}}</div><div class="bars">`;
      (block.retailers || []).forEach(r => {{
        const share = (r.share || 0) * 100;
        const cls = r.is_samokat ? 'smkt' : '';
        const nameCls = r.is_samokat ? 'bar-name smkt' : 'bar-name';
        const label = r.is_samokat ? 'Самокат' : r.merchant;
        html += `<div class="bar-row">
          <div class="${{nameCls}}">${{label}}</div>
          <div class="bar-track"><div class="bar-fill ${{cls}}" style="width:${{Math.min(share,100)}}%"></div></div>
          <div class="num">${{Math.round(share)}}%</div>
        </div>`;
      }});
      html += `</div></div>`;
    }});
    html += `</div>`;
    document.getElementById('mission-card').innerHTML = html;
  }}
  megaSelect.addEventListener('change', e => renderMission(+e.target.value));
  if (cards.length) renderMission(0);

  // MCC explorer
  function renderMcc(mcc) {{
    const rows = mccPayload[mcc] || [];
    const labels = rows.map(r => r.merchant).reverse();
    const shares = rows.map(r => (r.share||0)*100).reverse();
    const colors = rows.map(r => r.is_samokat ? '#0f6e56' : '#94a3b8').reverse();
    Plotly.newPlot('chart-mcc', [{{
      type:'bar', orientation:'h', y:labels, x:shares,
      marker:{{ color:colors }},
      hovertemplate:'%{{y}}<br>%{{x:.1f}}%<extra></extra>'
    }}], {{
      margin:{{l:130,r:12,t:8,b:36}},
      paper_bgcolor:'rgba(0,0,0,0)', plot_bgcolor:'rgba(0,0,0,0)',
      xaxis:{{ title:'% в MCC', gridcolor:'#eef2f6' }},
      yaxis:{{ automargin:true }},
      font:{{ family:'Segoe UI,sans-serif', size:12, color:'#15202b' }}
    }}, {{responsive:true, displayModeBar:false}});

    document.getElementById('mcc-bars').innerHTML = rows.map(r => {{
      const share = (r.share||0)*100;
      const cls = r.is_samokat ? 'smkt' : '';
      const name = r.is_samokat ? 'Самокат' : r.merchant;
      return `<div class="bar-row">
        <div class="bar-name ${{cls}}">${{name}}</div>
        <div class="bar-track"><div class="bar-fill ${{cls}}" style="width:${{Math.min(share,100)}}%"></div></div>
        <div class="num">${{Math.round(share)}}%</div>
      </div>`;
    }}).join('');
  }}
  const mccSelect = document.getElementById('mcc-select');
  mccSelect.addEventListener('change', e => renderMcc(e.target.value));
  if (mccSelect.value) renderMcc(mccSelect.value);
  else if (mccSelect.options.length) {{
    // prefer grocery
    for (const o of mccSelect.options) {{
      if (o.value.includes('Продуктовые')) {{ mccSelect.value = o.value; break; }}
    }}
    renderMcc(mccSelect.value);
  }}

  // Magnit / Pyaterochka cohort explorer (one merch at a time — no sum)
  function renderMp(merch) {{
    const rows = (mpCompare || []).filter(r => r.retail_merch === merch)
      .sort((a,b) => (b.cohort_gmv||0) - (a.cohort_gmv||0));
    const topN = rows.slice(0, 10);
    const labels = topN.map(r => r.mcc_category).reverse();
    const cohort = topN.map(r => (r.cohort_gmv||0)/1e9).reverse();
    const samokat = topN.map(r => (r.samokat_aud_gmv||0)/1e9).reverse();
    const chartEl = document.getElementById('chart-mp-mcc');
    if (chartEl && typeof Plotly !== 'undefined') {{
      Plotly.newPlot('chart-mp-mcc', [
        {{ type:'bar', orientation:'h', y:labels, x:cohort, name:'Когорта', marker:{{color:'#334155'}},
          hovertemplate:'%{{y}}<br>когорта %{{x:.2f}} млрд<extra></extra>' }},
        {{ type:'bar', orientation:'h', y:labels, x:samokat, name:'Ауд. Самоката', marker:{{color:'#0f6e56'}},
          hovertemplate:'%{{y}}<br>СМКТ %{{x:.2f}} млрд<extra></extra>' }},
      ], {{
        barmode:'group',
        margin:{{l:150,r:12,t:8,b:36}},
        paper_bgcolor:'rgba(0,0,0,0)', plot_bgcolor:'rgba(0,0,0,0)',
        xaxis:{{ title:'млрд ₽', gridcolor:'#eef2f6' }},
        yaxis:{{ automargin:true }},
        legend:{{ orientation:'h', y:1.12 }},
        font:{{ family:'Segoe UI,sans-serif', size:12, color:'#15202b' }}
      }}, {{responsive:true, displayModeBar:false}});
    }}
    const tbody = document.getElementById('mp-compare-tbody');
    if (tbody) {{
      tbody.innerHTML = rows.map(r => `<tr>
        <td>${{r.mcc_category || ''}}</td>
        <td class="num">${{money(r.cohort_gmv)}}</td>
        <td class="num">${{pct(r.cohort_share_of_cat)}}</td>
        <td class="num">${{money(r.samokat_aud_gmv)}}</td>
        <td class="num">${{r.cohort_vs_samokat_aud_gmv == null || isNaN(r.cohort_vs_samokat_aud_gmv) ? '—' : r.cohort_vs_samokat_aud_gmv.toFixed(2).replace('.', ',') + '×'}}</td>
      </tr>`).join('');
    }}
    const tops = (mpTop || []).filter(r => r.retail_merch === merch)
      .sort((a,b) => (b.retail_gmv||0) - (a.retail_gmv||0));
    const topBody = document.getElementById('mp-top-tbody');
    if (topBody) {{
      topBody.innerHTML = tops.slice(0, 40).map(r => {{
        const isSm = String(r.merchant||'').toLowerCase().includes('самокат');
        const name = isSm ? `<span class="badge-smkt">Самокат</span> ${{r.merchant}}` : (r.merchant||'');
        return `<tr>
          <td>${{r.mcc_category || ''}}</td>
          <td>${{name}}</td>
          <td class="num">${{money(r.retail_gmv)}}</td>
          <td class="num">${{pct(r.share_in_mcc_cohort)}}</td>
        </tr>`;
      }}).join('');
    }}
  }}
  const mpSelect = document.getElementById('mp-merch-select');
  if (mpSelect) {{
    mpSelect.addEventListener('change', e => renderMp(e.target.value));
    if (mpSelect.value) renderMp(mpSelect.value);
  }}
</script>
</body>
</html>
"""
    out_html.parent.mkdir(parents=True, exist_ok=True)
    out_html.write_text(html, encoding="utf-8")

    # Auto-conclusions → separate markdown (not in HTML)
    concl_path = out_html.with_name("consumption_map_conclusions.md")
    concl_lines = [
        "# Авто-выводы (карта потребления)",
        "",
        f"Город: **{city}**" + (f" · сценарии: {period}" if period else ""),
        "",
        "## Как связаны данные",
        "",
        synth.get("join_logic", ""),
        "",
        "## Выводы",
        "",
    ]
    for c in synth.get("conclusions", []):
        concl_lines += [
            f"### {c.get('tag', '')}: {c.get('title', '')}",
            "",
            c.get("body", ""),
            "",
            f"**Что делать:** {c.get('action', '')}",
            "",
        ]
    concl_path.write_text("\n".join(concl_lines), encoding="utf-8")
    return out_html


if __name__ == "__main__":
    import argparse

    ap = argparse.ArgumentParser()
    ap.add_argument("--xlsx", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--city", default="Москва")
    ap.add_argument("--cards", type=Path, default=None)
    args = ap.parse_args()
    p = render_html(args.xlsx, args.out, city=args.city, cards_path=args.cards)
    print("wrote", p, p.stat().st_size)
