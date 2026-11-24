"""
PULSE Phase 3a — Build Observed Headways (scripts/build_headways.py)

Reads matched GPS pings (output of match_to_shapes.py) for training days and
computes, for each (stop_id, route_id, time_bucket_15min, day_type), how often
a bus actually passes each stop.  Inter-arrival gaps are the headways.

Outputs:
  data/models/stop_headways.parquet        — primary artefact
  gtfs.duckdb :: stop_headways             — table for the headway service

Usage:
  python scripts/build_headways.py [--date-range YYYY-MM-DD YYYY-MM-DD]
                                   [--max-gap-s MAX_GAP_S]
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path
from datetime import date, timedelta
from typing import Optional

# ---------------------------------------------------------------------------
# Resolve project root (scripts/ → parent)
# ---------------------------------------------------------------------------
PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from app.core.config import settings
from app.core.logging import logger

import duckdb
import numpy as np
import pandas as pd

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
MATCHED_ROOT   = settings.PROCESSED_ROOT / "matched"
GTFS_DB_PATH   = settings.DATABASE_ROOT / "gtfs.duckdb"
OUT_PARQUET    = settings.WORKSPACE_ROOT / "data" / "models" / "stop_headways.parquet"
MAX_SNAP_M     = 60.0   # metres — how close to a stop centre a ping must be
EARTH_R        = 6_371_000.0
MIN_SAMPLES    = 3      # minimum inter-arrival gaps before we trust a headway
IST_OFFSET_S   = 19800  # UTC+5:30

# October 2026 holiday dates
HOLIDAYS = {date(2026, 10, 2), date(2026, 10, 12)}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Return great-circle distance in metres."""
    phi1, phi2 = np.radians(lat1), np.radians(lat2)
    dphi       = np.radians(lat2 - lat1)
    dlam       = np.radians(lon2 - lon1)
    a = np.sin(dphi / 2)**2 + np.cos(phi1) * np.cos(phi2) * np.sin(dlam / 2)**2
    return 2 * EARTH_R * np.arcsin(np.sqrt(np.clip(a, 0, 1)))


def _day_type(d: date) -> str:
    if d in HOLIDAYS:
        return "holiday"
    if d.weekday() >= 5:
        return "weekend"
    return "weekday"


def _glob_matched(start: date, end: date) -> list[Path]:
    """Collect matched parquet files in [start, end]."""
    files = []
    cur = start
    while cur <= end:
        p = (MATCHED_ROOT / f"year={cur.year}" / f"month={cur.month:02d}"
             / f"day={cur.day:02d}" / "matched.parquet")
        if p.exists():
            files.append(p)
        cur += timedelta(days=1)
    return files


# ---------------------------------------------------------------------------
# Core logic
# ---------------------------------------------------------------------------

def _load_stops(con: duckdb.DuckDBPyConnection) -> pd.DataFrame:
    """Load stop positions from GTFS."""
    return con.execute(
        "SELECT stop_id, stop_lat, stop_lon FROM stops"
    ).fetchdf()


def _load_trips_routes(con: duckdb.DuckDBPyConnection) -> pd.DataFrame:
    """Load trip→route mapping."""
    return con.execute(
        "SELECT trip_id, route_id FROM trips"
    ).fetchdf()


