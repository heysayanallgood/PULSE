# Phase 0 Preflight Report — PULSE
**Date:** 2026-11-20  
**Host:** Windows 11 Desktop  
**Workspace:** `E:\Pulse` on SanDisk PortableSSD (exFAT, 1.82 TB total, 793.22 GB free)  

---

## 1. Storage & Environment Assessment
- **Workspace Disk (`E:`):** 793.22 GB free out of 1.82 TB. Sufficient space for all processed Parquet, analytical models, DuckDB databases, logs, and cache.
- **Operating System Disk (`C:`):** 4.02 GB free remaining. **Crucial operational invariant:** No data, package caches, virtual environments, or analytical spills may be placed on `C:`. Pip caching is explicitly routed to `E:\Pulse\data\cache\pip`.
- **Python Environment:** Miniconda Python 3.12.9 located at `C:\Users\User\miniconda3\python.exe`.
- **Project Virtual Environment:** `E:\Pulse\.venv` successfully created using Python 3.12.9 (pip 24.3.1).
- **Git Version:** 2.56.0.windows.3 available.

---

## 2. Dataset Inventory & Integrity Verification

### A. Historical GPS Archive (`delhi-dtc-bus-gtfs-rt-2026-10`)
- **Archive Status:** Compressed 7z file `delhi-dtc-bus-gtfs-rt-2026-10.7z` (16.07 GB) preserved and immutable.
- **Extracted Status:** **All 31 daily SQLite databases** (`bus_movements_2026_10_01.db` through `bus_movements_2026_10_31.db`) are already uncompressed and present in `E:\Pulse\delhi-dtc-bus-gtfs-rt-2026-10`.
- **Individual Database Inspection (`bus_movements_2026_10_01.db`):**
  - Table name: `vehicle_feed`
  - Columns:
    - `vehicle_id` (TEXT): Bus registration number (e.g. DL1PD6884)
    - `lat` (TEXT): WGS84 latitude as text string (e.g. '28.7040405273437')
    - `lng` (TEXT): WGS84 longitude as text string (e.g. '77.259033203125')
    - `speed` (REAL): Speed in meters per second (min 0.0, max 54.72, avg 9.77 m/s ≈ 35.2 km/h)
    - `route_id` (REAL): Route identifier stored as float (e.g. 1728.0)
    - `trip_id` (TEXT): Assigned trip identifier (e.g. '1728_21_54_1365')
    - `timestamp` (TEXT): Unix epoch seconds UTC (e.g. '1790792992')
    - `date` (DATE): IST calendar date (e.g. '2026-10-01')
    - `time` (TEXT): IST clock time (e.g. '00:00:01')
  - Record Count (Day 1): **31,290,299 observations**
  - Distinct Vehicles: **6,264**
  - Distinct Routes: **2,201**
  - Distinct Trips: **80,637**

### B. Static GTFS Dataset (`delhi_buses_static_gtfs_v1`)
- **Archive Status:** `delhi_buses_static_gtfs_v1.zip` (30.05 MB) preserved.
- **Extracted Status:** Directory `E:\Pulse\delhi_buses_static_gtfs_v1` verified with complete GTFS files:
  - `stops.txt`: 6,862 stops with latitude, longitude, and stop names.
  - `routes.txt`: 2,574 routes across DTC and DIMTS agencies.
  - `trips.txt`: 80,357 scheduled trips.
  - `shapes.txt`: 965,607 shape coordinate points defining physical bus route corridors.
  - `stop_times.txt`: 2,737,136 scheduled stop times.
  - `agency.txt`, `calendar.txt`, `feed_info.txt`.

### C. Live Realtime Feed
- Endpoint: `https://otd.delhi.gov.in/api/realtime/VehiclePositions.pb`
- Protocol: Protocol Buffers (GTFS-RT)
- Configured via local `.env` variables (`OTD_API_KEY`, `OTD_API_KEY_PARAM`).

---

## 3. ID Cross-Referencing Verification
- Cross-referencing `route_id` 1728.0 from SQLite `vehicle_feed` directly resolves to `route_id` '1728' in GTFS `routes.txt` (DTC Route 227AUP, Old Delhi Railway Station to Sabha Pur X-ing).
- GTFS `trips.txt` contains 100 scheduled trips for route 1728 mapped to `shape_id` `shp_3_2436`.
- GTFS `shapes.txt` provides the exact physical road alignment for metric map-matching.

---

## 4. Phase 0 Acceptance Gate Status: PASSED
- [x] Workspace identified and confirmed at `E:\Pulse`
- [x] Storage verified: 793.22 GB free on `E:`, with safeguards against writing to `C:`
- [x] Static GTFS files inventoried, parsed, and validated
- [x] Historical 31-day archive verified (all 31 daily SQLite databases extracted)
- [x] Raw databases remain immutable
- [x] Python 3.12.9 virtual environment active
- [x] Preflight report documented
