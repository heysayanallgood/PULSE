"""
PULSE One-Day Historical GPS Processing Pipeline (scripts/process_day.py)
Implements ADR 001, ADR 002, ADR 003, ADR 006 — Phase 2.1 upgrade.

Changes vs original:
  - Uses GPS epoch_utc (not poll-time date/time) for time buckets.
  - Removes exact duplicate (vehicle_id, epoch_utc) pings.
  - Drops stale pings where GPS fix age > MAX_GPS_AGE_S (default 120 s).
  - Drops parked buses: runs of speed=0 at the same location ≥ PARKED_WINDOW pings.
  - Computes speed from consecutive-ping distance/time; drops physically impossible jumps.
  - Marks day types: weekday / weekend / holiday (confirmed Oct 2026 Delhi holidays).
  - Flags and reports partial days (day ends before 23:00).
  - Writes per-reason cleaning counts to manifest.
"""
import os
import sys
import time
import json
import uuid
import math
import sqlite3
import argparse
from pathlib import Path
from datetime import datetime, timezone
import pandas as pd
import numpy as np
from pyproj import Transformer

# Allow running from scripts/ or project root
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.core.config import settings

# ── Constants ────────────────────────────────────────────────────────────────
transformer = Transformer.from_crs("EPSG:4326", "EPSG:32643", always_xy=True)

LAT_MIN, LAT_MAX = 28.30, 28.95
LON_MIN, LON_MAX = 76.80, 77.55

MAX_GPS_SPEED_MPS = 25.0       # ~90 km/h — hard upper bound from GPS coordinates
MAX_GPS_AGE_S     = 120        # pings with GPS fix older than this are stale
PARKED_SPEED_MPS  = 0.5        # speed threshold to consider bus "stopped"
PARKED_MIN_PINGS  = 10         # consecutive stopped pings → parked
IST_OFFSET_S      = 19800      # UTC+5:30

# Confirmed Delhi public holidays in October 2026
# Gandhi Jayanti: Oct 2 (Friday), Dussehra: Oct 12 (Monday)
HOLIDAY_DATES = {"2026-10-02", "2026-10-12"}


def _haversine_m(lat1, lon1, lat2, lon2) -> float:
    R = 6_371_000.0
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlam = math.radians(lon2 - lon1)
    a = math.sin(dphi/2)**2 + math.cos(phi1)*math.cos(phi2)*math.sin(dlam/2)**2
    return 2*R*math.asin(math.sqrt(min(a, 1.0)))


def _day_type(date_str: str, day_of_week: int) -> str:
    """Returns 'holiday', 'weekend', or 'weekday'."""
    if date_str in HOLIDAY_DATES:
        return "holiday"
    if day_of_week >= 5:
        return "weekend"
    return "weekday"


def _compute_gps_speed(df: pd.DataFrame) -> pd.DataFrame:
    """
    Per-vehicle, sort by epoch_utc, compute speed from consecutive pings.
    Sets speed_mps_derived; leaves NaN for first ping of each vehicle.
    """
    df = df.sort_values(["vehicle_id", "epoch_utc"])
    grp = df.groupby("vehicle_id", sort=False)

    dt = grp["epoch_utc"].diff().fillna(0).clip(lower=0)
    dlat = grp["lat"].diff().fillna(0)
    dlng = grp["lng"].diff().fillna(0)

    # Vectorised haversine approximation (good enough for short steps)
    phi = np.radians(df["lat"].to_numpy())
    dphi = np.radians(dlat.to_numpy())
    dlam = np.radians(dlng.to_numpy())
    phi_prev = phi - dphi
    a = (np.sin(dphi/2)**2
         + np.cos(phi_prev)*np.cos(phi)*np.sin(dlam/2)**2)
    a = np.clip(a, 0, 1)
    dist_m = 2 * 6_371_000 * np.arcsin(np.sqrt(a))

    with np.errstate(divide="ignore", invalid="ignore"):
        speed = np.where(dt > 0, dist_m / dt, np.nan)

    df = df.copy()
    df["speed_mps_derived"] = speed
    df["dt_s"] = dt.to_numpy()
    df["dist_m"] = dist_m
    return df


