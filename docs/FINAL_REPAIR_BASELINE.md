# PULSE — Final Repair Baseline Audit Report

**Date:** 2026-11-22  
**Environment:** Windows 11, Python 3.12 (`.venv`), FastAPI Backend, Leaflet 1.9.4 Frontend  
**Directive Target:** ULTIMATE MASTER IMPLEMENTATION DIRECTIVE  

---

## 1. Baseline Defect Analysis & Root Causes

Prior to this implementation cycle, browser inspection and developer feedback identified the following primary defects in the PULSE application:

### Defect 1: Circular Green/Yellow/Red Dots Instead of 2D Bus SVGs
- **Symptom:** Live bus markers on the Leaflet map rendered as generic `L.circleMarker` elements colored green/yellow/red. Vehicles lacked vehicle contours, headlights, windshield, wheels, and bearing rotation.
- **Root Cause:** In `frontend/static/js/app.js`, `L.circleMarker([b.lat, b.lon], ...)` was hardcoded inside `updateLiveBuses()`. No `L.divIcon` using SVG bus graphics existed.
- **Files Responsible:**
  - `frontend/static/js/app.js`
  - `frontend/static/css/pulse.css`
  - Missing SVG assets in `frontend/static/assets/buses/`

### Defect 2: Missing Map Layer Selector & Map Stuck on Dark CARTO Basemap
- **Symptom:** Leaflet map was locked to CARTO Dark Matter (`https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png`). No visible UI control existed on the map to switch basemaps, and MapTiler satellite imagery was unavailable.
- **Root Cause:** In `app/main.py`, there was no public map configuration endpoint to safely pass client keys (`MAPTILER_API_KEY`, `CARTO_API_KEY`) to the browser. In `frontend/index.html` and `frontend/static/js/app.js`, the default layer was hardcoded to Dark Matter without a custom layer switch widget.
- **Files Responsible:**
  - `app/main.py` (missing `GET /api/v1/config/map`)
  - `frontend/index.html` (missing `#pulse-layer-selector` widget)
  - `frontend/static/js/app.js` (`initMap()` and layer control logic)
  - `frontend/static/css/pulse.css` (styling for floating layer switcher)

### Defect 3: Ineffective "Pick on Map" Controls
- **Symptom:** Clicking "Pick on Map" did not clearly activate an interactive state, didn't provide cancel controls, and clicking the map canvas did not place distinct pins or write high-precision coordinates to form inputs.
- **Root Cause:** Handlers for origin and destination picking lacked distinct UI banners, crosshair cursors, and coordinate formatting. Additionally, subsequent route queries cleared all map layers, accidentally wiping the user's origin/destination pin markers.
- **Files Responsible:**
  - `frontend/index.html`
  - `frontend/static/js/app.js` (`startPickMode()`, `cancelPickMode()`, `onMapClick()`, `state.originDestLayer`)
  - `frontend/static/css/pulse.css`

### Defect 4: Static / Stale Route Polyline Slicing
- **Symptom:** Bus route geometry did not accurately reflect different origin/destination queries or direction of travel when `idx_board > idx_alight`.
- **Root Cause:** In `app/data/gtfs/repository.py`, the shape point slicing logic inverted point order when slicing backwards, resulting in distorted or flipped shape polylines.
- **Files Responsible:**
  - `app/data/gtfs/repository.py` (`get_clipped_shape_coordinates()`)

### Defect 5: Unhandled JSON Errors & Delayed Form Race Conditions
- **Symptom:** Invalid stops resulted in broken UI state. A delayed `setTimeout` auto-submit on page load caused unprovoked queries.
- **Root Cause:** `frontend/static/js/app.js` had an automatic timer calling form submit 600ms after load, and lacked standardized `safeFetchJson` error surfacing.
- **Files Responsible:**
  - `frontend/static/js/app.js`

---

## 2. Baseline Status Matrix

| Component | Initial Baseline State | Repaired Target State |
|---|---|---|
| Map Basemap | Dark Matter only | CARTO Positron Light (default) + 6-Layer Selector (Satellite Plain & Hybrid) |
| Bus Markers | Circular dots | Genuine 2D Rapido-style SVG buses with bearing rotation & headlights |
| Bus Clustering | Clustered at all levels | `disableClusteringAtZoom: 13` allowing individual 2D SVG buses |
| Pick on Map | Broken / non-functional | Full Pick on Map banner, crosshairs, emerald/coral pins & coordinate writing |
| Route Geometry | Slicing inversion bug | Real GTFS shapes with directional slicing preserving travel vector |
| Configuration | Hidden / leaked API keys | `GET /api/v1/config/map` returning public tile keys; OTD key backend-only |
| Test Suite | 53 tests | 64 tests (53 original + 3 SVG marker unit + 8 dynamic routing) |
| Evidence | None | 13 high-resolution browser screenshots in `docs/evidence/` |
