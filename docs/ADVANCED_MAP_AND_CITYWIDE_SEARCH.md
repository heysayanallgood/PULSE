# PULSE — Advanced Map Experience, Rapido-Style Live Bus Icons & Citywide Search
### Team HopCode | Transport Stack Hackathon 2026 — Phase 1, Problem 1
> *"The City Moves. We Decode Its Pulse."*

---

## 1. Executive Summary

This engineering directive upgraded **PULSE** from a dark-themed prototype into a citywide, production-grade urban transit engine for the National Capital Territory of Delhi. 

Key upgrades delivered and verified:
1. **Light & Realistic Street Basemap**: CARTO Positron is now the default high-visibility street basemap, complemented by CARTO Voyager, CARTO Dark Matter, Satellite Imagery, and OpenStreetMap via an interactive Leaflet Layer Control.
2. **Satellite Mode**: Integrated high-resolution satellite imagery (supporting dedicated MapTiler Satellite via `MAPTILER_API_KEY` with automatic Esri World Imagery fallback).
3. **Rapido-Inspired 2D City Bus SVGs**: Replaced circular vehicle dots with custom top-down aerodynamic 2D bus vector silhouettes featuring headlights, windshields, roof AC vents, directional headings rotated by vehicle bearing, and luminous freshness halos (`FRESH` green, `AGING` amber, `STALE` red).
4. **Marker Clustering & High-Throughput Performance**: Deployed `Leaflet.markercluster` to cluster 2,500+ active DTC buses at city-wide zoom levels (< 14), expanding into individual directional buses at corridor zoom (>= 14) with in-place marker updates.
5. **Citywide Stop & Place Autocomplete**: Connected autocomplete search across all **6,862 verified DTC stops** with duplicate name disambiguation (`[stop_id]`), prefix ranking, arbitrary coordinate inputs (`lat, lon`), and Geoapify Address Autocomplete.
6. **Authentic GTFS Shape Polyline Visualization**: Sliced and rendered true road-following GTFS shapes (up to 360+ points per leg) rather than simplified straight lines, distinguishing walking legs (dashed) from transit legs (vibrant solid).

---

## 2. Map Providers & Basemap Architecture

### Implemented Basemap Styles

| Basemap Style | Provider | Tile Endpoint Pattern | Use Case / Characteristics |
|---|---|---|---|
| **☀️ Street (Positron)** *(Default)* | CARTO Basemaps | `https://{s}.basemaps.cartocdn.com/rastertiles/light_all/{z}/{x}/{y}.png?key={KEY}` | Ultra-clean, high-contrast light street basemap. Accentuates transit lines, bus icons, and stop labels. |
| **🧭 Voyager (Detailed)** | CARTO Basemaps | `https://{s}.basemaps.cartocdn.com/rastertiles/voyager/{z}/{x}/{y}.png?key={KEY}` | Rich building footprints, parks, metro stations, and arterial corridors. |
| **🌙 Dark Matter** | CARTO Basemaps | `https://{s}.basemaps.cartocdn.com/rastertiles/dark_all/{z}/{x}/{y}.png?key={KEY}` | High-contrast night mode preserving previous dark glassmorphism theme. |
| **🛰️ Satellite Imagery** | MapTiler / Esri | `https://api.maptiler.com/maps/satellite/...` or `https://server.arcgisonline.com/...` | High-resolution aerial imagery for inspecting physical bus stops, footpaths, and flyovers. |
| **🗺️ OpenStreetMap** | OpenStreetMap | `https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png` | Free, open fallback layer in case of third-party API issues. |

### Credentials & Security Compliance
- **CARTO Key**: Embedded securely for client-side raster tile requests via `window.PULSE_CONFIG.cartoApiKey`.
- **Delhi OTD Feed Key**: **Strictly quarantined on the backend**. Never exposed to client-side JavaScript or HTML source.
- **Geoapify Key**: Kept exclusively server-side in `app/core/config.py` and accessed solely via backend proxy endpoint `/api/v1/places/autocomplete`.
- **Attributions**: Maintained proper attribution for OpenStreetMap, CARTO, and Esri/MapTiler on the bottom-right corner of the map viewport.

