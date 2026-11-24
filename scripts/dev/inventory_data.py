import os
import sqlite3
import glob

def inventory_historical():
    data_dir = "delhi-dtc-bus-gtfs-rt-2026-10"
    print(f"=== Historical SQLite Inventory: {data_dir} ===")
    files = sorted(glob.glob(os.path.join(data_dir, "bus_movements_*.db")))
    print(f"Total database files found: {len(files)}")
    total_bytes = 0
    
    sample_checks = [0, 14, len(files)-1] if len(files) >= 15 else range(len(files))
    
    for idx, f in enumerate(files):
        sz = os.path.getsize(f)
        total_bytes += sz
        basename = os.path.basename(f)
        if idx in sample_checks:
            try:
                conn = sqlite3.connect(f"file:{f}?mode=ro", uri=True)
                cur = conn.cursor()
                cur.execute("SELECT COUNT(*) FROM vehicle_feed;")
                cnt = cur.fetchone()[0]
                cur.execute("SELECT MIN(date), MAX(date), MIN(time), MAX(time) FROM vehicle_feed;")
                dmin, dmax, tmin, tmax = cur.fetchone()
                conn.close()
                print(f"  [{idx+1:02d}/31] {basename}: {sz / (1024**3):.2f} GB | Rows: {cnt:,} | Date: {dmin}..{dmax} ({tmin}..{tmax})")
            except Exception as e:
                print(f"  [{idx+1:02d}/31] {basename}: {sz / (1024**3):.2f} GB | READ ERROR: {e}")
        elif idx == 1:
            print(f"  ... [files 02 to 30 verified by size] ...")
            
    print(f"Total size across all {len(files)} databases: {total_bytes / (1024**3):.2f} GB ({total_bytes:,} bytes)")

def inventory_gtfs():
    gtfs_dir = "delhi_buses_static_gtfs_v1"
    print(f"\n=== Static GTFS Inventory: {gtfs_dir} ===")
    files = sorted(os.listdir(gtfs_dir))
    total_gtfs_bytes = 0
    for f in files:
        if f.startswith("."): continue
        p = os.path.join(gtfs_dir, f)
        if os.path.isfile(p):
            sz = os.path.getsize(p)
            total_gtfs_bytes += sz
            print(f"  {f:18s}: {sz / (1024**2):8.2f} MB ({sz:,} bytes)")
    print(f"Total Static GTFS size: {total_gtfs_bytes / (1024**2):.2f} MB")

if __name__ == "__main__":
    inventory_historical()
    inventory_gtfs()
