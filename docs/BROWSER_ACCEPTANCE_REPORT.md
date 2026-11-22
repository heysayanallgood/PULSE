# PULSE — Browser-Level End-to-End Acceptance Report

## Executive Summary
This report provides formal verification of the PULSE web application running in a real browser session (Microsoft Edge via Playwright on Windows 11). All 10 verification phases completed successfully without timeouts or unhandled exceptions, producing 13 high-resolution evidence artifacts stored in `docs/evidence/`.

## 1. Acceptance Checklist

| Phase | Test Scenario | Verified Feature | Status | Evidence Artifact |
|---|---|---|---|---|
| **01** | Default Map Loading | Bright CARTO Positron basemap + Floating Layer Selector + Cyan Action Buttons | **PASS** | `01_journey_planner_default.png` |
| **02** | Origin Map Picker | Active glowing `#btn-pick-origin` + Floating top banner instruction | **PASS** | `02_pick_origin_active.png` |
| **03** | Origin Pin Placed | High-precision numeric coordinates populated + Emerald Origin pin on canvas | **PASS** | `03_origin_pinned.png` |
| **04** | Destination Pin Placed | High-precision numeric coordinates populated + Coral Destination pin on canvas | **PASS** | `04_destination_pinned.png` |
| **05** | Dynamic Route A | Anand Vihar ISBT $\to$ Nehru Place: Genuine East-to-South Delhi GTFS shape polyline | **PASS** | `05_dynamic_route_anand_vihar_nehru_place.png` |
| **06** | Dynamic Route B | Anand Vihar ISBT $\to$ Badarpur Border: Distinct southern terminus polyline | **PASS** | `06_dynamic_route_anand_vihar_badarpur_border.png` |
| **07** | Satellite Plain | MapTiler high-res satellite imagery without labels | **PASS** | `07_satellite_plain_view.png` |
| **08** | Satellite Hybrid | MapTiler satellite imagery with sharp road network vector overlays | **PASS** | `08_satellite_hybrid_view.png` |
| **09** | Live Bus Overview | Authentic OTD stream (~2,500 active DTC buses) with marker clustering | **PASS** | `09_live_bus_map_overview.png` |
| **10** | Rapido-Style Bus SVGs | Zoom 16: Top-down 2D bus SVGs with bearing orientation, headlights, wheels & freshness glows | **PASS** | `10_live_bus_svg_close_up.png` |
| **11** | Vehicle Popup | Vehicle ID, speed, route, freshness age & corridor match displayed in Leaflet popup | **PASS** | `11_bus_popup_provenance.png` |
| **12** | Citywide Autocomplete | Debounced stop & landmark search across all 6,862 Delhi stops | **PASS** | `12_citywide_search_autocomplete.png` |
| **13** | Standardized Error | Invalid stop gracefully displays friendly empty state without crashing UI | **PASS** | `13_genuine_no_route_error.png` |

## 2. Evidence Gallery

### Map Basemaps & Satellite Imagery
- **CARTO Positron Light (Default)**:
  ![01 Journey Planner](evidence/01_journey_planner_default.png)
- **MapTiler Satellite Plain**:
  ![07 Satellite Plain](evidence/07_satellite_plain_view.png)
- **MapTiler Satellite Hybrid**:
  ![08 Satellite Hybrid](evidence/08_satellite_hybrid_view.png)

### Pick on Map Functionality
- **Pick Mode Activated**:
  ![02 Pick Origin Active](evidence/02_pick_origin_active.png)
- **Origin Coordinate Captured**:
  ![03 Origin Pinned](evidence/03_origin_pinned.png)
- **Destination Coordinate Captured**:
  ![04 Destination Pinned](evidence/04_destination_pinned.png)

### Dynamic Route Geometry (No Hardcoded Fallbacks)
- **Anand Vihar to Nehru Place**:
  ![05 Dynamic Route A](evidence/05_dynamic_route_anand_vihar_nehru_place.png)
- **Anand Vihar to Badarpur Border**:
  ![06 Dynamic Route B](evidence/06_dynamic_route_anand_vihar_badarpur_border.png)

### Live Bus Map & Rapido-Style 2D Bus SVGs
- **Network Overview**:
  ![09 Live Bus Map](evidence/09_live_bus_map_overview.png)
- **2D Bus SVGs Oriented by Bearing**:
  ![10 Live Bus SVG](evidence/10_live_bus_svg_close_up.png)
- **Vehicle Details Popup**:
  ![11 Bus Popup](evidence/11_bus_popup_provenance.png)

### Search & Resilient JSON Handling
- **Citywide Search Autocomplete**:
  ![12 Autocomplete Search](evidence/12_citywide_search_autocomplete.png)
- **Graceful Empty State**:
  ![13 Error Handling](evidence/13_genuine_no_route_error.png)
