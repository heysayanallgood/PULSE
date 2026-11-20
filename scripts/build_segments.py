"""
PULSE Shape Segmentation Engine (scripts/build_segments.py)
Implements ADR 003: Slices all GTFS route shapes into stable 300m–500m metric segments
in projected EPSG:32643 (UTM Zone 43N) coordinates and stores them in gtfs.duckdb.
"""
import time
import math
import duckdb
from pyproj import Transformer
from shapely.geometry import LineString
from pathlib import Path

DB_PATH = Path("E:/Pulse/data/database/gtfs.duckdb")
transformer = Transformer.from_crs("EPSG:4326", "EPSG:32643", always_xy=True)


def build_route_segments(target_length_m: float = 400.0):
    print("=== Building Metric Route Segments (ADR 003) ===")
    con = duckdb.connect(str(DB_PATH))
    con.execute("SET temp_directory = 'E:/Pulse/data/cache/duckdb';")

    # Drop previous segments table if exists
    con.execute("DROP TABLE IF EXISTS route_segments;")
    con.execute("""
        CREATE TABLE route_segments (
            segment_id VARCHAR PRIMARY KEY,
            shape_id VARCHAR,
            segment_sequence INTEGER,
            start_dist_m DOUBLE,
            end_dist_m DOUBLE,
            length_m DOUBLE,
            start_lat DOUBLE,
            start_lon DOUBLE,
            end_lat DOUBLE,
            end_lon DOUBLE
        );
    """)

    t0 = time.time()
    
    # Fetch distinct shape_ids
    shapes = con.execute("SELECT DISTINCT shape_id FROM shapes ORDER BY shape_id;").fetchall()
    print(f"Total shapes to segment: {len(shapes):,}")

    total_segments = 0
    batch = []

    for idx, (shape_id,) in enumerate(shapes):
        # Fetch shape points in sequence
        pts = con.execute("""
            SELECT shape_pt_lat, shape_pt_lon, shape_pt_sequence
            FROM shapes
            WHERE shape_id = ?
            ORDER BY shape_pt_sequence ASC;
        """, [shape_id]).fetchall()

        if len(pts) < 2:
            continue

        # Project coordinates to EPSG:32643
        projected_coords = []
        for lat, lon, seq in pts:
            x, y = transformer.transform(lon, lat)
            projected_coords.append((x, y))

        line = LineString(projected_coords)
        total_len = line.length

        if total_len < 100.0:
            continue

        num_segments = max(1, round(total_len / target_length_m))
        seg_step = total_len / num_segments

        # Inverse transformer back to lat/lon for segment boundary coordinates
        inv_transformer = Transformer.from_crs("EPSG:32643", "EPSG:4326", always_xy=True)

        for s_idx in range(num_segments):
            d_start = s_idx * seg_step
            d_end = min((s_idx + 1) * seg_step, total_len)
            seg_len = d_end - d_start

            pt_start = line.interpolate(d_start)
            pt_end = line.interpolate(d_end)

            start_lon, start_lat = inv_transformer.transform(pt_start.x, pt_start.y)
            end_lon, end_lat = inv_transformer.transform(pt_end.x, pt_end.y)

            seg_id = f"{shape_id}_seg_{s_idx+1:03d}"
            batch.append((
                seg_id, shape_id, s_idx + 1,
                round(d_start, 2), round(d_end, 2), round(seg_len, 2),
                round(start_lat, 6), round(start_lon, 6),
                round(end_lat, 6), round(end_lon, 6)
            ))
            total_segments += 1

        if len(batch) >= 10000:
            con.executemany("INSERT INTO route_segments VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?);", batch)
            batch.clear()

        if (idx + 1) % 500 == 0:
            print(f"  Processed {idx+1:,} / {len(shapes):,} shapes... (Segments so far: {total_segments:,})")

    if batch:
        con.executemany("INSERT INTO route_segments VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?);", batch)
        batch.clear()

    con.execute("CREATE INDEX idx_seg_shape ON route_segments(shape_id);")

    elapsed = time.time() - t0
    print(f"\n=== Route Segmentation Completed in {elapsed:.2f}s ===")
    print(f"Total Segments Created: {total_segments:,}")
    print(f"Average segments per shape: {total_segments / max(len(shapes), 1):.1f}")

    con.close()


if __name__ == "__main__":
    build_route_segments()
