# PULSE — REST API Reference Documentation
**Base URL:** `http://127.0.0.1:8000`  
**Interactive Swagger UI:** `http://127.0.0.1:8000/docs`  
**OpenAPI Specification:** `http://127.0.0.1:8000/openapi.json`  

---

## 1. System & Diagnostic Endpoints

### `GET /api/v1/health`
Liveness probe reporting process status and uptime.
```json
{
  "status": "HEALTHY",
  "timestamp": "2026-11-20T21:30:00Z",
  "uptime_seconds": 1420.5,
  "version": "1.0.0",
  "environment": "development"
}
```

### `GET /api/v1/ready`
Readiness probe verifying that the workspace storage (`E:\Pulse`) is accessible, writable, and disk capacity exceeds thresholds.

### `GET /api/v1/system/status`
Comprehensive operational status of storage volumes, datasets, models, and real-time feed connectivity.

### `GET /api/v1/data/sources`
Inventory of all active datasets, record counts, file formats, and data provenance tags.

---

## 2. Bus Stops & Geometry Endpoints

### `GET /api/v1/stops/search?q={query}&limit={limit}`
Searches bus stops by name or `stop_id`.
**Parameters:**
- `q` (string, required): Search query (e.g. `Kashmere Gate`)
- `limit` (int, optional, default: 10): Max results

### `GET /api/v1/stops/nearby?lat={lat}&lon={lon}&radius={radius}&limit={limit}`
Finds nearest bus stops using in-memory KD-Tree in metric EPSG:32643 coordinates.
**Parameters:**
- `lat` (float, required): WGS84 Latitude
- `lon` (float, required): WGS84 Longitude
- `radius` (float, optional, default: 1000.0): Search radius in meters

### `GET /api/v1/stops/{stop_id}`
Retrieves detailed metadata for a specific bus stop.

---

## 3. Transit Routes & Shapes Endpoints

### `GET /api/v1/routes?limit={limit}&agency={agency}`
Lists bus routes with optional agency filtering (`DTC` or `DIMTS`).

### `GET /api/v1/routes/{route_id}`
Returns route details, short name, long name, and agency.

### `GET /api/v1/routes/{route_id}/shape`
Returns the complete polyline coordinate sequence (`lat`, `lon`, `seq`) for the primary shape of the route.

---

## 4. Journey Planning Endpoints

### `GET /api/v1/journeys`
Computes Pareto-optimal bus journeys driven by the PULSE Spatiotemporal Model.
**Parameters:**
- `from` (string, required): Origin stop name or coordinates (`lat,lon`)
- `to` (string, required): Destination stop name or coordinates (`lat,lon`)
- `depart_at` (string, optional): Departure time in `HH:MM:SS` (default: current local time)
- `date` (string, optional): Departure date in `YYYY-MM-DD` (default: current date)

**Sample Response:**
```json
{
  "status": "SUCCESS",
  "origin": "ISBT Kashmere Gate Terminal",
  "destination": "Nehru Place",
  "departure_time": "08:30:00",
  "journey_options_count": 1,
  "options": [
    {
      "option_id": 1,
      "total_duration_minutes": 90.7,
      "in_vehicle_minutes": 81.4,
      "walking_minutes": 5.7,
      "waiting_minutes": 3.6,
      "transfers": 0,
      "confidence": "HIGH",
      "provenance": "HISTORICAL",
      "lower_bound_minutes": 78.2,
      "upper_bound_minutes": 95.1,
      "legs": [
        {
          "type": "WALK",
          "instruction": "Walk to ISBT Kashmere Gate Terminal",
          "distance_m": 108.6,
          "duration_minutes": 1.5,
          "walk_type": "APPROXIMATED_WALK"
        },
        {
          "type": "BUS",
          "route_id": "2753",
          "route_name": "425UP",
          "boarding_stop": "ISBT Kashmere Gate Terminal",
          "alighting_stop": "Paras Cinema",
          "stops_traversed": 34,
          "distance_km": 17.58,
          "departure_time": "08:35:00",
          "predicted_duration_minutes": 81.4,
          "confidence": "HIGH",
          "provenance": "HISTORICAL"
        },
        {
          "type": "WALK",
          "instruction": "Walk from Paras Cinema to destination",
          "distance_m": 303.7,
          "duration_minutes": 4.2,
          "walk_type": "APPROXIMATED_WALK"
        }
      ]
    }
  ],
  "off_peak_comparison": {
    "off_peak_departure": "23:00 (Late Night)",
    "off_peak_duration_minutes": 33.2,
    "peak_duration_minutes": 81.4,
    "congestion_delay_minutes": 48.2,
    "insight": "At 11:00 PM, free-flow traffic saves ~48.2 minutes on this journey."
  }
}
```

---

## 5. Analytics & Live Vehicle Endpoints

### `GET /api/v1/analytics/time-comparison`
Compares travel times across key periods of the day for a route corridor:
- Morning Peak (08:30)
- Midday (11:00)
- Afternoon (14:00)
- Evening Peak (18:30)
- Late Night (23:00)

### `GET /api/v1/vehicles`
Returns authentic active live vehicle positions from the Delhi OTD GTFS-RT stream.
**Attributes per vehicle:**
- `vehicle_id`: Bus registration
- `lat`, `lon`: Coordinates
- `speed_kmh`: Current speed
- `freshness`: `FRESH`, `AGING`, or `STALE`
- `age_seconds`: Elapsed time since observation
