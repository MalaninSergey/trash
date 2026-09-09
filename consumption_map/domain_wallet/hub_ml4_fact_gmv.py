#!/usr/bin/env python3
"""Custom JH job: factual ML4 GMV + scenario×ML4 allocated GMV (no full report).

Steps
-----
1) CSV order lines → `_positions.parquet` (order_id, ml4, line_gmv), cut < 2026-05-31
2) ML4-only: sum(line_gmv) by ml4 → `ml4_gmv_fact.parquet/.csv`
3) scenario×ML4 by alloc rule (line_gmv / n_active_scenarios_containing_ml4)
   using aligned `_assignments.parquet` + ScenarioIndex catalog
   → `scenario_ml4_gmv_fact.parquet/.csv`

STEP3 is sharded by hash(order_id) % N to keep DuckDB temp under control.
ETA is written to status.json at start and after each step/shard.
"""

from __future__ import annotations

import json
import os
import sys
import time
import traceback
from datetime import datetime, timezone
from pathlib import Path

import duckdb
import pandas as pd

SCENARIES = Path("/home/jovyan/data/src/scenaries")
sys.path.insert(0, str(SCENARIES))

from category_tree import CategoryTreeMap  # noqa: E402
from scenario_assign import (  # noqa: E402
    CATALOG_SPACE_OLD,
    ScenarioIndex,
)

CSV_PATH = SCENARIES / "inputs" / "scenario_order_lines_202512_202605_all.csv"
ASSIGN_PATH = (
    SCENARIES
    / "outputs"
    / "6m_202512_202605"
    / "all_extend_da_rooms_aligned_20260530"
    / "_assignments.parquet"
)
SCENARIOS_XLSX = (
    SCENARIES
    / "inputs"
    / "Сценарии_описания_ml3_ml4_v9_extend_da_rooms_manual_added_20260819_161113.xlsx"
)
TREE_XLSX = SCENARIES / "inputs" / "дерево товаров смкт.xlsx"
OUT_DIR = SCENARIES / "outputs" / "6m_202512_202605" / "ml4_fact_aligned_20260530"
DATE_TO_EXCL = "2026-05-31"  # aligned cut: keep < 2026-05-31

# STEP3 memory / spill controls
N_SHARDS = int(os.environ.get("ML4_FACT_SHARDS", "24"))
DUCK_THREADS = int(os.environ.get("ML4_FACT_THREADS", "28"))
DUCK_MEM = os.environ.get("ML4_FACT_MEMORY", "400GB")
DUCK_MAX_TEMP = os.environ.get("ML4_FACT_MAX_TEMP", "900GB")
# Minimum size / row heuristics for resume skips
POS_MIN_BYTES = 10 * 10**9  # ~10 GB
POS_MIN_ROWS = 100_000_000
ML4_MIN_ROWS = 1000
CAT_MIN_PAIRS = 1000


def _utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _log(msg: str) -> None:
    line = f"[{datetime.now():%Y-%m-%d %H:%M:%S}] {msg}"
    print(line, flush=True)
    try:
        with (OUT_DIR / "job.log").open("a", encoding="utf-8") as fh:
            fh.write(line + "\n")
    except OSError:
        pass


def _write_status(payload: dict) -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    path = OUT_DIR / "status.json"
    cur = {}
    if path.exists():
        try:
            cur = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            cur = {}
    cur.update(payload)
    cur["updated_at"] = _utc()
    path.write_text(json.dumps(cur, ensure_ascii=False, indent=2), encoding="utf-8")


def _fmt_min(seconds: float) -> str:
    if seconds < 60:
        return f"{seconds:.0f}s"
    return f"{seconds / 60:.1f}m"


