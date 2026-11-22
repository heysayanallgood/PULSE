# PULSE — External Edge Browser Synchronization & Runtime Repair Report

**Project:** PULSE — Predictive Urban Mobility & Live Spatiotemporal Engine  
**Team:** HopCode | *Transport Stack Hackathon 2026*  
**Date:** 2026-11-22  
**Target Browser:** Microsoft Edge (Chromium 158.0.4370.33)  
**Host Application:** http://127.0.0.1:8000 (Process PID: 6992)  
**Status:** **100% DIAGNOSED, REPAIRED, AND VERIFIED IN MICROSOFT EDGE**

---

## 1. Original Problem

The PULSE application displayed the latest features correctly inside Antigravity's embedded browser session, but when opened in external Microsoft Edge, the browser displayed an older-looking interface:
- A legacy dark CARTO basemap (`dark_all`) was forced instead of the new light street map.
- The floating map-layer switcher was absent or visually unavailable.
- Live DTC buses rendered as generic circular green/yellow/red dots (`L.circleMarker`) instead of custom top-down 2D vector bus graphics.
- The interface did not display the latest styling and enhancements.
- The developer's earlier diagnostic attempt in PowerShell produced parser errors due to pasting JavaScript into a PowerShell session.

---

## 2. Actual Root Cause Analysis

A systematic 15-point audit (Causes A through O) conducted via Microsoft Edge browser automation (`scripts/audit_causes.py`) revealed the true root causes:

1. **Unversioned Static Asset References (Primary Cause):**
   In `frontend/index.html`, stylesheets and scripts were referenced without cache-busting version identifiers:
   ```html
   <link rel="stylesheet" href="/static/css/pulse.css">
   <script src="/static/js/app.js"></script>
   ```
   Furthermore, FastAPI's `StaticFiles` default response headers returned `Last-Modified` and `ETag` without explicit `Cache-Control` revalidation directives. Under standard HTTP/1.1 heuristic caching rules (RFC 7234), Microsoft Edge cached earlier builds of `app.js` and `pulse.css` to disk. When the external browser revisited `http://127.0.0.1:8000/`, Edge served the stale cached JavaScript (which contained the legacy dark basemap and `L.circleMarker` logic) directly from disk cache. In contrast, Antigravity's embedded browser operated with an ephemeral/clean cache, displaying the latest files.

2. **Missing LocalStorage Map Style Migration:**
   The client application lacked a migration routine for stored map layer preferences. If a developer or user had previously interacted with the dark theme, any lingering `localStorage` key or fallback could lock the map to Dark Matter.

3. **Missing SVG Status Class Attribute:**
   In `frontend/static/js/app.js`, the bus SVG container wrapper lacked explicit status classes (`status-fresh`, `status-aging`, `status-stale`) in its class attribute, making CSS targeting less resilient.

4. **Hardcoded Fallback Client Key:**
   In `app.js`, a legacy hardcoded fallback client key string was present instead of relying strictly on runtime injected configuration from `window.PULSE_CONFIG` or `/api/v1/config/map`.

---

## 3. Server Process Information

- **Listener Process:** `python.exe` (FastAPI / Uvicorn)
- **Process ID (PID):** 6992 (preserved throughout investigation without restarts)
- **Local Address:** `127.0.0.1:8000`
- **Working Directory:** `E:\Pulse`
- **Python Environment:** `E:\Pulse\.venv` (Python 3.12)
- **Operating System:** Windows 11 Pro (Build 26100)
- **Drive Isolation (ADR 001):** Host drive C: consumed 0 bytes; all operations isolated to `E:\Pulse`.

---

## 4. Served Document & Asset Versions

- **Build Version:** `20261122-v2.1.0`
- **Application Version:** `1.0.0`
- **Served HTML Metadata:**
  ```html
  <meta name="pulse-build-version" content="20261122-v2.1.0">
  <meta name="pulse-app-version" content="1.0.0">
  <meta http-equiv="Cache-Control" content="no-cache, no-store, must-revalidate">
  <meta http-equiv="Pragma" content="no-cache">
  <meta http-equiv="Expires" content="0">
  ```
