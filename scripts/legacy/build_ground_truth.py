"""
PULSE Ground-Truth Builder (scripts/build_ground_truth.py)
Phase 1.2 — extracts actual bus travel times from held-out GPS data (days 25-31).

For each observed trip on a test day:
  1. Sorts pings by GPS timestamp.
  2. Identifies stop-to-stop durations by interpolating when the bus crossed each stop.
  3. Saves to data/validation/ground_truth.parquet.

Output schema:
  trip_id, vehicle_id, route_id, date_ist, is_weekend,
  from_stop_seq, to_stop_seq, from_stop_id, to_stop_id,
  actual_start_time_s,   # seconds-since-midnight when bus left from_stop
  actual_duration_s,     # seconds to reach to_stop
  distance_m             # GTFS straight-line distance between the two stops
"""

import sys
import json
import time
import math
import duckdb
import numpy as np
import pandas as pd
from pathlib import Path
from datetime import datetime, timezone

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.core.config import settings

# ── Config ──────────────────────────────────────────────────────────────────
TEST_DAYS      = list(range(25, 32))          # days 25-31 (Oct 2026)
YEAR, MONTH    = 2026, 10
MIN_PINGS      = 6                            # minimum pings to trust a trip
MAX_STOP_GAP_M = 1500.0                       # only use stop pairs ≤ 1.5 km apart
MAX_PAUSE_S    = 600.0                        # discard trip segments with >10 min pause

HIST_DIR       = settings.PROCESSED_DATA_ROOT / "historical"
GTFS_DB        = settings.DATABASE_ROOT / "gtfs.duckdb"
OUT_DIR        = settings.DATA_ROOT / "validation"
OUT_FILE       = OUT_DIR / "ground_truth.parquet"
MANIFEST_FILE  = OUT_DIR / "ground_truth_manifest.json"


def haversine_m(lat1, lon1, lat2, lon2) -> float:
    """Great-circle distance in metres."""
    R = 6_371_000.0
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlam = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlam / 2) ** 2
    return 2 * R * math.asin(math.sqrt(a))