def estimate_eta(resume_positions: bool, resume_ml4: bool) -> dict:
    csv_gb = CSV_PATH.stat().st_size / 1e9 if CSV_PATH.exists() else 0.0
    assign_gb = ASSIGN_PATH.stat().st_size / 1e9 if ASSIGN_PATH.exists() else 0.0
    pos_min = 0.0 if resume_positions else max(12.0, csv_gb * 0.22)
    ml4_min = 0.0 if resume_ml4 else 2.0
    # Sharded join: ~2–4 min/shard historically for hash-partitioned joins on ~18GB pos
    per_shard = max(1.5, (assign_gb + 18.0) / N_SHARDS * 0.35 + 1.2)
    scen_min = per_shard * N_SHARDS + 3.0  # + merge
    total = pos_min + ml4_min + 1.0 + scen_min  # +1 catalog
    return {
        "csv_gb": round(csv_gb, 2),
        "assign_gb": round(assign_gb, 2),
        "n_shards": N_SHARDS,
        "eta_per_shard_min": round(per_shard, 2),
        "eta_positions_min": round(pos_min, 1),
        "eta_ml4_only_min": round(ml4_min, 1),
        "eta_scenario_ml4_min": round(scen_min, 1),
        "eta_total_min": round(total, 1),
        "eta_total_human": f"~{_fmt_min(total * 60)} (band {_fmt_min(total * 0.7 * 60)}–{_fmt_min(total * 1.5 * 60)})",
        "resume_positions": resume_positions,
        "resume_ml4": resume_ml4,
        "basis": f"sharded hash(order_id)%{N_SHARDS}; threads≤{DUCK_THREADS}; mem={DUCK_MEM}",
    }


def positions_look_valid(con: duckdb.DuckDBPyConnection, path: Path) -> dict | None:
    if not path.exists() or path.stat().st_size < POS_MIN_BYTES:
        return None
    try:
        n, gmv, n_ml4 = con.execute(
            f"""
            SELECT count(*), coalesce(sum(line_gmv),0), count(DISTINCT ml4_n)
            FROM read_parquet('{path.as_posix()}')
            """
        ).fetchone()
    except Exception as e:
        _log(f"positions probe failed: {e}")
        return None
    if int(n) < POS_MIN_ROWS:
        return None
    return {
        "path": str(path),
        "rows": int(n),
        "n_ml4": int(n_ml4),
        "line_gmv_sum": float(gmv),
        "size_gb": round(path.stat().st_size / 1e9, 3),
        "resumed": True,
        "elapsed_s": 0.0,
    }


def ml4_only_look_valid(path_pq: Path, path_csv: Path) -> dict | None:
    if not path_pq.exists() or not path_csv.exists():
        return None
    try:
        df = pd.read_parquet(path_pq)
    except Exception as e:
        _log(f"ml4_only probe failed: {e}")
        return None
    if len(df) < ML4_MIN_ROWS or "gmv" not in df.columns:
        return None
    return {
        "parquet": str(path_pq),
        "csv": str(path_csv),
        "rows": int(len(df)),
        "gmv_sum": float(df["gmv"].sum()),
        "resumed": True,
        "elapsed_s": 0.0,
    }


def catalog_look_valid(path: Path) -> dict | None:
    if not path.exists():
        return None
    try:
        df = pd.read_parquet(path)
    except Exception as e:
        _log(f"catalog probe failed: {e}")
        return None
    if len(df) < CAT_MIN_PAIRS or "mission" not in df.columns or "ml4_n" not in df.columns:
        return None
    return {
        "path": str(path),
        "n_scenarios": int(df["mission"].nunique()),
        "n_pairs": int(len(df)),
        "resumed": True,
        "elapsed_s": 0.0,
    }


def configure_duckdb(con: duckdb.DuckDBPyConnection) -> Path:
    spill = OUT_DIR / "runs" / "duckdb_spill"
    spill.mkdir(parents=True, exist_ok=True)
    threads = min(DUCK_THREADS, max(1, os.cpu_count() or 8))
    con.execute(f"PRAGMA threads={threads}")
    con.execute(f"PRAGMA memory_limit='{DUCK_MEM}'")
    con.execute(f"PRAGMA temp_directory='{spill.as_posix()}'")
    try:
        con.execute(f"PRAGMA max_temp_directory_size='{DUCK_MAX_TEMP}'")
    except Exception as e:
        _log(f"max_temp_directory_size not set ({e}); continuing")
    _log(
        f"duckdb threads={threads} memory_limit={DUCK_MEM} "
        f"temp_directory={spill} max_temp={DUCK_MAX_TEMP}"
    )
    return spill


