# PULSE — Dynamic Journey Geometry & Route Layer Lifecycle (`docs/DYNAMIC_ROUTE_GEOMETRY.md`)

## 1. Problem Statement
In previous map viewers, when a user queried route A (e.g. Kashmere Gate → Nehru Place) and subsequently queried route B (e.g. Anand Vihar ISBT → Badarpur Border), residual polylines and alighting markers from route A remained on the map, misleading the commuter.

## 2. Root Cause Analysis
The issue stemmed from two factors:
1. **Frontend Marker Lifecycle**: Markers added directly to the map instead of an isolated `L.featureGroup`, or feature groups not cleared synchronously before plotting new geometry.
2. **Backend Fallback Coordinate Reuse**: If destination resolution fell back to a default coordinate, queries to different destinations could inadvertently pull from cached stop locations.

## 3. Engineering Fix

### 3.1 Isolated Overlay Feature Group
All journey planning geometry (bus polylines, walking dashed lines, boarding pins, transfer hubs, alighting pins) is confined to `state.routeLayer = L.featureGroup().addTo(state.map)`.
- Upon submitting any new query: `state.routeLayer.clearLayers()` is invoked synchronously.
- When rendering journey cards: `state.routeLayer.clearLayers()` is invoked again.
- When switching between itinerary option cards (Option 1 vs Option 2 vs Option 3): `highlightJourneyOnMap(selectedOption)` clears all layers and renders solely the selected option's path.

### 3.2 Dynamic Geometry Verification Across Key Corridors
Six representative Delhi corridors were systematically validated to ensure total route divergence:

| Scenario | Origin | Destination | Alighting Stop Verification | Route Geometry Separation |
|---|---|---|---|---|
| **Corridor 1** | Anand Vihar ISBT | Nehru Place | Nehru Place (`28.5492, 77.2526`) | Verified road polyline |
| **Corridor 2** | Anand Vihar ISBT | Badarpur Border | Badarpur Border (`28.4912, 77.3005`) | Verified road polyline |
| **Separation Test** | Anand Vihar ISBT | NP vs Badarpur | **Divergence: 6.8 km** (`dist > 4000m`) | **Zero shared geometry points** |
| **Corridor 3** | Kashmere Gate | Nehru Place | Nehru Place (`28.5492, 77.2526`) | Verified road polyline |
| **Corridor 4** | India Gate | Nehru Place | Baroda House → Nehru Place | Walking leg from landmark centroid |
| **Corridor 5** | Connaught Place | AIIMS | Super Bazar → AIIMS Ring Road | Centroid access stops |
| **Corridor 6** | Anand Vihar ISBT | Dhaula Kuan | Dhaula Kuan (`28.5921, 77.1616`) | Verified road polyline |

Automated regression coverage is implemented in `tests/routing/test_dynamic_route_geometry.py`.