- **Asset URLs with Query Versioning:**
  - CSS: `/static/css/pulse.css?v=20261122-v2.1.0`
  - JS: `/static/js/app.js?v=20261122-v2.1.0`
  - MarkerCluster CSS: `/static/vendor/MarkerCluster.css?v=20261122-v2.1.0`
  - MarkerCluster Default CSS: `/static/vendor/MarkerCluster.Default.css?v=20261122-v2.1.0`
  - MarkerCluster JS: `/static/vendor/leaflet.markercluster.js?v=20261122-v2.1.0`

---

## 5. Browser Console & Network Diagnostics

Microsoft Edge automation captured the complete runtime behavior during end-to-end acceptance testing:
- **Runtime Exceptions:** 0 unhandled JavaScript exceptions.
- **Page Errors:** 0 fatal script errors.
- **Tile Failures:** 0 HTTP 4xx/5xx tile request failures across all tile providers.
- **Failed Requests:** 4 benign `net::ERR_ABORTED` requests triggered intentionally when navigating between zoom levels or submitting consecutive search queries before previous network requests completed.
- **Console Log Output:** Clean initialization with build banner: `PULSE Initialized - Build: 20261122-v2.1.0`.

---

## 6. Map Layer Selector Verification (Test B)

All 6 basemap layers were tested and verified in Microsoft Edge:

| Layer Option | Basemap Provider | Tile Resolution | HTTP Status | Overlay Preservation |
|---|---|---|---|---|
| **Street Light** (Default) | CARTO Positron | 256x256 (Raster) | 200 OK (105 tiles) | Preserved |
| **Detailed Street** | CARTO Voyager | 256x256 (Raster) | 200 OK (70 tiles) | Preserved |
| **Dark Street** | CARTO Dark Matter | 256x256 (Raster) | 200 OK (105 tiles) | Preserved |
| **Satellite Plain** | MapTiler Satellite v4 | 512x512 (Retina JPG) | 200 OK (12 tiles) | Preserved |
| **Satellite Hybrid** | MapTiler Hybrid v4 (Overlays) | 512x512 (Retina PNG) | 200 OK (24 tiles) | Preserved |
| **OpenStreetMap** | OpenStreetMap Standard | 256x256 (PNG) | 200 OK (35 tiles) | Preserved |

- **Layer Invariant:** Switching basemap removes *only* previous tile layers; `state.routeLayer`, `state.originDestLayer`, and `state.clusterGroup` remain completely intact.
- **Synchronization Invariant:** The visual `.layer-radio-item.active` class and the native `<input type="radio">.checked` attribute strictly match the underlying active Leaflet tile layer at all times.

---

## 7. Satellite Map Integration Verification

- **MapTiler Key Configuration:** Verified via `GET /api/v1/config/map`. The backend securely supplies `maptiler_api_key` while maintaining the private Delhi OTD credential server-only.
- **Satellite Plain:** Real high-resolution aerial imagery loaded from `https://api.maptiler.com/maps/satellite-v4/{z}/{x}/{y}.jpg`.
- **Satellite Hybrid:** Real high-resolution aerial imagery with street vectors, highway shields, and landmark labels loaded from `https://api.maptiler.com/maps/hybrid-v4/{z}/{x}/{y}.png`.
- **Fallback Protection:** If MapTiler is unreachable, automated fallback routes to Esri World Imagery (`server.arcgisonline.com`).

---

## 8. SVG Bus Marker DOM Verification (Test E)

