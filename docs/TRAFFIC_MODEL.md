# PULSE traffic model — how it is built

Everything here is produced by one script, `scripts/build_traffic_model.py`,
from the raw October 2026 DTC GPS archive and the static GTFS feed. No speed
or travel time in the model is typed by hand.

```
python scripts/build_traffic_model.py snap --days 1-31      # ~3–4 min per day
python scripts/build_traffic_model.py stops                 # stop positions along shapes
python scripts/build_traffic_model.py train --train-days 1-24
python scripts/build_traffic_model.py headways --train-days 1-24
python scripts/build_traffic_model.py evaluate --test-days 25-31
# or all of it:
python scripts/build_traffic_model.py all
```

## 1. Snap (per day)

Input: `delhi-dtc-bus-gtfs-rt-2026-10/bus_movements_2026_10_DD.db`, opened
read-only through DuckDB's SQLite scanner.

| Step | Rule |
|---|---|
| Time | GPS fix time (`timestamp`, epoch) is used for every time bucket — not the poll `date`/`time`. |
| Duplicates | One row per `(vehicle_id, timestamp)`; the feed repeats each fix ~1.6× on average. |
| Stale fixes | Dropped when the fix was logged more than 120 s after it was taken. |
| Area | Delhi box 28.30–28.95 N, 76.80–77.55 E. |
| Snapping | Each ping is projected onto the 300–500 m stretches (`route_segments`) of its own route's shapes, within 80 m. |
| Direction | Every vehicle-trip is pinned to one shape: the shape whose direction agrees with the bus's movement for most pings. |

Outputs `data/processed/snapped/day=DD.parquet` (one row per snapped ping,
with distance along the shape) and per-day stretch statistics.

## 2. Per-stretch measurements

Consecutive pings of the same bus on the same trip form pairs. Each pair adds
its elapsed time `dt` and its along-shape progress `dd` to the stretch it ends
on, in its 15-minute IST bucket. Rules:

- `1 ≤ dt ≤ 120 s`, progress at most 25 m/s, at most 3 stretches skipped.
- Small backwards jitter (≤ 30 m) counts as standing still.
- Standing runs longer than 180 s (terminal layovers, breakdowns) are removed.
  Ordinary stops and signals stay in: a rider's travel time includes them.

The estimator is the **space-mean pace** `Σdt / Σdd` (seconds per metre),
the correct average for travel time over distance. Stretch travel time =
stretch length × pace.

## 3. Train (days 1–24 only)

Cells are `stretch × 15-min bucket × day type`. Weekend and public holidays
(Gandhi Jayanti 2 Oct, Dussehra 20 Oct 2026) share the weekend profile.

A cell is **measured** (`HISTORICAL`) when its pooled pairs cover at least half
the stretch length and come from at least two distinct buses. Other cells
borrow from coarser *measured* data, in this order, and record which level
was used (`source.npy`):

| Level | Source |
|---|---|
| `HISTORICAL` | this stretch, this bucket, this day type |
| `SEGMENT_HOUR` | this stretch, same hour |
| `SEGMENT_PROFILE` | this stretch's all-day pace × the network's time-of-day profile |
| `ROUTE_LEVEL` | this route, this bucket |
| `NETWORK_LEVEL` | whole network, this bucket |

Uncertainty: the day-to-day spread of a measured cell's pace gives its
coefficient of variation; unmeasured cells use the network median CV (×1.35
when borrowed from the route or network). A trip's band treats stretches as
half independent, half fully correlated (a slow evening is slow everywhere).

Free-flow time per stretch = its 10th-percentile time across all cells, so
`congestion index = expected time ÷ free-flow time ≥ 1`.

Artefacts (memory-mapped by the API, so startup is instant):
`data/models/traffic_model/{tt,var,samples,source,ff_tt,...}.npy`, `meta.json`.

## 4. Waiting time (observed headways)

From the snapped training days, the times buses actually pass points at 25%,
50% and 75% along each shape give real gaps between buses per route, hour and
day type. A rider arriving at random waits `E[gap²] / (2·E[gap])`, which is
longer than half the average gap when buses bunch. Stored in
`stop_headways.parquet`; the router uses it instead of a fixed guess.

## 5. Live fusion

The realtime service keeps a 15-minute window of each route's live movement
(Σdistance/Σtime, including standing time, so it matches the historical
estimator). Journeys departing within 30 minutes of now fuse each bus leg with
`app/models/live_fusion.py` (precision-weighted; stale or thin evidence gets
zero weight). The response carries `live_weight`, `freshness` and
`provenance = "LIVE + HISTORICAL"` only when live data actually moved the
estimate.

## 6. Evaluation (days 25–31, never seen in training)

Ground truth = real bus runs: a random start ping on a vehicle-trip and the
first ping 2–15 km further along the same shape (no gap > 5 min). Compared:

- **PULSE**: the model, clock advanced stretch by stretch from the real departure time;
- **Flat speed**: the network's all-day average speed (shows what the time-of-day model adds);
- **Timetable**: GTFS `stop_times` of the trip with the same route and HH_MM start,
  interpolated along the shape.

Results: `data/validation/results.json` and `docs/VALIDATION_REPORT.md`.
Google Maps: `scripts/compare_google.py` (Routes API, transit/bus) writes
`data/validation/google_comparison.json`.

## Known limits

- Stretch geometry is the chord between stretch end points; strongly curved
  roads can push pings past the 80 m snap limit.
- Feed trip IDs (`route_HH_MM_xxxx`) do not match GTFS trip IDs; the timetable
  baseline matches on route + start time, so it covers only part of the runs.
- Night hours and minor routes have few buses; those cells borrow more.
- The router searches direct and one-transfer journeys; two-transfer search is
  not implemented.
