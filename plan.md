# PULSE — Improvement Plan

Goal: make PULSE do what Problem 1 asks, and be able to **prove** it.

> Build a traffic model from real-time + historical bus location data, plug it into a Google Maps-like API that estimates bus travel times between any two locations. Success = plausible journey options with travel times that hold up against **known actual travel times** and **Google Maps**.

Status of each requirement today:

| Requirement | Status | Phase |
|---|---|---|
| Traffic model from historical bus GPS | Partial (route-level only, not per road stretch) | 2 |
| Real-time data used in the model | Not connected | 5 |
| Journey API between any two locations | Works, but routing is simplified | 4 |
| Times hold up vs actual bus times | **Not proven (numbers are hardcoded)** | 1 |
| Times hold up vs Google Maps | **Not proven (numbers are hardcoded)** | 6 |

---

## Phase 0 — Honesty cleanup (do first, ~1 hour)

Nothing in the README should claim what the code doesn't do.

- [ ] `app/api/v1/validation.py`: delete the hardcoded `BENCHMARKS` list. Replace with a function that reads results from `data/validation/results.json` (produced in Phase 1). If the file doesn't exist, return `{"status": "NOT_RUN"}`.
- [ ] `README.md`: remove or mark as "to be measured" every number that is not computed: MAE 1.9, RMSE 2.8, 94.6%, 1,250 runs, 94.2% coverage, 240% divergence, Google Maps comparison.
- [ ] `README.md`: fix test counts (says 53 in one place, 35 in others).
- [ ] `README.md`: fix "Zero Synthetic Data" wording until hardcoded speed priors are removed (Phase 2).
- [ ] Delete `__pycache__` folders from everything you zip/submit.
- [ ] `core/config.py`: move all hardcoded `E:/Pulse/...` paths (in `prediction_service.py`, `process_day.py`, `train_travel_time_model.py`) into config / env variables.

**Done when:** no number in the README or API is typed by hand.

---

## Phase 1 — Real evaluation harness (the most important phase)

Build the test first so every later change can be measured.

### 1.1 Train/test split
- [ ] Train only on days **1–24**. Test only on days **25–31**.
- [ ] Add `--train-days` / `--exclude-days` options to `scripts/train_travel_time_model.py`.
- [ ] Never let test days appear in the training Parquet glob.

### 1.2 Ground truth from the data
- [ ] New script `scripts/build_ground_truth.py`:
  - For each test-day trip (`trip_id` + `vehicle_id`), sort pings by GPS `timestamp`.
  - Find actual time between pairs of stops on that trip (interpolate from pings).
  - Save to `data/validation/ground_truth.parquet`: trip, from_stop, to_stop, actual_start_time, actual_duration_s.
  - Sample several thousand trips across all hours and all major routes.
- [ ] Verify `trip_id` format (`route_HH_MM_suffix`) against GTFS `trips` before relying on it.

### 1.3 Scoring script
- [ ] New script `scripts/evaluate_model.py`:
  - For each ground-truth trip, ask PULSE to predict the duration (same stops, same departure time).
  - Also compute the **static GTFS timetable** prediction as baseline.
  - Report: MAE, median error, RMSE, % within ±5 min, % within ±20%, and 90% interval coverage.
  - Break results down by hour of day, weekday/weekend, and trip length.
  - Write `data/validation/results.json` and a short `docs/VALIDATION_REPORT.md`.

**Done when:** the validation endpoint shows numbers computed from held-out real trips. Report them even if worse than before.

---

## Phase 2 — Per-road-stretch traffic model (core upgrade)

Today the model learns speed per **route** and time slot. It should learn per **stretch of road** and time slot.

### 2.1 Clean the raw GPS (`scripts/process_day.py`)
- [ ] Use the GPS `timestamp` (epoch → IST) for time buckets, **not** the `date`/`time` columns (those are poll time).
- [ ] Remove duplicate pings: same `(vehicle_id, timestamp)`.
- [ ] Drop stale pings (GPS fix much older than poll time, e.g. > 120 s; seen up to ~27 min in the data).
- [ ] Drop parked buses: long runs of speed 0 at the same location (depots, terminals).
- [ ] Compute speed from distance moved / time elapsed between consecutive pings; drop impossible jumps instead of clamping them.
- [ ] Mark day types: weekday, weekend, **holiday** (e.g. Oct 2 Gandhi Jayanti was a Friday holiday; Dussehra falls in late October — confirm exact dates).
- [ ] Flag partial days (Oct 7 ends at ~19:51) and exclude their missing hours from model training.
- [ ] Write cleaning stats to the manifest (counts of each removal reason).

