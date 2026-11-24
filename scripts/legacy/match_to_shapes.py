"""
PULSE Shape Matcher (scripts/match_to_shapes.py)
Phase 2.2 — projects every GPS ping onto its GTFS route shape.

For each trip:
  1. Gets the GTFS shape from trip_id → shape_id.
  2. Projects each ping to the nearest point on that shape (shape_dist_traveled).
  3. Makes distance monotonically non-decreasing (removes GPS jitter going backwards).
  4. Drops pings farther than MAX_SNAP_M from the shape.

Output Parquet schema (per day):
  trip_id, vehicle_id, route_id, shape_id, date_ist, epoch_utc,
  hour_ist, time_bucket_15min, day_type, is_weekend,
  lat, lng, snap_dist_m,          # distance from GPS point to shape
  shape_dist_m                    # cumulative distance along shape (monotone)

Usage:
  python scripts/match_to_shapes.py --date 2026-10-01
  python scripts/match_to_shapes.py --date-range 2026-10-01 2026-10-24
"""

import sys
import time
import json
import argparse
from pathlib import Path
from datetime import datetime, timezone, date, timedelta

import numpy as np
import pandas as pd
from pyproj import Transformer
import duckdb

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.core.config import settings

# ── Constants ────────────────────────────────────────────────────────────────
MAX_SNAP_M   = 50.0    # maximum distance from shape to accept a ping
GTFS_DB      = settings.DATABASE_ROOT / "gtfs.duckdb"
HIST_DIR     = settings.PROCESSED_DATA_ROOT / "historical"
MATCHED_DIR  = settings.DATA_ROOT / "processed" / "matched"

transformer_fwd = Transformer.from_crs("EPSG:4326", "EPSG:32643", always_xy=True)


# ── Shape geometry cache ─────────────────────────────────────────────────────

class ShapeCache:
    """Loads and caches GTFS shape polylines and trip→shape mapping."""

    def __init__(self):
        if not GTFS_DB.exists():
            raise FileNotFoundError(f"GTFS DB not found: {GTFS_DB}. Run ingest_gtfs.py first.")
        con = duckdb.connect(str(GTFS_DB), read_only=True)
        print("Loading trip→shape mapping…")
        trips = con.execute(
            "SELECT trip_id, shape_id, route_id FROM trips WHERE shape_id IS NOT NULL"
        ).df()
        self.trip_to_shape: dict[str, str]  = dict(zip(trips["trip_id"].astype(str),
                                                        trips["shape_id"].astype(str)))
        self.trip_to_route: dict[str, str]  = dict(zip(trips["trip_id"].astype(str),
                                                        trips["route_id"].astype(str)))

        print("Loading shape point coordinates…")
        shapes = con.execute(
            "SELECT shape_id, shape_pt_lat, shape_pt_lon, shape_pt_sequence "
            "FROM shapes ORDER BY shape_id, shape_pt_sequence"
        ).df()
        con.close()

        # Build projected shape arrays: shape_id → (N×2 array in EPSG:32643, cumulative dist)
        self._shapes: dict[str, tuple[np.ndarray, np.ndarray]] = {}
        for sid, grp in shapes.groupby("shape_id"):
            lons = grp["shape_pt_lon"].to_numpy()
            lats = grp["shape_pt_lat"].to_numpy()
            xs, ys = transformer_fwd.transform(lons, lats)
            pts = np.column_stack([xs, ys])   # (N, 2)
            diffs = np.diff(pts, axis=0)
            seg_len = np.sqrt((diffs**2).sum(axis=1))
            cum_dist = np.concatenate([[0.0], np.cumsum(seg_len)])
            self._shapes[str(sid)] = (pts, cum_dist)

        print(f"  {len(self._shapes):,} shapes loaded.")

    def get_shape(self, shape_id: str):
        return self._shapes.get(shape_id)


def _snap_pings_to_shape(
    ping_xs: np.ndarray, ping_ys: np.ndarray,
    shape_pts: np.ndarray, shape_cum: np.ndarray
) -> tuple[np.ndarray, np.ndarray]:
    """
    Vectorised snap of N pings to a polyline with M−1 segments.
    Returns (snap_dist_m, shape_dist_m):
      snap_dist_m   – perpendicular distance from ping to nearest segment (m)
      shape_dist_m  – cumulative distance along shape at the snap point (m)
    """
    N = len(ping_xs)
    M = len(shape_pts)

    best_snap  = np.full(N, np.inf)
    best_sdist = np.zeros(N)

    for i in range(M - 1):
        ax, ay = shape_pts[i]
        bx, by = shape_pts[i + 1]
        abx, aby = bx - ax, by - ay
        ab2 = abx**2 + aby**2
        if ab2 == 0:
            continue

        apx = ping_xs - ax
        apy = ping_ys - ay
        t   = np.clip((apx*abx + apy*aby) / ab2, 0.0, 1.0)

        cx = ax + t * abx
        cy = ay + t * aby
        d  = np.sqrt((ping_xs - cx)**2 + (ping_ys - cy)**2)

        seg_len_i  = np.sqrt(ab2)
        snap_along = shape_cum[i] + t * seg_len_i

        better = d < best_snap
        best_snap  = np.where(better, d,          best_snap)
        best_sdist = np.where(better, snap_along, best_sdist)

    return best_snap, best_sdist


