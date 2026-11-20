# PULSE — Live GTFS-Realtime Integration & Bayesian Fusion
**Project:** Predictive Urban Mobility & Live Spatiotemporal Engine  
**Team:** HopCode | **Hackathon:** Transport Stack Hackathon 2026 (Problem 1)  
**Authoritative Architectural Alignment:** ADR 005  

---

## 1. Live Integration Philosophy

Live vehicle tracking must enhance, rather than replace, historical spatiotemporal knowledge. A single live GPS ping does not establish corridor speed. Live integration in PULSE adheres to strict reliability rules:
1. **Zero Simulation**: Under no circumstances are fictional buses or synthetic congestion values displayed when the live feed is offline.
2. **Consecutive Ping Movement**: Real-time velocity is derived exclusively from consecutive pings of the same physical vehicle along its matched shape.
3. **Precision-Weighted Bayesian Fusion**: Live speeds are fused with the historical time-of-day prior using an inverse-variance, freshness-decaying weight.
4. **Graceful Fail-Safe**: If the live feed fails or times out, the system continues functioning seamlessly using historical models with explicit `HISTORICAL` provenance labeling.

---

## 2. Ingestion & Protobuf Decoding

### Feed Specification
- **URL**: `https://otd.delhi.gov.in/api/realtime/VehiclePositions.pb`
- **Format**: Binary Protocol Buffers (`FeedMessage`)
- **Polling Loop**: Background asynchronous worker (`app/services/realtime_service.py`) polling every 30 seconds.
- **Credential Storage**: Managed via `E:\Pulse\.env` (`OTD_API_KEY`). Query parameters containing credentials are never printed or logged.

### Protobuf Decoding
Using official `google.transit.gtfs_realtime_pb2`:
```python
feed = gtfs_realtime_pb2.FeedMessage()
feed.ParseFromString(response.content)
for entity in feed.entity:
    if entity.HasField('vehicle'):
        v = entity.vehicle
        vehicle_id = v.vehicle.id
        lat = v.position.latitude
        lon = v.position.longitude
        timestamp = v.timestamp
        route_id = v.trip.route_id
```

---

## 3. Real-Time Movement Estimation

When vehicle $V$ reports position $(lat_1, lon_1)$ at $t_1$ and position $(lat_2, lon_2)$ at $t_2$:
1. Both coordinates are projected to EPSG:32643 and matched to the route shape, yielding linear distances $s_1$ and $s_2$.
2. Condition checks:
   - Same `vehicle_id` and same `route_id`.
   - Time delta: $10\text{s} \le \Delta t \le 120\text{s}$.
   - Spatial progression: $\Delta s = s_2 - s_1 \ge 0$.
3. Derived live speed:
   $$v_{\text{live}} = \frac{\Delta s}{\Delta t}$$
4. Derived segment live travel time:
   $$T_L(s) = \frac{L(s)}{v_{\text{live}}}$$

---

## 4. Precision-Weighted Bayesian Fusion (ADR 005)

When both live evidence ($T_L$) and historical prior ($T_H$) are available for segment $s$:

$$T_{\text{fused}} = w_{\text{live}} T_L + (1 - w_{\text{live}}) T_H$$

### Weighting Derivation:
$$w_{\text{live}} = \frac{\frac{q_{\text{live}}}{\sigma_L^2}}{\frac{q_{\text{live}}}{\sigma_L^2} + \frac{q_{\text{hist}}}{\sigma_H^2}}$$

Where:
- $\sigma_L^2$: Sample variance of recent live traversals on that segment.
- $\sigma_H^2$: Historical variance for that 15-minute time bucket.
- $q_{\text{live}} = \exp\left(-\frac{\text{age}}{\tau}\right) \cdot \min\left(1, \frac{N_{\text{live}}}{3}\right)$ with decay constant $\tau = 60\text{s}$.
- $q_{\text{hist}} = \min\left(1, \frac{N_{\text{hist}}}{30}\right)$.

### Freshness States:
- **FRESH** ($\text{age} \le 60\text{s}$): Live weight active; high influence.
- **AGING** ($60\text{s} < \text{age} \le 120\text{s}$): Live weight decays exponentially.
- **STALE** ($\text{age} > 120\text{s}$): $w_{\text{live}} \to 0$; live observation discarded.
- **UNAVAILABLE**: Feed inactive or unreachable; 100% historical model.

---

## 5. Provenance Contract

Every API journey response explicitly includes the data provenance for each segment:
```json
{
  "segment_id": "shp_3_2436_seg_004",
  "estimated_travel_time_s": 145,
  "confidence": "HIGH",
  "provenance": "LIVE + HISTORICAL",
  "live_weight": 0.68,
  "data_freshness_seconds": 24
}
```
If the live feed is offline, the provenance automatically transitions to `"HISTORICAL"`, ensuring total transparency to the commuter and evaluating judges.
