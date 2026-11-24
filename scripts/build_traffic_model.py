"""
PULSE traffic-model pipeline (scripts/build_traffic_model.py)

One DuckDB-based pipeline that replaces the pandas prototype in
process_day.py / match_to_shapes.py / measure_segments.py, which could not
hold a full day (~29M rows) in memory. It implements plan.md phases 1–2:

  snap      Read one raw SQLite day read-only, clean it and snap every GPS
            ping onto its route's GTFS road stretches (route_segments):
              - GPS fix time (`timestamp`, epoch) is used, not poll time
              - duplicate (vehicle_id, timestamp) pings are dropped
              - stale fixes (logged > 120 s after the fix) are dropped
              - pings > 80 m from their route's shape are dropped
              - each (vehicle, trip) is pinned to one shape (direction),
                chosen by heading agreement, so jitter cannot flip direction
            Output: data/processed/snapped/day=DD.parquet
                    data/processed/cells/day=DD.parquet  (per-stretch stats)

  train     Pool per-stretch cells over the TRAINING days only and build the
            in-memory model arrays used by the API:
              travel time = segment length × space-mean pace (Σdt / Σdistance)
            Sparse cells borrow from coarser *measured* levels, never from
            typed-in speed tables:
              L1 segment × 15-min bucket × day type          (HISTORICAL)
              L2 segment × hour × day type                   (SEGMENT_HOUR)
              L3 segment all-day pace × network time-of-day  (SEGMENT_PROFILE)
              L4 route × bucket × day type                   (ROUTE_LEVEL)
              L5 network × bucket × day type                 (NETWORK_LEVEL)
            Output: data/models/traffic_model/*.npy + meta.json

  evaluate  Build ground truth from HELD-OUT days (default 25–31): real bus
            runs between two points 2–15 km apart along a shape, and score
            the model, a static-timetable baseline and a flat-speed baseline.
            Output: data/validation/results.json, docs/VALIDATION_REPORT.md

Usage:
  python scripts/build_traffic_model.py snap --days 1-31
  python scripts/build_traffic_model.py train --train-days 1-24
  python scripts/build_traffic_model.py evaluate --test-days 25-31
  python scripts/build_traffic_model.py all
"""
from __future__ import annotations

import argparse
import json
import math
import sys
import time
from datetime import date, datetime, timezone
from pathlib import Path

import duckdb
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.core.config import settings  # noqa: E402
from app.models.traffic_model import (  # noqa: E402
    SOURCE_LEVELS, TrafficModel, MODEL_DIR_NAME,
)

YEAR, MONTH = 2026, 10
IST_OFFSET_S = 19800
LAT0, LON0 = 28.6, 77.2
M_PER_DEG_LAT = 110574.0
M_PER_DEG_LON = 111320.0 * math.cos(math.radians(LAT0))
CELL_M = 400.0
SNAP_MAX_M = 80.0
MAX_FIX_AGE_S = 120
MAX_PAIR_DT_S = 120
MAX_SPEED_MPS = 25.0
LONG_STOP_S = 180          # stationary runs longer than this are layovers/breakdowns
MIN_MEASURED_COVER = 0.5   # a cell needs Σdistance ≥ 0.5 × stretch length
MIN_MEASURED_VEH = 2       # … from at least two distinct buses

# Oct 2026 Delhi public holidays: Gandhi Jayanti (Fri 2 Oct) and Dussehra
# (Tue 20 Oct 2026). Holidays are modelled with the weekend profile.
HOLIDAYS = {date(2026, 10, 2), date(2026, 10, 20)}

RAW_DIR = settings.HISTORICAL_SQLITE_DIR
GTFS_DB = settings.DATABASE_ROOT / "gtfs.duckdb"
SNAP_DIR = settings.PROCESSED_DATA_ROOT / "snapped"
CELL_DIR = settings.PROCESSED_DATA_ROOT / "cells"
MODEL_DIR = settings.MODEL_ROOT / MODEL_DIR_NAME
VALID_DIR = settings.DATA_ROOT / "validation"
REPORT = ROOT / "docs" / "VALIDATION_REPORT.md"


def parse_days(spec: str) -> list[int]:
    out: list[int] = []
    for part in spec.split(","):
        if "-" in part:
            a, b = part.split("-")
            out.extend(range(int(a), int(b) + 1))
        elif part:
            out.append(int(part))
    return sorted(set(out))


def is_weekend_like(d: date) -> int:
    return 1 if (d.weekday() >= 5 or d in HOLIDAYS) else 0


def connect(mem_gb: int = 9) -> duckdb.DuckDBPyConnection:
    con = duckdb.connect()
    tmp = (settings.CACHE_ROOT / "duckdb").resolve()
    tmp.mkdir(parents=True, exist_ok=True)
    con.execute(f"SET temp_directory='{tmp.as_posix()}'")
    con.execute(f"SET memory_limit='{mem_gb}GB'")
    con.execute("SET preserve_insertion_order=false")
    con.execute("INSTALL sqlite; LOAD sqlite;")
    con.execute(f"ATTACH '{GTFS_DB.as_posix()}' AS g (READ_ONLY)")
    return con


def prepare_segment_grid(con) -> None:
    """Segments in a local metric frame, indexed by (route, 400 m cell)."""
    con.execute(f"""
        CREATE OR REPLACE TEMP TABLE segs AS
        SELECT r.segment_id, r.shape_id, r.segment_sequence AS seq, rs.route_id,
               r.start_dist_m, r.length_m,
               (r.start_lon - {LON0}) * {M_PER_DEG_LON} AS x0,
               (r.start_lat - {LAT0}) * {M_PER_DEG_LAT} AS y0,
               (r.end_lon   - {LON0}) * {M_PER_DEG_LON} AS x1,
               (r.end_lat   - {LAT0}) * {M_PER_DEG_LAT} AS y1
        FROM g.route_segments r
        JOIN (SELECT DISTINCT route_id, shape_id FROM g.trips) rs USING (shape_id)
    """)
    con.execute(f"""
        CREATE OR REPLACE TEMP TABLE seg_cells AS
        SELECT s.*, cx, cy
        FROM segs s,
             unnest(range(CAST(floor((least(x0,x1) - 100) / {CELL_M}) AS BIGINT),
                          CAST(floor((greatest(x0,x1) + 100) / {CELL_M}) AS BIGINT) + 1)) AS t1(cx),
             unnest(range(CAST(floor((least(y0,y1) - 100) / {CELL_M}) AS BIGINT),
                          CAST(floor((greatest(y0,y1) + 100) / {CELL_M}) AS BIGINT) + 1)) AS t2(cy)
    """)


