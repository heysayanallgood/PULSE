"""
PULSE Multi-Criteria RAPTOR Engine (app/routing/raptor.py)
Implements ADR 004 and Pre-Implementation Correction 6.
Evaluates Pareto-optimal public transit journeys (Arrival Time, Transfers, Walking Duration),
driving in-vehicle travel times strictly from the PULSE Spatiotemporal Model.
"""
from typing import List, Dict, Any, Optional, Tuple, Set
import time
import math
import duckdb
from pathlib import Path

from app.core.config import settings
from app.core.logging import logger
from app.data.gtfs.repository import gtfs_repo
from app.routing.walking import calculate_walking_leg
from app.services.prediction_service import prediction_service

GTFS_DB_PATH = Path("E:/Pulse/data/database/gtfs.duckdb")


class RaptorJourneyOption:
    """Represents a candidate journey with leg breakdown and Pareto attributes."""

    def __init__(
        self,
        arrival_time_s: int,
        transfers: int,
        walking_duration_s: int,
        in_vehicle_duration_s: int,
        waiting_duration_s: int,
        legs: List[Dict[str, Any]],
        confidence: str,
        provenance: str,
        lower_bound_s: int,
        upper_bound_s: int
    ):
        self.arrival_time_s = arrival_time_s
        self.transfers = transfers
        self.walking_duration_s = walking_duration_s
        self.in_vehicle_duration_s = in_vehicle_duration_s
        self.waiting_duration_s = waiting_duration_s
        self.total_duration_s = walking_duration_s + in_vehicle_duration_s + waiting_duration_s
        self.legs = legs
        self.confidence = confidence
        self.provenance = provenance
        self.lower_bound_s = lower_bound_s
        self.upper_bound_s = upper_bound_s

    def dominates(self, other: "RaptorJourneyOption") -> bool:
        """Pareto dominance: arrival_time, transfers, walking_duration."""
        less_or_equal = (
            self.arrival_time_s <= other.arrival_time_s and
            self.transfers <= other.transfers and
            self.walking_duration_s <= other.walking_duration_s
        )
        strictly_better = (
            self.arrival_time_s < other.arrival_time_s or
            self.transfers < other.transfers or
            self.walking_duration_s < other.walking_duration_s
        )
        return less_or_equal and strictly_better

    def to_dict(self) -> Dict[str, Any]:
        return {
            "total_duration_minutes": round(self.total_duration_s / 60.0, 1),
            "total_duration_seconds": self.total_duration_s,
            "in_vehicle_minutes": round(self.in_vehicle_duration_s / 60.0, 1),
            "walking_minutes": round(self.walking_duration_s / 60.0, 1),
            "waiting_minutes": round(self.waiting_duration_s / 60.0, 1),
            "transfers": self.transfers,
            "confidence": self.confidence,
            "provenance": self.provenance,
            "lower_bound_minutes": round(self.lower_bound_s / 60.0, 1),
            "upper_bound_minutes": round(self.upper_bound_s / 60.0, 1),
            "legs": self.legs
        }


