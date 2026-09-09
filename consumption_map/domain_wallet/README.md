# Domain wallet report

Новый отчёт (не `budget_gap`): кошелёк Сбера по MCC × implied-кошелёк Самоката из **листовых** сценариев.

**Правило:** один сценарий (`Миссия` в Scenario_Aggregates) → один домен MCC.

## Запуск

```bash
python consumption_map/domain_wallet/build_domain_wallet_report.py
```

## Входы

- prefs (gmv по MCC)
- `scenarios_gmv_report.xlsx` → `Scenario_Aggregates`
- `inputs/scenario_leaf_mcc_bridge.csv`
- etalons NEW + `mcc_l1_crosswalk.csv`

## Эталон NEW

Эксклюзивные SKU из `scenarios_with_etalon.xlsx` (каждая lvl4 только в одном сценарии; пересечение целиком у сценария с наибольшим GMV):

- **на сценарий** — колонки 15 мин / МАКС / сумма
- **на домен** — сумма эталонов его сценариев (без двойного счёта категорий)
- домены без сценариев (например обувь, если категории ушли в одежду) — 0 SKU

## Магнит / Пятёрочка

Отдельные когорты оффлайн (не суммировать):

- в **карточке домена** — доля MCC в кошельке Магнита / Пятёрочки
- блок **grocery** — размер когорты vs `smkt_gmv` аудитории Самоката + доля Самоката внутри grocery когорты

## Outputs

- `outputs/domain_wallet_report.html` — bar (+ bar без продуктовых), pie, specialty, города, карточка, Магнит/5ка grocery
- `outputs/domain_wallet_report_core.html` — то же **без** Магнит/Пятёрочка
- `outputs/domain_wallet_report_no_marketplace.html` — без домена Маркетплейсы (gift-сценарии перенесены; без Магнит/5ка)
- `inputs/scenario_leaf_mcc_bridge_no_marketplace.csv` — bridge для этого варианта

```bash
python consumption_map/domain_wallet/build_domain_wallet_report.py --no-marketplace
```

- `outputs/domain_wallet_report.xlsx` — листы:
  - **Сравнение** — доли, gap, ₽/клиент Сбер/Самокат (период и /мес), отклонение, кол-во сценариев, эталон 15/МАКС/сумма и доля
  - **Сценарии_доли** — все сценарии с долями кошелька
  - **Магнит_5ка** / **Grocery_MP**
  - **Specialty** / Master / Справка / Coverage / Leaf_bridge
  - **Сравнение_SPB** / **Сравнение_KRD**
- `outputs/domain_wallet_payload.json`

### ₽/клиент

- **Сбер:** `smkt_gmv` домена / `smkt_customers` города (`Без МСС` — аудитория Самоката в Сбере); месяц = ÷12 (prefs за 12 мес по ТЗ).
- **Самокат:** GMV листовых сценариев / `national_users` из `_run_meta.json` (`count(distinct customer_id)` по `_orders_slim.parquet` за окно сценариев); месяц = ÷6. Не использовать городской `smkt_customers` из prefs — числитель сценариев национальный.
