"""
PULSE Spatiotemporal Prediction Service (app/services/prediction_service.py)
Implements ADR 002, ADR 004, ADR 005.
Provides sub-millisecond predicted travel times for route segments,
aggregates route in-vehicle durations, and computes multi-time-of-day traffic comparisons.
"""
from pathlib import Path
from typing import List, Dict, Any, Optional, Tuple
from datetime import datetime
import math
import duckdb

from app.core.config import settings
from app.core.logging import logger

MODEL_DB_PATH = Path("E:/Pulse/data/database/travel_time.duckdb")
GTFS_DB_PATH = Path("E:/Pulse/data/database/gtfs.duckdb")


class TravelTimePredictionService:
    """Service for predicting time-dependent bus in-vehicle travel times."""

    def __init__(self, db_path: Optional[Path] = None):
        self.db_path = db_path or MODEL_DB_PATH
        self._con: Optional[duckdb.DuckDBPyConnection] = None

    def _get_connection(self) -> duckdb.DuckDBPyConnection:
        if self._con is None:
            self._con = duckdb.connect(str(self.db_path), read_only=True)
            self._con.execute("SET temp_directory = 'E:/Pulse/data/cache/duckdb';")
            # Attach GTFS database as schema gtfs
            gtfs_path = Path("E:/Pulse/data/database/gtfs.duckdb")
            if gtfs_path.exists():
                self._con.execute(f"ATTACH '{gtfs_path.as_posix()}' AS gtfs (READ_ONLY);")
        return self._con

    def predict_segment_travel_time(
        self,
        route_id: str,
        segment_id: str,
        time_bucket_15min: int,
        is_weekend: int = 0
    ) -> Dict[str, Any]:
        """
        Retrieves predicted travel time and uncertainty variance for a single segment.
        """
        con = self._get_connection()
        bucket = max(0, min(95, int(time_bucket_15min)))
        
        row = con.execute("""
            SELECT 
                segment_id,
                route_id,
                length_m,
                speed_median_mps,
                travel_time_median_s,
                travel_time_variance,
                sample_count,
                confidence,
                provenance
            FROM travel_time_model
            WHERE route_id = ? AND segment_id = ? AND time_bucket_15min = ? AND is_weekend = ?
            LIMIT 1;
        """, [str(route_id), segment_id, bucket, is_weekend]).fetchone()

        if row:
            return {
                "segment_id": row[0],
                "route_id": row[1],
                "length_m": row[2],
                "speed_median_mps": row[3],
                "travel_time_s": row[4],
                "variance": row[5],
                "sample_count": row[6],
                "confidence": row[7],
                "provenance": row[8]
            }

        # Fallback to route-independent segment query if route_id not directly mapped
        row_fallback = con.execute("""
            SELECT 
                segment_id,
                route_id,
                length_m,
                speed_median_mps,
                travel_time_median_s,
                travel_time_variance,
                sample_count,
                confidence,
                provenance
            FROM travel_time_model
            WHERE segment_id = ? AND time_bucket_15min = ? AND is_weekend = ?
            LIMIT 1;
        """, [segment_id, bucket, is_weekend]).fetchone()

        if row_fallback:
            return {
                "segment_id": row_fallback[0],
                "route_id": row_fallback[1],
                "length_m": row_fallback[2],
                "speed_median_mps": row_fallback[3],
                "travel_time_s": row_fallback[4],
                "variance": row_fallback[5],
                "sample_count": row_fallback[6],
                "confidence": "MEDIUM",
                "provenance": "ESTIMATED_FALLBACK"
            }

        # Global network default fallback
        return {
            "segment_id": segment_id,
            "route_id": str(route_id),
            "length_m": 400.0,
            "speed_median_mps": 5.0,
            "travel_time_s": 80.0,
            "variance": 16.0,
            "sample_count": 0,
            "confidence": "LOW",
            "provenance": "ESTIMATED_FALLBACK"
        }

    def predict_leg_travel_time(
        self,
        route_id: str,
        shape_id: str,
        start_dist_m: float,
        end_dist_m: float,
        departure_time_seconds: int,
        is_weekend: int = 0
    ) -> Dict[str, Any]:
        """
        Computes dynamic travel time for a sequence of segments along a shape between start and end distances.
        Updates arrival clock dynamically across segments.
        """
        con = self._get_connection()
        d_min = min(start_dist_m, end_dist_m)
        d_max = max(start_dist_m, end_dist_m)

        # Retrieve all segments lying between d_min and d_max
        segments = con.execute("""
            SELECT 
                segment_id,
                segment_sequence,
                start_dist_m,
                end_dist_m,
                length_m
            FROM gtfs.route_segments
            WHERE shape_id = ?
              AND end_dist_m >= ?
              AND start_dist_m <= ?
            ORDER BY segment_sequence ASC;
        """, [shape_id, d_min, d_max]).fetchall()

        if not segments:
            # Fallback estimation based on distance
            dist = max(100.0, d_max - d_min)
            hour = (departure_time_seconds // 3600) % 24
            speed = 4.0 if 8 <= hour <= 10 or 17 <= hour <= 20 else 7.5
            tt = dist / speed
            return {
                "total_travel_time_s": round(tt, 1),
                "total_distance_m": round(dist, 1),
                "segment_count": 0,
                "confidence": "LOW",
                "provenance": "ESTIMATED_FALLBACK",
                "lower_bound_s": round(tt * 0.85, 1),
                "upper_bound_s": round(tt * 1.35, 1)
            }

        total_tt = 0.0
        total_dist = 0.0
        total_var = 0.0
        current_time_s = departure_time_seconds
        sample_counts = []

        for seg_id, seq, s_start, s_end, s_len in segments:
            # Fraction of segment traversed
            overlap_start = max(d_min, s_start)
            overlap_end = min(d_max, s_end)
            overlap_len = max(10.0, overlap_end - overlap_start)
            ratio = overlap_len / max(s_len, 1.0)

            # Determine 15-min bucket for current arrival clock
            current_hour = (int(current_time_s) // 3600) % 24
            current_minute = (int(current_time_s) % 3600) // 60
            bucket = (current_hour * 4 + current_minute // 15) % 96

            pred = self.predict_segment_travel_time(route_id, seg_id, bucket, is_weekend)
            seg_duration = pred["travel_time_s"] * ratio
            
            total_tt += seg_duration
            total_dist += overlap_len
            total_var += pred["variance"] * ratio
            current_time_s += seg_duration
            sample_counts.append(pred["sample_count"])

        std_dev = math.sqrt(max(total_var, 4.0))
        lower_bound = max(total_dist / 15.0, total_tt - 1.28 * std_dev)
        upper_bound = total_tt + 1.28 * std_dev

        avg_samples = sum(sample_counts) / max(len(sample_counts), 1)
        conf = "HIGH" if avg_samples >= 15 else ("MEDIUM" if avg_samples >= 5 else "LOW")
        prov = "HISTORICAL" if avg_samples >= 5 else "ESTIMATED_FALLBACK"

        return {
            "total_travel_time_s": round(total_tt, 1),
            "total_distance_m": round(total_dist, 1),
            "segment_count": len(segments),
            "confidence": conf,
            "provenance": prov,
            "lower_bound_s": round(lower_bound, 1),
            "upper_bound_s": round(upper_bound, 1),
            "variance": round(total_var, 1)
        }

    def compare_departure_times(
        self,
        route_id: str,
        shape_id: str,
        start_dist_m: float,
        end_dist_m: float,
        is_weekend: int = 0
    ) -> List[Dict[str, Any]]:
        """
        Compares predicted travel times for a corridor across key periods of the day.
        Directly satisfies the Problem 1 benchmark requirement.
        """
        test_hours = [
            (8, 30, "Morning Peak (08:30)"),
            (11, 0, "Midday Off-Peak (11:00)"),
            (14, 0, "Afternoon (14:00)"),
            (18, 30, "Evening Peak (18:30)"),
            (23, 0, "Late Night (23:00)")
        ]

        results = []
        for h, m, label in test_hours:
            dep_s = h * 3600 + m * 60
            pred = self.predict_leg_travel_time(
                route_id=route_id,
                shape_id=shape_id,
                start_dist_m=start_dist_m,
                end_dist_m=end_dist_m,
                departure_time_seconds=dep_s,
                is_weekend=is_weekend
            )
            results.append({
                "time_label": label,
                "hour": h,
                "minute": m,
                "duration_seconds": pred["total_travel_time_s"],
                "duration_minutes": round(pred["total_travel_time_s"] / 60.0, 1),
                "speed_kmh": round((pred["total_distance_m"] / max(pred["total_travel_time_s"], 1.0)) * 3.6, 1),
                "lower_bound_minutes": round(pred["lower_bound_s"] / 60.0, 1),
                "upper_bound_minutes": round(pred["upper_bound_s"] / 60.0, 1),
                "confidence": pred["confidence"],
                "provenance": pred["provenance"]
            })

        return results


# Global singleton prediction service
prediction_service = TravelTimePredictionService()