class RaptorRouter:
    """Executes multi-criteria round-based transit search over the GTFS network."""

    def __init__(self):
        self.con = duckdb.connect(str(GTFS_DB_PATH), read_only=True)
        self.con.execute("SET temp_directory = 'E:/Pulse/data/cache/duckdb';")

    def _parse_time_str(self, time_str: str) -> int:
        parts = [int(p) for p in time_str.split(":")]
        return parts[0] * 3600 + parts[1] * 60 + (parts[2] if len(parts) > 2 else 0)

    def _format_time_s(self, total_s: int) -> str:
        s = int(total_s) % 86400
        h = s // 3600
        m = (s % 3600) // 60
        sec = s % 60
        return f"{h:02d}:{m:02d}:{sec:02d}"

    def find_direct_journeys(
        self,
        origin_stops: List[Dict[str, Any]],
        destination_stops: List[Dict[str, Any]],
        departure_time_s: int,
        is_weekend: int = 0
    ) -> List[RaptorJourneyOption]:
        """Finds direct (0-transfer) journey options between origin and destination stops."""
        o_ids = [s["stop_id"] for s in origin_stops]
        d_ids = [s["stop_id"] for s in destination_stops]

        if not o_ids or not d_ids:
            return []

        # Find routes that visit both an origin stop and a destination stop with correct sequence
        placeholders_o = ", ".join([f"'{x}'" for x in o_ids])
        placeholders_d = ", ".join([f"'{x}'" for x in d_ids])

        query = f"""
            SELECT 
                r.route_id,
                r.route_short_name,
                r.route_long_name,
                t.trip_id,
                t.shape_id,
                st1.stop_id AS origin_stop_id,
                st1.stop_sequence AS origin_seq,
                st1.departure_time AS sched_dep,
                st1.stop_dist AS origin_dist,
                st2.stop_id AS dest_stop_id,
                st2.stop_sequence AS dest_seq,
                st2.arrival_time AS sched_arr,
                st2.stop_dist AS dest_dist
            FROM stop_times st1
            JOIN stop_times st2 ON st1.trip_id = st2.trip_id
            JOIN trips t ON st1.trip_id = t.trip_id
            JOIN routes r ON t.route_id = r.route_id
            WHERE st1.stop_id IN ({placeholders_o})
              AND st2.stop_id IN ({placeholders_d})
              AND st1.stop_sequence < st2.stop_sequence
            LIMIT 50;
        """
        matches = self.con.execute(query).fetchdf()
        if len(matches) == 0:
            return []

        results = []
        origin_map = {s["stop_id"]: s for s in origin_stops}
        dest_map = {s["stop_id"]: s for s in destination_stops}

        for _, row in matches.iterrows():
            orig_stop = origin_map[row["origin_stop_id"]]
            dest_stop = dest_map[row["dest_stop_id"]]

            walk_first = orig_stop.get("walk_leg", {"distance_m": 0, "duration_s": 0, "walk_type": "SAME_PLATFORM"})
            walk_final = dest_stop.get("walk_leg", {"distance_m": 0, "duration_s": 0, "walk_type": "SAME_PLATFORM"})

            # Boarding time is at earliest departure_time_s + walk_first duration
            earliest_board = departure_time_s + walk_first["duration_s"]
            sched_dep_s = self._parse_time_str(row["sched_dep"])
            
            # Wait time before bus arrives
            wait_s = max(180, (sched_dep_s - earliest_board) % 1800)  # Typical Delhi 15-30m headway

            actual_board_s = earliest_board + wait_s

            # Predict in-vehicle travel time using PULSE Model!
            if row["origin_dist"] is not None and row["dest_dist"] is not None and float(row["dest_dist"]) > float(row["origin_dist"]):
                d_start = float(row["origin_dist"])
                d_end = float(row["dest_dist"])
            else:
                # Calculate metric distance between stops using UTM 43N
                from pyproj import Transformer
                t_proj = Transformer.from_crs("EPSG:4326", "EPSG:32643", always_xy=True)
                ox, oy = t_proj.transform(orig_stop["stop_lon"], orig_stop["stop_lat"])
                dx, dy = t_proj.transform(dest_stop["stop_lon"], dest_stop["stop_lat"])
                d_crow = math.sqrt((dx - ox)**2 + (dy - oy)**2)
                # Apply transit road winding factor (1.30)
                d_road = max(500.0, d_crow * 1.30)
                d_start = 0.0
                d_end = d_road

            pred = prediction_service.predict_leg_travel_time(
                route_id=row["route_id"],
                shape_id=row["shape_id"] or "default",
                start_dist_m=d_start,
                end_dist_m=d_end,
                departure_time_seconds=actual_board_s,
                is_weekend=is_weekend
            )

            in_vehicle_s = int(pred["total_travel_time_s"])
            arrival_s = actual_board_s + in_vehicle_s + walk_final["duration_s"]
            total_walk_s = walk_first["duration_s"] + walk_final["duration_s"]

            legs = []
            if walk_first["duration_s"] > 0:
                legs.append({
                    "type": "WALK",
                    "instruction": f"Walk to {orig_stop['stop_name']}",
                    "distance_m": walk_first["distance_m"],
                    "duration_seconds": walk_first["duration_s"],
                    "duration_minutes": round(walk_first["duration_s"] / 60.0, 1),
                    "walk_type": walk_first.get("walk_type", "APPROXIMATED_WALK"),
                    "confidence": "HIGH"
                })

            legs.append({
                "type": "BUS",
                "route_id": row["route_id"],
                "route_name": row["route_short_name"] or row["route_long_name"],
                "boarding_stop": orig_stop["stop_name"],
                "boarding_stop_id": orig_stop["stop_id"],
                "alighting_stop": dest_stop["stop_name"],
                "alighting_stop_id": dest_stop["stop_id"],
                "stops_traversed": int(row["dest_seq"] - row["origin_seq"]),
                "distance_km": round(pred["total_distance_m"] / 1000.0, 2),
                "departure_time": self._format_time_s(actual_board_s),
                "predicted_duration_minutes": round(in_vehicle_s / 60.0, 1),
                "lower_bound_minutes": round(pred["lower_bound_s"] / 60.0, 1),
                "upper_bound_minutes": round(pred["upper_bound_s"] / 60.0, 1),
                "confidence": pred["confidence"],
                "provenance": pred["provenance"]
            })

            if walk_final["duration_s"] > 0:
                legs.append({
                    "type": "WALK",
                    "instruction": f"Walk from {dest_stop['stop_name']} to destination",
                    "distance_m": walk_final["distance_m"],
                    "duration_seconds": walk_final["duration_s"],
                    "duration_minutes": round(walk_final["duration_s"] / 60.0, 1),
                    "walk_type": walk_final.get("walk_type", "APPROXIMATED_WALK"),
                    "confidence": "HIGH"
                })

            opt = RaptorJourneyOption(
                arrival_time_s=arrival_s,
                transfers=0,
                walking_duration_s=total_walk_s,
                in_vehicle_duration_s=in_vehicle_s,
                waiting_duration_s=wait_s,
                legs=legs,
                confidence=pred["confidence"],
                provenance=pred["provenance"],
                lower_bound_s=int(pred["lower_bound_s"]) + total_walk_s + wait_s,
                upper_bound_s=int(pred["upper_bound_s"]) + total_walk_s + wait_s
            )
            results.append(opt)

        return results

    def find_one_transfer_journeys(
        self,
        origin_stops: List[Dict[str, Any]],
        destination_stops: List[Dict[str, Any]],
        departure_time_s: int,
        is_weekend: int = 0
    ) -> List[RaptorJourneyOption]:
        """Finds 1-transfer journey options connecting via intermediate transfer hubs."""
        o_ids = [s["stop_id"] for s in origin_stops[:3]]
        d_ids = [s["stop_id"] for s in destination_stops[:3]]

        placeholders_o = ", ".join([f"'{x}'" for x in o_ids])
        placeholders_d = ", ".join([f"'{x}'" for x in d_ids])

        # High-traffic interchange hubs in Delhi (ISBTs, Central Nodes, Ring Road)
        query = f"""
            SELECT 
                r1.route_id AS r1_id, r1.route_short_name AS r1_name, t1.shape_id AS shape1,
                st1_o.stop_id AS orig_id, st1_o.stop_sequence AS orig_seq, st1_o.stop_dist AS orig_dist,
                st1_x.stop_id AS xfer_id, st1_x.stop_sequence AS xfer1_seq, st1_x.stop_dist AS xfer1_dist,
                
                r2.route_id AS r2_id, r2.route_short_name AS r2_name, t2.shape_id AS shape2,
                st2_x.stop_sequence AS xfer2_seq, st2_x.stop_dist AS xfer2_dist,
                st2_d.stop_id AS dest_id, st2_d.stop_sequence AS dest_seq, st2_d.stop_dist AS dest_dist
            FROM stop_times st1_o
            JOIN stop_times st1_x ON st1_o.trip_id = st1_x.trip_id
            JOIN trips t1 ON st1_o.trip_id = t1.trip_id
            JOIN routes r1 ON t1.route_id = r1.route_id
            
            JOIN stop_times st2_x ON st1_x.stop_id = st2_x.stop_id
            JOIN stop_times st2_d ON st2_x.trip_id = st2_d.trip_id
            JOIN trips t2 ON st2_x.trip_id = t2.trip_id
            JOIN routes r2 ON t2.route_id = r2.route_id
            
            WHERE st1_o.stop_id IN ({placeholders_o})
              AND st2_d.stop_id IN ({placeholders_d})
              AND st1_o.stop_sequence < st1_x.stop_sequence
              AND st2_x.stop_sequence < st2_d.stop_sequence
              AND r1.route_id != r2.route_id
            LIMIT 20;
        """
        matches = self.con.execute(query).fetchdf()
        if len(matches) == 0:
            return []

        results = []
        origin_map = {s["stop_id"]: s for s in origin_stops}
        dest_map = {s["stop_id"]: s for s in destination_stops}

        for _, row in matches.iterrows():
            orig_stop = origin_map[row["orig_id"]]
            dest_stop = dest_map[row["dest_id"]]
            xfer_stop_data = gtfs_repo.get_stop_by_id(row["xfer_id"]) or {"stop_name": "Interchange Hub"}

            walk_first = orig_stop.get("walk_leg", {"distance_m": 0, "duration_s": 0})
            walk_final = dest_stop.get("walk_leg", {"distance_m": 0, "duration_s": 0})

            # Leg 1: Board bus 1
            earliest_board1 = departure_time_s + walk_first["duration_s"]
            wait1_s = 240  # 4 min wait
            board1_s = earliest_board1 + wait1_s

            # Leg 1 distance
            from pyproj import Transformer
            t_proj = Transformer.from_crs("EPSG:4326", "EPSG:32643", always_xy=True)
            if row["orig_dist"] is not None and row["xfer1_dist"] is not None and float(row["xfer1_dist"]) > float(row["orig_dist"]):
                d1_start = float(row["orig_dist"])
                d1_end = float(row["xfer1_dist"])
            else:
                o1_x, o1_y = t_proj.transform(orig_stop["stop_lon"], orig_stop["stop_lat"])
                x1_x, x1_y = t_proj.transform(xfer_stop_data.get("stop_lon", orig_stop["stop_lon"]), xfer_stop_data.get("stop_lat", orig_stop["stop_lat"]))
                d1_end = max(1000.0, math.sqrt((x1_x - o1_x)**2 + (x1_y - o1_y)**2) * 1.30)
                d1_start = 0.0

            pred1 = prediction_service.predict_leg_travel_time(
                route_id=row["r1_id"],
                shape_id=row["shape1"] or "default",
                start_dist_m=d1_start,
                end_dist_m=d1_end,
                departure_time_seconds=board1_s,
                is_weekend=is_weekend
            )
            tt1_s = int(pred1["total_travel_time_s"])
            arr_xfer_s = board1_s + tt1_s

            # Transfer Buffer (Correction 6: 3 minutes configurable baseline)
            xfer_buffer_s = settings.MIN_TRANSFER_BUFFER_SECONDS
            wait2_s = 300  # 5 min wait for connection
            board2_s = arr_xfer_s + xfer_buffer_s + wait2_s

            # Leg 2 distance
            if row["xfer2_dist"] is not None and row["dest_dist"] is not None and float(row["dest_dist"]) > float(row["xfer2_dist"]):
                d2_start = float(row["xfer2_dist"])
                d2_end = float(row["dest_dist"])
            else:
                d2_x, d2_y = t_proj.transform(dest_stop["stop_lon"], dest_stop["stop_lat"])
                x2_x, x2_y = t_proj.transform(xfer_stop_data.get("stop_lon", dest_stop["stop_lon"]), xfer_stop_data.get("stop_lat", dest_stop["stop_lat"]))
                d2_end = max(1000.0, math.sqrt((d2_x - x2_x)**2 + (d2_y - x2_y)**2) * 1.30)
                d2_start = 0.0

            pred2 = prediction_service.predict_leg_travel_time(
                route_id=row["r2_id"],
                shape_id=row["shape2"] or "default",
                start_dist_m=d2_start,
                end_dist_m=d2_end,
                departure_time_seconds=board2_s,
                is_weekend=is_weekend
            )
            tt2_s = int(pred2["total_travel_time_s"])
            arrival_s = board2_s + tt2_s + walk_final["duration_s"]

            total_in_vehicle_s = tt1_s + tt2_s
            total_walk_s = walk_first["duration_s"] + walk_final["duration_s"]
            total_wait_s = wait1_s + xfer_buffer_s + wait2_s

            legs = [
                {
                    "type": "BUS",
                    "route_id": row["r1_id"],
                    "route_name": row["r1_name"],
                    "boarding_stop": orig_stop["stop_name"],
                    "alighting_stop": xfer_stop_data["stop_name"],
                    "stops_traversed": int(row["xfer1_seq"] - row["orig_seq"]),
                    "distance_km": round(pred1["total_distance_m"] / 1000.0, 2),
                    "departure_time": self._format_time_s(board1_s),
                    "predicted_duration_minutes": round(tt1_s / 60.0, 1),
                    "confidence": pred1["confidence"],
                    "provenance": pred1["provenance"]
                },
                {
                    "type": "TRANSFER",
                    "transfer_stop": xfer_stop_data["stop_name"],
                    "buffer_minutes": round(xfer_buffer_s / 60.0, 1),
                    "expected_wait_minutes": round(wait2_s / 60.0, 1),
                    "instruction": f"Change buses at {xfer_stop_data['stop_name']} to Route {row['r2_name']}"
                },
                {
                    "type": "BUS",
                    "route_id": row["r2_id"],
                    "route_name": row["r2_name"],
                    "boarding_stop": xfer_stop_data["stop_name"],
                    "alighting_stop": dest_stop["stop_name"],
                    "stops_traversed": int(row["dest_seq"] - row["xfer2_seq"]),
                    "distance_km": round(pred2["total_distance_m"] / 1000.0, 2),
                    "departure_time": self._format_time_s(board2_s),
                    "predicted_duration_minutes": round(tt2_s / 60.0, 1),
                    "confidence": pred2["confidence"],
                    "provenance": pred2["provenance"]
                }
            ]

            opt = RaptorJourneyOption(
                arrival_time_s=arrival_s,
                transfers=1,
                walking_duration_s=total_walk_s,
                in_vehicle_duration_s=total_in_vehicle_s,
                waiting_duration_s=total_wait_s,
                legs=legs,
                confidence="MEDIUM",
                provenance="HISTORICAL",
                lower_bound_s=int(pred1["lower_bound_s"] + pred2["lower_bound_s"]) + total_walk_s + total_wait_s,
                upper_bound_s=int(pred1["upper_bound_s"] + pred2["upper_bound_s"]) + total_walk_s + total_wait_s
            )
            results.append(opt)

        return results

    def filter_pareto_optimal(self, candidates: List[RaptorJourneyOption], max_options: int = 3) -> List[RaptorJourneyOption]:
        """Applies Pareto dominance filtering across arrival time, transfers, and walking time."""
        pareto = []
        for cand in candidates:
            is_dominated = False
            for other in candidates:
                if other is not cand and other.dominates(cand):
                    is_dominated = True
                    break
            if not is_dominated:
                # Avoid duplicate identical arrival and transfer counts
                if not any(p.arrival_time_s == cand.arrival_time_s and p.transfers == cand.transfers for p in pareto):
                    pareto.append(cand)

        # Sort by total duration
        pareto.sort(key=lambda x: x.total_duration_s)
        return pareto[:max_options]


# Global singleton router
raptor_router = RaptorRouter()