---

## 3. Rapido-Inspired 2D Bus Marker Architecture

### Vector Silhouette Specifications
The vehicle marker is rendered as a clean, responsive 24x44px SVG vector icon:
- **Body & Chassis**: Low-floor city bus silhouette with rounded aerodynamic front and rear bumpers.
- **Forward Directional Beams**: Two bright wedge headlights at the front indicating travel direction.
- **Driver Cabin**: Curved dark-tinted front windshield (`#0f172a`).
- **Passenger Area**: Side window strips and roof climate/AC unit with realistic ventilation fins.
- **Freshness State Machine Halos**:
  - `FRESH` ($\le 60\text{s}$): Emerald green outer drop shadow (`#00e676`, glow radius: 2.5px) and front bumper strip.
  - `AGING` ($61$–$90\text{s}$): Amber/gold outer drop shadow (`#ffab00`) and front bumper strip.
  - `STALE` ($> 90\text{s}$): Crimson warning outer drop shadow (`#ff5252`) with explicit stale status.
  - `UNAVAILABLE`: Do not render fabricated vehicles.

### Bearing Rotation & Animation
- **Vehicle Bearing**: Directly drives CSS `transform: rotate(${bearing}deg)`.
- If bearing is null or 0 with 0 km/h speed, neutral forward orientation is preserved without inventing false headings.
- Smooth CSS transition `transition: transform 0.35s cubic-bezier(0.2, 0, 0, 1)` smoothly rotates vehicles when updated.
- Respects `prefers-reduced-motion` media query by disabling transitions for accessibility.

### Interactive Vehicle Inspection Popup
Clicking any bus marker opens an informative popup displaying:
- **Bus Registration**: Vehicle ID (e.g. `DL1PD6072`)
- **Route Assigned**: GTFS Route Number or "DTC Corridor"
- **Trip ID**: Scheduled Trip Identifier
- **Speed**: Actual observed speed in km/h (or "UNKNOWN" if missing)
- **Freshness Badge**: Real-time evaluation with observation age in seconds
- **Matching Status**: "Matched to GTFS Corridor" or "Raw AVL Position"

---

## 4. Marker Clustering & 2,500+ Vehicle Performance

### The High-Density Challenge
Delhi's live AVL feed delivers approximately 2,500 to 3,200 active buses simultaneously. Re-instantiating thousands of DOM elements every 30 seconds causes severe frame drops and memory spikes.

### Performance Optimizations Implemented
1. **In-Place Marker Mutation**: `state.busMarkers` maintains a `Map<vehicle_id, L.Marker>`. Incoming live feed positions update existing markers via `.setLatLng([lat, lon])` and `.setIcon(...)` without tearing down DOM nodes.
2. **Adaptive Zoom Clustering**:
   - At city-wide zoom levels ($z < 14$), buses are clustered into circular counter badges (`.pulse-cluster`).
   - At corridor zoom levels ($z \ge 14$), clusters automatically expand to individual Rapido-style 2D bus SVGs rotated along the road.
3. **Local Vendor Fallback**: Leaflet.markercluster assets are packaged locally in `frontend/static/vendor/` to eliminate external CDN dependencies and latency.

---

## 5. Citywide Stop & Place Search Engine

### Scope & Verified GTFS Counts
The static GTFS dataset was queried and verified in `data/database/gtfs.duckdb`:
- **Total Bus Stops**: 6,862
- **Unique Stop Names**: 4,614
- **Routes**: 2,574
- **Shapes**: 3,498 (965,607 shape points)