def build_positions(con: duckdb.DuckDBPyConnection, out_path: Path) -> dict:
    _log(f"STEP1 positions from {CSV_PATH.name} cut < {DATE_TO_EXCL}")
    t0 = time.perf_counter()
    tmp = out_path.with_suffix(".tmp.parquet")
    if tmp.exists():
        tmp.unlink()
    con.execute(
        f"""
        COPY (
          SELECT
            order_id,
            trim(CAST(ml4 AS VARCHAR)) AS ml4,
            lower(trim(CAST(ml4 AS VARCHAR))) AS ml4_n,
            sum(CAST(line_gmv AS DOUBLE)) AS line_gmv
          FROM read_csv(
            ?,
            header=true,
            columns={{
              'customer_id': 'VARCHAR',
              'order_id': 'VARCHAR',
              'accepted_dttm': 'VARCHAR',
              'check_gmv': 'DOUBLE',
              'line_gmv': 'DOUBLE',
              'ml4': 'VARCHAR',
              'ml4_guid': 'VARCHAR'
            }},
            parallel=true,
            delim=','
          )
          WHERE accepted_dttm IS NOT NULL
            AND accepted_dttm < ?
            AND ml4 IS NOT NULL
            AND trim(CAST(ml4 AS VARCHAR)) <> ''
          GROUP BY 1, 2, 3
        ) TO '{tmp.as_posix()}' (FORMAT PARQUET, COMPRESSION ZSTD, ROW_GROUP_SIZE 1000000)
        """,
        [str(CSV_PATH), DATE_TO_EXCL],
    )
    if out_path.exists():
        out_path.unlink()
    tmp.rename(out_path)
    elapsed = time.perf_counter() - t0
    n, gmv, n_ml4 = con.execute(
        f"""
        SELECT count(*), coalesce(sum(line_gmv),0), count(DISTINCT ml4_n)
        FROM read_parquet('{out_path.as_posix()}')
        """
    ).fetchone()
    meta = {
        "path": str(out_path),
        "rows": int(n),
        "n_ml4": int(n_ml4),
        "line_gmv_sum": float(gmv),
        "size_gb": round(out_path.stat().st_size / 1e9, 3),
        "elapsed_s": round(elapsed, 1),
        "resumed": False,
    }
    _log(
        f"STEP1 done in {_fmt_min(elapsed)}: rows={n:,} ml4={n_ml4:,} "
        f"gmv={gmv:,.0f} size={meta['size_gb']}GB"
    )
    return meta


def build_ml4_only(con: duckdb.DuckDBPyConnection, positions: Path) -> dict:
    _log("STEP2 ML4-only aggregate")
    t0 = time.perf_counter()
    pq = OUT_DIR / "ml4_gmv_fact.parquet"
    csv = OUT_DIR / "ml4_gmv_fact.csv"
    con.execute(
        f"""
        COPY (
          SELECT
            any_value(ml4) AS ml4,
            ml4_n,
            sum(line_gmv) AS gmv,
            count(*) AS n_order_ml4_rows
          FROM read_parquet('{positions.as_posix()}')
          GROUP BY ml4_n
          ORDER BY gmv DESC
        ) TO '{pq.as_posix()}' (FORMAT PARQUET, COMPRESSION ZSTD)
        """
    )
    df = con.execute(f"SELECT * FROM read_parquet('{pq.as_posix()}')").df()
    df.to_csv(csv, index=False, encoding="utf-8-sig")
    elapsed = time.perf_counter() - t0
    meta = {
        "parquet": str(pq),
        "csv": str(csv),
        "rows": int(len(df)),
        "gmv_sum": float(df["gmv"].sum()),
        "elapsed_s": round(elapsed, 1),
        "resumed": False,
    }
    _log(f"STEP2 done in {_fmt_min(elapsed)}: ml4={meta['rows']:,} gmv={meta['gmv_sum']:,.0f}")
    return meta


def build_catalog_parquet(path: Path) -> dict:
    _log(f"Load ScenarioIndex from {SCENARIOS_XLSX.name}")
    t0 = time.perf_counter()
    tree = CategoryTreeMap.from_excel(TREE_XLSX) if TREE_XLSX.exists() else None
    index = ScenarioIndex.from_excel(
        SCENARIOS_XLSX,
        wide_threshold=30,
        category_tree=tree,
        catalog_space=CATALOG_SPACE_OLD,
        ready_food_mono=True,
    )
    rows = []
    for sc in index.scenarios:
        for cat_n in sc.cats:
            rows.append(
                {
                    "mission": sc.label,
                    "mega": sc.mega,
                    "sub": sc.sub,
                    "ml4_n": str(cat_n),
                }
            )
    df = pd.DataFrame(rows)
    df.to_parquet(path, index=False)
    elapsed = time.perf_counter() - t0
    meta = {
        "path": str(path),
        "n_scenarios": int(index.n_scenarios),
        "n_pairs": int(len(df)),
        "elapsed_s": round(elapsed, 1),
        "resumed": False,
    }
    _log(
        f"Catalog: scenarios={meta['n_scenarios']} mission×ml4={meta['n_pairs']:,} "
        f"in {_fmt_min(elapsed)}"
    )
    return meta


