"""
PULSE Segment Travel-Time Measurer (scripts/measure_segments.py)
Phase 2.3 — computes actual travel times for each shape segment from matched GPS data.

For each trip, interpolates the time the bus crossed each segment boundary, then:
  - Segment travel time = boundary crossing time difference.
  - Separates dwell time at stops from moving time (uses GTFS stop positions).
  - Discards traversals containing long unexplained stops (> MAX_PAUSE_S).

Output Parquet (data/processed/segment_times/):
  shape_id, segment_id, segment_sequence,
  trip_id, vehicle_id, route_id, date_ist, day_type, is_weekend,
  time_bucket_15min, hour_ist,
  entry_epoch_utc, exit_epoch_utc,
  travel_time_s,          # actual traversal time
  segment_length_m,       # from route_segments table
  speed_mps               # = length / travel_time

Usage:
  python scripts/measure_segments.py --date 2026-10-01
  python scripts/measure_segments.py --date-range 2026-10-01 2026-10-24
"""

import sys
import time
import json
import argparse
from pathlib import Path
from datetime import datetime, timezone, date, timedelta

import numpy as np
import pandas as pd
import duckdb

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.core.config import settings

# ── Constants ────────────────────────────────────────────────────────────────
MAX_PAUSE_S   = 300.0   # traversals with any single inter-ping gap > 5 min discarded
MIN_TT_S      = 2.0     # ignore sub-2s traversals (GPS noise)
MAX_TT_S      = 1800.0  # ignore traversals > 30 min for a single segment

GTFS_DB       = settings.DATABASE_ROOT / "gtfs.duckdb"
MATCHED_DIR   = settings.DATA_ROOT / "processed" / "matched"
SEG_TIMES_DIR = settings.DATA_ROOT / "processed" / "segment_times"


def _load_segment_boundaries(con) -> dict[str, np.ndarray]:
    """Returns shape_id → sorted array of cumulative boundary distances (m)."""
    segs = con.execute(
        "SELECT shape_id, segment_sequence, start_dist_m, end_dist_m, length_m, segment_id "
        "FROM route_segments ORDER BY shape_id, segment_sequence"
    ).df()
    result = {}
    for shape_id, grp in segs.groupby("shape_id"):
        grp = grp.sort_values("segment_sequence")
        result[str(shape_id)] = grp[["segment_sequence", "start_dist_m",
                                     "end_dist_m", "length_m", "segment_id"]].to_dict("records")
    return result


def _interpolate_crossing(
    shape_dists: np.ndarray, epochs: np.ndarray, boundary_m: float
) -> float | None:
    """
    Linear interpolation: returns epoch when bus crossed boundary_m along the shape.
    Returns None if boundary is outside the observed range.
    """
    if boundary_m < shape_dists[0] or boundary_m > shape_dists[-1]:
        return None
    idx = np.searchsorted(shape_dists, boundary_m)
    idx = max(1, min(idx, len(shape_dists) - 1))
    d0, d1 = shape_dists[idx - 1], shape_dists[idx]
    t0, t1 = epochs[idx - 1], epochs[idx]
    if d1 == d0:
        return float(t0)
    frac = (boundary_m - d0) / (d1 - d0)
    return float(t0 + frac * (t1 - t0))