### 2.2 Place every ping on the road (new `scripts/match_to_shapes.py`)
- [ ] For each trip, get its GTFS shape from `trip_id`.
- [ ] Project each ping onto that shape → distance along route (`shape_dist_traveled`).
- [ ] Per trip, sort by time and make distance non-decreasing (remove GPS jitter going backwards).
- [ ] Drop pings farther than ~50 m from the shape.
- [ ] Output: trip, vehicle, time, distance along shape.

### 2.3 Measure real stretch travel times
- [ ] For each trip, interpolate the time the bus crossed each segment boundary.
- [ ] Segment travel time = crossing time difference. Keep dwell at stops separate from moving time.
- [ ] Discard traversals that include long unexplained stops (breakdowns, breaks).

### 2.4 Build the model (`scripts/train_travel_time_model.py`)
- [ ] Aggregate per `segment × 15-min bucket × day type`: **median**, p10, p90, sample count, number of distinct buses.
- [ ] Fill sparse cells by borrowing, in order: same segment neighbouring bucket → same segment same hour → same route and bucket → network-wide bucket. Record which level was used in a `source_level` column.
- [ ] **Delete the hardcoded hourly speed tables** from the SQL (both weekday and weekend). Fallback must come from data aggregated at a coarser level.
- [ ] Fix variance: use variance of observed **travel time in seconds²**, not speed variance × length.
- [ ] Add a free-flow speed per segment (e.g. 85th percentile of night-time speeds) so **congestion index = free-flow time ÷ expected time** can be shown.
- [ ] Store provenance honestly: `HISTORICAL` only when real samples exist at that exact cell.
- [ ] Print a coverage report: % of segment-bucket cells with real data vs borrowed.

### 2.5 Faster lookup (`app/services/prediction_service.py`)
- [ ] Load the model once at startup into memory (dict or NumPy array keyed by `segment, bucket, daytype`).
- [ ] Remove the per-segment SQL query inside the loop.
- [ ] Remove the hardcoded `80 s / 5 m/s` global fallback; use the network-level model instead.

**Done when:** the Phase 1 score improves versus the route-level model, and a map of congestion index differs visibly between stretches of the same route.

---

## Phase 3 — Observed waiting times

- [ ] New script `scripts/build_headways.py`: from real GPS, find when buses actually pass each stop on each route; compute typical gap between buses by hour and day type.
- [ ] Store in `stop_headways` table (stop, route, bucket, daytype, median_gap_s, sample_count).
- [ ] Expected wait = half the typical gap (or time to next scheduled bus if the schedule is reliable for that route).
- [ ] If no data for a stop: use route-level gap, then network-level gap, and label it.

**Done when:** the hardcoded `% 1800` wait guess in `raptor.py` is gone.

---

## Phase 4 — Proper journey router

File: `app/routing/raptor.py`, `app/services/journey_service.py`

- [ ] Load `stop_times`, routes and trips once at startup into in-memory arrays.
- [ ] Implement real round-based RAPTOR: round 0 walk, round k = ride one more route. Support **at least 2 transfers** (the README already claims this).
- [ ] Remove `LIMIT 50` SQL self-joins; return the best options, not an arbitrary subset.
- [ ] Use Phase 2 model for in-vehicle time and Phase 3 for waiting time.
- [ ] Create the `pyproj` Transformer once, not inside loops.
- [ ] Keep Pareto filtering (arrival time, transfers, walking) and return top 3.
- [ ] Add a journey-level uncertainty range using the Phase 2 variance.
- [ ] Add tests: direct trip, 1 transfer, 2 transfers, no route found, out-of-city coordinates, time past midnight.

**Done when:** results for common origin–destination pairs are stable, fast (target under ~1 s) and include 2-transfer options when needed.

---

## Phase 5 — Connect real-time data

Files: `app/services/realtime_service.py`, `app/models/live_fusion.py`, `app/services/prediction_service.py`

