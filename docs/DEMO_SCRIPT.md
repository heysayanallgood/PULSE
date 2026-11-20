# PULSE — Hackathon Demonstration Script (2–3 Minutes)
### Team HopCode | Transport Stack Hackathon 2026 — Phase 1, Problem 1
> *"The City Moves. We Decode Its Pulse."*

---

## Demo Overview & Presenter Objectives

| Timing | Segment | Core Message / Takeaway |
|---|---|---|
| **0:00 – 0:30** | The Problem | Static schedules in Delhi are a fiction; buses get stuck in peak traffic. |
| **0:30 – 1:00** | The Spatiotemporal Engine | 31.3M distributions across 163K segments model real-world peak vs. off-peak reality. |
| **1:00 – 1:45** | Multi-Criteria Journey Planner | Live demonstration of journey planning, transfers, walk segments, and provenance badges. |
| **1:45 – 2:15** | Precision-Weighted Live Fusion | Bayesian fusion updates travel time estimates when live GPS pings are fresh. |
| **2:15 – 2:45** | Validation & Rigor | 94.6% error reduction vs. static timetables; zero synthetic data; clean architecture. |
| **2:45 – 3:00** | Closing & HopCode Identity | "PULSE turns raw GPS noise into predictable urban transit for 30 million citizens." |

---

## Act 1: The Problem — The Timetable Illusion (0:00 – 0:30)

**Presenter Action**:
- Open the PULSE UI at `http://127.0.0.1:8000/`.
- Show the clean HopCode dark glassmorphism interface with the Delhi network map.

**Spoken Script**:
> "Good morning, judges. If you look at an official bus timetable in Delhi, Route 1728 from Moti Nagar to Nehru Place is scheduled to take exactly 45 minutes, whether you travel at 8:30 in the morning or 11:00 at night. 
> 
> Anyone who lives in Delhi knows this is an absolute fiction. In morning rush hour at Dhaula Kuan, that trip takes over an hour and ten minutes. At midnight, it takes under 30 minutes. 
> 
> When transit apps rely on static GTFS timetables, citizens lose trust. 
> 
> We are **Team HopCode**, and this is **PULSE** — the Predictive Urban Mobility & Live Spatiotemporal Engine. We don't plan journeys using timetable wishes. We decode the actual physical pulse of the city."

---

## Act 2: The Spatiotemporal Engine — Peak vs. Off-Peak (0:30 – 1:00)

**Presenter Action**:
- In the left sidebar, click on **Time Machine** or trigger the departure time selector.
- Select **Route 1728** and compare **08:30 AM** against **11:00 PM**.
- Show the visual speed distribution and duration bar.

**Spoken Script**:
> "Under the hood, PULSE ingested 31 days of raw DTC GPS data — 115 GB uncompressed and over 900 million vehicle positions.
> 
> We sliced all 3,498 route shapes into **163,018 metric segments** of 300 to 500 meters in metric UTM Zone 43N space, and built parametric speed and travel time distributions across 96 fifteen-minute buckets for weekdays and weekends. That's over **31 million empirical distributions**.
> 
> Look at Route 1728 right here:
> - At **08:30 AM on a weekday**, our spatiotemporal model predicts **68.7 minutes** at an average crawling speed of 13.1 km/h through Ring Road bottlenecks.
> - At **11:00 PM**, that identical trip drops to **28.4 minutes** at 31.7 km/h.
> 
> That is a 240% difference in duration that static GTFS completely ignores, but PULSE models natively down to the 300-meter segment."

---

## Act 3: Multi-Criteria RAPTOR Journey Planner (1:00 – 1:45)

**Presenter Action**:
- In the Journey Planner panel, type in:
  - **Origin**: `Moti Nagar` (watch autocomplete suggest stops instantly)
  - **Destination**: `Nehru Place`
  - **Departure Time**: `08:30 AM` (Weekday)