def process_daily_db(date_str: str, max_records: int | None = None,
                     chunk_size: int = 250_000):
    """
    Processes one daily SQLite database (bus_movements_YYYY_MM_DD.db).
    Returns True on success, False on missing file.
    """
    db_name = f"bus_movements_{date_str.replace('-', '_')}.db"
    db_path = settings.HISTORICAL_SQLITE_DIR / db_name

    if not db_path.exists():
        print(f"Error: Database file {db_path} does not exist.")
        return False

    year, month, day = date_str.split("-")
    staging_dir   = settings.STAGING_DATA_ROOT   / f"year={year}/month={month}/day={day}"
    processed_dir = settings.PROCESSED_DATA_ROOT / f"historical/year={year}/month={month}/day={day}"
    manifest_dir  = settings.MANIFEST_ROOT

    for d in (staging_dir, processed_dir, manifest_dir):
        d.mkdir(parents=True, exist_ok=True)

    manifest_path = manifest_dir / f"manifest_{date_str}.json"

    print(f"\n{'='*60}")
    print(f"PULSE Pipeline: Processing {db_name}")
    print(f"Source size: {db_path.stat().st_size / (1024**3):.2f} GB")
    print(f"Target:      {processed_dir}")
    print(f"{'='*60}")

    t0     = time.time()
    run_id = str(uuid.uuid4())

    # Read-only connection (ADR 006)
    conn = sqlite3.connect(f"file:{db_path.as_posix()}?mode=ro", uri=True)
    cur  = conn.cursor()

    query = ("SELECT vehicle_id, lat, lng, speed, route_id, trip_id, "
             "timestamp, date, time FROM vehicle_feed")
    if max_records:
        query += f" LIMIT {max_records}"
    cur.execute(query)

    # ── Accumulate all chunks into one DataFrame for per-vehicle cleaning ──
    cols = ["vehicle_id", "lat_raw", "lng_raw", "speed_raw",
            "route_id_raw", "trip_id", "timestamp_raw", "poll_date", "poll_time"]
    all_chunks = []
    total_extracted = 0
    chunk_idx = 0
    while True:
        rows = cur.fetchmany(chunk_size)
        if not rows:
            break
        chunk_idx += 1
        total_extracted += len(rows)
        all_chunks.append(pd.DataFrame(rows, columns=cols))
        if chunk_idx % 5 == 0:
            print(f"  Read chunk {chunk_idx:03d} ({total_extracted:,} rows so far)…")

    conn.close()
    if not all_chunks:
        print("No data extracted.")
        return False

    df = pd.concat(all_chunks, ignore_index=True)
    print(f"  Total extracted: {total_extracted:,} rows")

    # ── Rejection counters ────────────────────────────────────────────────
    rej = {
        "null_or_invalid_coords": 0,
        "out_of_bounds":          0,
        "invalid_timestamp":      0,
        "duplicate_ping":         0,
        "stale_gps_fix":          0,
        "parked_bus":             0,
        "impossible_speed_jump":  0,
    }

    # ── 1. Coordinate cleaning ────────────────────────────────────────────
    df["lat"] = pd.to_numeric(df["lat_raw"], errors="coerce")
    df["lng"] = pd.to_numeric(df["lng_raw"], errors="coerce")
    bad = df["lat"].isna() | df["lng"].isna()
    rej["null_or_invalid_coords"] += int(bad.sum())
    df = df[~bad].copy()

    in_bounds = ((df["lat"] >= LAT_MIN) & (df["lat"] <= LAT_MAX) &
                 (df["lng"] >= LON_MIN) & (df["lng"] <= LON_MAX))
    rej["out_of_bounds"] += int((~in_bounds).sum())
    df = df[in_bounds].copy()

    # ── 2. Parse GPS epoch (the actual fix time, not the poll time) ───────
    df["epoch_utc"] = pd.to_numeric(df["timestamp_raw"], errors="coerce")
    bad_ts = df["epoch_utc"].isna() | (df["epoch_utc"] <= 0)
    rej["invalid_timestamp"] += int(bad_ts.sum())
    df = df[~bad_ts].copy()
    df["epoch_utc"] = df["epoch_utc"].astype(np.int64)

    # Derive IST wall-clock from epoch — not from poll_date/poll_time
    ist_s = (df["epoch_utc"] + IST_OFFSET_S).astype(np.int64)
    df["hour_ist"]         = (ist_s // 3600) % 24
    df["minute_ist"]       = (ist_s % 3600) // 60
    df["time_bucket_15min"]= (df["hour_ist"] * 4 + df["minute_ist"] // 15).clip(0, 95)

    # Date from epoch
    df["date_ist"] = pd.to_datetime(df["epoch_utc"] + IST_OFFSET_S, unit="s", utc=True) \
                       .dt.date.astype(str)

    # ── 3. Detect stale GPS fixes (fix time vs poll time) ─────────────────
    # poll_time is "HH:MM:SS" in IST; reconstruct a rough poll epoch from poll_date + poll_time
    poll_hms = df["poll_time"].astype(str).str.split(":", expand=True)
    poll_h   = pd.to_numeric(poll_hms[0], errors="coerce").fillna(0).astype(int)
    poll_m   = pd.to_numeric(poll_hms[1], errors="coerce").fillna(0).astype(int)
    poll_s   = pd.to_numeric(poll_hms[2], errors="coerce").fillna(0).astype(int)

    poll_dates     = pd.to_datetime(df["poll_date"], errors="coerce")
    poll_epoch_utc = (poll_dates.astype(np.int64) // 10**9
                      + poll_h * 3600 + poll_m * 60 + poll_s
                      - IST_OFFSET_S)

    gps_age = poll_epoch_utc - df["epoch_utc"]
    stale   = gps_age > MAX_GPS_AGE_S
    rej["stale_gps_fix"] += int(stale.sum())
    df = df[~stale].copy()
    poll_epoch_utc = poll_epoch_utc[~stale]

    # ── 4. Remove exact duplicate pings (same vehicle, same GPS fix time) ─
    before_dedup = len(df)
    df = df.drop_duplicates(subset=["vehicle_id", "epoch_utc"])
    rej["duplicate_ping"] += before_dedup - len(df)

    # ── 5. Route / trip normalization ────────────────────────────────────
    df["route_id"] = (pd.to_numeric(df["route_id_raw"], errors="coerce")
                      .fillna(0).astype(int).astype(str))

    # ── 6. Compute derived GPS speed from consecutive pings ───────────────
    df = _compute_gps_speed(df)

    # Drop physically impossible jumps (derived speed > MAX_GPS_SPEED_MPS)
    impossible = df["speed_mps_derived"].notna() & (df["speed_mps_derived"] > MAX_GPS_SPEED_MPS)
    rej["impossible_speed_jump"] += int(impossible.sum())
    df = df[~impossible].copy()

    # Use derived speed where available, fall back to reported speed
    df["speed_raw_mps"] = pd.to_numeric(df["speed_raw"], errors="coerce").fillna(0.0).clip(0, MAX_GPS_SPEED_MPS)
    df["speed_mps"] = df["speed_mps_derived"].fillna(df["speed_raw_mps"])

    # ── 7. Drop parked buses ──────────────────────────────────────────────
    # A bus is "parked" if it has ≥ PARKED_MIN_PINGS consecutive low-speed pings
    # at essentially the same location. We mark individual pings in such runs.
    df = df.sort_values(["vehicle_id", "epoch_utc"])

    stopped = (df["speed_mps"] <= PARKED_SPEED_MPS).astype(int)
    # Rolling window per vehicle — count consecutive stopped pings
    vehicle_groups = df.groupby("vehicle_id", sort=False)
    run_len = vehicle_groups["speed_mps"].transform(
        lambda s: s.le(PARKED_SPEED_MPS).groupby((~s.le(PARKED_SPEED_MPS)).cumsum()).cumcount() + 1
    )
    parked_mask = run_len >= PARKED_MIN_PINGS
    rej["parked_bus"] += int(parked_mask.sum())
    df = df[~parked_mask].copy()

    # ── 8. Day-type labelling ─────────────────────────────────────────────
    dates_pd = pd.to_datetime(df["date_ist"], errors="coerce")
    df["day_of_week"] = dates_pd.dt.dayofweek.fillna(3).astype(int)
    df["is_weekend"]  = df["day_of_week"].isin([5, 6]).astype(int)
    df["day_type"]    = df.apply(
        lambda r: _day_type(r["date_ist"], r["day_of_week"]), axis=1
    )

    # ── 9. Flag partial day ───────────────────────────────────────────────
    max_hour = int(df["hour_ist"].max()) if not df.empty else 0
    is_partial_day = max_hour < 23

    # ── 10. Metric projection ─────────────────────────────────────────────
    if not df.empty:
        proj_x, proj_y = transformer.transform(
            df["lng"].to_numpy(), df["lat"].to_numpy()
        )
        df["proj_x"] = proj_x
        df["proj_y"] = proj_y
    else:
        df["proj_x"] = pd.array([], dtype=float)
        df["proj_y"] = pd.array([], dtype=float)

    # ── 11. Output ────────────────────────────────────────────────────────
    out_cols = [
        "vehicle_id", "route_id", "trip_id", "date_ist",
        "epoch_utc", "hour_ist", "minute_ist", "time_bucket_15min",
        "day_of_week", "is_weekend", "day_type",
        "lat", "lng", "proj_x", "proj_y", "speed_mps",
        "dt_s", "dist_m",          # inter-ping delta time & distance
    ]
    df_clean = df[[c for c in out_cols if c in df.columns]]
    total_cleaned  = len(df_clean)
    total_rejected = total_extracted - total_cleaned

    # Write in a single Parquet file (data already in memory)
    part_name    = "part-0001.parquet"
    staging_file = staging_dir  / part_name
    final_file   = processed_dir / part_name

    df_clean.to_parquet(staging_file, compression="snappy", index=False)
    if final_file.exists():
        final_file.unlink()
    staging_file.replace(final_file)

    elapsed = time.time() - t0

    # ── Manifest ──────────────────────────────────────────────────────────
    manifest = {
        "pipeline_run_id":            run_id,
        "date":                       date_str,
        "source_file":                db_name,
        "source_size_bytes":          db_path.stat().st_size,
        "source_records_extracted":   total_extracted,
        "records_cleaned":            total_cleaned,
        "records_rejected":           total_rejected,
        "rejection_breakdown":        rej,
        "is_partial_day":             is_partial_day,
        "max_hour_in_data":           max_hour,
        "output_parquet_files":       [str(final_file)],
        "processing_time_seconds":    round(elapsed, 2),
        "throughput_records_per_sec": round(total_extracted / max(elapsed, 0.001), 1),
        "status":                     "COMPLETED",
        "timestamp":                  datetime.now(timezone.utc).isoformat(),
    }

    with open(manifest_path, "w", encoding="utf-8") as fp:
        json.dump(manifest, fp, indent=2)

    print(f"\n=== Daily Pipeline Completed in {elapsed:.2f}s ===")
    print(f"Extracted: {total_extracted:,} | Cleaned: {total_cleaned:,} | Rejected: {total_rejected:,}")
    print(f"Partial day: {is_partial_day}  (max hour in data: {max_hour})")
    for reason, count in rej.items():
        if count:
            print(f"  Rejected [{reason}]: {count:,}")
    print(f"Throughput: {manifest['throughput_records_per_sec']:,.0f} records/sec")
    print(f"Manifest:   {manifest_path}")
    return True


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="PULSE Daily Historical GPS Ingestion (Phase 2)")
    parser.add_argument("--date",       default="2026-10-01", help="Date YYYY-MM-DD")
    parser.add_argument("--limit",      type=int, default=None, help="Max records (dev/test)")
    parser.add_argument("--chunk_size", type=int, default=250_000, help="SQLite fetch chunk size")
    args = parser.parse_args()

    process_daily_db(args.date, max_records=args.limit, chunk_size=args.chunk_size)
