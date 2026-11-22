# PULSE — Known Limitations & Operational Boundaries (`docs/KNOWN_LIMITATIONS.md`)

## 1. Upstream Real-Time Data (Delhi OTD Feed)
- **Device Transmit Jitter**: Individual onboard bus GPS units transmit at varying intervals (typically 10 to 60 seconds). During peak network congestion or underpasses, intermittent packet gaps occur. PULSE marks observations older than 60 seconds as `AGING` and older than 90 seconds as `STALE`, dropping live weight accordingly (ADR 005).
- **Zero Speed Transmissions**: Several DTC buses report `speed = 0.0` when stuck in severe traffic jams or waiting at signals. PULSE distinguishes vehicle dwell from movement using consecutive GPS point differentials.
- **Unassigned Routes**: A small percentage (~5%) of active GPS devices in the live feed transmit `route_id = null` (e.g. depot deadheading or depot transfers). These are displayed on the live bus map as "Raw AVL Position" but excluded from scheduled route matching.

## 2. Transit Network Service Bounds
- **Walking Radius Threshold**: The default walking access radius is set to 800m, expanding to a maximum of 1,500m. If a user drops a pin in remote rural farmland in outer Delhi (> 1.5 km from any bus stop), the system safely returns `NO_STOPS_FOUND` with an explanatory notification.
- **Inter-State Long Distance Routes**: Static GTFS covers Delhi Transport Corporation routes within Delhi NCR. Inter-state express buses to neighboring states (Haryana, Uttar Pradesh, Punjab) operating outside DTC's public feed are outside scope.

## 3. Map Tile Providers
- **MapTiler Free Tier Quotas**: Free-tier MapTiler keys provide 100,000 requests/month. If quotas are exhausted, PULSE automatically fails over to Esri World Imagery without interrupting the map experience.
- **Client Offline Mode**: If internet access drops entirely, CARTO and satellite raster tiles cannot load, but local GTFS routing, stop search, and DuckDB analytical queries continue functioning offline.