def _find_passages(
    pings: pd.DataFrame,
    stops: pd.DataFrame,
    trips_routes: pd.DataFrame,
    snap_m: float,
) -> pd.DataFrame:
    """
    For each trip in `pings`, find which stops it passed and when.

    Returns DataFrame with columns:
        stop_id, route_id, epoch_utc, day_type, time_bucket_15min
    """
    if pings.empty or stops.empty:
        return pd.DataFrame()

    pings = pings.merge(trips_routes, on="trip_id", how="left")
    pings = pings.dropna(subset=["route_id"])

    rows = []
    for (trip_id, route_id), trip_df in pings.groupby(["trip_id", "route_id"]):
        trip_df = trip_df.sort_values("epoch_utc").reset_index(drop=True)
        lat_arr = trip_df["lat"].to_numpy()
        lon_arr = trip_df["lon"].to_numpy()
        epoch_arr = trip_df["epoch_utc"].to_numpy()

        for _, stop in stops.iterrows():
            # Vectorised haversine to every ping in this trip
            phi1 = np.radians(stop["stop_lat"])
            phi2 = np.radians(lat_arr)
            dphi = np.radians(lat_arr - stop["stop_lat"])
            dlam = np.radians(lon_arr - stop["stop_lon"])
            a = (np.sin(dphi / 2)**2
                 + np.cos(phi1) * np.cos(phi2) * np.sin(dlam / 2)**2)
            dists = 2 * EARTH_R * np.arcsin(np.sqrt(np.clip(a, 0, 1)))

            close_mask = dists <= snap_m
            if not np.any(close_mask):
                continue

            # Closest ping time = passage time
            best_idx  = int(np.argmin(np.where(close_mask, dists, np.inf)))
            epoch_pas = int(epoch_arr[best_idx])
            ist_epoch = epoch_pas + IST_OFFSET_S
            bucket    = int((ist_epoch % 86400) // 900)   # 0–95
            d         = date.fromtimestamp(epoch_pas)

            rows.append({
                "stop_id":           stop["stop_id"],
                "route_id":          str(route_id),
                "epoch_utc":         epoch_pas,
                "day_type":          _day_type(d),
                "is_weekend":        int(d.weekday() >= 5 or d in HOLIDAYS),
                "time_bucket_15min": bucket,
            })

    return pd.DataFrame(rows)


def _compute_headways(passages: pd.DataFrame) -> pd.DataFrame:
    """
    Given a DataFrame of bus passages, compute inter-arrival gaps per
    (stop_id, route_id, time_bucket_15min, day_type, is_weekend).

    Returns DataFrame with schema:
        stop_id, route_id, time_bucket_15min, day_type, is_weekend,
        median_gap_s, p25_gap_s, p75_gap_s, sample_count, source_level
    """
    if passages.empty:
        return pd.DataFrame()

    passages = passages.sort_values(["stop_id", "route_id", "epoch_utc"])

    records = []

    for (stop_id, route_id, bucket, day_type, is_weekend), grp in passages.groupby(
        ["stop_id", "route_id", "time_bucket_15min", "day_type", "is_weekend"]
    ):
        epochs = grp["epoch_utc"].to_numpy()
        if len(epochs) < 2:
            continue
        gaps = np.diff(np.sort(epochs)).astype(float)
        # Filter obviously wrong gaps (< 60 s or > 3600 s)
        gaps = gaps[(gaps >= 60) & (gaps <= 3600)]
        if len(gaps) < MIN_SAMPLES:
            continue

        records.append({
            "stop_id":           str(stop_id),
            "route_id":          str(route_id),
            "time_bucket_15min": int(bucket),
            "day_type":          str(day_type),
            "is_weekend":        int(is_weekend),
            "median_gap_s":      float(np.median(gaps)),
            "p25_gap_s":         float(np.percentile(gaps, 25)),
            "p75_gap_s":         float(np.percentile(gaps, 75)),
            "sample_count":      len(gaps),
            "source_level":      "STOP_ROUTE_BUCKET",
        })

    return pd.DataFrame(records)


def _add_fallback_rows(
    headways: pd.DataFrame,
    passages: pd.DataFrame,
) -> pd.DataFrame:
    """
    Add route-level and network-level fallback rows so the headway service
    never returns None for a known route / time-of-day.
    """
    fallback_rows = []

    # Route-level fallback: aggregate across all stops of a route+bucket+day_type
    if not passages.empty:
        for (route_id, bucket, day_type, is_weekend), grp in passages.groupby(
            ["route_id", "time_bucket_15min", "day_type", "is_weekend"]
        ):
            epochs = grp.sort_values("epoch_utc")["epoch_utc"].to_numpy()
            if len(epochs) < 2:
                continue
            gaps = np.diff(np.sort(epochs)).astype(float)
            gaps = gaps[(gaps >= 60) & (gaps <= 3600)]
            if len(gaps) < MIN_SAMPLES:
                continue
            fallback_rows.append({
                "stop_id":           "__ROUTE_FALLBACK__",
                "route_id":          str(route_id),
                "time_bucket_15min": int(bucket),
                "day_type":          str(day_type),
                "is_weekend":        int(is_weekend),
                "median_gap_s":      float(np.median(gaps)),
                "p25_gap_s":         float(np.percentile(gaps, 25)),
                "p75_gap_s":         float(np.percentile(gaps, 75)),
                "sample_count":      len(gaps),
                "source_level":      "ROUTE_BUCKET",
            })

    # Network-level fallback: one row per (bucket, is_weekend)
    if not passages.empty:
        for (bucket, is_weekend), grp in passages.groupby(
            ["time_bucket_15min", "is_weekend"]
        ):
            epochs = grp.sort_values("epoch_utc")["epoch_utc"].to_numpy()
            if len(epochs) < 2:
                continue
            gaps = np.diff(np.sort(epochs)).astype(float)
            gaps = gaps[(gaps >= 60) & (gaps <= 3600)]
            if len(gaps) < MIN_SAMPLES:
                continue
            fallback_rows.append({
                "stop_id":           "__NETWORK_FALLBACK__",
                "route_id":          "__ALL__",
                "time_bucket_15min": int(bucket),
                "day_type":          "all",
                "is_weekend":        int(is_weekend),
                "median_gap_s":      float(np.median(gaps)),
                "p25_gap_s":         float(np.percentile(gaps, 25)),
                "p75_gap_s":         float(np.percentile(gaps, 75)),
                "sample_count":      len(gaps),
                "source_level":      "NETWORK_BUCKET",
            })

    if fallback_rows:
        headways = pd.concat(
            [headways, pd.DataFrame(fallback_rows)], ignore_index=True
        )

    return headways


def _write_outputs(headways: pd.DataFrame) -> None:
    """Write parquet + insert into gtfs.duckdb."""
    OUT_PARQUET.parent.mkdir(parents=True, exist_ok=True)
    headways.to_parquet(str(OUT_PARQUET), index=False)
    logger.info(f"Wrote {len(headways):,} headway rows → {OUT_PARQUET}")

    # Upsert into GTFS DB
    if not GTFS_DB_PATH.exists():
        logger.warning(f"GTFS DB not found at {GTFS_DB_PATH}; skipping DB write.")
        return

    con = duckdb.connect(str(GTFS_DB_PATH))
    try:
        con.execute("DROP TABLE IF EXISTS stop_headways")
        con.execute("""
            CREATE TABLE stop_headways (
                stop_id           VARCHAR,
                route_id          VARCHAR,
                time_bucket_15min INTEGER,
                day_type          VARCHAR,
                is_weekend        INTEGER,
                median_gap_s      DOUBLE,
                p25_gap_s         DOUBLE,
                p75_gap_s         DOUBLE,
                sample_count      INTEGER,
                source_level      VARCHAR
            )
        """)
        con.register("_hw_df", headways)
        con.execute("INSERT INTO stop_headways SELECT * FROM _hw_df")
        con.unregister("_hw_df")
        logger.info(
            f"Inserted {len(headways):,} rows into gtfs.duckdb::stop_headways"
        )
    finally:
        con.close()


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def build_headways(
    start: date,
    end: date,
    max_gap_s: int = 3600,
) -> None:
    t0 = time.time()
    files = _glob_matched(start, end)
    if not files:
        logger.error(f"No matched parquet files found between {start} and {end}.")
        sys.exit(1)
    logger.info(f"Found {len(files)} matched day files from {start} to {end}")

    # Load GTFS reference tables
    if not GTFS_DB_PATH.exists():
        logger.error(f"GTFS DB not found: {GTFS_DB_PATH}")
        sys.exit(1)

    gtfs_con = duckdb.connect(str(GTFS_DB_PATH), read_only=True)
    try:
        stops       = _load_stops(gtfs_con)
        trips_routes = _load_trips_routes(gtfs_con)
    finally:
        gtfs_con.close()

    logger.info(f"Loaded {len(stops):,} stops and {len(trips_routes):,} trips")

    all_passages: list[pd.DataFrame] = []

    for f in files:
        try:
            pings = pd.read_parquet(str(f))
        except Exception as exc:
            logger.warning(f"Could not read {f}: {exc}")
            continue

        required = {"trip_id", "lat", "lon", "epoch_utc"}
        if not required.issubset(pings.columns):
            logger.warning(f"Missing columns in {f}: {required - set(pings.columns)}")
            continue

        passages = _find_passages(pings, stops, trips_routes, snap_m=MAX_SNAP_M)
        if not passages.empty:
            all_passages.append(passages)
            logger.info(f"  {f.parent.name}: {len(passages):,} passages found")

    if not all_passages:
        logger.error("No bus passages found across all matched files. "
                     "Run match_to_shapes.py first.")
        sys.exit(1)

    combined = pd.concat(all_passages, ignore_index=True)
    logger.info(f"Total passages: {len(combined):,}")

    headways  = _compute_headways(combined)
    logger.info(f"Computed {len(headways):,} stop+route+bucket headway records")

    headways  = _add_fallback_rows(headways, combined)
    logger.info(f"After fallbacks: {len(headways):,} total headway rows")

    _write_outputs(headways)
    logger.info(f"build_headways done in {time.time() - t0:.1f}s")


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Build observed bus headways from matched GPS pings."
    )
    p.add_argument(
        "--date-range", nargs=2, metavar=("START", "END"),
        default=["2026-10-01", "2026-10-24"],
        help="Training date range (inclusive). Default: 2026-10-01 to 2026-10-24",
    )
    p.add_argument(
        "--max-gap-s", type=int, default=3600,
        help="Maximum inter-arrival gap to include (seconds). Default: 3600",
    )
    return p.parse_args()


if __name__ == "__main__":
    args    = _parse_args()
    start_d = date.fromisoformat(args.date_range[0])
    end_d   = date.fromisoformat(args.date_range[1])
    build_headways(start_d, end_d, max_gap_s=args.max_gap_s)
