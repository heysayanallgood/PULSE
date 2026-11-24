"""
PULSE Spatiotemporal Travel-Time Model Trainer (scripts/train_travel_time_model.py)
Phase 2.4 — per-road-stretch model with hierarchical borrowing.

Training pipeline:
  1. Load segment-level travel times from data/processed/segment_times/ (Phase 2.3 output).
  2. Aggregate per segment × 15-min bucket × day_type: median, p10, p90, variance, counts.
  3. Add free-flow speed per segment (85th-percentile of night-time 22:00–05:00 traversals).
  4. Fill sparse cells by hierarchical borrowing:
       same segment, neighbouring bucket
       → same segment, same hour (any bucket)
       → same route, same bucket
       → network-wide bucket median
     Record source_level for every cell.
  5. Variance: uses VAR_SAMP of observed travel_time_s² (not speed × length).
  6. Write travel_time_model.parquet + travel_time.duckdb with lookup indexes.
  7. Print coverage report: % of cells with real data vs borrowed.

Hardcoded hourly speed priors are DELETED. All fallback comes from data at coarser levels.
"""
import sys
import time
import json
import duckdb
import numpy as np
import pandas as pd
from pathlib import Path
from datetime import datetime, timezone

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.core.config import settings

GTFS_DB_PATH     = settings.DATABASE_ROOT / "gtfs.duckdb"
SEG_TIMES_DIR    = settings.DATA_ROOT / "processed" / "segment_times"
MODEL_DIR        = settings.MODEL_ROOT
MODEL_PARQUET    = MODEL_DIR / "travel_time_model.parquet"
MODEL_DB         = settings.DATABASE_ROOT / "travel_time.duckdb"


def _build_seg_times_glob(train_days: list[int] | None,
                           exclude_days: list[int] | None) -> list[str]:
    """Return list of segment_times parquet file paths respecting the train/test split."""
    base = SEG_TIMES_DIR / "year=2026/month=10"
    all_day_dirs = sorted(base.glob("day=*")) if base.exists() else []

    def _day_num(d: Path) -> int:
        return int(d.name.split("=")[1])

    if train_days:
        selected = [d for d in all_day_dirs if _day_num(d) in train_days]
    elif exclude_days:
        selected = [d for d in all_day_dirs if _day_num(d) not in exclude_days]
    else:
        selected = all_day_dirs

    files = []
    for d in selected:
        files.extend(d.glob("*.parquet"))
    return [f.as_posix() for f in files]