# ─────────────────────────────────────────────────────────────────────────────
# SNAP
# ─────────────────────────────────────────────────────────────────────────────
def snap_day(con, day: int) -> dict | None:
    d = date(YEAR, MONTH, day)
    db = RAW_DIR / f"bus_movements_{YEAR}_{MONTH:02d}_{day:02d}.db"
    if not db.exists():
        print(f"[snap] {d}: raw file missing, skipped")
        return None
    SNAP_DIR.mkdir(parents=True, exist_ok=True)
    CELL_DIR.mkdir(parents=True, exist_ok=True)
    snap_out = SNAP_DIR / f"day={day:02d}.parquet"
    cell_out = CELL_DIR / f"day={day:02d}.parquet"
    t0 = time.time()
    wk = is_weekend_like(d)

    con.execute(f"ATTACH '{db.as_posix()}' AS raw (TYPE sqlite, READ_ONLY)")
    try:
        # 1. Clean pings (fix time, dedupe, stale fixes, Delhi box).
        con.execute(f"""
            CREATE OR REPLACE TEMP TABLE pings AS
            WITH src AS (
              SELECT vehicle_id, trip_id,
                     CAST(CAST(route_id AS BIGINT) AS VARCHAR) AS route_id,
                     TRY_CAST(timestamp AS BIGINT) AS ts,
                     TRY_CAST(lat AS DOUBLE) AS lat, TRY_CAST(lng AS DOUBLE) AS lon,
                     epoch(date) + COALESCE(TRY_CAST(split_part(time, ':', 1) AS INT), 0) * 3600
                       + COALESCE(TRY_CAST(split_part(time, ':', 2) AS INT), 0) * 60
                       + COALESCE(TRY_CAST(split_part(time, ':', 3) AS INT), 0) - {IST_OFFSET_S} AS poll_ts
              FROM raw.vehicle_feed
              WHERE route_id IS NOT NULL AND trip_id IS NOT NULL
            ), firstseen AS (
              SELECT vehicle_id, ts, arg_min(trip_id, poll_ts) AS trip_id, arg_min(route_id, poll_ts) AS route_id,
                     arg_min(lat, poll_ts) AS lat, arg_min(lon, poll_ts) AS lon, min(poll_ts) AS poll_ts
              FROM src
              WHERE ts IS NOT NULL AND lat BETWEEN 28.30 AND 28.95 AND lon BETWEEN 76.80 AND 77.55
              GROUP BY vehicle_id, ts
            )
            SELECT vehicle_id, trip_id, route_id, ts, lat, lon,
                   (lon - {LON0}) * {M_PER_DEG_LON} AS x,
                   (lat - {LAT0}) * {M_PER_DEG_LAT} AS y
            FROM firstseen
            WHERE poll_ts - ts <= {MAX_FIX_AGE_S} AND poll_ts - ts >= -60
        """)
        n_raw = con.execute("SELECT count(*) FROM raw.vehicle_feed").fetchone()[0]
    finally:
        con.execute("DETACH raw")
    n_clean = con.execute("SELECT count(*) FROM pings").fetchone()[0]

    # 2. Heading from the previous ping of the same vehicle+trip (if it moved ≥15 m).
    con.execute("""
        CREATE OR REPLACE TEMP TABLE pings_h AS
        SELECT *, CASE WHEN mv >= 15 THEN hx / mv END AS ux, CASE WHEN mv >= 15 THEN hy / mv END AS uy
        FROM (
          SELECT *, x - lag(x) OVER w AS hx, y - lag(y) OVER w AS hy,
                 sqrt(power(x - lag(x) OVER w, 2) + power(y - lag(y) OVER w, 2)) AS mv
          FROM pings WINDOW w AS (PARTITION BY vehicle_id, trip_id ORDER BY ts)
        )
    """)

    # 3. All candidate stretches of the ping's route within SNAP_MAX_M.
    con.execute(f"""
        CREATE OR REPLACE TEMP TABLE cand AS
        WITH j AS (
          SELECT p.vehicle_id, p.trip_id, p.route_id, p.ts, p.ux, p.uy,
                 s.segment_id, s.shape_id, s.seq, s.start_dist_m, s.length_m,
                 s.x1 - s.x0 AS dx, s.y1 - s.y0 AS dy,
                 greatest(0.0, least(1.0, ((p.x - s.x0) * (s.x1 - s.x0) + (p.y - s.y0) * (s.y1 - s.y0))
                     / greatest(power(s.x1 - s.x0, 2) + power(s.y1 - s.y0, 2), 1.0))) AS t,
                 p.x, p.y, s.x0, s.y0
          FROM pings_h p
          JOIN seg_cells s
            ON s.route_id = p.route_id
           AND s.cx = CAST(floor(p.x / {CELL_M}) AS BIGINT)
           AND s.cy = CAST(floor(p.y / {CELL_M}) AS BIGINT)
        )
        SELECT vehicle_id, trip_id, route_id, ts, segment_id, shape_id, seq,
               start_dist_m + t * length_m AS shape_dist,
               sqrt(power(x - (x0 + t * dx), 2) + power(y - (y0 + t * dy), 2)) AS snap_m,
               CASE WHEN ux IS NULL THEN NULL
                    ELSE (ux * dx + uy * dy) / greatest(sqrt(dx * dx + dy * dy), 1.0) END AS cosh
        FROM j
        WHERE sqrt(power(x - (x0 + t * dx), 2) + power(y - (y0 + t * dy), 2)) <= {SNAP_MAX_M}
    """)

    # 4. One shape (direction) per vehicle+trip: most heading-consistent votes.
    con.execute("""
        CREATE OR REPLACE TEMP TABLE trip_shape AS
        SELECT vehicle_id, trip_id, arg_max(shape_id, votes) AS shape_id
        FROM (
          SELECT vehicle_id, trip_id, shape_id, count(*) AS votes
          FROM (
            SELECT vehicle_id, trip_id, ts, arg_min(shape_id, snap_m) AS shape_id
            FROM cand WHERE cosh > 0.5 GROUP BY ALL
          ) GROUP BY ALL
        ) GROUP BY ALL
    """)

    # 5. Final snap restricted to the trip's shape; keep monotone progress.
    con.execute(f"""
        CREATE OR REPLACE TEMP TABLE snapped AS
        SELECT c.vehicle_id, c.trip_id, c.route_id, c.shape_id, c.ts,
               arg_min(c.segment_id, c.snap_m) AS segment_id,
               arg_min(c.seq, c.snap_m) AS seq,
               arg_min(c.shape_dist, c.snap_m) AS shape_dist,
               min(c.snap_m) AS snap_m
        FROM cand c JOIN trip_shape ts USING (vehicle_id, trip_id, shape_id)
        GROUP BY c.vehicle_id, c.trip_id, c.route_id, c.shape_id, c.ts
    """)
    n_snapped = con.execute("SELECT count(*) FROM snapped").fetchone()[0]
    con.execute(f"COPY (SELECT * FROM snapped ORDER BY shape_id, vehicle_id, ts) TO '{snap_out.as_posix()}' (FORMAT parquet, COMPRESSION zstd)")

    # 6. Consecutive pairs → per-stretch cells. Long stationary runs (layover,
    #    breakdown) are removed; ordinary stops and signals stay in, because a
    #    passenger's travel time includes them.
    con.execute(f"""
        CREATE OR REPLACE TEMP TABLE pairs AS
        WITH p AS (
          SELECT *, ts - lag(ts) OVER w AS dt, shape_dist - lag(shape_dist) OVER w AS dd,
                 lag(seq) OVER w AS prev_seq
          FROM snapped WINDOW w AS (PARTITION BY vehicle_id, trip_id ORDER BY ts)
        ), v AS (
          SELECT *, CASE WHEN dd BETWEEN -30 AND 0 THEN 0.0 ELSE dd END AS ddc
          FROM p
          WHERE dt BETWEEN 1 AND {MAX_PAIR_DT_S} AND dd >= -30 AND dd <= {MAX_SPEED_MPS} * dt + 30
            AND seq - prev_seq BETWEEN 0 AND 3
        ), runs AS (
          SELECT *, sum(CASE WHEN ddc >= 3 THEN 1 ELSE 0 END) OVER (PARTITION BY vehicle_id, trip_id ORDER BY ts) AS grp
          FROM v
        ), runlen AS (
          SELECT *, sum(CASE WHEN ddc < 3 THEN dt ELSE 0 END) OVER (PARTITION BY vehicle_id, trip_id, grp) AS stop_run_s
          FROM runs
        )
        SELECT vehicle_id, segment_id, route_id, ts, dt, ddc AS dd,
               CAST(floor(((ts - dt / 2.0 + {IST_OFFSET_S}) % 86400) / 900.0) AS INTEGER) AS bucket
        FROM runlen
        WHERE NOT (ddc < 3 AND stop_run_s > {LONG_STOP_S})
    """)
    con.execute(f"""
        COPY (
          SELECT segment_id, any_value(route_id) AS route_id, bucket, {wk} AS is_weekend, {day} AS day,
                 sum(dt)::DOUBLE AS sum_dt, sum(dd)::DOUBLE AS sum_dd, count(*) AS n_pairs,
                 count(DISTINCT vehicle_id) AS n_vehicles
          FROM pairs GROUP BY segment_id, bucket
        ) TO '{cell_out.as_posix()}' (FORMAT parquet, COMPRESSION zstd)
    """)
    stats = {
        "day": day, "date": d.isoformat(), "is_weekend_like": wk,
        "raw_rows": int(n_raw), "clean_unique_fresh_pings": int(n_clean), "snapped_pings": int(n_snapped),
        "snap_rate": round(n_snapped / max(n_clean, 1), 4),
        "seconds": round(time.time() - t0, 1),
    }
    for t in ("pings", "pings_h", "cand", "trip_shape", "snapped", "pairs"):
        con.execute(f"DROP TABLE IF EXISTS {t}")
    print(f"[snap] {d}: raw {n_raw:,} -> clean {n_clean:,} -> snapped {n_snapped:,} "
          f"({stats['snap_rate']:.1%}) in {stats['seconds']}s")
    return stats


