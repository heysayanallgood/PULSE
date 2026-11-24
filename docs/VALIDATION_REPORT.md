# PULSE Validation Report

_Generated 2026-11-23T19:07:20.401591+00:00 by `scripts/build_traffic_model.py evaluate`. Every number below is computed; none is typed by hand._

## Method

- Training days: [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20, 21, 22, 23, 24]; test days (held out): [25, 26, 27, 28, 29, 30, 31].
- Ground truth: Real bus runs on held-out days: a start ping and the first ping 2–15 km further along the same vehicle's trip shape (no gap > 5 min). Actual time = GPS fix-time difference.
- PULSE: Per-stretch travel-time model, clock advanced stretch by stretch from the real departure time.
- Timetable baseline: GTFS stop_times for the trip with the same route and HH_MM start, interpolated by distance along the shape. Matched for 41.8% of runs.
- Flat-speed baseline: Same distance at the network's all-day average bus speed (no time-of-day model).
- Model cells backed by direct measurements: 22.2%.

## Overall

| Predictor | Runs | MAE (min) | Median abs err (min) | RMSE (min) | Within ±5 min | Within ±20% |
|---|---|---|---|---|---|---|
| PULSE model | 10,500 | 4.61 | 2.47 | 8.03 | 71.9% | 63.7% |
| Flat average speed | 10,500 | 6.77 | 4.54 | 10.4 | 53.6% | 38.6% |
| Static GTFS timetable | 4,387 | 6.57 | 4.23 | 10.35 | 56.6% | 39.9% |
| PULSE (same runs as timetable) | 4,387 | 4.25 | 2.32 | 7.24 | 73.8% | 65.2% |

PULSE uncertainty band (p10–p90 style) contained the actual time in 84.2% of runs.

## By time of day

| Band | Runs | PULSE MAE | Flat MAE | Timetable MAE |
|---|---|---|---|---|
| night 00-06 | 252 | 2.92 | 8.4 | 7.21 |
| am peak 07-10 | 2,463 | 3.89 | 5.69 | 5.48 |
| midday 11-16 | 3,215 | 4.67 | 6.26 | 6.21 |
| pm peak 17-20 | 3,018 | 5.99 | 8.56 | 8.8 |
| evening 21-23 | 1,265 | 3.39 | 5.26 | 4.74 |

## By trip length

| Length | Runs | PULSE MAE | Within ±20% |
|---|---|---|---|
| 2-5 km | 4,658 | 3.77 | 58.4% |
| 5-10 km | 5,741 | 5.25 | 67.8% |
| 10-15 km | 101 | 6.36 | 72.3% |

## Google Maps

Not run yet. `scripts/compare_google.py` queries the Google Routes API (transit) and needs GOOGLE_MAPS_API_KEY.
