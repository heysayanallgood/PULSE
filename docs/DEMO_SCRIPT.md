# PULSE — Demo Script (≈3 minutes)
### Team HopCode | Transport Stack Hackathon 2026 — Problem 1

All numbers quoted here come from `data/validation/results.json`
(`scripts/build_traffic_model.py evaluate`). Re-check them if the model is rebuilt.

| Time | Segment | Message |
|---|---|---|
| 0:00–0:20 | Globe intro | Real GPS from every DTC bus, on a 3D globe |
| 0:20–1:20 | Three trips | Peak vs night, a transfer, live vs history |
| 1:20–2:00 | Congestion | The model, stretch by stretch, hour by hour |
| 2:00–2:45 | Validation | Held-out real trips: 4.6 min error vs 6.6 timetable |
| 2:45–3:00 | Close | API + UI, every number measured |

## 0:00 — Globe

Open <http://127.0.0.1:8000>. The camera dives from orbit into Delhi.
> "PULSE learned Delhi's bus traffic from 31 days of real DTC GPS — about 920
> million raw rows — snapped onto 163,000 road stretches."

Switch to **Live**: ~2,000+ buses as dots coloured by fix age; zoom in to see
bus icons pointing along their heading; click one.

## 0:20 — Trip 1: peak vs night

Journey mode, *Kashmere Gate → Nehru Place*, **PM peak**, Find journeys.
Point at the 3D route, the range ("likely 68–92 min"), the walk/wait/ride bar,
and the **% MEASURED** badge. Switch preset to **Night** and re-run: the ride
gets faster, but the wait gets longer because buses run less often. PULSE
models both from real data.

## 0:45 — Trip 2: a transfer

Pick two points on the globe far apart (e.g. Dwarka → Mayur Vihar) with
**Pick on globe**. Show a one-transfer option with its change beam and the
separate wait times.

## 1:05 — Trip 3: live vs history

Press **Now** and plan. If the route's buses are on the road, the leg shows
"live N% (k buses)" and the card says **LIVE + HISTORICAL**; otherwise it
stays HISTORICAL and says why. Nothing live is ever invented.

## 1:20 — Congestion

Congestion mode → **Play day**. Stretches turn red through the evening peak;
the bar chart shows network bus speed falling from ~27 km/h at 2 am to
~12 km/h at 6–7 pm. Tilt (rail button) with **3D** on to see delay walls.

## 2:00 — Validation

> "We trained on 1–24 October and tested on 10,500 real bus runs from the last
> week the model never saw. PULSE is off by 4.6 minutes on average — median
> 2.5 — against 6.6 for the official timetable and 6.8 for a flat average
> speed. Its predicted range caught the real time 84% of the time."

Show the time-of-day table: biggest gain at the PM peak (6.0 vs 8.8 timetable).
Google Maps: the benchmark script is ready; say whether it has been run.

## 2:45 — Close

> "One API, one 3D map, and every number on screen is measured from Delhi's
> own buses."
