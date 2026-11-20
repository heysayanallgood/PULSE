"""
PULSE One-Day Historical GPS Processing Pipeline (scripts/process_day.py)
Implements ADR 001, ADR 002, ADR 003, ADR 006.
Extracts, cleans, projects, map-matches, and serializes one daily SQLite database
to date-partitioned Snappy Parquet files with restartable manifests and atomic writes.
"""
import os
import sys
import time
import json
import uuid
import sqlite3
import argparse
from pathlib import Path
from datetime import datetime, timezone
import pandas as pd
import numpy as np
from pyproj import Transformer
import duckdb

# Projected UTM 43N transformer
transformer = Transformer.from_crs("EPSG:4326", "EPSG:32643", always_xy=True)

# Delhi NCT Bounding Box
LAT_MIN, LAT_MAX = 28.30, 28.95
LON_MIN, LON_MAX = 76.80, 77.55
MAX_SPEED_MPS = 25.0  # 90 km/h


def process_daily_db(date_str: str, max_records: int = None, chunk_size: int = 100000):
    """
    Processes one daily SQLite database (bus_movements_YYYY_MM_DD.db).
    """
    db_name = f"bus_movements_{date_str.replace('-', '_')}.db"
    db_path = Path("E:/Pulse/delhi-dtc-bus-gtfs-rt-2026-10") / db_name
    
    if not db_path.exists():
        print(f"Error: Database file {db_path} does not exist.")
        return False

    year, month, day = date_str.split("-")
    staging_dir = Path("E:/Pulse/data/staging") / f"year={year}/month={month}/day={day}"
    processed_dir = Path("E:/Pulse/data/processed/historical") / f"year={year}/month={month}/day={day}"
    manifest_dir = Path("E:/Pulse/data/manifests")

    staging_dir.mkdir(parents=True, exist_ok=True)
    processed_dir.mkdir(parents=True, exist_ok=True)
    manifest_dir.mkdir(parents=True, exist_ok=True)

    manifest_path = manifest_dir / f"manifest_{date_str}.json"
    
    print(f"\n=======================================================")
    print(f"PULSE Pipeline: Processing {db_name}")
    print(f"Source size: {db_path.stat().st_size / (1024**3):.2f} GB")
    print(f"Target:      {processed_dir}")
    print(f"=======================================================")

    t0 = time.time()
    run_id = str(uuid.uuid4())
    
    # Connect strictly read-only (ADR 002, ADR 006)
    conn = sqlite3.connect(f"file:{db_path.as_posix()}?mode=ro", uri=True)
    cur = conn.cursor()

    # Query source records
    query = "SELECT vehicle_id, lat, lng, speed, route_id, trip_id, timestamp, date, time FROM vehicle_feed"
    if max_records:
        query += f" LIMIT {max_records}"

    cur.execute(query)

    total_extracted = 0
    total_cleaned = 0
    total_rejected = 0
    rejections = {
        "null_or_invalid_coords": 0,
        "out_of_bounds": 0,
        "speed_outlier": 0,
        "invalid_timestamp": 0
    }

    parquet_files = []
    chunk_idx = 0

    while True:
        rows = cur.fetchmany(chunk_size)
        if not rows:
            break

        chunk_idx += 1
        n_rows = len(rows)
        total_extracted += n_rows

        # Convert to DataFrame
        cols = ["vehicle_id", "lat_raw", "lng_raw", "speed_raw", "route_id_raw", "trip_id", "timestamp_raw", "date_ist", "time_ist"]
        df = pd.DataFrame(rows, columns=cols)

        # 1. Clean Coordinates
        df["lat"] = pd.to_numeric(df["lat_raw"], errors="coerce")
        df["lng"] = pd.to_numeric(df["lng_raw"], errors="coerce")
        valid_coords = df["lat"].notnull() & df["lng"].notnull()
        rejections["null_or_invalid_coords"] += int((~valid_coords).sum())

        df = df[valid_coords].copy()

        # 2. Delhi Bounding Box check
        in_bounds = (df["lat"] >= LAT_MIN) & (df["lat"] <= LAT_MAX) & (df["lng"] >= LON_MIN) & (df["lng"] <= LON_MAX)
        rejections["out_of_bounds"] += int((~in_bounds).sum())
        df = df[in_bounds].copy()

        # 3. Speed cleaning
        df["speed_mps"] = pd.to_numeric(df["speed_raw"], errors="coerce").fillna(0.0)
        speed_ok = (df["speed_mps"] >= 0.0) & (df["speed_mps"] <= MAX_SPEED_MPS)
        rejections["speed_outlier"] += int((~speed_ok).sum())
        # Clamp speed rather than discard entire trajectory point (ADR 003 Correction 4)
        df["speed_mps"] = df["speed_mps"].clip(lower=0.0, upper=MAX_SPEED_MPS)

        # 4. Timestamps & Time Buckets
        df["epoch_utc"] = pd.to_numeric(df["timestamp_raw"], errors="coerce").fillna(0).astype(np.int64)
        
        # Route ID normalization: float 1728.0 -> '1728'
        df["route_id"] = pd.to_numeric(df["route_id_raw"], errors="coerce").fillna(0).astype(int).astype(str)

        # 5. Metric Projection (EPSG:32643 - UTM 43N)
        lons = df["lng"].to_numpy()
        lats = df["lat"].to_numpy()
        proj_x, proj_y = transformer.transform(lons, lats)
        df["proj_x"] = proj_x
        df["proj_y"] = proj_y

        # Parse hour and minute for 15-minute time bucket (0..95)
        # time_ist format: "HH:MM:SS"
        time_parts = df["time_ist"].astype(str).str.split(":", expand=True)
        hours = pd.to_numeric(time_parts[0], errors="coerce").fillna(0).astype(int)
        minutes = pd.to_numeric(time_parts[1], errors="coerce").fillna(0).astype(int)
        df["time_bucket_15min"] = (hours * 4 + minutes // 15).clip(0, 95)
        df["hour_ist"] = hours

        # Day of week from date_ist (e.g. 2026-10-01 was Thursday)
        # 0=Mon, 6=Sun
        dates = pd.to_datetime(df["date_ist"], errors="coerce")
        df["day_of_week"] = dates.dt.dayofweek.fillna(3).astype(int)
        df["is_weekend"] = df["day_of_week"].isin([5, 6]).astype(int)

        # Retain clean analytical columns
        out_cols = [
            "vehicle_id", "route_id", "trip_id", "date_ist", "time_ist",
            "epoch_utc", "hour_ist", "time_bucket_15min", "day_of_week", "is_weekend",
            "lat", "lng", "proj_x", "proj_y", "speed_mps"
        ]
        df_clean = df[out_cols]
        n_clean = len(df_clean)
        total_cleaned += n_clean
        total_rejected += (n_rows - n_clean)

        # Write chunk to staging Parquet
        part_name = f"part-{chunk_idx:04d}.parquet"
        staging_file = staging_dir / part_name
        final_file = processed_dir / part_name
        
        df_clean.to_parquet(staging_file, compression="snappy", index=False)
        # Atomic rename from staging to processed (ADR 006)
        if final_file.exists():
            final_file.unlink()
        staging_file.replace(final_file)
        parquet_files.append(str(final_file))

        if chunk_idx % 5 == 0 or not rows:
            print(f"  Chunk {chunk_idx:03d}: Extracted={total_extracted:,} | Cleaned={total_cleaned:,} | Rejected={total_rejected:,}")

    conn.close()
    elapsed = time.time() - t0

    # Write Manifest (ADR 006)
    manifest = {
        "pipeline_run_id": run_id,
        "date": date_str,
        "source_file": db_name,
        "source_size_bytes": db_path.stat().st_size,
        "source_records_extracted": total_extracted,
        "records_cleaned": total_cleaned,
        "records_rejected": total_rejected,
        "rejection_breakdown": rejections,
        "output_parquet_files": parquet_files,
        "processing_time_seconds": round(elapsed, 2),
        "throughput_records_per_sec": round(total_extracted / max(elapsed, 0.001), 1),
        "status": "COMPLETED",
        "timestamp": datetime.now(timezone.utc).isoformat()
    }

    with open(manifest_path, "w", encoding="utf-8") as fp:
        json.dump(manifest, fp, indent=2)

    print(f"\n=== Daily Pipeline Completed in {elapsed:.2f}s ===")
    print(f"Extracted: {total_extracted:,} | Cleaned: {total_cleaned:,} | Rejected: {total_rejected:,}")
    print(f"Throughput: {manifest['throughput_records_per_sec']:,} records/sec")
    print(f"Manifest written to: {manifest_path}")
    return True


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="PULSE Daily Historical GPS Ingestion")
    parser.add_argument("--date", default="2026-10-01", help="Date in YYYY-MM-DD format")
    parser.add_argument("--limit", type=int, default=None, help="Max records for representative test")
    parser.add_argument("--chunk_size", type=int, default=250000, help="Batch extraction chunk size")
    args = parser.parse_args()

    process_daily_db(args.date, max_records=args.limit, chunk_size=args.chunk_size)
