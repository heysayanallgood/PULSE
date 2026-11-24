"""
PULSE Static GTFS Ingestion Pipeline (scripts/ingest_gtfs.py)
Reads raw GTFS text files from delhi_buses_static_gtfs_v1
and creates an indexed, validated analytical DuckDB database at data/database/gtfs.duckdb.
"""
import os
import sys
import time
import duckdb
from pathlib import Path

GTFS_DIR = Path("delhi_buses_static_gtfs_v1")
DB_PATH = Path("data/database/gtfs.duckdb")

def ingest_gtfs():
    print(f"=== Starting Static GTFS Ingestion ===")
    print(f"Source Directory: {GTFS_DIR}")
    print(f"Target Database:  {DB_PATH}")
    
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    if DB_PATH.exists():
        print(f"Removing previous database at {DB_PATH}")
        try:
            DB_PATH.unlink()
        except Exception as e:
            print(f"Note: {e}")
        
    con = duckdb.connect(str(DB_PATH))
    con.execute("SET temp_directory = 'data/cache/duckdb';")
    
    t0 = time.time()
    
    # 1. Ingest agency.txt
    print("Ingesting agency.txt...")
    con.execute(f"""
        CREATE TABLE agency AS 
        SELECT 
            TRIM(CAST(agency_id AS VARCHAR)) AS agency_id,
            TRIM(CAST(agency_name AS VARCHAR)) AS agency_name,
            TRIM(CAST(agency_url AS VARCHAR)) AS agency_url,
            TRIM(CAST(agency_timezone AS VARCHAR)) AS agency_timezone,
            TRIM(CAST(agency_lang AS VARCHAR)) AS agency_lang,
            TRIM(CAST(agency_phone AS VARCHAR)) AS agency_phone
        FROM read_csv('{(GTFS_DIR / "agency.txt").as_posix()}', header=True, all_varchar=True);
    """)
    
    # 2. Ingest calendar.txt
    print("Ingesting calendar.txt...")
    con.execute(f"""
        CREATE TABLE calendar AS 
        SELECT 
            TRIM(CAST(service_id AS VARCHAR)) AS service_id,
            CAST(monday AS INTEGER) AS monday,
            CAST(tuesday AS INTEGER) AS tuesday,
            CAST(wednesday AS INTEGER) AS wednesday,
            CAST(thursday AS INTEGER) AS thursday,
            CAST(friday AS INTEGER) AS friday,
            CAST(saturday AS INTEGER) AS saturday,
            CAST(sunday AS INTEGER) AS sunday,
            TRIM(CAST(start_date AS VARCHAR)) AS start_date,
            TRIM(CAST(end_date AS VARCHAR)) AS end_date
        FROM read_csv('{(GTFS_DIR / "calendar.txt").as_posix()}', header=True, all_varchar=True);
    """)
    
    # 3. Ingest routes.txt
    print("Ingesting routes.txt...")
    con.execute(f"""
        CREATE TABLE routes AS 
        SELECT 
            TRIM(CAST(route_id AS VARCHAR)) AS route_id,
            TRIM(CAST(agency_id AS VARCHAR)) AS agency_id,
            TRIM(CAST(route_short_name AS VARCHAR)) AS route_short_name,
            TRIM(CAST(route_long_name AS VARCHAR)) AS route_long_name,
            TRIM(CAST(route_desc AS VARCHAR)) AS route_desc,
            CAST(route_type AS INTEGER) AS route_type
        FROM read_csv('{(GTFS_DIR / "routes.txt").as_posix()}', header=True, all_varchar=True);
    """)
    con.execute("CREATE INDEX idx_routes_id ON routes(route_id);")
    
    # 4. Ingest stops.txt
    print("Ingesting stops.txt...")
    con.execute(f"""
        CREATE TABLE stops AS 
        SELECT 
            TRIM(CAST(stop_id AS VARCHAR)) AS stop_id,
            TRIM(CAST(stop_code AS VARCHAR)) AS stop_code,
            TRIM(CAST(stop_name AS VARCHAR)) AS stop_name,
            CAST(stop_lat AS DOUBLE) AS stop_lat,
            CAST(stop_lon AS DOUBLE) AS stop_lon
        FROM read_csv('{(GTFS_DIR / "stops.txt").as_posix()}', header=True, all_varchar=True);
    """)
    con.execute("CREATE INDEX idx_stops_id ON stops(stop_id);")
    con.execute("CREATE INDEX idx_stops_name ON stops(stop_name);")
    
    # 5. Ingest trips.txt
    print("Ingesting trips.txt (~80K rows)...")
    con.execute(f"""
        CREATE TABLE trips AS 
        SELECT 
            TRIM(CAST(trip_id AS VARCHAR)) AS trip_id,
            TRIM(CAST(route_id AS VARCHAR)) AS route_id,
            TRIM(CAST(service_id AS VARCHAR)) AS service_id,
            TRIM(CAST(trip_headsign AS VARCHAR)) AS trip_headsign,
            TRIM(CAST(shape_id AS VARCHAR)) AS shape_id,
            TRY_CAST(direction_id AS INTEGER) AS direction_id
        FROM read_csv('{(GTFS_DIR / "trips.txt").as_posix()}', header=True, all_varchar=True);
    """)
    con.execute("CREATE INDEX idx_trips_id ON trips(trip_id);")
    con.execute("CREATE INDEX idx_trips_route ON trips(route_id);")
    con.execute("CREATE INDEX idx_trips_shape ON trips(shape_id);")
    
    # 6. Ingest stop_times.txt
    print("Ingesting stop_times.txt (~2.7M rows)...")
    con.execute(f"""
        CREATE TABLE stop_times AS 
        SELECT 
            TRIM(CAST(trip_id AS VARCHAR)) AS trip_id,
            TRIM(CAST(arrival_time AS VARCHAR)) AS arrival_time,
            TRIM(CAST(departure_time AS VARCHAR)) AS departure_time,
            TRIM(CAST(stop_id AS VARCHAR)) AS stop_id,
            CAST(stop_sequence AS INTEGER) AS stop_sequence,
            TRY_CAST(stop_dist AS DOUBLE) AS stop_dist
        FROM read_csv('{(GTFS_DIR / "stop_times.txt").as_posix()}', header=True, all_varchar=True);
    """)
    con.execute("CREATE INDEX idx_st_trip_seq ON stop_times(trip_id, stop_sequence);")
    con.execute("CREATE INDEX idx_st_stop ON stop_times(stop_id);")
    
    # 7. Ingest shapes.txt
    print("Ingesting shapes.txt (~965K points)...")
    con.execute(f"""
        CREATE TABLE shapes AS 
        SELECT 
            TRIM(CAST(shape_id AS VARCHAR)) AS shape_id,
            CAST(shape_pt_lat AS DOUBLE) AS shape_pt_lat,
            CAST(shape_pt_lon AS DOUBLE) AS shape_pt_lon,
            CAST(shape_pt_sequence AS INTEGER) AS shape_pt_sequence,
            TRY_CAST(shape_dist_traveled AS DOUBLE) AS shape_dist_traveled
        FROM read_csv('{(GTFS_DIR / "shapes.txt").as_posix()}', header=True, all_varchar=True);
    """)
    con.execute("CREATE INDEX idx_shapes_id_seq ON shapes(shape_id, shape_pt_sequence);")
    
    elapsed = time.time() - t0
    print(f"\n=== GTFS Ingestion Completed in {elapsed:.2f} seconds ===")
    
    tables = ["agency", "calendar", "routes", "stops", "trips", "stop_times", "shapes"]
    for t in tables:
        count = con.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
        print(f"  Table '{t:12s}': {count:10,d} rows")
        
    con.close()
    print(f"Database written to: {DB_PATH} ({DB_PATH.stat().st_size / (1024**2):.2f} MB)")

if __name__ == "__main__":
    ingest_gtfs()
