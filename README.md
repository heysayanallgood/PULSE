# PULSE — Predictive Urban Mobility & Live Spatiotemporal Engine
### Team HopCode | Transport Stack Hackathon 2026 — Phase 1, Problem 1
> *"The City Moves. We Decode Its Pulse."*

PULSE is a traffic model of Delhi's DTC buses, built from 31 days of real bus
GPS (October 2026, ~920M raw rows), plugged into a journey planner and a
Google-Maps-like API that estimates bus travel times between any two points in
Delhi — shown on a 3D globe.

**Measured on held-out days** (trained on 1–24 Oct, tested on 10,500 real bus
runs from 25–31 Oct; see [docs/VALIDATION_REPORT.md](docs/VALIDATION_REPORT.md)):

| Predictor | Mean abs. error | Median abs. error | Within ±20% |
|---|---|---|---|
| **PULSE model** | **4.61 min** | **2.47 min** | **63.7%** |
| Flat average bus speed | 6.77 min | 4.54 min | 38.6% |
| Static GTFS timetable¹ | 6.57 min | 4.23 min | 39.9% |

¹ on the 41.8% of runs whose trip matched a GTFS timetable; PULSE on those same runs: 4.25 min.
The actual time fell inside PULSE's predicted range in 84.2% of runs.
Google Maps comparison: script ready (`scripts/compare_google.py`), **not run yet** (billed Routes API).

All of these numbers are produced by `scripts/build_traffic_model.py evaluate`;
none is typed by hand.

---

## What's in it

- **3D globe UI** (CesiumJS): orbit-to-Delhi fly-in, satellite / dark / light
  maps, optional Google Photorealistic 3D city, NVG / FLIR / CRT vision looks,
  intel-style HUD. Journeys are drawn in 3D (glowing route, curtain wall, stop
  beams); congestion can be extruded into 3D walls.
- **Per-stretch traffic model**: 163,018 road stretches × 96 fifteen-minute
  buckets × weekday/weekend. 22.2% of cells are direct GPS measurements; the
  rest borrow from the same stretch at other times, the route, or the
  network — never from typed-in speed tables. Each cell records its source.
- **Journey planner**: direct and one-transfer journeys, predicting the exact
  stretch between boarding and alighting stops, with a likely range, observed
  waiting times (from real gaps between buses), walk/wait/ride split and a
  data-source badge.
- **Live**: GTFS-RT positions from Delhi Open Transit Data; headings derived
  from movement; journeys departing now are fused with each route's live pace.
- **Congestion view**: every measured stretch coloured by congestion index
  (expected ÷ free-flow time) for any hour, animatable through the day.
- **Validation view**: the numbers above, by time of day, day type and trip length.

Network bus speed (weekday, from the model): ~27 km/h at 02:00, ~15 km/h
midday, ~12 km/h at 18:00–19:00.

## Run it

```powershell
pip install -r requirements.txt
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Open <http://127.0.0.1:8000> (API docs at `/docs`). A full feature tour is in
[walkthrough.md](walkthrough.md).

`.env` (see `.env.example`): `OTD_API_KEY` + `LIVE_FEED_ENABLED=true` for live
buses; `GOOGLE_MAPS_API_KEY` for the photoreal 3D city (needs the Map Tiles
API enabled on the key) and the Google benchmark (Routes API);
`MAPTILER_API_KEY`, `CARTO_API_KEY`, `GEOAPIFY_API_KEY` optional.

## Rebuild the model

```bash
PY=python bash scripts/run_pipeline.sh      # snap 31 days (~2 min/day), train 1–24, headways, evaluate 25–31
python scripts/compare_google.py --pairs 60 # optional Google Routes benchmark (billed)
python -m pytest tests                      # 53 tests
```

Method: [docs/TRAFFIC_MODEL.md](docs/TRAFFIC_MODEL.md).

## API

| Endpoint | Purpose |
|---|---|
| `GET /api/v1/journeys?from=&to=&depart_at=HH:MM:SS&date=` | Journey options with time, range, waits, provenance, live weight, geometry |
| `GET /api/v1/analytics/congestion?hour=&is_weekend=` | Congestion index per stretch |
| `GET /api/v1/analytics/time-comparison?route_id=` | One corridor at every hour |
| `GET /api/v1/analytics/model` | Model coverage and training days |
| `GET /api/v1/vehicles` | Live buses with freshness |
| `GET /api/v1/places/autocomplete?q=` | Stops, places, coordinates |
| `GET /api/v1/validation/summary` | Measured accuracy (+ Google, once run) |
| `GET /api/v1/system/status` | Datasets, storage, feed, model |

## Repository

```
app/            FastAPI app: routing (raptor.py), services, models/traffic_model.py
frontend/       index.html, static/js/{app.js,globe.js}, static/css/pulse.css
scripts/        build_traffic_model.py, run_pipeline.sh, compare_google.py,
                ingest_gtfs.py, build_segments.py; dev/ (one-off), legacy/ (superseded)
docs/           TRAFFIC_MODEL.md, VALIDATION_REPORT.md, DEMO_SCRIPT.md, …
data/           gtfs.duckdb, model arrays, validation results (derived data is git-ignored)
tests/          53 pytest tests
```

## Known limits

- The router covers direct and one-transfer journeys; two-transfer search is not built.
- Rarely-run route variants have little GPS and lean on borrowed estimates (their badge says so).
- Feed trip IDs don't match GTFS trip IDs, so the timetable baseline covers 41.8% of test runs.
- Live fusion has no replay/backtest yet; it only applies to departures within 30 min of now.
- The Google key in `.env` currently gets a 403 for 3D tiles until the Map Tiles API is enabled.

Data: Transport Stack and IIIT Delhi with DTC and ONDC.
