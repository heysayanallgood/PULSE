"""
PULSE vs Google Maps benchmark (scripts/compare_google.py) — plan.md phase 6.

Picks origin–destination pairs along real DTC corridors, asks the Google
Routes API (computeRoutes, TRANSIT, bus only) for each pair at a departure
time, asks PULSE for the same pair/time/day type, and writes a small
benchmark file read by the Validation view:

    data/validation/google_comparison.json

Notes
- Uses GOOGLE_MAPS_API_KEY from .env (the Routes API must be enabled for it).
  Each pair × time is one billable Routes request.
- Google only answers for current/future departures, so the departure date is
  the next date with the same weekday type as requested.
- Google's terms restrict caching; keep this as a small, dated benchmark set.
- Pairs Google can't serve by bus are recorded as "not available", not guessed.

Usage:
  python scripts/compare_google.py --pairs 60 --times 08:30,14:00,18:30,23:00
"""
from __future__ import annotations

import argparse
import json
import random
import statistics
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import duckdb
import httpx

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.core.config import settings  # noqa: E402

URL = "https://routes.googleapis.com/directions/v2:computeRoutes"
FIELDS = ("routes.duration,routes.distanceMeters,"
          "routes.legs.steps.travelMode,routes.legs.steps.staticDuration,"
          "routes.legs.steps.transitDetails.transitLine.nameShort,"
          "routes.legs.steps.transitDetails.transitLine.vehicle.type")
IST = ZoneInfo("Asia/Kolkata")
OUT = settings.DATA_ROOT / "validation" / "google_comparison.json"


def sample_pairs(n: int, seed: int) -> list[dict]:
    """Stop pairs 3–12 km apart on the same shape, from busy routes."""
    stop_pos = settings.MODEL_ROOT / "traffic_model" / "stop_shape_dist.parquet"
    con = duckdb.connect()
    con.execute(f"ATTACH '{(settings.DATABASE_ROOT / 'gtfs.duckdb').as_posix()}' AS g (READ_ONLY)")
    rows = con.execute(f"""
        WITH busy AS (
          SELECT shape_id FROM g.trips GROUP BY shape_id ORDER BY count(*) DESC LIMIT 400
        ), sp AS (
          SELECT p.shape_id, p.stop_id, p.dist_m, s.stop_name, s.stop_lat, s.stop_lon
          FROM read_parquet('{stop_pos.as_posix()}') p JOIN g.stops s USING (stop_id)
          WHERE p.shape_id IN (SELECT shape_id FROM busy) AND p.offset_m < 40
        )
        SELECT a.shape_id, a.stop_name, a.stop_lat, a.stop_lon, b.stop_name, b.stop_lat, b.stop_lon, b.dist_m - a.dist_m
        FROM sp a JOIN sp b ON a.shape_id = b.shape_id AND b.dist_m - a.dist_m BETWEEN 3000 AND 12000
        USING SAMPLE 4000 ROWS
    """).fetchall()
    random.Random(seed).shuffle(rows)
    seen, out = set(), []
    for r in rows:
        key = (round(r[2], 2), round(r[3], 2), round(r[5], 2), round(r[6], 2))
        if key in seen:
            continue
        seen.add(key)
        out.append({"shape_id": r[0], "from_name": r[1], "from": [r[2], r[3]], "to_name": r[4], "to": [r[5], r[6]],
                    "corridor_km": round(r[7] / 1000, 1)})
        if len(out) >= n:
            break
    return out


def next_departure(hhmm: str, weekend: bool) -> datetime:
    now = datetime.now(IST)
    h, m = (int(x) for x in hhmm.split(":"))
    d = now.date()
    for i in range(0, 9):
        cand = datetime(d.year, d.month, d.day, h, m, tzinfo=IST) + timedelta(days=i)
        if cand > now + timedelta(minutes=5) and (cand.weekday() >= 5) == weekend:
            return cand
    raise RuntimeError("no departure found")


