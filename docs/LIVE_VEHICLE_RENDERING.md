# PULSE — Live Vehicle Positions & Cluster Lifecycle (`docs/LIVE_VEHICLE_RENDERING.md`)

## 1. Live Feed Ingestion
PULSE ingests authentic GTFS-Realtime Protocol Buffers directly from the Delhi Open Transit Data (OTD) portal:
- **Endpoint**: `https://otd.delhi.gov.in/api/realtime/VehiclePositions.pb`
- **Authentication**: `OTD_API_KEY` passed as private query parameter `?key=...` on the backend.
- **Strict Invariant**: Zero synthetic, simulated, or hallucinated vehicles. If the feed drops, the engine clearly announces fallback status rather than fabricating fake congestion.

## 2. In-Place Marker Mutation (`loadLiveBuses`)
Rendering 2,500+ active buses in Leaflet can cause severe memory leaks and DOM thrashing if markers are destroyed and recreated on each 30-second poll.

PULSE solves this via an in-place mutation map: `state.busMarkers = new Map()`:
1. **Existing Vehicles**: For each vehicle already in `state.busMarkers`, `marker.setLatLng([b.lat, b.lon])` updates its position smoothly.
2. **Icon & Bearing Update**: `marker.setIcon(...)` updates the 2D bus SVG with the latest heading rotation and freshness halo.
3. **New Vehicles**: Created and appended to `state.clusterGroup`.
4. **Expired Vehicles**: Buses that have ceased transmitting are removed via `state.clusterGroup.removeLayer(marker)` and deleted from the Map.

## 3. Two-Tier Marker Clustering (`Leaflet.markercluster`)
- **City-wide Zoom ($Z < 14$)**: High vehicle density over Delhi (up to 2,500 dots) is aggregated into sleek circular cluster bubbles with cyan glowing halos and vehicle count badges.
- **Corridor Zoom ($Z \ge 14$)**: Clustering automatically disengages (`disableClusteringAtZoom: 14`), expanding the cluster into individual, rotatable 2D bus icons showing exact vehicle direction, route identifiers, and speeds.