def build_ground_truth(test_days: list[int] = TEST_DAYS):
    print("=" * 60)
    print("PULSE Ground-Truth Builder — Phase 1.2")
    print(f"Test days (day-of-month): {test_days}")
    print("=" * 60)

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    t0 = time.time()

    # ── 1. Load stop positions from GTFS ─────────────────────────────────────
    if not GTFS_DB.exists():
        print(f"ERROR: GTFS database not found at {GTFS_DB}")
        print("Run scripts/ingest_gtfs.py first.")
        sys.exit(1)

    print("Loading GTFS stop positions and stop_times …")
    gtfs_con = duckdb.connect(str(GTFS_DB), read_only=True)

    stops_df = gtfs_con.execute(
        "SELECT stop_id, stop_lat, stop_lon FROM stops"
    ).df()
    stop_pos = dict(zip(
        stops_df["stop_id"],
        zip(stops_df["stop_lat"], stops_df["stop_lon"])
    ))

    # stop_times: for each trip, ordered list of (seq, stop_id, arrival_s)
    # arrival_time may be "HH:MM:SS" with HH ≥ 24 for overnight trips
    def parse_gtfs_time(t: str) -> int:
        """Convert GTFS time string (possibly ≥24h) to seconds since midnight."""
        try:
            h, m, s = t.strip().split(":")
            return int(h) * 3600 + int(m) * 60 + int(s)
        except Exception:
            return -1

    print("Loading stop_times …")
    st_df = gtfs_con.execute(
        "SELECT trip_id, stop_sequence, stop_id, arrival_time FROM stop_times ORDER BY trip_id, stop_sequence"
    ).df()
    gtfs_con.close()

    st_df["arrival_s"] = st_df["arrival_time"].apply(parse_gtfs_time)
    st_df = st_df[st_df["arrival_s"] >= 0]

    # Build dict: trip_id → list of (seq, stop_id, arrival_s)
    trip_stops: dict[str, list] = {}
    for row in st_df.itertuples(index=False):
        trip_stops.setdefault(row.trip_id, []).append(
            (row.stop_sequence, row.stop_id, row.arrival_s)
        )
    print(f"  {len(trip_stops):,} GTFS trips loaded.")

    # ── 2. Load GPS pings for test days ──────────────────────────────────────
    parquet_files = []
    for day in test_days:
        day_dir = HIST_DIR / f"year={YEAR}/month={MONTH:02d}/day={day:02d}"
        parquet_files.extend(day_dir.glob("*.parquet"))

    if not parquet_files:
        print(f"ERROR: No processed Parquet files found for test days {test_days}.")
        print(f"Expected under: {HIST_DIR}/year={YEAR}/month={MONTH:02d}/day=XX/")
        print("Run scripts/process_day.py for each test day first.")
        sys.exit(1)

    print(f"\nLoading GPS pings from {len(parquet_files)} Parquet file(s) …")
    gps_df = pd.read_parquet(parquet_files, columns=[
        "vehicle_id", "route_id", "trip_id",
        "date_ist", "epoch_utc", "time_bucket_15min",
        "lat", "lng", "is_weekend"
    ])

    # epoch_utc → seconds since midnight IST (UTC+5:30 = +19800 s)
    IST_OFFSET_S = 19800
    gps_df["time_ist_s"] = (gps_df["epoch_utc"] + IST_OFFSET_S) % 86400

    print(f"  {len(gps_df):,} pings loaded across {gps_df['trip_id'].nunique():,} unique trip_ids.")

    # ── 3. For each trip, interpolate stop crossing times ─────────────────────
    records = []
    skipped_no_gtfs   = 0
    skipped_few_pings = 0
    skipped_bad_pause = 0

    grouped = gps_df.sort_values("epoch_utc").groupby("trip_id")
    total_trips = len(grouped)
    processed = 0

    for trip_id, grp in grouped:
        processed += 1
        if processed % 500 == 0:
            print(f"  Processed {processed:,}/{total_trips:,} trips …")

        # Need GTFS stop sequence for this trip
        stops = trip_stops.get(str(trip_id))
        if not stops or len(stops) < 2:
            skipped_no_gtfs += 1
            continue

        # Sort pings by epoch
        pings = grp.sort_values("epoch_utc")
        if len(pings) < MIN_PINGS:
            skipped_few_pings += 1
            continue

        # Check for long unexplained pauses
        ping_times = pings["epoch_utc"].to_numpy()
        if np.any(np.diff(ping_times) > MAX_PAUSE_S):
            skipped_bad_pause += 1
            continue

        # Sort stops by sequence
        stops_sorted = sorted(stops, key=lambda x: x[0])

        vehicle_id = pings["vehicle_id"].iloc[0]
        route_id   = pings["route_id"].iloc[0]
        date_ist   = pings["date_ist"].iloc[0]
        is_weekend = int(pings["is_weekend"].iloc[0])

        ping_lats  = pings["lat"].to_numpy()
        ping_lons  = pings["lng"].to_numpy()
        ping_times_ist = pings["time_ist_s"].to_numpy()
        ping_epochs    = pings["epoch_utc"].to_numpy()

        # For each stop, find nearest ping in time
        def nearest_ping_time_s(stop_lat, stop_lon):
            """Find the IST time (s since midnight) when bus was nearest to stop."""
            dists = np.array([
                haversine_m(stop_lat, stop_lon, lat, lon)
                for lat, lon in zip(ping_lats, ping_lons)
            ])
            idx = int(np.argmin(dists))
            if dists[idx] > 500.0:   # bus never came within 500 m — skip
                return None
            return float(ping_times_ist[idx])

        # Compute crossing time for each stop
        stop_crossings = []  # (seq, stop_id, crossing_time_s)
        for seq, stop_id, gtfs_arrival_s in stops_sorted:
            pos = stop_pos.get(stop_id)
            if pos is None:
                continue
            t = nearest_ping_time_s(pos[0], pos[1])
            if t is not None:
                stop_crossings.append((seq, stop_id, t))

        if len(stop_crossings) < 2:
            continue

        # Emit consecutive stop-pair records
        for i in range(len(stop_crossings) - 1):
            seq_a, sid_a, t_a = stop_crossings[i]
            seq_b, sid_b, t_b = stop_crossings[i + 1]

            duration_s = t_b - t_a
            if duration_s <= 0 or duration_s > 7200:   # ignore negative / >2h
                continue

            pos_a = stop_pos.get(sid_a)
            pos_b = stop_pos.get(sid_b)
            dist_m = haversine_m(*pos_a, *pos_b) if pos_a and pos_b else None

            if dist_m is not None and dist_m > MAX_STOP_GAP_M:
                continue    # skip very long inter-stop distances

            records.append({
                "trip_id":             str(trip_id),
                "vehicle_id":          str(vehicle_id),
                "route_id":            str(route_id),
                "date_ist":            str(date_ist),
                "is_weekend":          is_weekend,
                "from_stop_seq":       int(seq_a),
                "to_stop_seq":         int(seq_b),
                "from_stop_id":        str(sid_a),
                "to_stop_id":          str(sid_b),
                "actual_start_time_s": float(t_a),
                "actual_duration_s":   float(duration_s),
                "distance_m":          float(dist_m) if dist_m is not None else None,
            })

    # ── 4. Save results ───────────────────────────────────────────────────────
    print(f"\nBuilt {len(records):,} stop-pair ground-truth records.")
    if not records:
        print("WARNING: No records produced. Check test day data and GTFS trip_id format.")
        sys.exit(1)

    result_df = pd.DataFrame(records)
    result_df.to_parquet(OUT_FILE, compression="snappy", index=False)

    elapsed = time.time() - t0
    manifest = {
        "built_at":           datetime.now(timezone.utc).isoformat(),
        "test_days":          test_days,
        "parquet_files_read": len(parquet_files),
        "total_trips":        total_trips,
        "skipped_no_gtfs":    skipped_no_gtfs,
        "skipped_few_pings":  skipped_few_pings,
        "skipped_bad_pause":  skipped_bad_pause,
        "records_produced":   len(records),
        "unique_trips":       int(result_df["trip_id"].nunique()),
        "unique_routes":      int(result_df["route_id"].nunique()),
        "output_file":        str(OUT_FILE),
        "elapsed_s":          round(elapsed, 2),
    }
    with open(MANIFEST_FILE, "w") as f:
        json.dump(manifest, f, indent=2)

    print(f"\n=== Ground Truth Built in {elapsed:.2f}s ===")
    print(f"  Records:        {len(records):,}")
    print(f"  Unique trips:   {manifest['unique_trips']:,}")
    print(f"  Unique routes:  {manifest['unique_routes']:,}")
    print(f"  Output:         {OUT_FILE}")
    print(f"  Manifest:       {MANIFEST_FILE}")


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="PULSE Ground-Truth Builder (Phase 1.2)")
    parser.add_argument(
        "--test-days", type=int, nargs="+", metavar="DAY",
        default=TEST_DAYS,
        help=f"Day-of-month numbers to use as test set (default: {TEST_DAYS})"
    )
    args = parser.parse_args()
    build_ground_truth(test_days=args.test_days)
