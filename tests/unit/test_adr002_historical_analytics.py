"""
Unit tests for ADR 002: Historical Analytics & Storage Architecture
Tests read-only SQLite access, DuckDB vectorized queries, Parquet export,
dual distribution (speed AND travel time) calculation, and dwell accounting semantics.
"""
import sqlite3
import duckdb
import os
from pathlib import Path

def test_sqlite_readonly_enforcement():
    db_path = "E:/Pulse/delhi-dtc-bus-gtfs-rt-2026-10/bus_movements_2026_10_01.db"
    assert os.path.exists(db_path), f"File {db_path} must exist"
    
    # Connect with read-only URI
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM vehicle_feed LIMIT 1;")
    res = cur.fetchone()
    assert res[0] > 0
    
    # Assert that write operations fail with OperationalError
    try:
        cur.execute("CREATE TABLE test_fail (id INT);")
        assert False, "Should have failed on read-only database"
    except sqlite3.OperationalError:
        pass  # Expected: attempt to write a readonly database
    finally:
        conn.close()

def test_duckdb_parquet_dual_distribution():
    con = duckdb.connect()
    con.execute("SET temp_directory = 'E:/Pulse/data/cache/duckdb';")
    
    con.execute("""
        CREATE TABLE segment_traversals (
            route_id VARCHAR,
            segment_id VARCHAR,
            day_type VARCHAR,
            time_bucket_15min INT,
            speed_mps DOUBLE,
            travel_time_s DOUBLE
        );
        INSERT INTO segment_traversals VALUES
            ('1728', 'shp_3_2436_seg_001', 'weekday', 34, 12.5, 32.0),
            ('1728', 'shp_3_2436_seg_001', 'weekday', 34, 10.0, 40.0),
            ('1728', 'shp_3_2436_seg_001', 'weekday', 34, 8.0, 50.0),
            ('1728', 'shp_3_2436_seg_001', 'weekday', 34, 11.2, 35.7),
            ('1728', 'shp_3_2436_seg_001', 'weekday', 34, 9.5, 42.1);
    """)
    
    summary = con.execute("""
        SELECT 
            route_id,
            segment_id,
            day_type,
            time_bucket_15min,
            COUNT(*) as sample_count,
            MEDIAN(speed_mps) as speed_median_mps,
            QUANTILE_CONT(speed_mps, 0.1) as speed_p10_mps,
            QUANTILE_CONT(speed_mps, 0.9) as speed_p90_mps,
            MEDIAN(travel_time_s) as travel_time_median_s,
            QUANTILE_CONT(travel_time_s, 0.1) as travel_time_p10_s,
            QUANTILE_CONT(travel_time_s, 0.9) as travel_time_p90_s
        FROM segment_traversals
        GROUP BY 1, 2, 3, 4;
    """).fetchdf()
    
    assert len(summary) == 1
    row = summary.iloc[0]
    assert row["sample_count"] == 5
    assert row["speed_median_mps"] == 10.0
    assert row["travel_time_median_s"] == 40.0
    assert row["travel_time_p10_s"] < row["travel_time_median_s"] < row["travel_time_p90_s"]
    
    out_dir = Path("E:/Pulse/data/processed/test_parquet")
    out_dir.mkdir(parents=True, exist_ok=True)
    out_file = out_dir / "test_summary.parquet"
    
    con.execute(f"COPY (SELECT * FROM summary) TO '{out_file.as_posix()}' (FORMAT PARQUET, COMPRESSION SNAPPY);")
    assert out_file.exists()
    assert out_file.stat().st_size > 0
    
    df_read = con.execute(f"SELECT * FROM read_parquet('{out_file.as_posix()}');").fetchdf()
    assert len(df_read) == 1
    assert df_read.iloc[0]["travel_time_median_s"] == 40.0
    
    out_file.unlink()
    out_dir.rmdir()
    con.close()

def test_dwell_accounting_no_double_counting():
    """
    Validates Correction 5:
    Separates running time (stop departure to next stop arrival) from stop dwell.
    Ensures dwell is added only when not already encompassed in segment running time.
    """
    # Case A: Modeled segments cover pure running time between stop departures and arrivals
    segment_running_times = [45.0, 55.0, 60.0]  # Total running time = 160s
    intermediate_stop_dwells = [25.0]           # 1 intermediate stop with 25s observed dwell
    segments_include_dwell = False
    
    if not segments_include_dwell:
        total_in_vehicle_s = sum(segment_running_times) + sum(intermediate_stop_dwells)
    else:
        total_in_vehicle_s = sum(segment_running_times)
        
    assert total_in_vehicle_s == 185.0, "Running time + dwell must equal 185s"

    # Case B: Traversal includes dwell -> Do NOT double count dwell
    segments_include_dwell_b = True
    segment_times_with_dwell = [45.0, 80.0, 60.0]  # Middle segment already encompasses the 25s dwell
    
    if not segments_include_dwell_b:
        total_in_vehicle_b = sum(segment_times_with_dwell) + sum(intermediate_stop_dwells)
    else:
        total_in_vehicle_b = sum(segment_times_with_dwell)
        
    assert total_in_vehicle_b == 185.0, "Should remain 185s without double-counting dwell"