### Duplicate Disambiguation & Search Ranking
Because multiple platforms share stop names across Delhi's wide arterial avenues (e.g., opposite sides of the Ring Road), PULSE disambiguates results:
- Every suggestion includes its GTFS Stop ID: `Kashmere Gate [7571]`.
- SQL ranking evaluates:
  1. Exact case-insensitive match (`LOWER(stop_name) = LOWER(?)`)
  2. Prefix match (`stop_name ILIKE query%`)
  3. Shortest stop name length
  4. Alphabetical ordering

### Geocoded Places (Geoapify Integration)
- Endpoint: `GET /api/v1/places/autocomplete?q={query}&limit=10`
- Proxies requests to Geoapify with bounding box restriction: `rect:76.8,28.2,77.55,28.95` (Delhi NCR) and proximity bias towards Connaught Place (`28.6328, 77.2167`).
- Implemented 1-hour in-memory TTL caching (1,000 entries max) to strictly preserve free-tier daily usage quotas.
- Seamless fallback: If no API key is provided or the geocoder is offline, the endpoint queries the complete 6,862 GTFS stop index with zero downtime.

### Arbitrary Coordinate Inputs & "Pick on Map"
- Coordinates formatted as `lat, lon` (e.g. `28.6139, 77.2090`) are validated against the Delhi service area.
- Users can click **"📍 Pick on Map"** or click anywhere on the Leaflet map to set Origin (green pin) or Destination (red pin).
- The nearest transit stop is resolved in sub-millisecond time via the metric SciPy KD-Tree index, and first-mile/last-mile pedestrian walking legs are computed with a 1.25 urban winding factor.

---

## 6. Real GTFS Route Shape Polyline Visualization

### The Limitation Removed
Previous iterations drew simplified straight lines between boarding and alighting stops.

### The Real Road Polyline Solution
- Built `gtfs_repo.get_clipped_shape_coordinates(shape_id, board_lat, board_lon, alight_lat, alight_lon)`.
- Slices the ordered coordinates in the GTFS `shapes` table between the nearest shape point to the boarding stop and the nearest shape point to the alighting stop.
- Slices average **180 to 360 road points per leg**, perfectly tracing turns, flyovers, and Ring Road segments.
- Visual Leg Breakdown:
  - **Walking Leg**: Grey dashed polyline (`#64748b`, `dashArray: '6, 8'`).
  - **Bus Leg**: Saturated route polyline (`#0284c7`, weight 5.5, opacity 0.95).
  - **Transfer Hub**: Distinct platform buffer marker.
  - **Boarding / Alighting Stops**: Green (boarding) and Red (alighting) circular station rings.

---

## 7. Verification & Automated Test Results

The test suite was expanded with `tests/integration/test_advanced_map_search.py`:

```powershell
& "E:\Pulse\.venv\Scripts\pytest.exe" tests/ -v
```

