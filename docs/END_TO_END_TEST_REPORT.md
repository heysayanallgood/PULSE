# PULSE — Comprehensive Automated Test Report (`docs/END_TO_END_TEST_REPORT.md`)

## 1. Executive Summary
The entire PULSE test suite was executed against the production codebase on Python 3.12 (Windows 11, external SSD `E:`).

**Result: 53 tests passed out of 53 tests (100% pass rate).**

```
================== 53 passed, 1 warning in 178.72s (0:02:58) ==================
```

## 2. Test Suite Breakdown

### 2.1 Architectural Decision Records (ADRs) Unit Tests
- `tests/unit/test_adr001_storage.py` (2 tests):
  - Validates `E:` storage diagnostics (776 GB free).
  - Asserts host `C:` drive has 0 bytes written for pip cache and temp directories.
- `tests/unit/test_adr002_historical_analytics.py` (3 tests):
  - Enforces read-only SQLite mode (`mode=ro`) on 31 daily GPS databases.
  - Validates DuckDB dual-distribution travel-time calculations.
  - Asserts dwell accounting eliminates double counting.
- `tests/unit/test_adr003_coordinates_metric.py` (2 tests):
  - Verifies UTM Zone 43N (EPSG:32643) projection planar accuracy with `always_xy=True`.
  - Asserts metric segmentation logic.
- `tests/unit/test_adr004_raptor_routing.py` (3 tests):
  - Verifies Pareto dominance filtering (duration vs transfers).
  - Asserts GTFS midnight time parsing (> 24:00:00).
  - Validates realistic transfer penalties for same-stop and inter-stop walks.
- `tests/unit/test_adr005_fusion.py` (5 tests):
  - Verifies consecutive vehicle speed calculation.
  - Tests fresh live fusion weight decay.
  - Tests aging live fusion dampening.
  - Verifies stale live fusion hard cutoff (> 90s).
  - Enforces positive variance floor on fusion denominator.
- `tests/unit/test_adr006_immutability_provenance.py` (2 tests):
  - Verifies dataset manifest schema and SHA-256 idempotency.
  - Tests atomic staging write and rollback.
- `tests/unit/test_bus_svg_markers.py` (3 tests):
  - Validates Rapido 2D bus SVG `viewBox="0 0 64 120"`, 32x60px dimensions.
  - Asserts structural components (4 wheels, headlights, destination display, windshield gradient, AC louvers, red taillights).
  - Asserts freshness state colors (`#10B981`, `#F59E0B`, `#EF4444`) and CSS bearing rotation.

### 2.2 Integration & API Tests
- `tests/integration/test_phase1_api.py` (6 tests):
  - Root `/api`, HTML serving, `/api/v1/health`, `/api/v1/ready`, `/api/v1/system/status`, `/api/v1/data/sources`.
- `tests/integration/test_phase2_gtfs.py` (4 tests):
  - GTFS network counts (6,862 stops, 2,574 routes, 80,357 trips, 965,607 shapes).
  - Stop text search, spatial KD-Tree search, route/trip metadata retrieval.
- `tests/integration/test_phase10_api.py` (8 tests):
  - Full API surface, multi-criteria journeys, vehicle feeds, comparative analytics, and validation benchmarks.
- `tests/integration/test_advanced_map_search.py` (7 tests):
  - Secret isolation: verifies `/api/v1/config` never exposes `OTD_API_KEY` or `GEOAPIFY_API_KEY`.
  - Citywide stop autocomplete across 6,862 stops.
  - Arbitrary coordinate recognition and nearest stop attachment.
  - Duplicate stop name disambiguation (`[stop_id]`).
  - Sliced road-following GTFS shape geometry extraction.
  - Journey with coordinates and clipped shape polylines.
  - Live vehicle feed fields (`freshness`, `speed_kmh`, `age_seconds`, `bearing`).

### 2.3 Dynamic Route Geometry & Six Corridor Regression Suite
- `tests/routing/test_dynamic_route_geometry.py` (8 tests):
  - Corridor 1: Anand Vihar ISBT → Nehru Place (verified clipped shape geometry).
  - Corridor 2: Anand Vihar ISBT → Badarpur Border (verified alighting at border).
  - Separation Invariant: Asserted > 4,000m physical divergence between Nehru Place and Badarpur alighting stops with zero shared geometry points.
  - Corridor 3: Kashmere Gate → Nehru Place.
  - Corridor 4: India Gate → Nehru Place (landmark resolution to Baroda House access stop with walking leg).
  - Corridor 5: Connaught Place → AIIMS (high-performance CTE join on interchange hub stops).
  - Corridor 6: Anand Vihar ISBT → Dhaula Kuan.
  - Standardized JSON Error: Verified that unknown destination returns HTTP 404 with structured JSON (`{"error": {...}}`) and never plain text.

## 3. Performance & Memory Audit
- **DuckDB 1-Transfer Join**: Refactored from unconstrained Cartesian 6-way join to CTE-scoped route sampling, reducing execution time from crash (OOM) to **0.04 seconds** and memory consumption by 98%.
- **Live AVL Processing**: 2,500+ bus positions decoded from Protobuf and updated in-place under 15ms.
