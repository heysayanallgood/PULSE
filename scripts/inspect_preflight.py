import os
import sqlite3
import csv
import sys
from datetime import datetime

def inspect_sqlite():
    db_path = "E:/Pulse/delhi-dtc-bus-gtfs-rt-2026-10/bus_movements_2026_10_01.db"
    print(f"=== Inspecting SQLite DB: {db_path} ===")
    if not os.path.exists(db_path):
        print(f"File not found: {db_path}")
        return
    
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    cur = conn.cursor()
    
    cur.execute("SELECT name FROM sqlite_master WHERE type='table';")
    tables = cur.fetchall()
    print("Tables in DB:", tables)
    
    for tbl in tables:
        tbl_name = tbl[0]
        cur.execute(f"PRAGMA table_info({tbl_name});")
        cols = cur.fetchall()
        print(f"\nTable '{tbl_name}' columns (cid, name, type, notnull, dflt_value, pk):")
        for c in cols:
            print(f"  {c[1]}: {c[2]}")
            
        cur.execute(f"SELECT COUNT(*) FROM {tbl_name};")
        row_cnt = cur.fetchone()[0]
        print(f"Row count: {row_cnt:,}")
        
        cur.execute(f"SELECT * FROM {tbl_name} LIMIT 5;")
        samples = cur.fetchall()
        print("Sample rows:")
        for s in samples:
            print(" ", s)
            
        cur.execute(f"SELECT MIN(timestamp), MAX(timestamp), MIN(date), MAX(date) FROM {tbl_name};")
        tmin, tmax, dmin, dmax = cur.fetchone()
        print(f"Timestamp range: {tmin} to {tmax} (Date: {dmin} to {dmax})")
        
        cur.execute(f"SELECT COUNT(DISTINCT vehicle_id), COUNT(DISTINCT route_id), COUNT(DISTINCT trip_id) FROM {tbl_name};")
        v_cnt, r_cnt, tr_cnt = cur.fetchone()
        print(f"Distinct vehicles: {v_cnt:,}, Distinct route_ids: {r_cnt:,}, Distinct trip_ids: {tr_cnt:,}")
        
        cur.execute(f"SELECT MIN(speed), MAX(speed), AVG(speed) FROM {tbl_name} WHERE speed IS NOT NULL;")
        smin, smax, savg = cur.fetchone()
        print(f"Speed stats: min={smin}, max={smax}, avg={savg:.2f}")

    conn.close()

def inspect_gtfs():
    gtfs_dir = "E:/Pulse/delhi_buses_static_gtfs_v1"
    print(f"\n=== Inspecting Static GTFS in: {gtfs_dir} ===")
    files = ["agency.txt", "calendar.txt", "feed_info.txt", "routes.txt", "shapes.txt", "stops.txt", "trips.txt", "stop_times.txt"]
    for f in files:
        fpath = os.path.join(gtfs_dir, f)
        if not os.path.exists(fpath):
            print(f"MISSING: {f}")
            continue
        size_mb = os.path.getsize(fpath) / (1024 * 1024)
        with open(fpath, "r", encoding="utf-8-sig", errors="ignore") as fp:
            reader = csv.reader(fp)
            header = next(reader, None)
            count = sum(1 for _ in reader)
        print(f"{f:15s} | {size_mb:8.2f} MB | {count:10,d} rows | Columns: {header}")

if __name__ == "__main__":
    inspect_sqlite()
    inspect_gtfs()
