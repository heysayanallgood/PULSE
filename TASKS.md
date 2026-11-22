# PULSE Engineering Tasks (TASKS.md)

## Authoritative Progress & Verification Tracker

### Phase 0: Machine, Storage & Data Preflight
- [x] Inspect `E:\Pulse` workspace and directory contents
- [x] Verify disk space across volumes (793 GB free on E:, 4 GB on C:)
- [x] Check Python 3.12, pip, and git availability
- [x] Create project-local virtual environment at `E:\Pulse\.venv`
- [x] Inspect static GTFS files (6,862 stops, 2,574 routes, 80,357 trips, 965,607 shape points)
- [x] Inspect historical GPS archive: all 31 daily SQLite databases verified (115.50 GB total)
- [x] Verify SQLite table schema (`vehicle_feed`, 31.3M records on Oct 01, speed in m/s)
- [x] Verify route_id mapping between SQLite and GTFS
- [x] Generate preflight report (`docs/PREFLIGHT_REPORT.md`)

### Architectural Review & ADR Alignment (Phase 0.5)
- [x] Step 1: Inspect root `DECISIONS.md`
- [x] Step 2: Inspect `E:\Pulse` directory and existing code
- [x] Step 3: Inventory extracted historical data (all 31 daily DBs, 115.5 GB) and GTFS source files
- [x] Step 4: Rewrite root `DECISIONS.md` with final six ADRs
  - [x] ADR 001: Storage & Virtual Environment Isolation (Accepted with Additional Requirements)
  - [x] ADR 002: Historical Analytics & Storage (Amended — Replaces zero-copy claim, speed + travel-time distributions)
  - [x] ADR 003: Coordinate System & Metric Projections (Accepted with Implementation Precisions)
  - [x] ADR 004: Public Transit Routing (Amended — Multi-criteria RAPTOR with arrival, transfers, walking)
  - [x] ADR 005: Live and Historical Fusion (Amended — Uncertainty-aware, freshness-aware Bayesian fusion)
  - [x] ADR 006: Raw Data Immutability and Provenance (New — Accepted, raw data read-only, manifests, lineage)
- [x] Step 5: Update cross-referenced architecture and engineering documentation (`docs/`)
- [x] Step 6: Audit actual code against decisions
- [x] Step 7: Correct safe, high-priority inconsistencies
- [x] Step 8: Write and run focused verification tests
- [x] Step 9: Produce `docs/ADR_IMPLEMENTATION_AUDIT.md`
- [x] Step 10: Deliver final architectural completion report

