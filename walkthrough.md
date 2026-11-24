# PULSE — Walkthrough

PULSE answers Problem 1: a traffic model of Delhi's buses built from real GPS
traces, plugged into a journey planner and API that estimates bus travel times
between any two points, with accuracy measured against real trips.

This guide covers starting the app, every screen, the API, and how to rebuild
the model.

---

## 1. Start it

```powershell
pip install -r requirements.txt
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Open <http://127.0.0.1:8000>. API docs: <http://127.0.0.1:8000/docs>.

`.env` keys (all optional except where noted):

| Key | What it unlocks |
|---|---|
| `OTD_API_KEY`, `LIVE_FEED_ENABLED=true` | Live bus positions and live-fused journey times |
| `GOOGLE_MAPS_API_KEY` | Photoreal 3D city tiles (needs **Map Tiles API** enabled) and the Google benchmark (needs **Routes API**) |
| `MAPTILER_API_KEY` | Sharper satellite imagery (falls back to Esri) |
| `CARTO_API_KEY` | Dark / light street basemaps |
| `GEOAPIFY_API_KEY` | Address search besides stop names |

---

## 2. The globe

On load the camera starts in orbit over India, spins, then dives into Delhi.

**Moving around**
- Left-drag: pan · scroll wheel, trackpad pinch or right-drag: zoom · middle-drag / Ctrl+drag: tilt and rotate.
- Right rail buttons: **+ / −** zoom, **fly to Delhi**, **toggle top-down / oblique**, **back to full globe**. Keyboard `+` / `−` also zoom.

**Top-right chips**
- **MAP**: `3D CITY` (Google photoreal buildings; greyed out with a tooltip if the key lacks the Map Tiles API), `SAT`, `DARK`, `LIGHT`, and `NAMES`, which overlays road and place names on the satellite map (street maps already have them). Your choices are remembered.
- **VISION**: `NORMAL`, `NVG` (night-vision green), `FLIR` (thermal white-hot), `CRT` (amber scanlines). The HUD recolours to match.

**HUD (corners)**: the lat/lon under the screen centre, camera altitude, heading,
pitch, the area name, IST clock, live feed status and how much of the model is
directly measured.

**Bottom dock** switches between the five modes below. `Esc` cancels picking
and closes the details card.

---

## 3. Journey mode — plan a trip

1. **From / To**: type a stop, landmark, address or `lat, lon`. Pick a
   suggestion (↑/↓ + Enter works). Or click **Pick on globe** and click the map.
   Clicking anywhere on the globe also offers *Set as From / Set as To*.
2. **Depart at / Date**: or use a preset — **Now** (uses the live feed),
   **AM peak**, **Midday**, **PM peak**, **Night**. The date decides weekday
   vs weekend/holiday traffic.
3. **Find journeys**: up to three options with different routes.

Each card shows:
- total minutes and the **likely range** (p10–p90 style band from the model);
- a bar splitting **walk / wait / ride**;
- a source badge: **% MEASURED** = share of road stretches with direct GPS
  measurements at that time; the rest borrow from the same stretch at nearby
  times, the route, or the network. **LIVE + HISTORICAL** appears only when the
  live feed actually changed the estimate;
- per leg: ride time and range, distance, stops, expected wait, how many times
  slower than free flow the stretch is, and the live weight if used.

On the globe the selected option is drawn as a **traffic heat map**: each
stretch of the ride is coloured by its congestion at the moment the bus is
predicted to reach it (same green → dark-red scale as the Congestion view),
with translucent walls that rise where traffic is slow. Click a stretch for its
time, speed and whether it was measured. Light beams with labels mark the
boarding, alighting and transfer stops, plus FROM / TO pins. The card shows the
same heat as a strip under the time bar, with the worst stretch.

**Live buses on your route**: buses currently running the chosen route(s) are
drawn on the globe (refreshed every 10 s, gliding between fixes), and the card
says how many are live and how far the nearest one is from your boarding stop.
Click one to see it, or **Zoom & follow** it. Click another card to switch.

---

## 4. Live mode — buses on the road now

- Every DTC bus from the GTFS-RT feed, refreshed every 30 s.
- Zoomed out: glowing dots coloured by fix age — green **FRESH** (≤ 60 s),
  amber **AGING**, red **STALE** (> 90 s). Zoomed in: top-down bus icons
  rotated to the heading (derived from successive positions).
- Counters for vehicles and freshness; **Filter by route** with the number on
  the bus: `534` shows 534UP, 534DOWN, 534A…; exact names like `0114(NS)UP`
  work too. The camera frames the matching buses. **Refresh** forces a poll.
- Buses glide to each new position instead of jumping. When zoomed in below
  ~8 km the view refreshes every 10 s instead of 30 s.
- Click a bus: route name, trip, speed, heading, fix age. **Zoom & follow**
  locks the camera on it and checks for a new fix every 3 s (the server asks
  the feed at most every 8 s; the DTC feed itself updates roughly every 10–30 s).
  **Stop following** or closing the card releases it.
- Nothing is simulated: if the feed is off or down the view says so and stays empty.

---

## 5. Congestion mode — the traffic model

- Every road stretch with real GPS coverage, coloured by **congestion index**
  = expected travel time ÷ that stretch's own free-flow time (green 1× → dark red 3×).
- **Hour slider**, **Weekday / Weekend**, and **Play day** to animate 24 hours.
- **3D**: stretches at ≥ 2× free flow rise as walls whose height is the delay —
  tilt the camera (rail button) to see hotspots.
- Tiles: stretches shown, median speed, share slowed ≥ 2×, share of cells measured.
- Bar chart: network median bus speed by hour; click a bar to jump there.

---

## 6. Validation mode — does it hold up?

Shows numbers computed by `scripts/build_traffic_model.py evaluate`; nothing
is typed by hand. If evaluation hasn't run it says so.

- Trained on 1–24 October, tested on **held-out** 25–31 October real bus runs
  (2–15 km along a route).
- PULSE vs a **flat average speed** and the **GTFS timetable**: MAE, median
  error, share within ±20% and ±5 min, how often the actual time fell inside
  the predicted range, error by time of day, and sample runs.
- **Google Maps**: filled in after `scripts/compare_google.py` runs; until then
  it is shown as not run, never guessed.

---

## 7. System mode

GPS archive and GTFS status, free disk, live feed state, traffic model
coverage and build date, and links to every API endpoint.

---

## 8. API

| Endpoint | Purpose |
|---|---|
| `GET /api/v1/journeys?from=&to=&depart_at=HH:MM:SS&date=YYYY-MM-DD` | Journey options with times, ranges, waits, provenance, live weight and leg geometry |
| `GET /api/v1/analytics/congestion?hour=&is_weekend=&bbox=` | Congestion index per stretch for one hour |
| `GET /api/v1/analytics/time-comparison?route_id=` | One corridor's predicted time for every hour |
| `GET /api/v1/analytics/model` | Model training days and coverage |
| `GET /api/v1/vehicles?route_id=&fresh=true`, `/vehicles/{id}`, `/vehicles/health` | Live buses (with route names), one bus as fresh as possible, feed health |
| `GET /api/v1/places/autocomplete?q=` | Stops, places, coordinates |
| `GET /api/v1/validation/summary` | Measured accuracy + Google benchmark |
| `GET /api/v1/system/status` | Datasets, storage, feed, model |

Example:

```powershell
curl "http://127.0.0.1:8000/api/v1/journeys?from=Kashmere%20Gate&to=Nehru%20Place&depart_at=08:30:00&date=2026-10-15"
```

---

## 9. Rebuild the model

```powershell
PY=python bash scripts/run_pipeline.sh               # snap 31 days (fresh process per day), train 1–24, headways, evaluate 25–31
python scripts/build_traffic_model.py stops          # stop positions along shapes (needed once)
python scripts/build_traffic_model.py snap --days 5 --skip-existing
python scripts/build_traffic_model.py train --train-days 1-24
python scripts/build_traffic_model.py evaluate --test-days 25-31
python scripts/compare_google.py --pairs 60          # Google Routes API, billed per request
```

Snapping takes ~2 minutes per day in its own process. Method details: `docs/TRAFFIC_MODEL.md`.
Results: `docs/VALIDATION_REPORT.md`.

---

## 10. Measured results

Trained on 1–24 Oct 2026, tested on **10,500 real bus runs** (2–15 km) from
25–31 Oct that the model never saw:

| Predictor | Mean abs. error | Median abs. error | Within ±20% | Within ±5 min |
|---|---|---|---|---|
| **PULSE** | **4.61 min** | **2.47 min** | **63.7%** | **71.9%** |
| Flat average speed | 6.77 | 4.54 | 38.6% | 53.6% |
| GTFS timetable (41.8% of runs matched) | 6.57 | 4.23 | 39.9% | 56.6% |

- Actual time inside PULSE's predicted range: **84.2%** of runs.
- By time of day, PULSE MAE: night 2.9 · AM peak 3.9 · midday 4.7 · PM peak 6.0 · evening 3.4 min.
- Model coverage: 22.2% of stretch × 15-min × day-type cells directly measured;
  142,327 of 163,018 stretches have GPS data.
- Network bus speed (weekday): ~27 km/h at 02:00 → ~12 km/h at 18:00–19:00.
- Google Maps: not run yet (`scripts/compare_google.py`, billed Routes API).

Full breakdown: `docs/VALIDATION_REPORT.md`.
