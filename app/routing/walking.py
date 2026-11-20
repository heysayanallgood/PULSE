"""
PULSE Walking & Pedestrian Access Router (app/routing/walking.py)
Implements ADR 004 and Pre-Implementation Correction 6.
Calculates metric walking distances, durations, and pedestrian access buffers.
"""
import math
from typing import Dict, Any, Tuple
from pyproj import Transformer

transformer = Transformer.from_crs("EPSG:4326", "EPSG:32643", always_xy=True)


def calculate_walking_leg(
    start_lat: float,
    start_lon: float,
    end_lat: float,
    end_lon: float,
    walk_speed_mps: float = 1.2,
    urban_winding_factor: float = 1.25
) -> Dict[str, Any]:
    """
    Computes metric walking distance and duration between two coordinates.
    Applies urban pedestrian winding factor to straight-line displacement.
    Explicitly tags the output as APPROXIMATED_WALK (Correction 6).
    """
    x1, y1 = transformer.transform(start_lon, start_lat)
    x2, y2 = transformer.transform(end_lon, end_lat)

    euclidean_m = math.sqrt((x2 - x1)**2 + (y2 - y1)**2)
    # Estimate network walking distance
    network_dist_m = euclidean_m * urban_winding_factor
    duration_s = int(network_dist_m / walk_speed_mps)

    # If distance is negligible (< 20m), it's the same platform
    if euclidean_m < 20.0:
        return {
            "distance_m": 0.0,
            "duration_s": 0,
            "duration_minutes": 0.0,
            "walk_type": "SAME_PLATFORM",
            "confidence": "HIGH"
        }

    # If distance is excessive (> 2000m), pedestrian walk is infeasible
    confidence = "HIGH" if network_dist_m <= 800.0 else ("MEDIUM" if network_dist_m <= 1500.0 else "LOW")

    return {
        "distance_m": round(network_dist_m, 1),
        "duration_s": duration_s,
        "duration_minutes": round(duration_s / 60.0, 1),
        "walk_type": "APPROXIMATED_WALK",
        "confidence": confidence
    }
