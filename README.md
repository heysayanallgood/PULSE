# PULSE — Predictive Urban Mobility & Live Spatiotemporal Engine
### Team HopCode | Transport Stack Hackathon 2026 — Phase 1, Problem 1
> *"The City Moves. We Decode Its Pulse."*

[![Python 3.12](https://img.shields.io/badge/python-3.12-blue.svg)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.115+-009688.svg)](https://fastapi.tiangolo.com)
[![DuckDB](https://img.shields.io/badge/DuckDB-1.1+-FFF000.svg)](https://duckdb.org)
[![Tests Passing](https://img.shields.io/badge/pytest-53%20passed-brightgreen.svg)](tests/)
[![Architecture ADRs](https://img.shields.io/badge/ADR-001--006%20Compliant-success.svg)](DECISIONS.md)

---

## 1. Executive Summary

**PULSE** is a real-time bus traffic model and journey planner for Delhi, India, built on 31 days of historical Delhi Transport Corporation (DTC) bus GPS records (over 115 GB uncompressed, ~900M vehicle records) and official static GTFS data. 

Unlike traditional timetable-based journey planners that produce static estimates regardless of actual traffic conditions, PULSE estimates travel times strictly from **empirically observed vehicle trajectories**:
- Morning peak hour vs. midnight travel times dynamically diverge by up to **240%** for identical routes.
- Segment travel times are modeled across **163,018 metric segments** (300m–500m) in 15-minute time buckets across weekdays and weekends (**31,299,456 parametric distributions**).
- Real-time GTFS-RT positions are fused with historical priors using **precision-weighted Bayesian fusion** with uncertainty floors and observation age decay.
- Journeys are calculated using a **multi-criteria RAPTOR transit router** optimizing arrival time, transfer count, and metric walking distance.
- **Dynamic Road-Snapped Geometry**: Slices true GTFS shape points (180–360+ points per leg) along actual road curves, completely eliminating straight-line shortcuts.
- **Rapido-Inspired 2D SVG Bus Markers**: Top-down vector silhouettes (`viewBox="0 0 64 120"`) rotated dynamically by vehicle bearing with headlights, AC vents, taillights, and freshness halos (`FRESH` green, `AGING` amber, `STALE` red).
- **Citywide Search & Landmark Resolution**: Indexes all 6,862 DTC bus stops with duplicate disambiguation, arbitrary coordinates (`lat, lon`), interactive map picking, and Geoapify address autocomplete with server-side key isolation.
- **Multi-Basemap Layer Control**: Defaults to CARTO Positron (light street map) alongside CARTO Voyager, CARTO Dark Matter, MapTiler Satellite Plain, MapTiler Satellite Hybrid, and OpenStreetMap.
- **Standardized API Error Architecture**: Strict JSON error schemas eliminate all plain-text and HTML 500 exceptions.
- **Validation**: Achieves a **Mean Absolute Error (MAE) of 1.9 minutes** against observed DTC trips (compared to 34.9 minutes for timetable baselines), representing a **94.6% error reduction**.

---

## 2. Key Capabilities & Architectural Innovations

### 1. Spatiotemporal Travel-Time Engine (Dual Distributions)
- **163,018 Metric Segments**: Every GTFS shape is sliced into uniform 300m–500m segments in metric Cartesian space (**EPSG:32643 / UTM Zone 43N**).
- **Dual Distributions**: Tracks both metric speeds ($m/s$) and segment traversals ($s$) across 96 fifteen-minute buckets and day types (weekday vs. weekend) to preserve traffic signals, intersection delays, and dwell characteristics without double-counting.
- **Time Machine**: Allows users to inspect city-wide bus speeds and route durations at any hour of the day or day type.

### 2. Precision-Weighted Bayesian Live Fusion (ADR 005)
When live GTFS-RT vehicle pings are available, PULSE updates segment travel times using precision-weighted fusion:
$$w_{\text{live}} = \frac{\frac{q_{\text{live}}}{V_{\text{live}}}}{\frac{q_{\text{live}}}{V_{\text{live}}} + \frac{q_{\text{hist}}}{V_{\text{hist}}}}, \quad T_{\text{fused}} = w_{\text{live}} \cdot T_{\text{live}} + (1 - w_{\text{live}}) \cdot T_{\text{hist}}$$
- **Variance Floor**: $V \ge 4.0\text{ s}^2$ prevents overconfident single-ping estimates.
- **Freshness State Machine**:
  - `FRESH` ($\le 60$s): Full live weight.
  - `AGING` ($61$–$90$s): Linearly degraded live weight.
  - `STALE` ($> 90$s): Complete fallback to historical prior ($w_{\text{live}} = 0$).
  - `UNAVAILABLE`: Clean fallback to historical prior with explicit provenance badge.

### 3. Multi-Criteria RAPTOR Transit Router (ADR 004)
- Pareto-optimal journey rounds optimizing:
  1. Earliest arrival time ($T_{\text{arr}}$)
  2. Minimal transfers ($k \le 2$)
  3. Total walking duration
- **Realistic Walk Modeling**: SciPy KDTree metric stop search with a 1.25 urban winding factor at 1.1 m/s (4.0 km/h).
- **Transfer Buffers**: Enforces minimum 3-minute physical platform transfer buffers; accounts for 24h+ GTFS midnight rollover service times.

### 4. Zero Synthetic Data Invariant & Provenance Transparency
Every planned journey and route segment clearly exposes its data provenance:
- `HISTORICAL`: Computed from 31 days of historical GPS distributions.
- `LIVE`: Supported by real-time vehicle pings within freshness threshold.
- `LIVE + HISTORICAL`: Precision-weighted fusion.
- `SCHEDULE-BASED` / `FALLBACK`: Clearly badged when zero GPS data exists.

---

## 3. System Architecture

```
                    ┌──────────────────────────────────────────────┐
                    │       PULSE Web Client (Leaflet + JS)        │
                    │  Journey Planner | Time Machine | Live Map   │
                    └───────────────────────┬──────────────────────┘
                                            │ REST API (JSON)
                    ┌───────────────────────▼──────────────────────┐
                    │          FastAPI Application Server          │
                    │           (app/main.py, Port 8000)           │
                    └───┬─────────────┬─────────────┬───────────┬──┘
                        │             │             │           │
       ┌────────────────▼─┐   ┌───────▼──────┐  ┌───▼──────┐  ┌─▼─────────────┐
       │ Journey Service  │   │  Prediction  │  │ Realtime │  │ GTFS & Spatial│
       │ (RAPTOR Router)  │   │   Service    │  │ Poller & │  │  Index Service│
       │                  │   │ (Spatiotemp) │  │  Fusion  │  │(SciPy KDTree) │
       └────────┬─────────┘   └───────┬──────┘  └───┬──────┘  └───────┬───────┘
                │                     │             │                 │
                └──────────────┬──────┴─────────────┴─────────────────┘
                               │
            ┌──────────────────┴──────────────────┐
            │       High-Performance Storage      │
            │  (DuckDB + Snappy Parquet on E:)    │
            ├─────────────────────────────────────┤
            │ • gtfs.duckdb (170 MB)              │
            │ • travel_time.duckdb (2.05 GB)      │
            │ • travel_time_model.parquet         │
            │ • Read-Only Daily SQLite (115.5 GB) │
            └─────────────────────────────────────┘
```

---

## 4. Repository Structure

```
E:\Pulse\
├── app/
│   ├── api/v1/                   # REST API Routers
│   │   ├── analytics.py          # Time machine & comparative peak/off-peak stats
│   │   ├── journeys.py           # Multi-criteria RAPTOR journey planner endpoint
│   │   ├── routes.py             # Route geometries, shapes, and schedules
│   │   ├── stops.py              # Autocomplete stop search and radius lookup
│   │   ├── validation.py         # Empirical benchmark and accuracy metrics
│   │   └── vehicles.py           # Real-time vehicle positions and status
│   ├── core/                     # Infrastructure Configuration
│   │   ├── config.py             # Pydantic v2 settings with secret masking
│   │   ├── logging.py            # Structured logging with zero credential leaks
│   │   └── storage.py            # ADR 001 storage invariant verification
│   ├── data/gtfs/repository.py   # DuckDB GTFS data access layer
│   ├── geo/spatial_index.py      # SciPy KDTree spatial index (EPSG:32643)
│   ├── models/live_fusion.py     # Precision-weighted Bayesian fusion math
│   ├── routing/
│   │   ├── raptor.py             # Multi-criteria RAPTOR routing engine
│   │   └── walking.py            # Metric walking duration and path generator
│   ├── services/
│   │   ├── journey_service.py    # Journey planning coordination
│   │   ├── prediction_service.py # Spatiotemporal segment model query engine
│   │   └── realtime_service.py   # GTFS-RT poller and freshness state machine
│   └── main.py                   # FastAPI application root & static asset mounter
├── data/
│   ├── cache/                    # Pip, DuckDB temp, and OS scratch caches on E:
│   ├── database/                 # DuckDB operational databases
│   │   ├── gtfs.duckdb           # Ingested static GTFS (170 MB)
│   │   └── travel_time.duckdb    # 31.3M segment speed distributions (2.05 GB)
│   ├── manifests/                # Ingestion manifests & SHA256 integrity logs
│   ├── models/                   # Compressed travel time model Parquet files
│   └── processed/historical/     # Daily Snappy Parquet partitions
├── docs/                         # Technical Documentation
│   ├── ADR_IMPLEMENTATION_AUDIT.md
│   ├── API_REFERENCE.md
│   ├── ARCHITECTURE.md
│   ├── DATA_SOURCES.md
│   ├── DEMO_SCRIPT.md
│   ├── GPS_PROCESSING.md
│   ├── LIVE_INTEGRATION.md
│   ├── MODEL_METHODOLOGY.md
│   ├── PREFLIGHT_REPORT.md
│   └── VALIDATION_REPORT.md
├── frontend/                     # Modern Web Client
│   ├── static/css/pulse.css      # HopCode dark-theme glassmorphism stylesheet
│   ├── static/js/app.js          # Reactive Leaflet map & journey renderer
│   └── index.html                # Single-page application UI
├── scripts/                      # Data Processing & Training Pipelines
│   ├── build_segments.py         # Slices 3,498 shapes into 163,018 metric segments
│   ├── ingest_gtfs.py            # GTFS ingestion to DuckDB
│   ├── process_day.py            # Streaming daily GPS SQLite to Snappy Parquet
│   └── train_travel_time_model.py# Aggregates 31M spatiotemporal distributions
├── tests/                        # Comprehensive Pytest Suite (35 tests)
│   ├── integration/              # End-to-end API and GTFS queries
│   └── unit/                     # ADR compliance (storage, raptor, fusion, etc.)
├── DECISIONS.md                  # Authoritative Architectural Decision Records
├── PROJECT_STATUS.md             # Project lifecycle tracking
├── TASKS.md                      # Detailed engineering task checklist
└── requirements.txt              # Pinned Python package dependencies
```

---

## 5. Quick Start & Installation

### Prerequisites
- **Operating System**: Windows 11 (or Linux/macOS)
- **Python**: 3.12+ (verified on Python 3.12.9)
- **Dedicated Storage**: SanDisk 2 TB Portable SSD (`E:\Pulse`) or minimum 50 GB free space on local SSD.

### Step 1: Environment Setup
```powershell
# Navigate to project root
cd E:\Pulse

# Activate virtual environment
.\.venv\Scripts\Activate.ps1

# Verify pip cache isolation on E: (ADR 001)
$env:PIP_CACHE_DIR = "E:\Pulse\data\cache\pip"
pip install -r requirements.txt --cache-dir E:\Pulse\data\cache\pip
```

### Step 2: Running Automated Tests
```powershell
# Execute the full 35-test suite
& "E:\Pulse\.venv\Scripts\pytest.exe" tests/ -v
```
*Expected result: 35 passed in ~19 seconds.*

### Step 3: Launching the Application
```powershell
# Start Uvicorn server on port 8000
& "E:\Pulse\.venv\Scripts\uvicorn.exe" app.main:app --host 127.0.0.1 --port 8000 --reload
```

Open your browser to:
- **Interactive Web Interface**: [http://127.0.0.1:8000/](http://127.0.0.1:8000/)
- **Interactive Swagger API Docs**: [http://127.0.0.1:8000/docs](http://127.0.0.1:8000/docs)
- **API Status**: [http://127.0.0.1:8000/api/v1/health](http://127.0.0.1:8000/api/v1/health)

---

## 6. Core REST API Endpoints

| Endpoint | Method | Description |
|---|---|---|
| `/api/v1/health` | `GET` | Health check and storage diagnostic check |
| `/api/v1/journeys/plan` | `GET` | Multi-criteria RAPTOR journey planning with coordinate or stop inputs |
| `/api/v1/stops/search` | `GET` | Autocomplete prefix and full-text search for 6,862 bus stops |
| `/api/v1/stops/nearby` | `GET` | Sub-millisecond radius search using metric KDTree (UTM Zone 43N) |
| `/api/v1/routes` | `GET` | Lists available bus routes |
| `/api/v1/routes/{route_id}` | `GET` | Retrieves full route details, shape geometry, and stop sequence |
| `/api/v1/analytics/time-comparison` | `GET` | Compares travel times for a route across morning peak, off-peak, and night |
| `/api/v1/vehicles` | `GET` | Real-time vehicle positions with freshness state (`FRESH`, `AGING`, `STALE`) |
| `/api/v1/validation/summary` | `GET` | Quantitative model accuracy benchmarks against observed ground truth |

*See [`docs/API_REFERENCE.md`](docs/API_REFERENCE.md) for complete schema and response examples.*

---

## 7. Model Validation & Accuracy Highlights

PULSE was validated against a ground-truth dataset of 1,250 observed DTC bus runs across 5 major Delhi corridors (including Ring Road, Outer Ring Road, and radial arterial corridors):

| Metric | Static GTFS Timetable | PULSE Historical Model | PULSE Live + Historical | Error Reduction |
|---|---|---|---|---|
| **Mean Absolute Error (MAE)** | 34.9 min | 2.1 min | **1.9 min** | **-94.6%** |
| **Root Mean Squared Error (RMSE)** | 41.2 min | 3.2 min | **2.8 min** | **-93.2%** |
| **Median Absolute Deviation (MAD)** | 31.5 min | 1.4 min | **1.2 min** | **-96.2%** |
| **Prediction Interval Coverage (90%)**| 12.4% | 91.8% | **94.2%** | **+81.8%** |

### Proof of Peak vs. Off-Peak Divergence (Route 1728)
- **08:30 AM (Morning Peak)**: Traversal duration **68.7 minutes** (Average speed: 13.1 km/h)
- **11:00 PM (Late Night Off-Peak)**: Traversal duration **28.4 minutes** (Average speed: 31.7 km/h)
- **Static Schedule Claim**: 45.0 minutes regardless of departure time (incorrect by up to 23.7 minutes).

*See [`docs/VALIDATION_REPORT.md`](docs/VALIDATION_REPORT.md) for full benchmarking methodology.*

---

## 8. Architectural Decision Records (ADRs)

| ADR | Domain | Key Architectural Decision |
|---|---|---|
| **[ADR 001](DECISIONS.md#adr-001)** | Storage & Caching | Strict external SSD isolation (`E:\Pulse`); zero cache leakage to `C:`. |
| **[ADR 002](DECISIONS.md#adr-002)** | Historical Storage | Dual distributions (speeds $m/s$ + travel times $s$); DuckDB + Parquet. |
| **[ADR 003](DECISIONS.md#adr-003)** | Coordinate Systems | EPSG:32643 (UTM Zone 43N) metric projection for all distance/segment math. |
| **[ADR 004](DECISIONS.md#adr-004)** | Transit Routing | Multi-criteria RAPTOR (arrival, transfers, walking); realistic transfer buffers. |
| **[ADR 005](DECISIONS.md#adr-005)** | Fusion Mathematics | Precision-weighted Bayesian fusion ($w = \frac{q_L/V_L}{q_L/V_L + q_H/V_H}$) with variance floor. |
| **[ADR 006](DECISIONS.md#adr-006)** | Data Provenance | Read-only SQLite URIs (`mode=ro`); cryptographic SHA256 run manifests. |

---

## 9. Hackathon Team & Acknowledgements

**Team HopCode**
- Principal Software Architect & Lead Backend Engineer
- Lead Spatiotemporal Data Scientist & Algorithm Engineer
- Full-Stack UI/UX & Geospatial Specialist

Developed for the **Transport Stack Hackathon 2026 — Phase 1, Problem 1**.  
Data provided by **Transport Stack** and **IIIT Delhi** in collaboration with **Delhi Transport Corporation (DTC)** and **Open Network for Digital Commerce (ONDC)**.
