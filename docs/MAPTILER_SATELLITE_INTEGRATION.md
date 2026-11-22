# PULSE — MapTiler Satellite & Multi-Basemap Architecture (`docs/MAPTILER_SATELLITE_INTEGRATION.md`)

## 1. Overview
PULSE defaults to a clean, light street cartography (CARTO Positron) while providing a top-tier multi-basemap layer control that supports high-resolution satellite imagery with zero proprietary vendor lock-in.

## 2. Basemap Catalog & Providers

| Layer Name | Provider | URL Endpoint | Notes |
|---|---|---|---|
| **☀️ Street (Positron)** | CARTO | `https://{s}.basemaps.cartocdn.com/rastertiles/light_all/{z}/{x}/{y}.png?key=...` | **Default Basemap**. Bright, minimal, optimal contrast for transit polylines. |
| **🧭 Voyager (Detailed)** | CARTO | `https://{s}.basemaps.cartocdn.com/rastertiles/voyager/{z}/{x}/{y}.png?key=...` | Rich street details, landmarks, building footprints. |
| **🌙 Dark Matter** | CARTO | `https://{s}.basemaps.cartocdn.com/rastertiles/dark_all/{z}/{x}/{y}.png?key=...` | High-contrast night mode for low-light monitoring. |
| **🛰️ Satellite (Plain)** | MapTiler / Esri | `https://api.maptiler.com/maps/satellite-v4/{z}/{x}/{y}.jpg?key=...` | Pure high-resolution aerial photography. |
| **🛰️ Satellite (Hybrid)** | MapTiler / Esri | `https://api.maptiler.com/maps/hybrid-v4/{z}/{x}/{y}.png?key=...` | Aerial photography overlaid with road names, highways, and borders. |
| **🗺️ OpenStreetMap** | OSM | `https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png` | Unauthenticated open-source standard fallback. |

## 3. MapTiler 512px High-DPI Optimization
MapTiler raster tiles are delivered at 512x512 resolution. The Leaflet layer definition configures:
```javascript
tileSize: maptilerKey ? 512 : 256,
zoomOffset: maptilerKey ? -1 : 0
```
This ensures crisp, sharp imagery on high-DPI retina displays without stretching or coordinate distortion.

## 4. Graceful Fallback Strategy
If `MAPTILER_API_KEY` is not provided in `.env`:
- The satellite endpoints seamlessly fall back to **Esri World Imagery** (`https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}`).
- The user is never presented with broken tile images or missing layers.

## 5. Overlay Persistence Invariant
All route polylines, walking segments, vehicle marker clusters, and search pins are attached to persistent overlay groups (`state.routeLayer` and `state.clusterGroup`). Switching between Positron, Dark Matter, or Satellite preserves all route and bus layers without reloading the page.