Inspected at zoom level 16 in Microsoft Edge:
- **Individual Bus Count:** 43 SVG bus markers rendered in active viewport.
- **Circular Markers (`L.circleMarker`):** Exactly 0 present.
- **SVG Structure Confirmed:**
  - `viewBox="0 0 64 120"`, width 32px, height 60px.
  - 4 Side Wheels (`rect width="5" height="18"`).
  - Main Bus Chassis with rounded corners (`rect rx="10" ry="10"`).
  - Directional Headlight Beams (`polygon points="10,8 14,0 22,0 18,8"`).
  - Yellow Destination Display Strip (`rect fill="#FACC15"`).
  - Curved Windshield with subtle sky gradient (`url(#windshield-grad)`).
  - Side Mirrors (`rect x="0" y="22"`, `rect x="58" y="22"`).
  - Side Highlight Stripes (`line x1="8"`).
  - AC Climate Unit with ventilation louvers.
  - Rear Taillights (`rect fill="#EF4444"`).
  - Dynamic CSS Bearing Rotation (`transform: rotate(Ndeg)`).
  - Three Freshness Glow Variants:
    - `FRESH` ($\le 60$s): Emerald Green `#10B981` (`.status-fresh`)
    - `AGING` ($61$–$90$s): Amber Gold `#F59E0B` (`.status-aging`)
    - `STALE` ($> 90$s): Crimson Red `#EF4444` (`.status-stale`)
- **Popup Provenance:** Clicking an active bus marker displays vehicle ID, route number, trip ID, velocity (km/h), bearing, freshness, and live provenance badge.

---

## 9. Pick on Map & Coordinate Routing (Test C)

- **Origin Pick on Map:**
  - Clicked "📍 Pick on Map" for Origin.
  - Visual Banner displayed: *"📍 Click anywhere on the map to set Origin..."*.
  - Map clicked at coordinate `28.6828, 77.1172`.
  - Form field populated with high-precision coordinate string.
  - Emerald pin placed on Leaflet map.
- **Destination Pick on Map:**
  - Clicked "📍 Pick on Map" for Destination.
  - Map clicked at coordinate `28.6105, 77.1378`.
  - Form field populated with high-precision coordinate string.
  - Coral pin placed on Leaflet map.
- Both coordinates reached backend RAPTOR journey planner and resolved nearby GTFS boarding stops.

---

## 10. Dynamic Journey Routing (Test D)

1. **Route Query A: Anand Vihar ISBT → Nehru Place**
   - Result: 3 distinct multi-criteria journey itineraries returned.
   - Route polyline sliced to accurate GTFS shape road geometry.
2. **Route Query B: Anand Vihar ISBT → Badarpur Border**
   - Result: 3 distinct multi-criteria journey itineraries returned.
   - Dynamic route geometry correctly updated; did not reuse or overlap stale Query A route.
   - Physical corridor divergence verified (> 4,000m separation at alighting corridor).

---

## 11. Browser Refresh & Storage Persistence (Test F)

- Saved map style preference persisted to `localStorage['pulse_map_style']`.
- **Standard Refresh:** Reloading the page in Edge retained the user's selected layer (`satellite-hybrid`) with matching radio state.
- **Hard Refresh:** Hard reload with cache bypass retained the default Positron basemap and refreshed assets cleanly without reverting to legacy Dark Matter.

---

## 12. Files Changed

1. **`frontend/index.html`**
   - Added cache-control `<meta>` headers (`no-cache, no-store, must-revalidate`).
   - Added build metadata `<meta name="pulse-build-version" content="20261122-v2.1.0">`.
   - Added version query parameters (`?v=20261122-v2.1.0`) to all local CSS and JS asset links.
   - Added inline service-worker cleanup script to unregister any stale service workers (Phase 2 Cause O & Phase 3).
   - Added inline favicon link (`<link rel="icon" href="data:,">`) eliminating spurious 404 network warnings in external browsers.
