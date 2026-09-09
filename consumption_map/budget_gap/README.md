# Budget gap report

Полный кошелёк клиента Сбера (`gmv`) × кошелёк аудитории Самоката (`smkt_gmv`) ×
структура сценариев по **мега** и **ml1** × NEW-эталон + аудит миссий без эталона.

## Запуск

```bash
python consumption_map/budget_gap/build_budget_gap_report.py
```

## Outputs

- `outputs/budget_gap_report.html` — интерактивный отчёт (Chart.js)
- `outputs/budget_gap_report.xlsx` — Master, Справка, Samokat_ml1, Etalon_audit
- `outputs/budget_gap_payload.json` — sidecar для HTML

## Gap

**Gap** = доля MCC в полном кошельке Сбера (`gmv / ∑`) − доля MCC после аллокации mega GMV через soft-bridge.

Дополнительно в Master: `gap_pp_vs_smkt_aud` — то же vs аудитории Самоката.

## Soft-bridge notes (электроника)

`inputs/scenario_mcc_bridge.csv` аллоцирует mega GMV → MCC. До правки в «Бытовая техника и электроника»
попадал только **Домашний офис** (~0.0006% кошелька сценариев) → Samokat-implied ≈ 0% при Sber ~4.7%.

Связки по описаниям комнат (техника/гаджеты в non-food), без трогания grocery-primary:

| mega | роль в электронике | вес | зачем |
|------|-------------------|-----|-------|
| Гостиная | primary | 0.5 | «Домашний кинотеатр» ≈93% GMV меги (ТВ, саундбар) |
| Кухня | secondary | 0.3 | крупная техника в «Обустройство кухни с нуля» |
| Ванная | secondary | 0.15 | стиралка / водонагреватель в обустройстве |
| Домашний офис | primary | 0.5 | мониторы / ПК / периферия |

Не линкуем: **Стирка** (химия), **Авто**, grocery-меги. Веса внутри mega нормализуются в билдере.

## Grocery etalon (NEW food lvl1)

`Продуктовые магазины` больше не «н/п» по эталону: NEW (МАКС+15) суммируется по food lvl1 из `etalons_qnf.xlsx`.

- Источник lvl1: маркеры `bg_new=FOODZOO` / `bg∈{FMCG DRY, FMCG FRESH}`, минус lvl1 уже в specialty-кроссвоке (зоо, химия, гигиена и т.п.), минус явный non-food шум.
- Явный список также в `inputs/mcc_l1_crosswalk.csv` (bridge_type=`grocery`); если lvl1 в кроссвоке заполнены — они приоритетнее авто-дискавери.
- Канал (`Маркетплейсы`) по-прежнему н/п.