def train_spatiotemporal_model(train_days: list[int] | None = None,
                                exclude_days: list[int] | None = None):
    """
    Build the per-road-stretch travel-time model from measured segment traversals.
    Falls back gracefully through coarser data levels when cells are sparse.
    """
    print("=== Training PULSE Per-Stretch Spatiotemporal Model (Phase 2.4) ===")
    MODEL_DIR.mkdir(parents=True, exist_ok=True)
    MODEL_DB.parent.mkdir(parents=True, exist_ok=True)
    cache_dir = settings.CACHE_ROOT / "duckdb"
    cache_dir.mkdir(parents=True, exist_ok=True)

    t0 = time.time()

    # ── 1. Discover segment-time files ───────────────────────────────────────
    seg_files = _build_seg_times_glob(train_days, exclude_days)
    if not seg_files:
        print("WARNING: No segment_times Parquet files found.")
        print("         Run scripts/measure_segments.py first, then re-train.")
        print("         Falling back to route-level GPS speed model.")
        _train_route_level_fallback(train_days, exclude_days, t0)
        return

    if train_days:
        print(f"Training on days: {sorted(train_days)}")
    elif exclude_days:
        print(f"Excluding days (test set): {sorted(exclude_days)}")
    print(f"Found {len(seg_files)} segment-time Parquet file(s).")

    # ── 2. Load segment-time observations into DuckDB in-memory ──────────────
    con = duckdb.connect()
    con.execute(f"SET temp_directory = '{cache_dir.as_posix()}';")
    con.execute(f"ATTACH '{GTFS_DB_PATH.as_posix()}' AS gtfs (READ_ONLY);")

    quoted = ", ".join(f"'{f}'" for f in seg_files)
    con.execute(f"""
        CREATE TEMP TABLE raw_obs AS
        SELECT
            segment_id,
            shape_id,
            route_id,
            time_bucket_15min,
            hour_ist,
            is_weekend,
            travel_time_s,
            segment_length_m,
            speed_mps
        FROM read_parquet([{quoted}])
        WHERE travel_time_s > 0
          AND speed_mps > 0
          AND speed_mps < 25.0;
    """)
    n_raw = con.execute("SELECT COUNT(*) FROM raw_obs;").fetchone()[0]
    print(f"Loaded {n_raw:,} raw segment traversal observations.")

    # ── 3. Level-1 aggregate: segment × bucket × is_weekend ──────────────────
    print("Aggregating per-segment × bucket × day-type …")
    con.execute("""
        CREATE TEMP TABLE seg_bucket AS
        SELECT
            segment_id,
            shape_id,
            route_id,
            time_bucket_15min,
            hour_ist,
            is_weekend,
            COUNT(*)                                       AS sample_count,
            COUNT(DISTINCT route_id)                       AS route_count,
            MEDIAN(travel_time_s)                          AS tt_median_s,
            QUANTILE_CONT(travel_time_s, 0.10)             AS tt_p10_s,
            QUANTILE_CONT(travel_time_s, 0.90)             AS tt_p90_s,
            VAR_SAMP(travel_time_s)                        AS tt_variance_s2,
            MEDIAN(speed_mps)                              AS speed_median_mps,
            AVG(segment_length_m)                          AS length_m
        FROM raw_obs
        GROUP BY segment_id, shape_id, route_id,
                 time_bucket_15min, hour_ist, is_weekend;
    """)

    # ── 4. Free-flow speed: 85th-pct of night traversals (22:00–05:00) ───────
    print("Computing free-flow speed per segment …")
    con.execute("""
        CREATE TEMP TABLE free_flow AS
        SELECT
            segment_id,
            QUANTILE_CONT(speed_mps, 0.85) AS free_flow_mps
        FROM raw_obs
        WHERE hour_ist >= 22 OR hour_ist <= 4
        GROUP BY segment_id
        HAVING COUNT(*) >= 3;
    """)

    # ── 5. Level-2 aggregate: segment × hour × is_weekend  (any bucket) ──────
    con.execute("""
        CREATE TEMP TABLE seg_hour AS
        SELECT
            segment_id, hour_ist, is_weekend,
            MEDIAN(travel_time_s) AS tt_median_s,
            VAR_SAMP(travel_time_s) AS tt_variance_s2,
            MEDIAN(speed_mps) AS speed_median_mps,
            COUNT(*) AS sample_count
        FROM raw_obs
        GROUP BY segment_id, hour_ist, is_weekend;
    """)

    # ── 6. Level-3 aggregate: route × bucket × is_weekend ────────────────────
    con.execute("""
        CREATE TEMP TABLE route_bucket AS
        SELECT
            route_id, time_bucket_15min, is_weekend,
            MEDIAN(speed_mps) AS speed_median_mps,
            VAR_SAMP(travel_time_s) AS tt_variance_s2,
            COUNT(*) AS sample_count
        FROM raw_obs
        GROUP BY route_id, time_bucket_15min, is_weekend;
    """)

    # ── 7. Level-4 aggregate: network-wide × bucket × is_weekend ─────────────
    con.execute("""
        CREATE TEMP TABLE network_bucket AS
        SELECT
            time_bucket_15min, is_weekend,
            MEDIAN(speed_mps) AS speed_median_mps,
            VAR_SAMP(travel_time_s) AS tt_variance_s2
        FROM raw_obs
        GROUP BY time_bucket_15min, is_weekend;
    """)

    # ── 8. Load segment skeleton from GTFS ───────────────────────────────────
    print("Loading segment skeleton from GTFS …")
    con.execute("""
        CREATE TEMP TABLE seg_base AS
        SELECT DISTINCT
            s.segment_id,
            s.shape_id,
            s.segment_sequence,
            s.length_m,
            t.route_id
        FROM gtfs.route_segments s
        JOIN (SELECT DISTINCT route_id, shape_id
              FROM gtfs.trips WHERE shape_id IS NOT NULL) t
          ON s.shape_id = t.shape_id;
    """)
    seg_count = con.execute("SELECT COUNT(*) FROM seg_base;").fetchone()[0]
    print(f"Segment skeleton: {seg_count:,} segment-route combinations.")

    # ── 9. Build the full model with hierarchical fill ────────────────────────
    print("Building full model table with hierarchical borrowing …")
    con.execute("""
        CREATE TEMP TABLE model_raw AS
        SELECT
            b.route_id,
            b.shape_id,
            b.segment_id,
            b.segment_sequence,
            b.length_m,
            h.hour              AS hour_ist,
            h.bucket            AS time_bucket_15min,
            dt.is_weekend,

            -- Observed travel time (Level-1 exact, then borrow)
            COALESCE(
                sb.tt_median_s,
                sh.tt_median_s,
                -- Level-3: derive from route-level speed × length
                CASE WHEN rb.speed_median_mps > 0
                     THEN b.length_m / rb.speed_median_mps END,
                -- Level-4: network
                CASE WHEN nb.speed_median_mps > 0
                     THEN b.length_m / nb.speed_median_mps END,
                -- Hard floor: 1 m/s = walking pace
                b.length_m
            ) AS travel_time_median_s,

            COALESCE(sb.tt_p10_s,
                     travel_time_median_s * 0.75) AS tt_p10_s,
            COALESCE(sb.tt_p90_s,
                     travel_time_median_s * 1.35) AS tt_p90_s,

            -- Speed
            COALESCE(
                sb.speed_median_mps,
                sh.speed_median_mps,
                rb.speed_median_mps,
                nb.speed_median_mps,
                1.0
            ) AS speed_median_mps,

            -- Variance on travel_time_s² (ADR 005 variance floor 4.0 s²)
            GREATEST(4.0,
                COALESCE(
                    sb.tt_variance_s2,
                    sh.tt_variance_s2,
                    rb.tt_variance_s2,
                    nb.tt_variance_s2,
                    -- floor fallback: (10% of median)²
                    POWER(COALESCE(sb.tt_median_s, b.length_m) * 0.10, 2)
                )
            ) AS travel_time_variance,

            COALESCE(sb.sample_count, 0) AS sample_count,

            -- Free-flow speed for congestion index
            COALESCE(ff.free_flow_mps,
                     nb.speed_median_mps * 1.5,
                     5.0) AS free_flow_mps,

            -- Confidence tier
            CASE
                WHEN sb.sample_count >= 20 THEN 'HIGH'
                WHEN sb.sample_count >= 5  THEN 'MEDIUM'
                WHEN sb.sample_count >= 1  THEN 'LOW'
                ELSE 'NONE'
            END AS confidence,

            -- Honest source_level provenance
            CASE
                WHEN sb.segment_id IS NOT NULL   THEN 'SEGMENT_BUCKET'
                WHEN sh.segment_id IS NOT NULL    THEN 'SEGMENT_HOUR'
                WHEN rb.route_id   IS NOT NULL    THEN 'ROUTE_BUCKET'
                WHEN nb.time_bucket_15min IS NOT NULL THEN 'NETWORK_BUCKET'
                ELSE 'HARD_FLOOR'
            END AS source_level

        FROM seg_base b
        CROSS JOIN (
            SELECT h AS hour, h * 4 + bk AS bucket
            FROM range(0, 24) t1(h)
            CROSS JOIN range(0, 4) t2(bk)
        ) h
        CROSS JOIN (SELECT 0 AS is_weekend UNION ALL SELECT 1 AS is_weekend) dt

        LEFT JOIN seg_bucket sb
               ON sb.segment_id      = b.segment_id
              AND sb.time_bucket_15min = h.bucket
              AND sb.is_weekend      = dt.is_weekend

        LEFT JOIN seg_hour sh
               ON sh.segment_id = b.segment_id
              AND sh.hour_ist   = h.hour
              AND sh.is_weekend = dt.is_weekend

        LEFT JOIN route_bucket rb
               ON rb.route_id          = b.route_id
              AND rb.time_bucket_15min  = h.bucket
              AND rb.is_weekend         = dt.is_weekend

        LEFT JOIN network_bucket nb
               ON nb.time_bucket_15min = h.bucket
              AND nb.is_weekend        = dt.is_weekend

        LEFT JOIN free_flow ff
               ON ff.segment_id = b.segment_id;
    """)

    # Compute congestion_index = free_flow_time / expected_time
    con.execute("""
        CREATE TABLE model_output AS
        SELECT *,
            ROUND(
                CASE WHEN speed_median_mps > 0
                     THEN free_flow_mps / speed_median_mps
                     ELSE 1.0 END,
                3) AS congestion_index,
            ROUND(travel_time_median_s, 2) AS travel_time_median_s_r,
            ROUND(speed_median_mps, 4)     AS speed_median_mps_r
        FROM model_raw;
    """)

    # ── 10. Coverage report ───────────────────────────────────────────────────
    total_cells = con.execute("SELECT COUNT(*) FROM model_output;").fetchone()[0]
    cov = con.execute("""
        SELECT source_level, COUNT(*) AS n
        FROM model_output
        GROUP BY source_level
        ORDER BY n DESC;
    """).fetchall()

    print(f"\n── Coverage Report ({total_cells:,} total cells) ──")
    for level, n in cov:
        pct = 100.0 * n / max(total_cells, 1)
        marker = "✓" if level == "SEGMENT_BUCKET" else " "
        print(f"  {marker} {level:<20} {n:>10,}  ({pct:5.1f}%)")
    real_cells = dict(cov).get("SEGMENT_BUCKET", 0)
    print(f"\n  Real data coverage: {100*real_cells/max(total_cells,1):.1f}% of cells")

    # ── 11. Export ────────────────────────────────────────────────────────────
    if MODEL_DB.exists():
        try:
            MODEL_DB.unlink()
        except Exception:
            pass

    print(f"\nExporting model Parquet → {MODEL_PARQUET} …")
    con.execute(f"COPY model_output TO '{MODEL_PARQUET.as_posix()}' (FORMAT PARQUET, COMPRESSION SNAPPY);")

    print(f"Writing indexed DuckDB → {MODEL_DB} …")
    con_out = duckdb.connect(str(MODEL_DB))
    con_out.execute(f"SET temp_directory = '{cache_dir.as_posix()}';")
    con_out.execute(f"CREATE TABLE travel_time_model AS SELECT * FROM read_parquet('{MODEL_PARQUET.as_posix()}');")
    con_out.execute("CREATE INDEX idx_tt_seg  ON travel_time_model(segment_id, time_bucket_15min, is_weekend);")
    con_out.execute("CREATE INDEX idx_tt_shape ON travel_time_model(shape_id, segment_sequence, time_bucket_15min, is_weekend);")
    con_out.execute("CREATE INDEX idx_tt_route ON travel_time_model(route_id, time_bucket_15min, is_weekend);")
    model_rows = con_out.execute("SELECT COUNT(*) FROM travel_time_model;").fetchone()[0]
    con_out.close()
    con.close()

    # Save coverage metadata next to model
    cov_path = MODEL_DIR / "coverage_report.json"
    with open(cov_path, "w") as f:
        json.dump({
            "generated_at":   datetime.now(timezone.utc).isoformat(),
            "total_cells":    total_cells,
            "real_data_pct":  round(100*real_cells/max(total_cells,1), 2),
            "by_level":       dict(cov),
        }, f, indent=2)

    elapsed = time.time() - t0
    print(f"\n=== Model built in {elapsed:.2f}s ===")
    print(f"Rows:  {model_rows:,}")
    print(f"Parquet: {MODEL_PARQUET.stat().st_size/(1024**2):.1f} MB")
    print(f"DuckDB:  {MODEL_DB.stat().st_size/(1024**2):.1f} MB")


