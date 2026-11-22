# PULSE — Delhi Citywide Stop & Location Search (`docs/DELHI_CITYWIDE_SEARCH.md`)

## 1. Search Scope & Dataset Coverage
PULSE indexes **all 6,862 verified Delhi Transport Corporation (DTC) bus stops** in a high-speed DuckDB spatial table, alongside curated prominent Delhi landmarks and an authenticated Geoapify address autocomplete proxy.

## 2. Capabilities

### 2.1 Full-Text Stop Search with Duplicate Disambiguation
- Multi-word prefix matching (`stop_name ILIKE '%query%'`).
- Disambiguation: Duplicate stop names across different corridors or opposite sides of the carriageway are appended with their GTFS identifier:
  ```
  Kashmere Gate [7571]
  Kashmere Gate [7572]
  ```

### 2.2 Arbitrary Coordinate Support
- Accepts direct WGS84 coordinates in the format `lat, lon` (e.g. `28.6139, 77.2090`).
- Validates that coordinates lie within the Delhi NCR transit bounding box (`28.2`°N to `28.95`°N, `76.8`°E to `77.55`°E).
- Automatically queries the spatial index to attach the nearest DTC bus stop within walking radius (up to 1,500m).

### 2.3 Interactive "Pick on Map"
- Users can click "Pick Origin on Map" or "Pick Destination on Map" to enter crosshair placement mode.
- Clicking any point on the map retrieves `e.latlng`, formats the coordinates into the input field, drops an origin/destination pin, and clears pick mode.
- In default exploration mode, clicking anywhere in Delhi opens a quick context popup offering one-click buttons: `🟢 Set Origin` / `🔴 Set Destination`.

### 2.4 Geoapify Address Proxy with Secret Isolation
- Endpoint: `GET /api/v1/places/autocomplete?q={query}&limit=8`
- Enforces strict secret isolation: `GEOAPIFY_API_KEY` resides strictly on the backend in `app/core/config.py` and is never exposed in client HTML or JavaScript.
- Biased to Delhi NCR (`filter: rect:76.8,28.2,77.55,28.95`, `bias: proximity:77.2167,28.6328`).
- 1-hour in-memory TTL caching (1,000 entries max) to prevent rate limit exhaustion.

### 2.5 Curated Delhi Landmark Catalog
- Built-in resolution for 35+ major landmarks (India Gate, Connaught Place, Red Fort, Lotus Temple, Qutub Minar, AIIMS, Dhaula Kuan, Delhi Airport T1/T3, New Delhi Railway Station, etc.).
- Resolves landmarks to geographic centroids and discovers all surrounding boarding stops within 800m, attaching walking access legs.
