# PULSE — Data Sources & Lineage Documentation
**Project:** Predictive Urban Mobility & Live Spatiotemporal Engine  
**Team:** HopCode | **Hackathon:** Transport Stack Hackathon 2026 (Problem 1)  
**Authoritative Architectural Alignment:** ADR 001, ADR 002, ADR 006  

---

## 1. Summary of Data Sources

| Source Name | Format / Protocol | Location / Endpoint | Size on Disk | Role in PULSE | Provenance Status |
|---|---|---|---|---|---|
| **Historical GPS Archive** | 31 Daily SQLite Databases | `E:/Pulse/delhi-dtc-bus-gtfs-rt-2026-10/` | **115.50 GB** (124 GB uncompressed) | Spatiotemporal travel-time model training & evaluation | **IMMUTABLE RAW** (Read-Only) |
| **Static GTFS v1** | Text CSVs in GTFS standard | `E:/Pulse/delhi_buses_static_gtfs_v1/` | **161.74 MB** (8 files) | Network topology, stop coordinates, route shapes, service calendar | **IMMUTABLE RAW** (Read-Only) |
| **Live GTFS-RT** | Protocol Buffers (GTFS-RT) | `https://otd.delhi.gov.in/api/realtime/VehiclePositions.pb` | Streamed in-memory (latest snapshot) | Real-time vehicle positions, live speed fusion, live map | **AUTHENTICATED STREAM** |

---

## 2. Historical Bus GPS Dataset Details

### 2.1 File Inventory
Extracted from `delhi-dtc-bus-gtfs-rt-2026-10.7z` (16.07 GB compressed). Contains 31 individual daily SQLite databases:
- `bus_movements_2026_10_01.db` (3.19 GB, 31,290,299 records)
- `bus_movements_2026_10_02.db` (2.98 GB)
- ...
- `bus_movements_2026_10_15.db` (4.20 GB, 29,271,900 records)
- ...
- `bus_movements_2026_10_31.db` (4.45 GB, 30,972,964 records)
- **Total database count**: 31
- **Total size**: 124,016,046,080 bytes (~115.50 GB)
- **Estimated total observations**: ~900 million GPS records

### 2.2 Schema Definition (Table: `vehicle_feed`)
```sql
CREATE TABLE vehicle_feed (
    vehicle_id TEXT,  -- Bus registration number (e.g., 'DL1PD6884')
    lat        TEXT,  -- WGS84 latitude as decimal text (e.g., '28.7040405273437')
    lng        TEXT,  -- WGS84 longitude as decimal text (e.g., '77.259033203125')
    speed      REAL,  -- Instantaneous speed in meters per second (m/s)
    route_id   REAL,  -- Numeric route identifier as float (e.g., 1728.0)
    trip_id    TEXT,  -- Assigned trip identifier (e.g., '1728_21_54_1365')
    timestamp  TEXT,  -- Unix epoch seconds in UTC (e.g., '1790792992')
    date       date,  -- Observation date in IST (e.g., '2026-10-01')
    time       TEXT   -- Observation clock time in IST (e.g., '00:00:01')
);
```

### 2.3 Characteristics & Quality Observations
- **Speed Units**: Speed is recorded in **meters per second (m/s)**. Day 1 average speed is $9.77\text{ m/s} \approx 35.2\text{ km/h}$. Maximum speeds reach $54.7\text{ m/s} \approx 197\text{ km/h}$, indicating GPS noise pings that must be filtered out ($> 25\text{ m/s}$ threshold).
- **Timezone Semantics**: `timestamp` represents UTC Unix epoch seconds. `date` and `time` represent local Indian Standard Time (IST, UTC+05:30). Both must be handled with timezone awareness.
- **Route Identifier Alignment**: `route_id` stored as REAL (e.g., 1728.0) maps directly to integer string `'1728'` in GTFS `routes.txt`.

---

## 3. Static GTFS Dataset Details

Location: `E:/Pulse/delhi_buses_static_gtfs_v1/`

| File | Size (MB) | Row Count | Key Columns | Role |
|---|---|---|---|---|
| `stops.txt` | 0.41 MB | 6,862 | `stop_id`, `stop_name`, `stop_lat`, `stop_lon` | Physical stop locations and spatial KD-Tree |
| `routes.txt` | 0.21 MB | 2,574 | `route_id`, `route_short_name`, `route_long_name`, `agency_id` | Transit route metadata (DTC & DIMTS) |
| `trips.txt` | 4.99 MB | 80,357 | `route_id`, `trip_id`, `service_id`, `shape_id` | Scheduled trips and shape associations |
| `stop_times.txt` | 116.10 MB | 2,737,136 | `trip_id`, `arrival_time`, `departure_time`, `stop_id`, `stop_sequence` | Stop order and scheduled departure anchors |
| `shapes.txt` | 40.02 MB | 965,607 | `shape_id`, `shape_pt_lat`, `shape_pt_lon`, `shape_pt_sequence` | Detailed road polyline shapes for metric segmentation |
| `agency.txt` | < 0.01 MB | 2 | `agency_id`, `agency_name` | DTC and DIMTS agency info |
| `calendar.txt` | < 0.01 MB | 1 | `service_id`, `monday`..`sunday`, `start_date`, `end_date` | Service operation days |
| `feed_info.txt` | < 0.01 MB | 2 | `feed_publisher_name`, `feed_version` | Feed version metadata |

---

## 4. Live GTFS-Realtime Endpoint

- **Feed URL**: `https://otd.delhi.gov.in/api/realtime/VehiclePositions.pb`
- **Protocol**: Protocol Buffers binary stream (`transit_realtime.FeedMessage`)
- **Authentication**: Key parameter via query string: `?key=<ROTATED_API_KEY>`
- **Security & Hygiene**: Managed exclusively via local `E:\Pulse\.env`. Never committed to Git, logged, or exposed in client responses.
- **Entity Structure**:
  - `entity.vehicle.vehicle.id`: Bus registration number
  - `entity.vehicle.position.latitude`, `longitude`
  - `entity.vehicle.position.speed` (where provided)
  - `entity.vehicle.trip.route_id`, `trip_id`
  - `entity.vehicle.timestamp`: Observation Unix timestamp