- [ ] Run live pings through the same Phase 2 cleaning + shape matching.
- [ ] Keep a rolling window (last ~10–15 min) of live speeds per segment.
- [ ] Call `fuse_live_and_historical` per segment inside `predict_leg_travel_time`. It is currently imported but never used.
- [ ] Add `live_weight` and `freshness` to each journey leg in the API response.
- [ ] **Replay mode:** stream a held-out historical day through the live path at normal speed. This lets you demo and test live fusion without the real feed.
- [ ] Backtest: compare error with history only vs history + live on test days. Report the real difference (it may be small; report honestly).
- [ ] Fail gracefully: if the live feed is down, fall back to history and say so.

**Done when:** the journey response shows `LIVE + HISTORICAL` only when live data was actually used, and the backtest shows the effect.

---

## Phase 6 — Google Maps comparison (real numbers)

- [ ] Use the Google **Routes API** (transit mode), not the legacy Directions/Distance Matrix APIs.
- [ ] Check first that Google returns Delhi DTC bus journeys for a few test pairs.
- [ ] New script `scripts/compare_google.py`:
  - Pick ~50–100 origin–destination pairs across Delhi.
  - Run each at several departure times (morning peak, midday, evening peak, night). Google gives current/future times, so run at those times and ask PULSE for the same time and day type.
  - Save Google ETA, PULSE ETA and, where possible, the historical actual time for the same corridor.
  - Write results to `data/validation/google_comparison.json`.
- [ ] Keep the Google API key in environment variables only. Do not commit it.
- [ ] Do not store Google results long-term (their terms restrict caching); keep it as a small benchmark set.
- [ ] If Google cannot be used for some pairs, show "not available" instead of a number.

**Done when:** the Google column in the app and README comes from `google_comparison.json`.

---

## Phase 7 — Frontend and demo

File: `frontend/static/js/app.js`, `frontend/index.html`

- [ ] **Congestion map layer:** colour bus stretches green → red by congestion index for a chosen time (the existing Time Machine can use this).
- [ ] Show on each journey: expected time, range (e.g. "34–42 min"), and a clear data-source badge (historical / live / borrowed).
- [ ] Show wait time separately from ride time.
- [ ] Add a validation page that displays real results from Phase 1 and Phase 6 (accuracy by hour, PULSE vs timetable vs Google).
- [ ] Update `docs/DEMO_SCRIPT.md` with three sample trips: peak vs night, a transfer journey, and a live-vs-history example.

---

## Phase 8 — Engineering polish

- [ ] Process days in parallel in `process_day.py` (multiprocessing, one day per worker).
- [ ] Sort Parquet output by route and time for faster aggregation.
- [ ] Replace f-string SQL with parameters.
- [ ] Add a single `scripts/run_pipeline.py` that runs clean → match → train → evaluate in order, with logs.
- [ ] Update tests: cleaning (duplicates, stale pings), shape matching, model lookup, fusion, router, validation endpoint.
- [ ] Rewrite README to match reality, and cite measured results only.
- [ ] Remove or merge one-off scripts (`audit_causes.py`, `diagnose_edge.py`, `check_route.py`, etc.) into a `scripts/dev/` folder.

---

## Suggested order and effort

| Order | Phase | Why this order | Rough effort |
|---|---|---|---|
| 1 | 0 | Removes risk of false claims | 1 hr |
| 2 | 1 | Lets you measure everything else | 1 day |
| 3 | 2 | Biggest accuracy gain | 2–3 days |
| 4 | 3 | Biggest source of remaining error (waiting) | 1 day |
| 5 | 4 | Better journey options | 1–2 days |
| 6 | 5 | Meets the "real-time" requirement | 1–2 days |
| 7 | 6 | Meets the "vs Google Maps" requirement | 0.5–1 day |
| 8 | 7, 8 | Demo quality and cleanup | 1–2 days |

If time is short, do **0 → 1 → 2 → 6**. That gives a real per-stretch model with honest accuracy numbers and a real Google comparison.

## Risks and open questions

- Delhi GTFS shapes may not match every ping (bad `trip_id`s, missing shapes). Measure the % of pings that match and report it.
- Some stretches will have few buses at night; the borrowing rules in 2.4 must be tested.
- The measured error may be larger than the old 1.9 min figure. That is fine as long as it is real.
- Google may not return DTC bus journeys for some pairs, so the comparison set may be smaller than planned.
- Exact holiday dates in October 2026 need confirming before labelling day types.