def _shard_partial_path(shard_dir: Path, shard: int) -> Path:
    return shard_dir / f"partial_{shard:03d}.parquet"


def build_scenario_ml4_sharded(
    con: duckdb.DuckDBPyConnection, positions: Path, catalog: Path
) -> dict:
    """Allocate GMV per mission×ml4 via hash(order_id) shards — no giant join."""
    _log(f"STEP3 scenario×ML4 sharded join N={N_SHARDS}")
    t0 = time.perf_counter()
    pq = OUT_DIR / "scenario_ml4_gmv_fact.parquet"
    csv = OUT_DIR / "scenario_ml4_gmv_fact.csv"
    shard_dir = OUT_DIR / "runs" / "scenario_ml4_shards"
    shard_dir.mkdir(parents=True, exist_ok=True)

    pos_s = positions.as_posix()
    cat_s = catalog.as_posix()
    assign_s = ASSIGN_PATH.as_posix()

    shard_times: list[float] = []
    completed = 0
    for shard in range(N_SHARDS):
        out_s = _shard_partial_path(shard_dir, shard)
        if out_s.exists() and out_s.stat().st_size > 100:
            # resume: keep existing partial
            completed += 1
            _log(f"STEP3 shard {shard}/{N_SHARDS} skip (exists {out_s.name})")
            _write_status(
                {
                    "stage": "scenario_ml4",
                    "shard": shard,
                    "shards_done": completed,
                    "shards_total": N_SHARDS,
                    "shard_status": "skipped_exists",
                }
            )
            continue

        _write_status(
            {
                "stage": "scenario_ml4",
                "shard": shard,
                "shards_done": completed,
                "shards_total": N_SHARDS,
                "shard_status": "running",
                "step_started_at": _utc(),
            }
        )
        _log(f"STEP3 shard {shard}/{N_SHARDS} start")
        ts = time.perf_counter()
        tmp = out_s.with_suffix(".tmp.parquet")
        if tmp.exists():
            tmp.unlink()
        # All rows for a given order_id land in one shard → window n_scen is correct.
        con.execute(
            f"""
            COPY (
              WITH pos AS (
                SELECT order_id, ml4, ml4_n, line_gmv
                FROM read_parquet('{pos_s}')
                WHERE (hash(order_id) % {N_SHARDS}) = {shard}
              ),
              asn AS (
                SELECT DISTINCT order_id, "Миссия" AS mission
                FROM read_parquet('{assign_s}')
                WHERE (hash(order_id) % {N_SHARDS}) = {shard}
              ),
              matched AS (
                SELECT
                  p.order_id,
                  p.ml4,
                  p.ml4_n,
                  p.line_gmv,
                  a.mission,
                  c.mega,
                  c.sub
                FROM pos p
                INNER JOIN asn a ON p.order_id = a.order_id
                INNER JOIN read_parquet('{cat_s}') c
                  ON c.mission = a.mission
                 AND c.ml4_n = p.ml4_n
              ),
              with_n AS (
                SELECT
                  *,
                  count(*) OVER (PARTITION BY order_id, ml4_n) AS n_scen
                FROM matched
              )
              SELECT
                mission,
                any_value(mega) AS mega,
                any_value(sub) AS sub,
                any_value(ml4) AS ml4,
                ml4_n,
                sum(line_gmv / n_scen) AS gmv,
                count(*) AS n_alloc_rows,
                count(DISTINCT order_id) AS n_orders
              FROM with_n
              GROUP BY mission, ml4_n
            ) TO '{tmp.as_posix()}' (FORMAT PARQUET, COMPRESSION ZSTD)
            """
        )
        if out_s.exists():
            out_s.unlink()
        tmp.rename(out_s)
        elapsed_s = time.perf_counter() - ts
        shard_times.append(elapsed_s)
        completed += 1
        n_rows = con.execute(
            f"SELECT count(*) FROM read_parquet('{out_s.as_posix()}')"
        ).fetchone()[0]
        avg = sum(shard_times) / len(shard_times)
        remain = (N_SHARDS - completed) * avg
        _log(
            f"STEP3 shard {shard}/{N_SHARDS} done in {_fmt_min(elapsed_s)}: "
            f"pairs={int(n_rows):,} ETA_remain~{_fmt_min(remain)}"
        )
        _write_status(
            {
                "stage": "scenario_ml4",
                "shard": shard,
                "shards_done": completed,
                "shards_total": N_SHARDS,
                "shard_status": "done",
                "last_shard_s": round(elapsed_s, 1),
                "last_shard_pairs": int(n_rows),
                "eta_remain_s": round(remain, 1),
                "eta_remain_human": _fmt_min(remain),
            }
        )

    _log("STEP3 merge shard partials")
    _write_status({"stage": "scenario_ml4_merge", "shards_done": N_SHARDS})
    glob_pat = (shard_dir / "partial_*.parquet").as_posix()
    # Exclude accidental *.tmp if any
    tmp_merge = pq.with_suffix(".tmp.parquet")
    if tmp_merge.exists():
        tmp_merge.unlink()
    con.execute(
        f"""
        COPY (
          SELECT
            mission,
            any_value(mega) AS mega,
            any_value(sub) AS sub,
            any_value(ml4) AS ml4,
            ml4_n,
            sum(gmv) AS gmv,
            sum(n_alloc_rows) AS n_alloc_rows,
            sum(n_orders) AS n_orders
          FROM read_parquet('{glob_pat}')
          GROUP BY mission, ml4_n
          ORDER BY gmv DESC
        ) TO '{tmp_merge.as_posix()}' (FORMAT PARQUET, COMPRESSION ZSTD, ROW_GROUP_SIZE 500000)
        """
    )
    if pq.exists():
        pq.unlink()
    tmp_merge.rename(pq)
    df = con.execute(f"SELECT * FROM read_parquet('{pq.as_posix()}')").df()
    df.to_csv(csv, index=False, encoding="utf-8-sig")
    elapsed = time.perf_counter() - t0
    meta = {
        "parquet": str(pq),
        "csv": str(csv),
        "rows": int(len(df)),
        "n_missions": int(df["mission"].nunique()) if len(df) else 0,
        "gmv_sum": float(df["gmv"].sum()) if len(df) else 0.0,
        "elapsed_s": round(elapsed, 1),
        "n_shards": N_SHARDS,
        "shard_dir": str(shard_dir),
        "mean_shard_s": round(sum(shard_times) / len(shard_times), 1) if shard_times else 0.0,
    }
    _log(
        f"STEP3 done in {_fmt_min(elapsed)}: pairs={meta['rows']:,} "
        f"missions={meta['n_missions']} gmv={meta['gmv_sum']:,.0f}"
    )
    return meta


