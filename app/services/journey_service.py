"""
PULSE Journey Planning Orchestrator (app/services/journey_service.py)
Coordinates origin/destination resolution, multi-criteria RAPTOR transit routing,
spatiotemporal travel-time model prediction, and comparative congestion analytics.
"""
from typing import List, Dict, Any, Optional, Tuple, Union
from datetime import datetime
import re
import time

from app.core.config import settings
from app.core.logging import logger
from app.data.gtfs.repository import gtfs_repo
from app.routing.walking import calculate_walking_leg
from app.routing.raptor import raptor_router, RaptorJourneyOption, resolve_geometries
from app.services.prediction_service import prediction_service
from app.services.places_service import places_service
from app.services.realtime_service import realtime_service
from app.models.live_fusion import fuse_live_and_historical


class JourneyPlanningService:
    """High-level service providing congestion-aware bus journey planning."""

    def _resolve_location_candidates(
        self,
        location_input: str
    ) -> Tuple[str, List[Dict[str, Any]]]:
        """
        Resolves a location string (either "lat,lon", "Stop Name [ID]", landmark, or stop name)
        into a resolved name and a list of candidate boarding/alighting stops.
        """
        loc_str = location_input.strip()
        
        # 1. Check if coordinates "lat,lon" e.g. "28.6675, 77.2281"
        coord_match = re.match(r"^([-+]?\d*\.?\d+)\s*,\s*([-+]?\d*\.?\d+)$", loc_str)
        if coord_match:
            lat = float(coord_match.group(1))
            lon = float(coord_match.group(2))
            
            # Check bounding box
            if not (28.2 <= lat <= 28.95 and 76.8 <= lon <= 77.55):
                logger.warning(f"Coordinate ({lat}, {lon}) is outside Delhi transit bounds.")
                return f"Out-of-Bounds ({lat:.4f}, {lon:.4f})", []

            nearby = gtfs_repo.find_nearby_stops(lat, lon, radius_m=settings.MAX_WALK_RADIUS_M, limit=10)
            if not nearby:
                # Expand to 1500m (walk limit)
                nearby = gtfs_repo.find_nearby_stops(lat, lon, radius_m=1500.0, limit=10)
            
            for s in nearby:
                w = calculate_walking_leg(lat, lon, float(s["stop_lat"]), float(s["stop_lon"]))
                s["walk_leg"] = w

            name = f"Location ({lat:.4f}, {lon:.4f})"
            return name, nearby

        # 2. Check for stop ID in brackets e.g. "Kashmere Gate [7571]"
        id_match = re.search(r"\[(\w+)\]", loc_str)
        if id_match:
            extracted_id = id_match.group(1)
            stop = gtfs_repo.get_stop_by_id(extracted_id)
            if stop:
                stop["walk_leg"] = {"distance_m": 0.0, "duration_s": 0, "walk_type": "SAME_PLATFORM"}
                return stop["stop_name"], [stop]

        # 3. Direct stop_id lookup
        if loc_str.isdigit():
            stop = gtfs_repo.get_stop_by_id(loc_str)
            if stop:
                stop["walk_leg"] = {"distance_m": 0.0, "duration_s": 0, "walk_type": "SAME_PLATFORM"}
                return stop["stop_name"], [stop]

        # 4. Check Delhi Landmarks Catalog (e.g. "Connaught Place", "India Gate")
        # Landmarks are resolved to spatial centroids to capture all access stops within 800m
        landmark = places_service.resolve_landmark(loc_str)
        if landmark:
            lm_title, lm_lat, lm_lon, lm_desc = landmark
            nearby = gtfs_repo.find_nearby_stops(lm_lat, lm_lon, radius_m=800.0, limit=10)
            if not nearby:
                nearby = gtfs_repo.find_nearby_stops(lm_lat, lm_lon, radius_m=1500.0, limit=10)
            if nearby:
                for s in nearby:
                    w = calculate_walking_leg(lm_lat, lm_lon, float(s["stop_lat"]), float(s["stop_lon"]))
                    s["walk_leg"] = w
                return lm_title, nearby

        # 5. Stop name text search in GTFS index
        stops = gtfs_repo.search_stops(loc_str, limit=8)
        if stops:
            primary_stop = stops[0]
            for s in stops:
                s["walk_leg"] = {"distance_m": 0.0, "duration_s": 0, "walk_type": "SAME_PLATFORM"}
            return primary_stop["stop_name"], stops

        return loc_str, []

    def plan_journey(
        self,
        origin: str,
        destination: str,
        departure_time_str: Optional[str] = None,
        date_str: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Computes Pareto-optimal bus journeys between origin and destination.
        Returns standardized contract with request_id, query, and unique journey IDs.
        """
        request_id = f"req_{int(time.time() * 1000)}"
        query_meta = {
            "origin": origin,
            "destination": destination,
            "departure_time": departure_time_str,
            "date": date_str
        }

        orig_name, orig_candidates = self._resolve_location_candidates(origin)
        dest_name, dest_candidates = self._resolve_location_candidates(destination)

        if not orig_candidates:
            return {
                "status": "NO_STOPS_FOUND",
                "request_id": request_id,
                "query": query_meta,
                "error": f"No transit stops found matching origin '{origin}'",
                "origin": origin,
                "destination": destination,
                "options": []
            }

        if not dest_candidates:
            return {
                "status": "NO_STOPS_FOUND",
                "request_id": request_id,
                "query": query_meta,
                "error": f"No transit stops found matching destination '{destination}'",
                "origin": origin,
                "destination": destination,
                "options": []
            }

        # Parse departure time
        if departure_time_str:
            parts = [int(p) for p in departure_time_str.split(":")]
            dep_s = parts[0] * 3600 + parts[1] * 60 + (parts[2] if len(parts) > 2 else 0)
        else:
            now = datetime.now()
            dep_s = now.hour * 3600 + now.minute * 60 + now.second

        # Weekend determination
        is_weekend = 0
        if date_str:
            try:
                dt = datetime.strptime(date_str, "%Y-%m-%d")
                is_weekend = 1 if dt.weekday() in [5, 6] else 0
            except Exception:
                pass

        # 1. Round 1: Direct journeys
        direct_opts = raptor_router.find_direct_journeys(orig_candidates, dest_candidates, dep_s, is_weekend)

        # 2. Round 2: 1-transfer journeys (if direct options are fewer than 3)
        xfer_opts = []
        if len(direct_opts) < 3:
            xfer_opts = raptor_router.find_one_transfer_journeys(orig_candidates, dest_candidates, dep_s, is_weekend)

        all_candidates = direct_opts + xfer_opts
        if not all_candidates:
            return {
                "status": "NO_ROUTES_FOUND",
                "request_id": request_id,
                "query": query_meta,
                "message": f"No continuous bus connection found between {orig_name} and {dest_name}",
                "origin": orig_name,
                "destination": dest_name,
                "options": []
            }

        # Filter Pareto optimal options
        pareto_opts = raptor_router.filter_pareto_optimal(all_candidates, max_options=3)
        resolve_geometries(pareto_opts)

        formatted_options = []
        for idx, opt in enumerate(pareto_opts):
            d = opt.to_dict()
            d["option_id"] = idx + 1
            d["journey_id"] = f"j_{request_id}_{idx + 1}"
            d["origin"] = orig_name
            d["destination"] = dest_name
            
            # Ensure boarding and alighting coordinates on bus legs
            for leg in d.get("legs", []):
                if leg["type"] == "BUS":
                    if "boarding_lat" not in leg and leg.get("geometry"):
                        leg["boarding_lat"] = leg["geometry"][0][0]
                        leg["boarding_lon"] = leg["geometry"][0][1]
                    if "alighting_lat" not in leg and leg.get("geometry"):
                        leg["alighting_lat"] = leg["geometry"][-1][0]
                        leg["alighting_lon"] = leg["geometry"][-1][1]

            formatted_options.append(d)

        live_used = self._apply_live_fusion(formatted_options, dep_s, date_str)

        # Comparative Off-Peak Benchmark (Satisfies 2.2 in Hackathon Brief)
        # Evaluate how long the same trip takes at off-peak (11:00 PM)
        off_peak_dep_s = 23 * 3600
        off_peak_opts = raptor_router.find_direct_journeys(orig_candidates, dest_candidates, off_peak_dep_s, is_weekend)
        if not off_peak_opts and len(direct_opts) < 3:
            off_peak_opts = raptor_router.find_one_transfer_journeys(orig_candidates, dest_candidates, off_peak_dep_s, is_weekend)

        off_peak_comparison = None
        if off_peak_opts and formatted_options:
            best_curr = formatted_options[0]["total_duration_minutes"]
            best_offpeak = round(off_peak_opts[0].total_duration_s / 60.0, 1)
            time_saved = max(0.0, round(best_curr - best_offpeak, 1))
            off_peak_comparison = {
                "off_peak_departure": "23:00 (Late Night)",
                "off_peak_duration_minutes": best_offpeak,
                "peak_duration_minutes": best_curr,
                "congestion_delay_minutes": time_saved,
                "insight": f"At 11:00 PM, free-flow traffic saves ~{time_saved} minutes on this journey."
            }

        return {
            "status": "SUCCESS",
            "request_id": request_id,
            "query": query_meta,
            "origin": orig_name,
            "destination": dest_name,
            "departure_time": departure_time_str or datetime.now().strftime("%H:%M:%S"),
            "journey_options_count": len(formatted_options),
            "options": formatted_options,
            "off_peak_comparison": off_peak_comparison,
            "live": live_used,
        }


    @staticmethod
    def _apply_live_fusion(options: List[Dict[str, Any]], dep_s: int, date_str: Optional[str]) -> Dict[str, Any]:
        """Blend each bus leg with the route's live pace when the trip departs
        within 30 min of now (IST) and the live window has enough evidence."""
        from zoneinfo import ZoneInfo
        now = datetime.now(ZoneInfo(settings.TIMEZONE))
        now_s = now.hour * 3600 + now.minute * 60 + now.second
        same_day = (not date_str) or date_str == now.strftime("%Y-%m-%d")
        near_now = same_day and abs(((dep_s - now_s + 43200) % 86400) - 43200) <= 1800
        info = {"applied": False, "reason": None}
        if not (settings.LIVE_FEED_ENABLED and settings.OTD_API_KEY):
            info["reason"] = "LIVE_FEED_OFF"
            return info
        if not near_now:
            info["reason"] = "DEPARTURE_NOT_NOW"
            return info
        for opt in options:
            delta_total = 0.0
            any_live = False
            for leg in opt.get("legs", []):
                if leg.get("type") != "BUS":
                    continue
                live = realtime_service.route_live_pace(str(leg.get("route_id")))
                t_hist = float(leg.get("predicted_duration_minutes", 0)) * 60.0
                dist_m = float(leg.get("distance_km", 0)) * 1000.0
                if not live or t_hist <= 0 or dist_m <= 0:
                    leg["live_weight"] = 0.0
                    leg["freshness"] = "UNAVAILABLE"
                    continue
                spread_h = max(1.0, (float(leg.get("upper_bound_minutes", 0)) - float(leg.get("lower_bound_minutes", 0))) * 60.0 / 2.56)
                fused = fuse_live_and_historical(
                    t_live=dist_m * live["pace_s_per_m"],
                    var_live=(dist_m ** 2) * live["pace_var"] / max(live["n_pairs"], 1) + (0.15 * dist_m * live["pace_s_per_m"]) ** 2,
                    vehicle_age_seconds=live["age_s"],
                    n_live_vehicles=live["n_vehicles"],
                    t_hist=t_hist,
                    var_hist=spread_h ** 2,
                    n_hist_trips=30,
                    stale_threshold_seconds=settings.LIVE_MAX_STALENESS_SECONDS,
                )
                leg["live_weight"] = fused["weight_live"]
                leg["freshness"] = fused["freshness_state"]
                leg["live_buses"] = live["n_vehicles"]
                if fused["weight_live"] > 0.05:
                    new_t = float(fused["estimated_travel_time_s"])
                    delta = new_t - t_hist
                    leg["historical_duration_minutes"] = leg["predicted_duration_minutes"]
                    leg["predicted_duration_minutes"] = round(new_t / 60.0, 1)
                    leg["lower_bound_minutes"] = round(float(leg["lower_bound_minutes"]) + delta / 60.0, 1)
                    leg["upper_bound_minutes"] = round(float(leg["upper_bound_minutes"]) + delta / 60.0, 1)
                    leg["provenance"] = "LIVE + HISTORICAL"
                    delta_total += delta
                    any_live = True
            if any_live:
                opt["total_duration_minutes"] = round(opt["total_duration_minutes"] + delta_total / 60.0, 1)
                opt["in_vehicle_minutes"] = round(opt["in_vehicle_minutes"] + delta_total / 60.0, 1)
                opt["lower_bound_minutes"] = round(opt["lower_bound_minutes"] + delta_total / 60.0, 1)
                opt["upper_bound_minutes"] = round(opt["upper_bound_minutes"] + delta_total / 60.0, 1)
                opt["provenance"] = "LIVE + HISTORICAL"
                info["applied"] = True
        if not info["applied"]:
            info["reason"] = "NOT_ENOUGH_LIVE_EVIDENCE"
        return info


# Global singleton journey service
journey_service = JourneyPlanningService()