# ─────────────────────────────────────────────────────────────────────────────
# TRAIN
# ─────────────────────────────────────────────────────────────────────────────
def train(con, train_days: list[int]) -> dict:
    files = [CELL_DIR / f"day={d:02d}.parquet" for d in train_days]
    files = [f for f in files if f.exists()]
    if not files:
        raise SystemExit("No cell files for the training days — run `snap` first.")
    flist = "[" + ",".join(f"'{f.as_posix()}'" for f in files) + "]"
    t0 = time.time()

    seg_rows = con.execute("""
        SELECT r.segment_id, r.shape_id, rs.route_id, r.segment_sequence, r.length_m,
               r.start_lat, r.start_lon, r.end_lat, r.end_lon, r.start_dist_m, r.end_dist_m
        FROM g.route_segments r
        JOIN (SELECT DISTINCT route_id, shape_id FROM g.trips) rs USING (shape_id)
        ORDER BY r.shape_id, r.segment_sequence
    """).fetchnumpy()
    seg_ids = seg_rows["segment_id"].astype(str)
    n = len(seg_ids)
    idx = {s: i for i, s in enumerate(seg_ids)}
    length = seg_rows["length_m"].astype(np.float64)
    route_codes, route_idx = np.unique(seg_rows["route_id"].astype(str), return_inverse=True)

    cells = con.execute(f"""
        SELECT segment_id, bucket, is_weekend,
               sum(sum_dt) AS sdt, sum(sum_dd) AS sdd, sum(n_vehicles) AS nveh, count(*) AS ndays,
               var_samp(CASE WHEN sum_dd > 0 THEN sum_dt / sum_dd END) AS pace_var_days
        FROM read_parquet({flist})
        GROUP BY ALL
    """).fetchnumpy()
    ci = np.array([idx.get(s, -1) for s in cells["segment_id"].astype(str)])
    ok = ci >= 0
    b = cells["bucket"].astype(int)[ok]
    w = cells["is_weekend"].astype(int)[ok]
    ci = ci[ok]
    sdt = cells["sdt"][ok].astype(np.float64)
    sdd = cells["sdd"][ok].astype(np.float64)
    nveh = cells["nveh"][ok].astype(np.float64)
    pvar = np.nan_to_num(cells["pace_var_days"][ok].astype(np.float64), nan=np.nan)

    SDT = np.zeros((n, 96, 2)); SDD = np.zeros((n, 96, 2)); NV = np.zeros((n, 96, 2))
    PV = np.full((n, 96, 2), np.nan)
    np.add.at(SDT, (ci, b, w), sdt)
    np.add.at(SDD, (ci, b, w), sdd)
    np.add.at(NV, (ci, b, w), nveh)
    PV[ci, b, w] = pvar

    L = length[:, None, None]
    measured = (SDD >= MIN_MEASURED_COVER * L) & (NV >= MIN_MEASURED_VEH)
    with np.errstate(divide="ignore", invalid="ignore"):
        pace = np.where(SDD > 0, SDT / SDD, np.nan)  # s per metre
    pace = np.clip(pace, 1 / MAX_SPEED_MPS, 1 / 0.8)  # 0.8–25 m/s band

    out_pace = np.full((n, 96, 2), np.nan)
    source = np.zeros((n, 96, 2), dtype=np.uint8)
    out_pace[measured] = pace[measured]
    source[measured] = SOURCE_LEVELS.index("HISTORICAL")

    def pooled(sdt_, sdd_, axis):
        s1, s2 = sdt_.sum(axis=axis), sdd_.sum(axis=axis)
        with np.errstate(divide="ignore", invalid="ignore"):
            return np.where(s2 > 0, s1 / s2, np.nan), s2

    # L2: same segment, same hour (4 buckets), same day type.
    sdt_h = SDT.reshape(n, 24, 4, 2); sdd_h = SDD.reshape(n, 24, 4, 2)
    p_h, d_h = pooled(sdt_h, sdd_h, 2)                      # (n,24,2)
    ok_h = d_h >= MIN_MEASURED_COVER * length[:, None, None]
    p_h_b = np.repeat(p_h, 4, axis=1); ok_h_b = np.repeat(ok_h, 4, axis=1)
    fill = np.isnan(out_pace) & ok_h_b
    out_pace[fill] = np.clip(p_h_b[fill], 1 / MAX_SPEED_MPS, 1 / 0.8)
    source[fill] = SOURCE_LEVELS.index("SEGMENT_HOUR")

    # Network time-of-day profile from measured cells (pace relative to the all-day mean).
    net_sdt = SDT.sum(axis=0); net_sdd = SDD.sum(axis=0)       # (96,2)
    with np.errstate(divide="ignore", invalid="ignore"):
        net_pace = np.where(net_sdd > 0, net_sdt / net_sdd, np.nan)
    for wi in (0, 1):  # fill empty network buckets from the other day type, then neighbours
        other = net_pace[:, 1 - wi]
        net_pace[:, wi] = np.where(np.isnan(net_pace[:, wi]), other, net_pace[:, wi])
    for _ in range(96):
        if not np.isnan(net_pace).any():
            break
        rolled = (np.roll(net_pace, 1, axis=0) + np.roll(net_pace, -1, axis=0)) / 2
        net_pace = np.where(np.isnan(net_pace), rolled, net_pace)
    net_all = net_sdt.sum() / max(net_sdd.sum(), 1.0)
    tod_factor = net_pace / net_all                                  # (96,2)

    # L3: segment all-day pace × network time-of-day factor.
    p_all, d_all = pooled(SDT.reshape(n, -1), SDD.reshape(n, -1), 1)
    ok_all = d_all >= 2 * length
    fill = np.isnan(out_pace) & ok_all[:, None, None]
    est = p_all[:, None, None] * tod_factor[None, :, :]
    out_pace[fill] = np.clip(np.broadcast_to(est, out_pace.shape)[fill], 1 / MAX_SPEED_MPS, 1 / 0.8)
    source[fill] = SOURCE_LEVELS.index("SEGMENT_PROFILE")

    # L4: route × bucket × day type.
    R = len(route_codes)
    r_sdt = np.zeros((R, 96, 2)); r_sdd = np.zeros((R, 96, 2))
    np.add.at(r_sdt, route_idx, SDT); np.add.at(r_sdd, route_idx, SDD)
    with np.errstate(divide="ignore", invalid="ignore"):
        r_pace = np.where(r_sdd > 2000, r_sdt / np.maximum(r_sdd, 1), np.nan)
    est = r_pace[route_idx]
    fill = np.isnan(out_pace) & ~np.isnan(est)
    out_pace[fill] = np.clip(est[fill], 1 / MAX_SPEED_MPS, 1 / 0.8)
    source[fill] = SOURCE_LEVELS.index("ROUTE_LEVEL")

    # L5: network × bucket × day type.
    fill = np.isnan(out_pace)
    est = np.broadcast_to(net_pace[None, :, :], out_pace.shape)
    out_pace[fill] = est[fill]
    source[fill] = SOURCE_LEVELS.index("NETWORK_LEVEL")

    tt = (out_pace * L).astype(np.float32)

    # Variance of stretch travel time (s²): day-to-day spread of measured pace,
    # otherwise the network's median coefficient of variation for that level.
    with np.errstate(invalid="ignore"):
        cv_measured = np.sqrt(PV) / np.where(pace > 0, pace, np.nan)
    cv_med = float(np.nanmedian(cv_measured[measured & ~np.isnan(cv_measured)])) if np.any(measured & ~np.isnan(cv_measured)) else 0.25
    cv_med = float(np.clip(cv_med, 0.1, 0.6))
    cv = np.where(measured & ~np.isnan(cv_measured), np.clip(cv_measured, 0.05, 1.0), cv_med * np.where(source <= 1, 1.0, 1.35))
    var = ((cv * tt) ** 2).astype(np.float32)

    samples = np.minimum(NV, 65535).astype(np.uint16)

    # Free-flow: fastest typical pace among the segment's own buckets (10th pct),
    # so congestion index = expected time ÷ free-flow time ≥ 1.
    ff_pace = np.nanpercentile(out_pace.reshape(n, -1), 10, axis=1)
    ff_tt = (ff_pace * length).astype(np.float32)

    MODEL_DIR.mkdir(parents=True, exist_ok=True)
    np.save(MODEL_DIR / "segment_ids.npy", seg_ids)
    np.save(MODEL_DIR / "tt.npy", tt)
    np.save(MODEL_DIR / "var.npy", var)
    np.save(MODEL_DIR / "samples.npy", samples)
    np.save(MODEL_DIR / "source.npy", source)
    np.save(MODEL_DIR / "ff_tt.npy", ff_tt)
    np.save(MODEL_DIR / "length.npy", length.astype(np.float32))
    np.save(MODEL_DIR / "net_pace.npy", net_pace.astype(np.float32))
    np.save(MODEL_DIR / "shape_ids.npy", seg_rows["shape_id"].astype(str))
    np.save(MODEL_DIR / "route_ids.npy", seg_rows["route_id"].astype(str))
    np.save(MODEL_DIR / "start_dist.npy", seg_rows["start_dist_m"].astype(np.float64))
    np.save(MODEL_DIR / "end_dist.npy", seg_rows["end_dist_m"].astype(np.float64))
    np.save(MODEL_DIR / "geom.npy", np.stack([seg_rows["start_lat"], seg_rows["start_lon"],
                                               seg_rows["end_lat"], seg_rows["end_lon"]], axis=1).astype(np.float32))
    np.save(MODEL_DIR / "gps_distance_m.npy", SDD.sum(axis=(1, 2)).astype(np.float32))

    counts = {lvl: int((source == i).sum()) for i, lvl in enumerate(SOURCE_LEVELS)}
    total = int(source.size)
    seg_with_data = int((SDD.sum(axis=(1, 2)) > 0).sum())
    meta = {
        "built_at": datetime.now(timezone.utc).isoformat(),
        "train_days": train_days,
        "train_files": [f.name for f in files],
        "segments": n,
        "segments_with_any_gps": seg_with_data,
        "cells_total": total,
        "cells_by_source": counts,
        "cells_measured_pct": round(100 * counts["HISTORICAL"] / total, 2),
        "network_cv_used_for_unmeasured": round(cv_med, 3),
        "network_speed_kmh_by_hour_weekday": [round(3.6 / float(np.mean(net_pace[h*4:(h+1)*4, 0])), 1) for h in range(24)],
        "network_speed_kmh_by_hour_weekend": [round(3.6 / float(np.mean(net_pace[h*4:(h+1)*4, 1])), 1) for h in range(24)],
        "estimator": "space-mean pace (Σdt/Σdistance along shape) per stretch × 15-min bucket × day type",
        "holidays_as_weekend": sorted(d.isoformat() for d in HOLIDAYS),
    }
    (MODEL_DIR / "meta.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
    print(f"[train] {n:,} stretches; measured cells {meta['cells_measured_pct']}% ; "
          f"by source {counts} ; {time.time() - t0:.1f}s")
    return meta


# ─────────────────────────────────────────────────────────────────────────────
# EVALUATE
# ─────────────────────────────────────────────────────────────────────────────
def build_ground_truth(con, test_days: list[int], per_day: int = 1500, seed: int = 7) -> "np.ndarray":
    files = [SNAP_DIR / f"day={d:02d}.parquet" for d in test_days]
    files = [f for f in files if f.exists()]
    if not files:
        raise SystemExit("No snapped files for test days — run `snap` first.")
    rows = []
    for f in files:
        day = int(f.stem.split("=")[1])
        wk = is_weekend_like(date(YEAR, MONTH, day))
        # For each vehicle-trip run, pick a start ping and the first ping 2–15 km
        # further along the shape. Runs with gaps > 5 min are rejected.
        q = f"""
            WITH s AS (
              SELECT vehicle_id, trip_id, route_id, shape_id, ts, shape_dist,
                     ts - lag(ts) OVER w AS gap
              FROM read_parquet('{f.as_posix()}')
              WINDOW w AS (PARTITION BY vehicle_id, trip_id ORDER BY ts)
            ), r AS (
              SELECT *, sum(CASE WHEN gap > 300 THEN 1 ELSE 0 END) OVER (PARTITION BY vehicle_id, trip_id ORDER BY ts) AS run
              FROM s
            ), starts AS (
              SELECT * FROM (
                SELECT *, row_number() OVER (PARTITION BY vehicle_id, trip_id, run ORDER BY hash(ts + {seed})) AS rk
                FROM r
              ) WHERE rk = 1
            ), pairs AS (
              SELECT a.vehicle_id, a.trip_id, a.route_id, a.shape_id,
                     a.ts AS t0, a.shape_dist AS d0,
                     min_by(b.ts, b.ts) AS t1, min_by(b.shape_dist, b.ts) AS d1
              FROM starts a JOIN r b
                ON b.vehicle_id = a.vehicle_id AND b.trip_id = a.trip_id AND b.run = a.run
               AND b.ts > a.ts AND b.shape_dist - a.shape_dist >= 2000 + (hash(a.ts) % 8000)
               AND b.shape_dist - a.shape_dist <= 15000
              GROUP BY ALL
            )
            SELECT * FROM pairs
            WHERE t1 - t0 BETWEEN 120 AND 7200 AND (d1 - d0) / (t1 - t0) BETWEEN 0.8 AND 20
            ORDER BY hash(t0 + {seed}) LIMIT {per_day}
        """
        part = con.execute(q).fetchnumpy()
        for i in range(len(part["t0"])):
            rows.append((day, wk, str(part["vehicle_id"][i]), str(part["trip_id"][i]), str(part["route_id"][i]),
                         str(part["shape_id"][i]), int(part["t0"][i]), float(part["d0"][i]),
                         int(part["t1"][i]), float(part["d1"][i])))
    dt = np.dtype([("day", "i4"), ("is_weekend", "i4"), ("vehicle_id", "U32"), ("trip_id", "U48"),
                   ("route_id", "U16"), ("shape_id", "U32"), ("t0", "i8"), ("d0", "f8"),
                   ("t1", "i8"), ("d1", "f8")])
    return np.array(rows, dtype=dt)


def timetable_durations(con, gt) -> np.ndarray:
    """Static GTFS timetable baseline: scheduled time between the two shape
    distances, using the GTFS trip with the same route and HH_MM start as the
    feed trip id (route_HH_MM_xxxx). NaN where no schedule matches."""
    con.execute("CREATE OR REPLACE TEMP TABLE gt_keys (i INTEGER, trip_id VARCHAR, route_id VARCHAR, shape_id VARCHAR, d0 DOUBLE, d1 DOUBLE)")
    con.executemany("INSERT INTO gt_keys VALUES (?,?,?,?,?,?)",
                    [(i, str(r["trip_id"]), str(r["route_id"]), str(r["shape_id"]), float(r["d0"]), float(r["d1"])) for i, r in enumerate(gt)])
    # Stop positions along each shape (project stops onto their shape's stretches).
    con.execute(f"""
        CREATE OR REPLACE TEMP TABLE sched AS
        WITH k AS (
          SELECT i, shape_id, d0, d1,
                 split_part(trip_id, '_', 1) AS r, split_part(trip_id, '_', 2) AS hh, split_part(trip_id, '_', 3) AS mm
          FROM gt_keys
        ), m AS (
          SELECT k.i, k.shape_id, k.d0, k.d1, min(t.trip_id) AS gtfs_trip
          FROM k JOIN g.trips t
            ON t.route_id = k.r AND t.shape_id = k.shape_id
           AND t.trip_id LIKE k.r || '\\_%\\_' || k.hh || '\\_' || k.mm ESCAPE '\\'
          GROUP BY ALL
        ), st AS (
          SELECT m.i, m.d0, m.d1, s.stop_sequence,
                 CAST(split_part(s.arrival_time, ':', 1) AS INT) * 3600 + CAST(split_part(s.arrival_time, ':', 2) AS INT) * 60
                   + CAST(split_part(s.arrival_time, ':', 3) AS INT) AS arr_s,
                 (sp.stop_lon - {LON0}) * {M_PER_DEG_LON} AS x, (sp.stop_lat - {LAT0}) * {M_PER_DEG_LAT} AS y,
                 m.shape_id
          FROM m JOIN g.stop_times s ON s.trip_id = m.gtfs_trip JOIN g.stops sp USING (stop_id)
        ), proj AS (
          SELECT st.i, st.d0, st.d1, st.stop_sequence, st.arr_s,
                 arg_min(sg.start_dist_m + greatest(0.0, least(1.0, ((st.x - sg.x0) * (sg.x1 - sg.x0) + (st.y - sg.y0) * (sg.y1 - sg.y0))
                        / greatest(power(sg.x1 - sg.x0, 2) + power(sg.y1 - sg.y0, 2), 1.0))) * sg.length_m,
                        power(st.x - (sg.x0 + sg.x1) / 2, 2) + power(st.y - (sg.y0 + sg.y1) / 2, 2)) AS sd
          FROM st JOIN segs sg ON sg.shape_id = st.shape_id
          GROUP BY ALL
        )
        SELECT i, d0, d1, list(sd ORDER BY stop_sequence) AS sds, list(arr_s ORDER BY stop_sequence) AS arrs
        FROM proj GROUP BY ALL
    """)
    out = np.full(len(gt), np.nan)
    for i, d0, d1, sds, arrs in con.execute("SELECT * FROM sched").fetchall():
        sds = np.maximum.accumulate(np.array(sds, dtype=float))
        arrs = np.array(arrs, dtype=float)
        if len(sds) < 2 or d0 < sds[0] or d1 > sds[-1]:
            continue
        out[i] = np.interp(d1, sds, arrs) - np.interp(d0, sds, arrs)
    out[out <= 0] = np.nan
    return out


def _metrics(err_s: np.ndarray, actual_s: np.ndarray, lo=None, hi=None, pred=None) -> dict:
    m = ~np.isnan(err_s)
    e = err_s[m]; a = actual_s[m]
    if len(e) == 0:
        return {"n": 0}
    out = {
        "n": int(len(e)),
        "mae_min": round(float(np.mean(np.abs(e))) / 60, 2),
        "median_abs_err_min": round(float(np.median(np.abs(e))) / 60, 2),
        "rmse_min": round(float(np.sqrt(np.mean(e ** 2))) / 60, 2),
        "bias_min": round(float(np.mean(e)) / 60, 2),
        "mape_pct": round(float(np.mean(np.abs(e) / a)) * 100, 1),
        "within_5min_pct": round(float(np.mean(np.abs(e) <= 300)) * 100, 1),
        "within_20pct_pct": round(float(np.mean(np.abs(e) <= 0.2 * a)) * 100, 1),
    }
    if lo is not None and hi is not None:
        out["interval_coverage_pct"] = round(float(np.mean((a >= lo[m]) & (a <= hi[m]))) * 100, 1)
    return out


def evaluate(con, test_days: list[int]) -> dict:
    t0 = time.time()
    model = TrafficModel(MODEL_DIR)
    model.load()
    if not model.ready:
        raise SystemExit("Model not built — run `train` first.")
    prepare_segment_grid(con)
    gt = build_ground_truth(con, test_days)
    print(f"[eval] ground truth: {len(gt):,} held-out bus runs from days {test_days}")
    VALID_DIR.mkdir(parents=True, exist_ok=True)

    actual = (gt["t1"] - gt["t0"]).astype(float)
    dist = gt["d1"] - gt["d0"]
    pred = np.zeros(len(gt)); lo = np.zeros(len(gt)); hi = np.zeros(len(gt))
    for i, r in enumerate(gt):
        dep_ist = int((r["t0"] + IST_OFFSET_S) % 86400)
        p = model.predict_leg(str(r["shape_id"]), float(r["d0"]), float(r["d1"]), dep_ist, int(r["is_weekend"]))
        pred[i] = p["total_travel_time_s"]; lo[i] = p["lower_bound_s"]; hi[i] = p["upper_bound_s"]
    flat_speed = 1.0 / float(np.mean(model.net_pace))
    flat = dist / flat_speed
    tt = timetable_durations(con, gt)

    hours = ((gt["t0"] + IST_OFFSET_S) % 86400) // 3600
    bands = {"night 00-06": (0, 6), "am peak 07-10": (7, 11), "midday 11-16": (11, 17), "pm peak 17-20": (17, 21), "evening 21-23": (21, 24)}
    by_band = {}
    for name, (a, b) in bands.items():
        m = (hours >= a) & (hours < b)
        if m.any():
            by_band[name] = {"pulse": _metrics((pred - actual)[m], actual[m], lo[m], hi[m]),
                             "timetable": _metrics((tt - actual)[m], actual[m]),
                             "flat_speed": _metrics((flat - actual)[m], actual[m])}
    by_hour = []
    for h in range(24):
        m = hours == h
        if m.sum() >= 20:
            by_hour.append({"hour": h, "n": int(m.sum()),
                            "pulse_mae_min": round(float(np.mean(np.abs(pred - actual)[m])) / 60, 2),
                            "flat_mae_min": round(float(np.mean(np.abs(flat - actual)[m])) / 60, 2),
                            "actual_median_min": round(float(np.median(actual[m])) / 60, 1)})
    by_day = {}
    for label, wv in (("weekday", 0), ("weekend_or_holiday", 1)):
        m = gt["is_weekend"] == wv
        if m.any():
            by_day[label] = _metrics((pred - actual)[m], actual[m], lo[m], hi[m])
    by_len = {}
    for label, (a, b) in {"2-5 km": (2000, 5000), "5-10 km": (5000, 10000), "10-15 km": (10000, 15001)}.items():
        m = (dist >= a) & (dist < b)
        if m.any():
            by_len[label] = _metrics((pred - actual)[m], actual[m], lo[m], hi[m])

    examples = []
    rng = np.random.default_rng(3)
    for i in rng.choice(len(gt), size=min(12, len(gt)), replace=False):
        r = gt[i]
        hhmm = int((r["t0"] + IST_OFFSET_S) % 86400)
        examples.append({
            "route_id": str(r["route_id"]), "date": date(YEAR, MONTH, int(r["day"])).isoformat(),
            "depart_ist": f"{hhmm // 3600:02d}:{(hhmm % 3600) // 60:02d}",
            "distance_km": round(float(dist[i]) / 1000, 1),
            "actual_min": round(actual[i] / 60, 1), "pulse_min": round(pred[i] / 60, 1),
            "pulse_range_min": [round(lo[i] / 60, 1), round(hi[i] / 60, 1)],
            "timetable_min": None if np.isnan(tt[i]) else round(tt[i] / 60, 1),
        })

    google_file = VALID_DIR / "google_comparison.json"
    google = None
    if google_file.exists():
        try:
            google = json.loads(google_file.read_text(encoding="utf-8"))
        except Exception:
            google = None

    tt_mask = ~np.isnan(tt)
    results = {
        "status": "OK",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "method": {
            "train_days": model.meta.get("train_days"),
            "test_days": test_days,
            "ground_truth": "Real bus runs on held-out days: a start ping and the first ping 2–15 km further along the same "
                            "vehicle's trip shape (no gap > 5 min). Actual time = GPS fix-time difference.",
            "pulse": "Per-stretch travel-time model, clock advanced stretch by stretch from the real departure time.",
            "timetable": "GTFS stop_times for the trip with the same route and HH_MM start, interpolated by distance along the shape.",
            "flat_speed": "Same distance at the network's all-day average bus speed (no time-of-day model).",
            "model_coverage_measured_cells_pct": model.meta.get("cells_measured_pct"),
        },
        "n_runs": int(len(gt)),
        "overall": {
            "pulse": _metrics(pred - actual, actual, lo, hi),
            "flat_speed": _metrics(flat - actual, actual),
            "timetable": _metrics(tt - actual, actual),
            "pulse_on_timetable_subset": _metrics(np.where(tt_mask, pred - actual, np.nan), actual,
                                                   np.where(tt_mask, lo, np.nan), np.where(tt_mask, hi, np.nan)),
        },
        "timetable_match_pct": round(100 * float(tt_mask.mean()), 1),
        "by_time_band": by_band,
        "by_hour": by_hour,
        "by_day_type": by_day,
        "by_trip_length": by_len,
        "examples": examples,
        "google": google if google else {"status": "NOT_RUN", "message": "Run scripts/compare_google.py with GOOGLE_MAPS_API_KEY set."},
    }
    (VALID_DIR / "results.json").write_text(json.dumps(results, indent=2), encoding="utf-8")
    write_report(results)
    o = results["overall"]
    print(f"[eval] PULSE MAE {o['pulse'].get('mae_min')} min | flat {o['flat_speed'].get('mae_min')} | "
          f"timetable {o['timetable'].get('mae_min')} (n={o['timetable'].get('n')}) | {time.time() - t0:.1f}s")
    return results


def write_report(res: dict) -> None:
    o = res["overall"]

    def row(name, m):
        if not m or not m.get("n"):
            return f"| {name} | – | – | – | – | – | – |"
        return (f"| {name} | {m['n']:,} | {m['mae_min']} | {m['median_abs_err_min']} | {m['rmse_min']} | "
                f"{m['within_5min_pct']}% | {m['within_20pct_pct']}% |")

    lines = [
        "# PULSE Validation Report",
        "",
        f"_Generated {res['generated_at']} by `scripts/build_traffic_model.py evaluate`. Every number below is computed; none is typed by hand._",
        "",
        "## Method",
        "",
        f"- Training days: {res['method']['train_days']}; test days (held out): {res['method']['test_days']}.",
        f"- Ground truth: {res['method']['ground_truth']}",
        f"- PULSE: {res['method']['pulse']}",
        f"- Timetable baseline: {res['method']['timetable']} Matched for {res['timetable_match_pct']}% of runs.",
        f"- Flat-speed baseline: {res['method']['flat_speed']}",
        f"- Model cells backed by direct measurements: {res['method']['model_coverage_measured_cells_pct']}%.",
        "",
        "## Overall",
        "",
        "| Predictor | Runs | MAE (min) | Median abs err (min) | RMSE (min) | Within ±5 min | Within ±20% |",
        "|---|---|---|---|---|---|---|",
        row("PULSE model", o["pulse"]),
        row("Flat average speed", o["flat_speed"]),
        row("Static GTFS timetable", o["timetable"]),
        row("PULSE (same runs as timetable)", o["pulse_on_timetable_subset"]),
        "",
        f"PULSE uncertainty band (p10–p90 style) contained the actual time in {o['pulse'].get('interval_coverage_pct')}% of runs.",
        "",
        "## By time of day",
        "",
        "| Band | Runs | PULSE MAE | Flat MAE | Timetable MAE |",
        "|---|---|---|---|---|",
    ]
    for band, v in res["by_time_band"].items():
        lines.append(f"| {band} | {v['pulse'].get('n', 0):,} | {v['pulse'].get('mae_min', '–')} | "
                     f"{v['flat_speed'].get('mae_min', '–')} | {v['timetable'].get('mae_min', '–')} |")
    lines += ["", "## By trip length", "", "| Length | Runs | PULSE MAE | Within ±20% |", "|---|---|---|---|"]
    for k, v in res["by_trip_length"].items():
        lines.append(f"| {k} | {v.get('n', 0):,} | {v.get('mae_min', '–')} | {v.get('within_20pct_pct', '–')}% |")
    lines += ["", "## Google Maps", ""]
    g = res.get("google") or {}
    if g.get("status") == "OK":
        lines.append(f"Compared on {g.get('n_pairs')} origin–destination pairs; see `data/validation/google_comparison.json`.")
    else:
        lines.append("Not run yet. `scripts/compare_google.py` queries the Google Routes API (transit) and needs GOOGLE_MAPS_API_KEY.")
    REPORT.write_text("\n".join(lines) + "\n", encoding="utf-8")


def build_headways(con, train_days: list[int]) -> None:
    """Observed headways (plan phase 3): when buses of each route actually pass
    three reference points (25/50/75% along every shape), by hour and day type.
    Expected wait for a rider arriving at random = E[gap²] / (2·E[gap]), which is
    longer than half the mean gap when buses bunch."""
    files = [SNAP_DIR / f"day={d:02d}.parquet" for d in train_days]
    files = [f for f in files if f.exists()]
    if not files:
        raise SystemExit("No snapped files for the training days — run `snap` first.")
    prepare_segment_grid(con)
    MODEL_DIR.mkdir(parents=True, exist_ok=True)
    parts = []
    for f in files:
        day = int(f.stem.split("=")[1])
        wk = is_weekend_like(date(YEAR, MONTH, day))
        part = MODEL_DIR / f"_cross_{day:02d}.parquet"
        con.execute(f"""
            COPY (
              WITH refs AS (
                SELECT shape_id, max(start_dist_m + length_m) * r AS ref, r
                FROM segs, (VALUES (0.25), (0.5), (0.75)) v(r) GROUP BY shape_id, r
              ), p AS (
                SELECT vehicle_id, trip_id, route_id, shape_id, ts, shape_dist,
                       lag(ts) OVER w AS pts, lag(shape_dist) OVER w AS pd
                FROM read_parquet('{f.as_posix()}')
                WINDOW w AS (PARTITION BY vehicle_id, trip_id ORDER BY ts)
              )
              SELECT p.route_id, p.shape_id, refs.r, p.vehicle_id, {wk} AS is_weekend,
                     min(p.pts + (refs.ref - p.pd) / nullif(p.shape_dist - p.pd, 0) * (p.ts - p.pts)) AS t_cross
              FROM p JOIN refs ON refs.shape_id = p.shape_id AND p.pd < refs.ref AND p.shape_dist >= refs.ref
              WHERE p.ts - p.pts <= 300
              GROUP BY p.route_id, p.shape_id, refs.r, p.vehicle_id, p.trip_id
            ) TO '{part.as_posix()}' (FORMAT parquet)
        """)
        parts.append(part)
    plist = "[" + ",".join(f"'{x.as_posix()}'" for x in parts) + "]"
    out = MODEL_DIR / "stop_headways.parquet"
    con.execute(f"""
        CREATE OR REPLACE TEMP TABLE gaps AS
        SELECT route_id, is_weekend,
               CAST(floor(((t_cross + {IST_OFFSET_S}) % 86400) / 3600) AS INTEGER) AS hour,
               t_cross - lag(t_cross) OVER (PARTITION BY shape_id, r, CAST((t_cross + {IST_OFFSET_S}) // 86400 AS BIGINT) ORDER BY t_cross) AS gap
        FROM read_parquet({plist})
    """)
    con.execute(f"""
        COPY (
          SELECT '__ROUTE_FALLBACK__' AS stop_id, route_id, hour * 4 AS time_bucket_15min, is_weekend,
                 sum(gap * gap) / sum(gap) AS median_gap_s,
                 quantile_cont(gap, 0.25) AS p25_gap_s, quantile_cont(gap, 0.75) AS p75_gap_s,
                 median(gap) AS raw_median_gap_s, count(*) AS sample_count, 'OBSERVED_ROUTE_HOUR' AS source_level
          FROM gaps WHERE gap BETWEEN 30 AND 5400 GROUP BY route_id, hour, is_weekend HAVING count(*) >= 4
          UNION ALL
          SELECT '__NETWORK_FALLBACK__', '__ALL__', hour * 4, is_weekend,
                 median(eff), NULL, NULL, NULL, sum(n), 'OBSERVED_NETWORK_HOUR'
          FROM (SELECT route_id, hour, is_weekend, sum(gap * gap) / sum(gap) AS eff, count(*) AS n
                FROM gaps WHERE gap BETWEEN 30 AND 5400 GROUP BY ALL HAVING count(*) >= 4)
          GROUP BY hour, is_weekend
        ) TO '{out.as_posix()}' (FORMAT parquet)
    """)
    for x in parts:
        x.unlink(missing_ok=True)
    n = con.execute(f"SELECT count(*), median(median_gap_s) FILTER (WHERE stop_id = '__ROUTE_FALLBACK__') FROM '{out.as_posix()}'").fetchone()
    print(f"[headways] {n[0]:,} route×hour rows; median effective gap {n[1] / 60:.1f} min")


def build_stop_positions(con) -> None:
    """Distance along each shape of every stop the shape serves (GTFS
    stop_times.stop_dist is empty in this feed). Lets the router predict the
    exact stretch between boarding and alighting stops."""
    prepare_segment_grid(con)
    MODEL_DIR.mkdir(parents=True, exist_ok=True)
    out = MODEL_DIR / "stop_shape_dist.parquet"
    con.execute(f"""
        COPY (
          WITH ss AS (
            SELECT DISTINCT t.shape_id, st.stop_id,
                   (sp.stop_lon - {LON0}) * {M_PER_DEG_LON} AS x, (sp.stop_lat - {LAT0}) * {M_PER_DEG_LAT} AS y
            FROM g.stop_times st JOIN g.trips t USING (trip_id) JOIN g.stops sp USING (stop_id)
          ), proj AS (
            SELECT ss.shape_id, ss.stop_id,
                   greatest(0.0, least(1.0, ((ss.x - sg.x0) * (sg.x1 - sg.x0) + (ss.y - sg.y0) * (sg.y1 - sg.y0))
                       / greatest(power(sg.x1 - sg.x0, 2) + power(sg.y1 - sg.y0, 2), 1.0))) AS t,
                   sg.start_dist_m, sg.length_m, sg.x0, sg.y0, sg.x1, sg.y1, ss.x, ss.y
            FROM ss JOIN segs sg ON sg.shape_id = ss.shape_id
          )
          SELECT shape_id, stop_id,
                 arg_min(start_dist_m + t * length_m,
                         power(x - (x0 + t * (x1 - x0)), 2) + power(y - (y0 + t * (y1 - y0)), 2)) AS dist_m,
                 sqrt(min(power(x - (x0 + t * (x1 - x0)), 2) + power(y - (y0 + t * (y1 - y0)), 2))) AS offset_m
          FROM proj GROUP BY ALL
        ) TO '{out.as_posix()}' (FORMAT parquet)
    """)
    n = con.execute(f"SELECT count(*), median(offset_m) FROM '{out.as_posix()}'").fetchone()
    print(f"[stops] {n[0]:,} stop positions along shapes (median offset {n[1]:.1f} m)")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("snap"); s.add_argument("--days", default="1-31"); s.add_argument("--skip-existing", action="store_true"); s.add_argument("--mem-gb", type=int, default=9)
    t = sub.add_parser("train"); t.add_argument("--train-days", default="1-24")
    e = sub.add_parser("evaluate"); e.add_argument("--test-days", default="25-31")
    sub.add_parser("stops")
    hw = sub.add_parser("headways"); hw.add_argument("--train-days", default="1-24")
    a = sub.add_parser("all"); a.add_argument("--train-days", default="1-24"); a.add_argument("--test-days", default="25-31")
    args = ap.parse_args()

    con = connect(getattr(args, "mem_gb", 9))
    if args.cmd in ("snap", "all"):
        prepare_segment_grid(con)
        days = parse_days(getattr(args, "days", "1-31"))
        stats_file = settings.MANIFEST_ROOT / "snap_stats.json"
        for d in days:
            if getattr(args, "skip_existing", False) and (CELL_DIR / f"day={d:02d}.parquet").exists():
                continue
            st = snap_day(con, d)
            if st:
                stats_file.parent.mkdir(parents=True, exist_ok=True)
                (stats_file.parent / f"snap_day_{d:02d}.json").write_text(json.dumps(st, indent=2), encoding="utf-8")
    if args.cmd in ("stops", "all"):
        build_stop_positions(con)
    if args.cmd in ("train", "all"):
        train(con, parse_days(args.train_days))
    if args.cmd in ("headways", "all"):
        build_headways(con, parse_days(args.train_days))
    if args.cmd in ("evaluate", "all"):
        evaluate(con, parse_days(args.test_days))


if __name__ == "__main__":
    main()