def main() -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    # Append resume marker; do not wipe prior log evidence.
    with (OUT_DIR / "job.log").open("a", encoding="utf-8") as fh:
        fh.write(f"\n===== RESUME/START {_utc()} pid={os.getpid()} =====\n")

    con = duckdb.connect()
    spill = configure_duckdb(con)

    positions = OUT_DIR / "_positions.parquet"
    ml4_pq = OUT_DIR / "ml4_gmv_fact.parquet"
    ml4_csv = OUT_DIR / "ml4_gmv_fact.csv"
    catalog = OUT_DIR / "_mission_ml4_catalog.parquet"

    pos_meta_probe = positions_look_valid(con, positions)
    ml4_meta_probe = ml4_only_look_valid(ml4_pq, ml4_csv)
    resume_pos = pos_meta_probe is not None
    resume_ml4 = ml4_meta_probe is not None

    eta = estimate_eta(resume_pos, resume_ml4)
    started = time.perf_counter()
    _log("=" * 60)
    _log("ML4 fact GMV job START (sharded STEP3)")
    _log(
        f"ETA total {eta['eta_total_human']} | "
        f"positions~{eta['eta_positions_min']}m · "
        f"ml4-only~{eta['eta_ml4_only_min']}m · "
        f"scenario×ml4~{eta['eta_scenario_ml4_min']}m "
        f"({N_SHARDS} shards × ~{eta['eta_per_shard_min']}m)"
    )
    _log(
        f"resume positions={resume_pos} ml4_only={resume_ml4} | "
        f"CSV={CSV_PATH} ({eta['csv_gb']}GB) assign={ASSIGN_PATH} ({eta['assign_gb']}GB)"
    )
    _write_status(
        {
            "stage": "starting",
            "started_at": _utc(),
            "pid": os.getpid(),
            "eta": eta,
            "spill_dir": str(spill),
            "n_shards": N_SHARDS,
            "resume": {"positions": resume_pos, "ml4_only": resume_ml4},
            "paths": {
                "csv": str(CSV_PATH),
                "assignments": str(ASSIGN_PATH),
                "scenarios_xlsx": str(SCENARIOS_XLSX),
                "out_dir": str(OUT_DIR),
            },
            "error": None,
        }
    )

    for p, label in [
        (CSV_PATH, "CSV"),
        (ASSIGN_PATH, "assignments"),
        (SCENARIOS_XLSX, "scenarios xlsx"),
    ]:
        if not p.exists():
            _log(f"MISSING {label}: {p}")
            _write_status({"stage": "error", "error": f"missing {label}: {p}"})
            return 1

    try:
        if resume_pos:
            pos_meta = pos_meta_probe
            _log(
                f"STEP1 SKIP resume: rows={pos_meta['rows']:,} "
                f"size={pos_meta['size_gb']}GB gmv={pos_meta['line_gmv_sum']:,.0f}"
            )
            _write_status(
                {
                    "stage": "positions_done",
                    "positions": pos_meta,
                    "elapsed_s": round(time.perf_counter() - started, 1),
                }
            )
        else:
            _write_status({"stage": "positions", "step_started_at": _utc()})
            pos_meta = build_positions(con, positions)
            _write_status(
                {
                    "stage": "positions_done",
                    "positions": pos_meta,
                    "elapsed_s": round(time.perf_counter() - started, 1),
                }
            )

        if resume_ml4:
            ml4_meta = ml4_meta_probe
            _log(
                f"STEP2 SKIP resume: ml4={ml4_meta['rows']:,} gmv={ml4_meta['gmv_sum']:,.0f}"
            )
            _write_status(
                {
                    "stage": "ml4_only_done",
                    "ml4_only": ml4_meta,
                    "elapsed_s": round(time.perf_counter() - started, 1),
                }
            )
        else:
            _write_status({"stage": "ml4_only", "step_started_at": _utc()})
            ml4_meta = build_ml4_only(con, positions)
            _write_status(
                {
                    "stage": "ml4_only_done",
                    "ml4_only": ml4_meta,
                    "elapsed_s": round(time.perf_counter() - started, 1),
                }
            )

        cat_probe = catalog_look_valid(catalog)
        if cat_probe is not None:
            cat_meta = cat_probe
            _log(
                f"Catalog SKIP resume: scenarios={cat_meta['n_scenarios']} "
                f"pairs={cat_meta['n_pairs']:,}"
            )
            _write_status({"stage": "catalog_done", "catalog": cat_meta})
        else:
            _write_status({"stage": "catalog", "step_started_at": _utc()})
            cat_meta = build_catalog_parquet(catalog)
            _write_status({"stage": "catalog_done", "catalog": cat_meta})

        # Clear stale incomplete scenario output only (never positions / ml4 fact).
        for stale in (
            OUT_DIR / "scenario_ml4_gmv_fact.parquet",
            OUT_DIR / "scenario_ml4_gmv_fact.csv",
        ):
            if stale.exists():
                # Only remove if we are (re)building; keep if somehow complete mid-run N/A
                stale.unlink()
                _log(f"removed stale {stale.name}")

        _write_status(
            {
                "stage": "scenario_ml4",
                "step_started_at": _utc(),
                "shards_done": 0,
                "shards_total": N_SHARDS,
            }
        )
        scen_meta = build_scenario_ml4_sharded(con, positions, catalog)
        total_s = time.perf_counter() - started
        _write_status(
            {
                "stage": "done",
                "finished_at": _utc(),
                "elapsed_s": round(total_s, 1),
                "elapsed_human": _fmt_min(total_s),
                "scenario_ml4": scen_meta,
                "eta": eta,
                "error": None,
            }
        )
        _log(f"ALL DONE in {_fmt_min(total_s)}")
        return 0
    except Exception as e:
        _log(f"ERROR {type(e).__name__}: {e}")
        _log(traceback.format_exc())
        _write_status(
            {
                "stage": "error",
                "error": f"{type(e).__name__}: {e}",
                "elapsed_s": round(time.perf_counter() - started, 1),
            }
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