def _train_route_level_fallback(train_days, exclude_days, t0):
    """
    Legacy route-level fallback used only when no segment_times data exists yet.
    Reads speed from processed historical GPS pings (Phase 1-era behaviour).
    No hardcoded speed tables — coarser borrowing chain: route→network.
    """
    print("  [Fallback] Training route-level model from GPS speed observations …")
    cache_dir = settings.CACHE_ROOT / "duckdb"
    cache_dir.mkdir(parents=True, exist_ok=True)

    base = settings.PROCESSED_DATA_ROOT / "historical/year=2026/month=10"
    all_dirs = sorted(base.glob("day=*")) if base.exists() else []

    def _day_num(d): return int(d.name.split("=")[1])
    if train_days:
        selected = [d for d in all_dirs if _day_num(d) in train_days]
    elif exclude_days:
        selected = [d for d in all_dirs if _day_num(d) not in exclude_days]
    else:
        selected = all_dirs

    files = [f for d in selected for f in d.glob("*.parquet")]
    if not files:
        print("  [Fallback] No historical GPS parquet found either — cannot train.")
        return

    quoted = ", ".join(f"'{f.as_posix()}'" for f in files)
    con = duckdb.connect()
    con.execute(f"SET temp_directory = '{cache_dir.as_posix()}';")
    con.execute(f"ATTACH '{GTFS_DB_PATH.as_posix()}' AS gtfs (READ_ONLY);")

    con.execute(f"""
        CREATE TEMP TABLE gps_obs AS
        SELECT route_id, time_bucket_15min, hour_ist, is_weekend, speed_mps, vehicle_id
        FROM read_parquet([{quoted}])
        WHERE speed_mps > 0 AND speed_mps < 25.0;
    """)

    # Route-level aggregation
    con.execute("""
        CREATE TEMP TABLE route_agg AS
        SELECT route_id, time_bucket_15min, is_weekend,
               MEDIAN(speed_mps) AS speed_median_mps,
               VAR_SAMP(speed_mps) AS speed_variance,
               COUNT(*) AS sample_count
        FROM gps_obs GROUP BY 1, 2, 3;
    """)

    # Network-level fallback
    con.execute("""
        CREATE TEMP TABLE net_agg AS
        SELECT time_bucket_15min, is_weekend,
               MEDIAN(speed_mps) AS speed_median_mps,
               VAR_SAMP(speed_mps) AS speed_variance
        FROM gps_obs GROUP BY 1, 2;
    """)

    con.execute("""
        CREATE TEMP TABLE seg_base AS
        SELECT DISTINCT s.segment_id, s.shape_id, s.segment_sequence,
                        s.length_m, t.route_id
        FROM gtfs.route_segments s
        JOIN (SELECT DISTINCT route_id, shape_id FROM gtfs.trips
              WHERE shape_id IS NOT NULL) t ON s.shape_id = t.shape_id;
    """)

    con.execute("""
        CREATE TABLE model_output AS
        SELECT
            b.route_id, b.shape_id, b.segment_id, b.segment_sequence, b.length_m,
            h.hour AS hour_ist, h.bucket AS time_bucket_15min, dt.is_weekend,
            COALESCE(ra.speed_median_mps, na.speed_median_mps, 1.0) AS speed_median_mps,
            ROUND(b.length_m / GREATEST(0.5, COALESCE(ra.speed_median_mps, na.speed_median_mps, 1.0)), 2)
                AS travel_time_median_s,
            NULL::DOUBLE AS tt_p10_s,
            NULL::DOUBLE AS tt_p90_s,
            GREATEST(4.0, COALESCE(ra.speed_variance, na.speed_variance, 4.0)
                         * (b.length_m / 100.0)) AS travel_time_variance,
            COALESCE(ra.sample_count, 0) AS sample_count,
            NULL::DOUBLE AS free_flow_mps,
            1.0 AS congestion_index,
            CASE WHEN ra.sample_count >= 5 THEN 'HISTORICAL' ELSE 'ESTIMATED_FALLBACK' END AS source_level,
            CASE WHEN ra.sample_count >= 20 THEN 'HIGH'
                 WHEN ra.sample_count >= 5  THEN 'MEDIUM'
                 ELSE 'LOW' END AS confidence
        FROM seg_base b
        CROSS JOIN (SELECT h AS hour, h*4+bk AS bucket
                    FROM range(0,24) t1(h) CROSS JOIN range(0,4) t2(bk)) h
        CROSS JOIN (SELECT 0 AS is_weekend UNION ALL SELECT 1 AS is_weekend) dt
        LEFT JOIN route_agg ra ON ra.route_id=b.route_id
              AND ra.time_bucket_15min=h.bucket AND ra.is_weekend=dt.is_weekend
        LEFT JOIN net_agg na ON na.time_bucket_15min=h.bucket AND na.is_weekend=dt.is_weekend;
    """)

    MODEL_DIR.mkdir(parents=True, exist_ok=True)
    if MODEL_DB.exists():
        try: MODEL_DB.unlink()
        except Exception: pass

    con.execute(f"COPY model_output TO '{MODEL_PARQUET.as_posix()}' (FORMAT PARQUET, COMPRESSION SNAPPY);")
    con_out = duckdb.connect(str(MODEL_DB))
    con_out.execute(f"SET temp_directory = '{cache_dir.as_posix()}';")
    con_out.execute(f"CREATE TABLE travel_time_model AS SELECT * FROM read_parquet('{MODEL_PARQUET.as_posix()}');")
    con_out.execute("CREATE INDEX idx_tt_seg ON travel_time_model(segment_id, time_bucket_15min, is_weekend);")
    con_out.execute("CREATE INDEX idx_tt_shape ON travel_time_model(shape_id, segment_sequence, time_bucket_15min, is_weekend);")
    rows = con_out.execute("SELECT COUNT(*) FROM travel_time_model;").fetchone()[0]
    con_out.close(); con.close()
    print(f"  [Fallback] Route-level model written: {rows:,} rows in {time.time()-t0:.1f}s")


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="PULSE Spatiotemporal Travel-Time Model Trainer")
    parser.add_argument(
        "--train-days", type=int, nargs="+", metavar="DAY",
        help="Day-of-month numbers to include in training (e.g. 1 2 ... 24). "
             "Mutually exclusive with --exclude-days."
    )
    parser.add_argument(
        "--exclude-days", type=int, nargs="+", metavar="DAY",
        help="Day-of-month numbers to EXCLUDE from training (use as test holdout). "
             "Mutually exclusive with --train-days."
    )
    args = parser.parse_args()

    if args.train_days and args.exclude_days:
        parser.error("--train-days and --exclude-days are mutually exclusive.")

    train_spatiotemporal_model(
        train_days=args.train_days,
        exclude_days=args.exclude_days,
    )