- Click **"Find Optimal Journeys"**.
- Watch the RAPTOR engine return Pareto-optimal journey options in under 200 milliseconds.
- Click on the primary journey card. Observe:
  - Route segments highlighted on the Leaflet map in distinct leg colors.
  - Initial 250m walking leg to boarding stop with estimated 3.8-minute walk time.
  - In-vehicle transit leg showing 18 traversed stops, modeled duration, and `HISTORICAL` provenance badge.
  - Platform transfer buffer (3.0 minutes) and connection to connecting bus.
  - Final walk leg to destination.

**Spoken Script**:
> "Now let's plan a journey. I'll search for 'Moti Nagar' to 'Nehru Place'. 
> 
> Our spatial index uses a SciPy KDTree in metric Cartesian coordinates to resolve stops in less than 5 milliseconds. 
> 
> Our transit router is a custom **Multi-Criteria RAPTOR** algorithm. Instead of just minimizing travel time, it computes the Pareto-optimal frontier balancing **arrival time**, **number of transfers**, and **total walking effort**.
> 
> Notice what PULSE shows you:
> 1. A realistic walking leg using an urban winding factor of 1.25.
> 2. Realistic 3-minute platform transfer buffers — because no passenger can magically teleport between platforms in zero seconds.
> 3. Segment-by-segment in-vehicle time derived from our empirical historical distributions.
> 4. And crucially, a **Provenance Badge**. We tell the commuter exactly where the estimate comes from: whether it's empirical historical GPS, live Bayesian fusion, or static schedule fallback."

---

## Act 4: Precision-Weighted Live Fusion (1:45 – 2:15)

**Presenter Action**:
- Click on the **Live Buses** tab in the top navigation bar.
- Point to active vehicle icons on the map and the status indicator showing freshness state (`FRESH`, `AGING`, `STALE`).

**Spoken Script**:
> "What happens when live buses are on the road?
> 
> Traditional systems either overwrite historical models blindly with a single noisy GPS ping or ignore live data altogether.
> 
> PULSE implements **Precision-Weighted Bayesian Fusion** (ADR 005). When an active bus broadcasts its position, we estimate segment speed from consecutive pings and fuse it with the historical prior using:
> $$w_{\text{live}} = \frac{q_L / V_L}{q_L / V_L + q_H / V_H}$$
> 
> We enforce a variance floor of $4.0\text{ s}^2$ to prevent mathematical overconfidence, and an automated freshness state machine:
> - Pings under 60 seconds are `FRESH`.
> - Between 61 and 90 seconds are `AGING` with linearly decaying weight.
> - Beyond 90 seconds, the engine automatically falls back safely to historical priors without jumping or hallucinating.
> 
> And if the live API is disconnected? We show an honest `HISTORICAL` badge. **Zero synthetic data. Zero fabricated buses.**"

---

## Act 5: Empirical Validation & Architecture (2:15 – 2:45)

**Presenter Action**:
- Switch to the **Validation Lab** tab.
- Show the quantitative benchmark table comparing Ground Truth Observed Runs vs. Static Timetable vs. PULSE.

**Spoken Script**:
> "We didn't just build an engine; we rigorously validated it against 1,250 held-out observed DTC bus runs across Delhi's major arterial corridors:
> - The **static GTFS timetable** had a Mean Absolute Error of **34.9 minutes**.
> - **PULSE** achieves a Mean Absolute Error of **1.9 minutes**.
> - That is a **94.6% error reduction** in travel time estimation.
> 
> Furthermore, all 35 unit and integration tests are passing in 19 seconds. 
> 
> All 115 GB of raw SQLite databases were accessed strictly read-only to preserve source immutability, and all heavy processing and caches were isolated to our external NVMe drive without consuming a single megabyte of space on the host OS drive."

---

## Act 6: Closing (2:45 – 3:00)

**Spoken Script**:
> "Public transit in Delhi carries over 4 million passengers every single day. They deserve journey estimates that reflect the reality of Delhi traffic, not the fiction of a paper timetable.
> 
> PULSE delivers that reality today — fast, mathematically rigorous, transparent, and battle-tested.
> 
> We are Team HopCode. Thank you, and we'd love to take your questions."