def match_day(date_str: str, cache: ShapeCache) -> dict:
    year, month, day = date_str.split("-")
    in_dir  = HIST_DIR / f"year={year}/month={month:}/day={day}"
    out_dir = MATCHED_DIR / f"year={year}/month={month}/day={day}"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_file = out_dir / "matched.parquet"

    parquet_files = list(in_dir.glob("*.parquet"))
    if not parquet_files:
        return {"date": date_str, "status": "NO_INPUT", "records": 0}

    df = pd.read_parquet(parquet_files, columns=[
        "vehicle_id", "trip_id", "route_id", "date_ist",
        "epoch_utc", "hour_ist", "time_bucket_15min",
        "is_weekend", "day_type",
        "lat", "lng", "proj_x", "proj_y",
    ])

    out_rows = []
    skipped_no_shape  = 0
    skipped_bad_snap  = 0
    total_in          = len(df)

    for trip_id, grp in df.groupby("trip_id"):
        tid = str(trip_id)
        shape_id = cache.trip_to_shape.get(tid)
        if shape_id is None:
            skipped_no_shape += len(grp)
            continue

        shape_data = cache.get_shape(shape_id)
        if shape_data is None:
            skipped_no_shape += len(grp)
            continue

        shape_pts, shape_cum = shape_data
        grp = grp.sort_values("epoch_utc")

        px = grp["proj_x"].to_numpy()
        py = grp["proj_y"].to_numpy()

        snap_d, shape_d = _snap_pings_to_shape(px, py, shape_pts, shape_cum)

        # Drop pings too far from shape
        ok = snap_d <= MAX_SNAP_M
        skipped_bad_snap += int((~ok).sum())
        if not ok.any():
            continue

        # Make shape_dist monotonically non-decreasing (remove backwards jitter)
        sd_ok = shape_d[ok]
        mono  = np.maximum.accumulate(sd_ok)

        sub = grp[ok].copy()
        sub["snap_dist_m"]  = snap_d[ok]
        sub["shape_dist_m"] = mono
        sub["shape_id"]     = shape_id
        out_rows.append(sub)

    if not out_rows:
        return {"date": date_str, "status": "NO_MATCHES",
                "total_in": total_in, "records": 0,
                "skipped_no_shape": skipped_no_shape,
                "skipped_bad_snap": skipped_bad_snap}

    result = pd.concat(out_rows, ignore_index=True)
    keep = ["trip_id", "vehicle_id", "route_id", "shape_id", "date_ist",
            "epoch_utc", "hour_ist", "time_bucket_15min", "day_type", "is_weekend",
            "lat", "lng", "snap_dist_m", "shape_dist_m"]
    result[[c for c in keep if c in result.columns]].to_parquet(
        out_file, compression="snappy", index=False
    )

    return {
        "date":               date_str,
        "status":             "OK",
        "total_in":           total_in,
        "records":            len(result),
        "skipped_no_shape":   skipped_no_shape,
        "skipped_bad_snap":   skipped_bad_snap,
        "output":             str(out_file),
    }


def main():
    parser = argparse.ArgumentParser(description="PULSE Shape Matcher (Phase 2.2)")
    grp = parser.add_mutually_exclusive_group(required=True)
    grp.add_argument("--date",       help="Single date YYYY-MM-DD")
    grp.add_argument("--date-range", nargs=2, metavar=("START", "END"),
                     help="Inclusive date range YYYY-MM-DD YYYY-MM-DD")
    args = parser.parse_args()

    cache = ShapeCache()

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
        print(f"\n── Matching {d} ──")
        result = match_day(d, cache)
        manifest_rows.append(result)
        if result["status"] == "OK":
            print(f"  Matched {result['records']:,} pings "
                  f"(dropped: no_shape={result['skipped_no_shape']:,}, "
                  f"bad_snap={result['skipped_bad_snap']:,})")
        else:
            print(f"  Status: {result['status']}")

    # Save manifest
    manifest_path = settings.MANIFEST_ROOT / "match_manifest.json"
    with open(manifest_path, "w") as f:
        json.dump({
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "elapsed_s":    round(time.time() - t0, 2),
            "days":         manifest_rows,
        }, f, indent=2)

    print(f"\n=== Shape matching complete in {time.time()-t0:.1f}s ===")
    print(f"Manifest: {manifest_path}")


if __name__ == "__main__":
    main()
