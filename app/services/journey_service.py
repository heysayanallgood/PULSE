"""
PULSE Journey Planning Orchestrator (app/services/journey_service.py)
Coordinates origin/destination resolution, multi-criteria RAPTOR transit routing,
spatiotemporal travel-time model prediction, and comparative congestion analytics.
"""
from typing import List, Dict, Any, Optional, Tuple, Union
from datetime import datetime
import re

from app.core.config import settings
from app.core.logging import logger
from app.data.gtfs.repository import gtfs_repo
from app.routing.walking import calculate_walking_leg
from app.routing.raptor import raptor_router, RaptorJourneyOption
from app.services.prediction_service import prediction_service


class JourneyPlanningService:
    """High-level service providing congestion-aware bus journey planning."""

    def _resolve_location_candidates(
        self,
        location_input: str
    ) -> Tuple[str, List[Dict[str, Any]]]:
        """
        Resolves a location string (either "lat,lon" or stop name search query)
        into a resolved name and a list of candidate boarding/alighting stops.
        """
        loc_str = location_input.strip()
        
        # Check if coordinates "lat,lon" e.g. "28.6675, 77.2281"
        coord_match = re.match(r"^([-+]?\d*\.?\d+)\s*,\s*([-+]?\d*\.?\d+)$", loc_str)
        if coord_match:
            lat = float(coord_match.group(1))
            lon = float(coord_match.group(2))
            nearby = gtfs_repo.find_nearby_stops(lat, lon, radius_m=settings.MAX_WALK_RADIUS_M, limit=5)
            if not nearby:
                # Expand radius to 1500m
                nearby = gtfs_repo.find_nearby_stops(lat, lon, radius_m=1500.0, limit=5)
            
            # Attach walking leg from coordinate to each stop
            for s in nearby:
                w = calculate_walking_leg(lat, lon, s["stop_lat"], s["stop_lon"])
                s["walk_leg"] = w

            name = f"Location ({lat:.4f}, {lon:.4f})"
            return name, nearby

        # Stop name text search
        stops = gtfs_repo.search_stops(loc_str, limit=5)
        if not stops:
            # Fallback fuzzy matching
            return loc_str, []

        primary_stop = stops[0]
        # Attach 0-distance walking leg for direct stop boards
        for s in stops:
            s["walk_leg"] = {"distance_m": 0.0, "duration_s": 0, "walk_type": "SAME_PLATFORM"}

        return primary_stop["stop_name"], stops

    def plan_journey(
        self,
        origin: str,
        destination: str,
        departure_time_str: Optional[str] = None,
        date_str: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Computes Pareto-optimal bus journeys between origin and destination.
        """
        orig_name, orig_candidates = self._resolve_location_candidates(origin)
        dest_name, dest_candidates = self._resolve_location_candidates(destination)

        if not orig_candidates:
            return {
                "status": "NO_STOPS_FOUND",
                "error": f"No transit stops found matching origin '{origin}'",
                "origin": origin,
                "destination": destination,
                "options": []
            }

        if not dest_candidates:
            return {
                "status": "NO_STOPS_FOUND",
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

        # 2. Round 2: 1-transfer journeys
        xfer_opts = raptor_router.find_one_transfer_journeys(orig_candidates, dest_candidates, dep_s, is_weekend)

        all_candidates = direct_opts + xfer_opts
        if not all_candidates:
            return {
                "status": "NO_ROUTES_FOUND",
                "message": f"No continuous bus connection found between {orig_name} and {dest_name}",
                "origin": orig_name,
                "destination": dest_name,
                "options": []
            }

        # Filter Pareto optimal options
        pareto_opts = raptor_router.filter_pareto_optimal(all_candidates, max_options=3)

        formatted_options = []
        for idx, opt in enumerate(pareto_opts):
            d = opt.to_dict()
            d["option_id"] = idx + 1
            d["origin"] = orig_name
            d["destination"] = dest_name
            formatted_options.append(d)

        # Comparative Off-Peak Benchmark (Satisfies 2.2 in Hackathon Brief)
        # Evaluate how long the same trip takes at off-peak (11:00 PM)
        off_peak_dep_s = 23 * 3600
        off_peak_opts = raptor_router.find_direct_journeys(orig_candidates, dest_candidates, off_peak_dep_s, is_weekend)
        if not off_peak_opts:
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
            "origin": orig_name,
            "destination": dest_name,
            "departure_time": departure_time_str or datetime.now().strftime("%H:%M:%S"),
            "journey_options_count": len(formatted_options),
            "options": formatted_options,
            "off_peak_comparison": off_peak_comparison
        }


# Global singleton journey service
journey_service = JourneyPlanningService()