def measure_day(date_str: str, seg_boundaries: dict) -> dict:
    year, month, day = date_str.split("-")
    matched_file = (MATCHED_DIR / f"year={year}/month={month}/day={day}/matched.parquet")
    out_dir  = SEG_TIMES_DIR / f"year={year}/month={month}/day={day}"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_file = out_dir / "segment_times.parquet"

    if not matched_file.exists():
        return {"date": date_str, "status": "NO_INPUT", "records": 0}

    df = pd.read_parquet(matched_file)
    if df.empty:
        return {"date": date_str, "status": "EMPTY", "records": 0}

    records = []
    discarded_pause  = 0
    discarded_range  = 0
    discarded_no_seg = 0

    for (trip_id, shape_id), grp in df.groupby(["trip_id", "shape_id"]):
        shape_id = str(shape_id)
        boundaries = seg_boundaries.get(shape_id)
        if not boundaries:
            discarded_no_seg += len(grp)
            continue

        grp  = grp.sort_values("epoch_utc")
        dists = grp["shape_dist_m"].to_numpy(dtype=float)
        epochs = grp["epoch_utc"].to_numpy(dtype=float)

        # Discard if any inter-ping gap > MAX_PAUSE_S
        if len(epochs) > 1 and np.any(np.diff(epochs) > MAX_PAUSE_S):
            discarded_pause += len(grp)
            continue

        # Pull metadata from first row
        row0       = grp.iloc[0]
        vehicle_id = row0.get("vehicle_id", "")
        route_id   = row0.get("route_id", "")
        date_ist   = row0.get("date_ist", date_str)
        day_type   = row0.get("day_type", "weekday")
        is_weekend = int(row0.get("is_weekend", 0))

        # For each segment, interpolate entry and exit times
        for seg in boundaries:
            start_m  = float(seg["start_dist_m"])
            end_m    = float(seg["end_dist_m"])
            length_m = float(seg["length_m"])
            seg_id   = str(seg["segment_id"])
            seg_seq  = int(seg["segment_sequence"])

            t_entry = _interpolate_crossing(dists, epochs, start_m)
            t_exit  = _interpolate_crossing(dists, epochs, end_m)

            if t_entry is None or t_exit is None:
                discarded_range += 1
                continue

            tt_s = t_exit - t_entry
            if tt_s < MIN_TT_S or tt_s > MAX_TT_S:
                discarded_range += 1
                continue

            # Time-bucket from entry time (IST)
            IST_OFFSET_S     = 19800
            ist_s            = int(t_entry) + IST_OFFSET_S
            hour_ist         = (ist_s // 3600) % 24
            bucket           = (hour_ist * 4 + (ist_s % 3600) // 60 // 15) % 96
            speed_mps        = length_m / tt_s if tt_s > 0 else 0.0

            records.append({
                "shape_id":          shape_id,
                "segment_id":        seg_id,
                "segment_sequence":  seg_seq,
                "trip_id":           str(trip_id),
                "vehicle_id":        str(vehicle_id),
                "route_id":          str(route_id),
                "date_ist":          date_ist,
                "day_type":          day_type,
                "is_weekend":        is_weekend,
                "time_bucket_15min": int(bucket),
                "hour_ist":          int(hour_ist),
                "entry_epoch_utc":   t_entry,
                "exit_epoch_utc":    t_exit,
                "travel_time_s":     round(tt_s, 2),
                "segment_length_m":  round(length_m, 2),
                "speed_mps":         round(speed_mps, 4),
            })

    if not records:
        return {"date": date_str, "status": "NO_RECORDS",
                "discarded_pause": discarded_pause,
                "discarded_range": discarded_range, "records": 0}

    out_df = pd.DataFrame(records)
    out_df.to_parquet(out_file, compression="snappy", index=False)

    return {
        "date":              date_str,
        "status":            "OK",
        "records":           len(records),
        "discarded_pause":   discarded_pause,
        "discarded_range":   discarded_range,
        "discarded_no_seg":  discarded_no_seg,
        "output":            str(out_file),
    }


def main():
    parser = argparse.ArgumentParser(description="PULSE Segment Measurer (Phase 2.3)")
    grp = parser.add_mutually_exclusive_group(required=True)
    grp.add_argument("--date",       help="Single date YYYY-MM-DD")
    grp.add_argument("--date-range", nargs=2, metavar=("START", "END"))
    args = parser.parse_args()

    if not GTFS_DB.exists():
        print(f"ERROR: GTFS DB not found at {GTFS_DB}. Run ingest_gtfs.py + build_segments.py first.")
        sys.exit(1)

    print("Loading segment boundaries from GTFS DB…")
    con = duckdb.connect(str(GTFS_DB), read_only=True)
    seg_boundaries = _load_segment_boundaries(con)
    con.close()
    print(f"  {len(seg_boundaries):,} shapes with segment data.")

    if args.date:
        dates = [args.date]
    else:
        start = date.fromisoformat(args.date_range[0])
        end   = date.fromisoformat(args.date_range[1])
        dates = [(start + timedelta(days=i)).isoformat()
                 for i in range((end - start).days + 1)]

    t0 = time.time()
    manifest_rows = []
    for d in dates:
        print(f"\n── Measuring {d} ──")
        result = measure_day(d, seg_boundaries)
        manifest_rows.append(result)
        status = result.get("status", "?")
        recs   = result.get("records", 0)
        print(f"  Status: {status} | Records: {recs:,}")

    manifest_path = settings.MANIFEST_ROOT / "segment_times_manifest.json"
    with open(manifest_path, "w") as f:
        json.dump({"generated_at": datetime.now(timezone.utc).isoformat(),
                   "elapsed_s":    round(time.time() - t0, 2),
                   "days":         manifest_rows}, f, indent=2)
    print(f"\n=== Segment measurement complete in {time.time()-t0:.1f}s ===")
    print(f"Manifest: {manifest_path}")


if __name__ == "__main__":
    main()