```
============================= test session starts =============================
platform win32 -- Python 3.12.9, pytest-9.2.0, pluggy-1.7.0
rootdir: E:\Pulse
configfile: pytest.ini

tests/integration/test_advanced_map_search.py::test_public_config_no_secret_leaks PASSED [  2%]
tests/integration/test_advanced_map_search.py::test_places_autocomplete_stops PASSED [  4%]
tests/integration/test_advanced_map_search.py::test_places_autocomplete_coordinates PASSED [  7%]
tests/integration/test_advanced_map_search.py::test_stop_disambiguation PASSED [  9%]
tests/integration/test_advanced_map_search.py::test_clipped_shape_geometry PASSED [ 11%]
tests/integration/test_advanced_map_search.py::test_journey_with_coordinates_and_shape_geometry PASSED [ 14%]
tests/integration/test_advanced_map_search.py::test_live_vehicles_fields PASSED [ 16%]
tests/integration/test_phase10_api.py::test_frontend_serving PASSED      [ 19%]
tests/integration/test_phase10_api.py::test_stops_search_api PASSED      [ 21%]
tests/integration/test_phase10_api.py::test_stops_nearby_api PASSED      [ 23%]
tests/integration/test_phase10_api.py::test_routes_api PASSED            [ 26%]
tests/integration/test_phase10_api.py::test_journeys_api PASSED          [ 28%]
tests/integration/test_phase10_api.py::test_analytics_time_comparison_api PASSED [ 30%]
tests/integration/test_phase10_api.py::test_validation_summary_api PASSED [ 33%]
tests/integration/test_phase10_api.py::test_vehicles_api PASSED          [ 35%]
tests/integration/test_phase1_api.py::test_root_endpoint PASSED          [ 38%]
tests/integration/test_phase1_api.py::test_html_index_endpoint PASSED    [ 40%]
tests/integration/test_phase1_api.py::test_health_endpoint PASSED        [ 42%]
tests/integration/test_phase1_api.py::test_ready_endpoint PASSED         [ 45%]
tests/integration/test_phase1_api.py::test_system_status_endpoint PASSED [ 47%]
tests/integration/test_phase1_api.py::test_data_sources_endpoint PASSED  [ 50%]
tests/integration/test_phase2_gtfs.py::test_gtfs_network_counts PASSED   [ 52%]
tests/integration/test_phase2_gtfs.py::test_stop_search PASSED           [ 54%]
tests/integration/test_phase2_gtfs.py::test_nearby_stops_spatial_search PASSED [ 57%]
tests/integration/test_phase2_gtfs.py::test_route_and_trip_retrieval PASSED [ 59%]
tests/unit/test_adr001_storage.py::test_storage_diagnostics_e_drive PASSED [ 61%]
tests/unit/test_adr001_storage.py::test_pip_cache_and_temp_on_e PASSED   [ 64%]
tests/unit/test_adr002_historical_analytics.py::test_sqlite_readonly_enforcement PASSED [ 66%]
tests/unit/test_adr002_historical_analytics.py::test_duckdb_parquet_dual_distribution PASSED [ 69%]
tests/unit/test_adr002_historical_analytics.py::test_dwell_accounting_no_double_counting PASSED [ 71%]
tests/unit/test_adr003_coordinates_metric.py::test_pyproj_epsg32643_always_xy PASSED [ 73%]
tests/unit/test_adr003_coordinates_metric.py::test_metric_segmentation_logic PASSED [ 76%]
tests/unit/test_adr004_raptor_routing.py::test_pareto_dominance PASSED   [ 78%]
tests/unit/test_adr004_raptor_routing.py::test_gtfs_midnight_time_parsing PASSED [ 80%]
tests/unit/test_adr004_raptor_routing.py::test_transfer_realism_same_and_different_stops PASSED [ 83%]
tests/unit/test_adr005_fusion.py::test_consecutive_vehicle_speed PASSED  [ 85%]
tests/unit/test_adr005_fusion.py::test_fresh_live_fusion PASSED          [ 88%]
tests/unit/test_adr005_fusion.py::test_aging_live_fusion PASSED          [ 90%]
tests/unit/test_adr005_fusion.py::test_stale_live_fusion_cutoff PASSED   [ 92%]
tests/unit/test_adr005_fusion.py::test_variance_floor_enforcement PASSED [ 95%]
tests/unit/test_adr006_immutability_provenance.py::test_manifest_schema_and_idempotency PASSED [ 97%]
tests/unit/test_adr006_immutability_provenance.py::test_atomic_staging_write PASSED [100%]

================== 42 passed, 1 warning in 61.99s ===================
```

---

## 8. Remaining Limitations & Edge Cases Handled

1. **Unmapped Isolated Corridors**: If an arbitrary coordinate is selected in rural outer Delhi far from any bus stop (> 1,500m), the planner explicitly displays: `"No transit stops found matching origin ... No bus stop within 1.5 km of this location"`.
2. **Missing Bearing in Live AVL**: For buses where the GPS device transmits `bearing = null`, the marker retains standard upright alignment without fabricating bogus vehicle orientations.
3. **Third-Party Geocoder Outages**: In the event that Geoapify rate limits are exceeded or the network is unreachable, autocomplete falls back instantly to the local DuckDB GTFS database, ensuring users can always search all 6,862 Delhi bus stops.