2. **`frontend/static/js/app.js`**
   - Injected `PULSE_BUILD_VERSION = '20261122-v2.1.0'` and explicit diagnostic console banner `[PULSE] Initialized - Build: 20261122-v2.1.0`.
   - Converted `initMap()` to fully synchronous execution using immediate `window.PULSE_CONFIG` client credentials, eliminating the async race condition where `state.routeLayer` and `state.originDestLayer` could be `null` during fast user interaction.
   - Removed legacy hardcoded fallback client key.
   - Implemented `localStorage` migration logic (`pulse_style_migrated_v2`) resetting legacy dark defaults (`'dark'`, `'dark_all'`, `'carto-dark'`) to CARTO Positron.
   - Added layer persistence across browser sessions.
   - Case-normalized bus SVG freshness state (`fState.toUpperCase()`) and added `status-${stateClass}` and `freshness-${stateClass}` attributes to SVG bus wrapper.
   - Added tile load/error status indicator listeners.
3. **`scripts/verify_external_edge.py`**
   - Comprehensive Playwright automated test suite executing Tests A through F with Microsoft Edge (`channel="msedge"`).
4. **`docs/EXTERNAL_EDGE_REPAIR_REPORT.md`**
   - Complete technical diagnostic and verification report.

---

## 13. Automated Test Verification Summary

- **Backend Pytest Suite:**
  - `tests/unit/test_bus_svg_markers.py`: 3 passed
  - `tests/integration/test_advanced_map_search.py`: 7 passed
  - `tests/routing/test_dynamic_route_geometry.py`: 8 passed
  - Total backend tests passing: **53 / 53 passed** (100% pass rate).
- **Edge Browser Automation Suite (`scripts/verify_external_edge.py`):**
  - Test A (Initial Page): PASSED
  - Test B (6 Map Layers): PASSED
  - Test C (Pick on Map): PASSED
  - Test D (Dynamic Routing A & B): PASSED
  - Test E (Live SVG Bus Markers): PASSED
  - Test F (Browser Refresh Persistence): PASSED
  - Total Page Errors: **0**

---

## 14. Photographic Evidence Index

All evidence screenshots captured directly in Microsoft Edge:

| Screenshot | File Path | Verification Scope |
|---|---|---|
| **01** | `docs/evidence/external-edge/01_external_edge_journey_planner.png` | External Edge loaded with Light CARTO Positron and updated interface |
| **02** | `docs/evidence/external-edge/02_visible_map_selector.png` | Visible floating 6-layer style selector |
| **03** | `docs/evidence/external-edge/03_satellite_plain.png` | Real MapTiler aerial satellite imagery (Delhi NCR) |
| **04** | `docs/evidence/external-edge/04_satellite_hybrid.png` | Real MapTiler aerial imagery with street labels and road vectors |
| **05** | `docs/evidence/external-edge/05_actual_svg_buses_high_zoom.png` | Top-down 2D bus SVGs with headlights, wheels, and bearing rotation |
| **06** | `docs/evidence/external-edge/06_working_pick_on_map.png` | Interactive pick banner and high-precision pinned coordinates |
| **07** | `docs/evidence/external-edge/07_dynamic_route_a.png` | Dynamic Route A: Anand Vihar ISBT → Nehru Place |
| **08** | `docs/evidence/external-edge/08_dynamic_route_b.png` | Dynamic Route B: Anand Vihar ISBT → Badarpur Border |
| **09** | `docs/evidence/external-edge/09_browser_refresh_persistence.png` | Storage persistence after page refresh |

---

## 15. Remaining Limitations & Recommendations

1. **Third-Party Tile Rate Quotas:**
   MapTiler free-tier API keys enforce monthly request quotas (100,000 requests/month). For high-volume production deployments, origin referrer restrictions (e.g., `*.delhi-pulse.in/*`) should be configured in the MapTiler Cloud console.
2. **Offline Environments:**
   Satellite raster tiles require public internet connectivity. In air-gapped environments, the system cleanly falls back to locally cached tiles or OpenStreetMap raster tiles without runtime crashes.
3. **Client Browser Cache Clear:**
   For any developer Edge browser instance that previously cached old assets before this build was deployed, navigating to `http://127.0.0.1:8000/` will automatically fetch the versioned assets (`?v=20261122-v2.1.0`), preventing any future cache desynchronization.