def google_transit(client: httpx.Client, key: str, o, d, dep: datetime) -> dict:
    body = {
        "origin": {"location": {"latLng": {"latitude": o[0], "longitude": o[1]}}},
        "destination": {"location": {"latLng": {"latitude": d[0], "longitude": d[1]}}},
        "travelMode": "TRANSIT",
        "departureTime": dep.astimezone(timezone.utc).isoformat().replace("+00:00", "Z"),
        "transitPreferences": {"allowedTravelModes": ["BUS"]},
        "computeAlternativeRoutes": False,
    }
    r = client.post(URL, json=body, headers={"X-Goog-Api-Key": key, "X-Goog-FieldMask": FIELDS}, timeout=20)
    if r.status_code != 200:
        return {"status": f"HTTP_{r.status_code}", "message": r.text[:200]}
    routes = r.json().get("routes") or []
    if not routes:
        return {"status": "NO_ROUTE"}
    rt = routes[0]
    steps = [s for leg in rt.get("legs", []) for s in leg.get("steps", [])]
    lines = [s["transitDetails"]["transitLine"].get("nameShort") for s in steps if s.get("transitDetails")]
    vtypes = {s["transitDetails"]["transitLine"].get("vehicle", {}).get("type") for s in steps if s.get("transitDetails")}
    if not lines or not vtypes <= {"BUS", "INTERCITY_BUS", "TROLLEYBUS"}:
        return {"status": "NOT_BUS", "vehicle_types": sorted(v for v in vtypes if v)}
    return {"status": "OK", "duration_min": round(int(rt["duration"].rstrip("s")) / 60, 1), "lines": lines}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--pairs", type=int, default=60)
    ap.add_argument("--times", default="08:30,14:00,18:30,23:00")
    ap.add_argument("--weekend", action="store_true")
    ap.add_argument("--seed", type=int, default=11)
    args = ap.parse_args()

    key = (settings.GOOGLE_MAPS_API_KEY or "").strip()
    if not key:
        raise SystemExit("GOOGLE_MAPS_API_KEY is not set in .env")

    from app.services.journey_service import journey_service

    pairs = sample_pairs(args.pairs, args.seed)
    results = []
    with httpx.Client() as client:
        for p in pairs:
            for t in args.times.split(","):
                dep = next_departure(t.strip(), args.weekend)
                g = google_transit(client, key, p["from"], p["to"], dep)
                j = journey_service.plan_journey(
                    origin=f"{p['from'][0]:.5f}, {p['from'][1]:.5f}",
                    destination=f"{p['to'][0]:.5f}, {p['to'][1]:.5f}",
                    departure_time_str=f"{t.strip()}:00",
                    date_str=dep.strftime("%Y-%m-%d"),
                )
                pulse = j["options"][0]["total_duration_minutes"] if j.get("options") else None
                results.append({**p, "depart_ist": dep.isoformat(), "google": g, "pulse_min": pulse})
                time.sleep(0.15)

    both = [r for r in results if r["google"].get("status") == "OK" and r["pulse_min"]]
    diffs = [r["pulse_min"] - r["google"]["duration_min"] for r in both]
    ratios = [r["pulse_min"] / r["google"]["duration_min"] for r in both if r["google"]["duration_min"] > 0]
    summary = {
        "status": "OK" if both else "NO_COMPARABLE_PAIRS",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "n_pairs": len(pairs),
        "n_queries": len(results),
        "n_comparable": len(both),
        "google_unavailable": sum(1 for r in results if r["google"].get("status") != "OK"),
        "mean_abs_diff_min": round(statistics.mean(abs(x) for x in diffs), 1) if diffs else None,
        "median_diff_min": round(statistics.median(diffs), 1) if diffs else None,
        "median_ratio_pulse_over_google": round(statistics.median(ratios), 2) if ratios else None,
        "within_20pct_of_google_pct": round(100 * sum(1 for r in ratios if 0.8 <= r <= 1.2) / len(ratios), 1) if ratios else None,
        "note": "Door-to-door totals (walk + wait + ride) for the same origin, destination and departure time.",
        "rows": results,
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(f"Google comparable {len(both)}/{len(results)}; mean |PULSE-Google| {summary['mean_abs_diff_min']} min; "
          f"median ratio {summary['median_ratio_pulse_over_google']}")


if __name__ == "__main__":
    main()