### Phase 1: System Architecture & Foundation
- [x] Setup `E:\Pulse\data\cache\` directory structure (`pip/`, `temp/`, `duckdb/`)
- [x] Install pinned Python dependencies into `E:\Pulse\.venv` with explicit pip cache on E:
- [x] Implement `app/core/config.py` with secret redaction and environment loading
- [x] Implement `app/core/storage.py` with storage diagnostic checks (ADR 001)
- [x] Implement `app/core/logging.py` ensuring zero secret leaks
- [x] Implement FastAPI application `app/main.py` with `/api/v1/health` and `/api/v1/ready`
- [x] Setup pytest automated test suite in `tests/`

### Phase 2: Static GTFS Ingestion & Network Graph
- [x] Build `scripts/ingest_gtfs.py` for high-throughput DuckDB loading
- [x] Ingest stops, routes, trips, stop_times, and shapes into `data/database/gtfs.duckdb` (170 MB)
- [x] Create metric projection spatial index in `app/geo/spatial_index.py` using SciPy KDTree (EPSG:32643)
- [x] Implement data access repository in `app/data/gtfs/repository.py`
- [x] Add unit tests in `tests/integration/test_phase2_gtfs.py`

### Phase 3 & 4: Historical GPS Processing & Segmentation
- [x] Implement `scripts/process_day.py` for streaming read-only SQLite processing
- [x] Filter out-of-bounds GPS coordinates (Delhi bounding box: 28.2°N–28.95°N, 76.8°E–77.55°E)
- [x] Filter unrealistic speeds (> 25 m/s / 90 km/h)
- [x] Convert timestamps to 15-minute time buckets (0–95) and day types (weekday/weekend)
- [x] Slice 3,498 route shapes into 163,018 metric 300m–500m segments (`scripts/build_segments.py`)
- [x] Output Snappy Parquet partitions with cryptographic SHA256 run manifests

### Phase 5: Core Spatiotemporal Travel-Time Engine
- [x] Build `scripts/train_travel_time_model.py` synthesizing dual distributions
- [x] Populate `data/database/travel_time.duckdb` with 31,299,456 indexed segment distribution records
- [x] Implement `app/services/prediction_service.py` with segment traversal prediction
- [x] Verify peak (08:30: 68.7m) vs. off-peak (23:00: 28.4m) duration differential on Route 1728
- [x] Add dwell time accounting without double-counting running time

### Phase 6: Live GTFS-RT & Bayesian Fusion
- [x] Implement precision-weighted Bayesian fusion math in `app/models/live_fusion.py`
- [x] Implement variance floor ($V \ge 4.0\text{ s}^2$) and observation weight decay
- [x] Implement consecutive vehicle ping velocity calculation
- [x] Implement freshness state machine (`FRESH` $\le 60$s, `AGING` $61$–$90$s, `STALE` $> 90$s, `UNAVAILABLE`)
- [x] Implement async GTFS-RT poller in `app/services/realtime_service.py`

### Phase 7: Multi-Criteria RAPTOR Transit Router
- [x] Implement metric walking path generator in `app/routing/walking.py` (1.25 urban winding factor)
- [x] Implement multi-criteria RAPTOR routing engine in `app/routing/raptor.py`
- [x] Implement Pareto dominance tracking (earliest arrival, transfer count, walking duration)
- [x] Implement realistic 3-minute platform transfer buffers
- [x] Support GTFS midnight rollover service times (> 24:00:00)
- [x] Implement `app/services/journey_service.py` coordinating origin/destination resolution and routing

### Phase 8: REST API Endpoints
- [x] Implement `/api/v1/stops/search` and `/api/v1/stops/nearby`
- [x] Implement `/api/v1/routes` and `/api/v1/routes/{route_id}`
- [x] Implement `/api/v1/journeys/plan`
- [x] Implement `/api/v1/analytics/time-comparison`
- [x] Implement `/api/v1/validation/summary`
- [x] Implement `/api/v1/vehicles`
- [x] Mount static files and single-page application at root `/`
- [x] Register OpenAPI docs and schemas at `/docs`

### Phase 9: Interactive Web Client
- [x] Build single-page web UI in `frontend/index.html`
- [x] Build HopCode glassmorphism dark theme in `frontend/static/css/pulse.css`
- [x] Implement Leaflet map renderer with dynamic route polyline rendering in `frontend/static/js/app.js`
- [x] Build interactive Journey Planner card list with collapsible step-by-step directions
- [x] Build Time Machine departure comparison slider
- [x] Build Live Bus Map visualizer with vehicle freshness badges
- [x] Build Validation Lab benchmark dashboard

### Phase 10: Validation, Benchmarking & Documentation
- [x] Conduct benchmark evaluation against 1,250 observed DTC bus runs
- [x] Compute MAE, RMSE, MAD, and 90% prediction interval coverage
- [x] Author comprehensive `docs/VALIDATION_REPORT.md`
- [x] Author comprehensive `docs/API_REFERENCE.md`
- [x] Author hackathon presentation script `docs/DEMO_SCRIPT.md`
- [x] Author authoritative `README.md`
- [x] Verify all 35 unit and integration tests passing (`pytest tests/ -v`)

### Phase 11: Advanced Map Experience, Rapido 2D Bus SVGs & Citywide Search Upgrade
- [x] Integrate clean, light CARTO Positron as default basemap
- [x] Add Leaflet Layer Control with Positron, Voyager, Dark Matter, Satellite (MapTiler/Esri), and OpenStreetMap
- [x] Ensure private Delhi OTD API key is never exposed to client-side code
- [x] Create original Rapido-inspired top-down 2D city bus SVG icons with windshield, roof AC vents, headlights, and bumpers
- [x] Rotate bus icons dynamically according to actual vehicle bearing (`b.bearing`)
- [x] Add luminous freshness halos (`FRESH` green, `AGING` amber, `STALE` red)
- [x] Implement marker clustering via `Leaflet.markercluster` (smooth clustering at zoom < 14, unclustering at zoom >= 14)
- [x] Implement in-place marker mutation for 2,500+ active DTC buses to maintain 60fps performance
- [x] Connect Journey Planner to all 6,862 imported Delhi GTFS bus stops
- [x] Implement duplicate stop name disambiguation (`[stop_id]`) and prefix-based search ranking
- [x] Implement debounced autocomplete dropdown for Origin and Destination
- [x] Support arbitrary coordinate inputs (`lat, lon`) within Delhi NCR bounding box
- [x] Add interactive "Pick on Map" mode and map-click context popups for setting Origin & Destination
- [x] Implement server-side Geoapify Address Autocomplete proxy with rate-limit protection cache and GTFS fallback
- [x] Implement true GTFS shape polyline clipping (`gtfs_repo.get_clipped_shape_coordinates`) displaying actual road geometry
- [x] Differentiate walking legs (dashed lines) from bus transit legs (vibrant solid route polylines)
- [x] Add comprehensive integration tests in `tests/integration/test_advanced_map_search.py`
- [x] Verify all 42 tests passing (`pytest tests/ -v`)
- [x] Author comprehensive documentation in `docs/ADVANCED_MAP_AND_CITYWIDE_SEARCH.md`

### Phase 12: Ultimate Multi-Phase Engineering & Repair Directive
- [x] Standardized API error contract eliminating plain-text / HTML 500 errors (`docs/JOURNEY_API_JSON_REPAIR.md`)
- [x] Global exception interceptors in `app/main.py` (`StarletteHTTPException`, `RequestValidationError`, `Exception`)
- [x] Client-side `safeFetchJson` error handling, AbortController, and atomic route layer clearing
- [x] Unique timestamped request identifier (`request_id`) and unique journey option identifiers (`journey_id`)
- [x] Systematic verification of dynamic route geometry across 6 core corridors:
  - [x] Scenario 1: Anand Vihar ISBT → Nehru Place (verified road geometry)
  - [x] Scenario 2: Anand Vihar ISBT → Badarpur Border (verified alighting at border)
  - [x] Separation Invariant: > 4,000m physical divergence between Nehru Place and Badarpur alighting stops with zero shared geometry points
  - [x] Scenario 3: Kashmere Gate → Nehru Place
  - [x] Scenario 4: India Gate → Nehru Place (curated landmark centroid resolution to Baroda House access stop with walking leg)
  - [x] Scenario 5: Connaught Place → AIIMS (high-performance CTE join on interchange hub stops)
  - [x] Scenario 6: Anand Vihar ISBT → Dhaula Kuan
- [x] DuckDB CTE-based 1-transfer routing optimization preventing memory exhaustion and reducing latency to < 0.05s
- [x] Full landmark catalog in `app/services/places_service.py` (35+ major Delhi destinations)
- [x] Vector Rapido-style 2D bus SVG icon specifications (`viewBox="0 0 64 120"`, 32x60px, 4 wheels, headlights, destination display, windshield gradient, AC louvers, red taillights, dynamic CSS bearing rotation)
- [x] MapTiler Satellite Plain, Satellite Hybrid with road overlays, and Esri World Imagery fallback
- [x] Complete automated test suite expanded to 53 tests:
  - [x] `tests/unit/test_bus_svg_markers.py` (3 tests)
  - [x] `tests/routing/test_dynamic_route_geometry.py` (8 tests)
  - [x] `tests/integration/test_advanced_map_search.py` (7 tests)
  - [x] 100% test pass rate: **53 passed out of 53 tests**
- [x] Complete documentation deliverables:
  - [x] `docs/JOURNEY_API_JSON_REPAIR.md`
  - [x] `docs/DYNAMIC_ROUTE_GEOMETRY.md`
  - [x] `docs/GPS_AND_GTFS_SHAPE_MATCHING.md`
  - [x] `docs/DELHI_CITYWIDE_SEARCH.md`
  - [x] `docs/BUS_SVG_MARKER_IMPLEMENTATION.md`
  - [x] `docs/MAPTILER_SATELLITE_INTEGRATION.md`
  - [x] `docs/LIVE_VEHICLE_RENDERING.md`
  - [x] `docs/END_TO_END_TEST_REPORT.md`
  - [x] `docs/KNOWN_LIMITATIONS.md`

### Phase 13: External Edge Browser Synchronization & Runtime Repair
- [x] Phase 0: Protect running FastAPI server (PID 6992 on 127.0.0.1:8000, 0 uncommitted changes lost, no WinError 10013)
- [x] Phase 1: Verify actual running server, served HTTP responses, content lengths, hashes, and client config endpoints
- [x] Phase 2: Diagnose true browser failure causes (A through O) in Microsoft Edge; identified root cause in heuristic disk caching of unversioned static assets and missing localStorage migration
- [x] Phase 3: Implement asset versioning (`?v=20261122-v2.1.0`), HTML cache-control meta headers, and `localStorage` migration resetting dark basemap defaults to CARTO Positron
- [x] Phase 4: Verify Leaflet map initialization, container sizing, zero duplicate instances, and 6-layer switcher event wiring
- [x] Phase 5: Complete MapTiler Satellite Plain and Satellite Hybrid live tile loading with attribution and 200 OK responses
- [x] Phase 6: Verify top-down 2D SVG bus markers in Edge DOM (4 wheels, headlights, destination display, windshield gradient, freshness classes, 0 circular dots)
- [x] Phase 7: Execute full Microsoft Edge automated acceptance suite (`scripts/verify_external_edge.py`) covering Tests A through F
- [x] Phase 8: Audit API keys (OTD private backend-only, Geoapify behind proxy, MapTiler & CARTO restricted client keys, .env ignored)
- [x] Phase 9: Implement surgical repairs in `frontend/index.html` and `frontend/static/js/app.js` without server downtime
- [x] Phase 10: Produce authoritative technical report (`docs/EXTERNAL_EDGE_REPAIR_REPORT.md`) and store 9 high-resolution Edge screenshots in `docs/evidence/external-edge/`
- [x] Phase 11: Fulfill all acceptance criteria with 0 console errors in Microsoft Edge and 53/53 pytest backend tests passing
