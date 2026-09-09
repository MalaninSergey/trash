# Карта потребления — черновик отчёта

Склейка: **Сбер (внешний кошелёк)** × **NEW-эталоны QNF** × **мегасценарии Самоката** × **аудитории Магнита/Пятёрочки**.

## На JupyterHub (уже залито)

Путь: `/home/jovyan/data/consumption_map/`

- **Главный отчёт для менеджеров:** `outputs/consumption_map_report.html`
- Excel: `consumption_map_draft.xlsx` (slim) + `consumption_map_draft_full.xlsx` (HTML cache)
- Также: `consumption_map_draft_brief.md`
- notebooks: `consumption_map_runbook.ipynb`

Открыть HTML в Lab:  
https://jupyterhub-ml-p02.samokat.ru/user/smalanin/lab/tree/data/consumption_map/outputs

Повторный прогон с Mac:

```bash
python consumption_map/upload_and_run_hub.py
```

## Быстрый старт (локально или JupyterHub)

```bash
cd consumption_map   # или /home/jovyan/data/consumption_map
pip install pandas openpyxl   # если ещё нет
python build_consumption_map_draft.py
```

Результат:
- `outputs/consumption_map_draft.xlsx` — **slim для менеджеров** (≤3 листа: `Master`, `Справка`, `Mega_ml4`)
- `outputs/consumption_map_draft_full.xlsx` — полный кэш (все аналитические листы; из него строится HTML)
- `outputs/consumption_map_draft_brief.md`, `outputs/consumption_map_report.html`

### Пути к файлам

Скрипт ищет inputs в таком порядке:

1. `consumption_map/inputs/<файл>`
2. `~/Downloads/<файл>` (prefs / offline / эталоны)
3. `../outputs/all_extend_da_rooms/scenarios_gmv_report.xlsx` (сценарии)

На Hub: залить xlsx в `inputs/` и запускать оттуда.

```bash
python build_consumption_map_draft.py \
  --downloads /home/jovyan/data/consumption_map/inputs \
  --repo /home/jovyan/data \
  --out-dir /home/jovyan/data/consumption_map/outputs
```

## Листы xlsx

### `consumption_map_draft.xlsx` (менеджеры)

| Лист | Содержание |
|------|------------|
| Master | Одна таблица: миссия × MCC × GMV сценария × Сбер × demand × NEW-эталоны × ритейлеры × ml4/leaf preview × гипотезы |
| Справка | Короткие ключи: периоды, доли, primary/secondary, ml4 |
| Mega_ml4 | Компактный mega → сценарии / полный список ml4 |

### `consumption_map_draft_full.xlsx` (HTML / аналитика)

| Лист | Содержание |
|------|------------|
| 00_Method | периоды, пути, смысл эталонов |
| 00b_Dictionary / 00c_Unified_Master | словарь и единая таблица |
| 01_Sber_* | внешний wallet MCC × город × бакет |
| 02_Etalon_* | только NEW-эталоны (МАКС / 15 мин / сумма) по lvl1 и ml4 |
| 03_Crosswalk | MCC ↔ lvl1 |
| 04_Wallet_x_Etalon | стык спроса и ширины (+ gap_score) |
| 05_Hypotheses | гипотезы для менеджеров (Москва) |
| 06_Scenario_Megas | мегасценарии из GMV-отчёта |
| 07_* | grocery wallet + offline TOP |
| 08_* | маркетплейсы как канал |
| 09_* / 10_* | доли мерчантов, пересечения, Магнит/Пятёрочка |

## Эталоны

- **Эталон** = только колонки **NEW** из QNF 3.0 (МАКС / 15 мин / МАКС+15)
- Старый эталон без NEW в отчёт не входит
- Ширину сверяем с рынком домена (топ-ритейлеры Сбера), не только с оборотом Самоката

## Следующий шаг на Hub

Internal GMV по ml1 из Greenplum → колонка capture рядом с `external_smkt_gmv`.
Ноутбук: `notebooks/consumption_map_runbook.ipynb`.
