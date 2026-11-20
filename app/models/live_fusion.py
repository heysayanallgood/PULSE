"""
PULSE Live/Historical Bayesian Fusion Engine (app/models/live_fusion.py)
Implements ADR 005 and Pre-Implementation Correction 1.
Computes precision-weighted fused travel times with positive variance floor
and strict freshness state machine.
"""
from typing import Dict, Any, Optional
import math


def fuse_live_and_historical(
    t_live: float,
    var_live: float,
    vehicle_age_seconds: Optional[float],
    n_live_vehicles: int,
    t_hist: float,
    var_hist: float,
    n_hist_trips: int,
    stale_threshold_seconds: float = 90.0,
    variance_floor: float = 4.0
) -> Dict[str, Any]:
    """
    Fuses live-derived segment travel time with historical spatiotemporal prior.
    
    Formula (Correction 1):
        w_live = (q_live / V_live) / ((q_live / V_live) + (q_hist / V_hist))
        T_fused = w_live * T_live + (1 - w_live) * T_hist
    """
    # 1. Freshness State Machine (Correction 2)
    if vehicle_age_seconds is None or n_live_vehicles <= 0 or t_live <= 0:
        freshness = "UNAVAILABLE"
    elif vehicle_age_seconds <= 60.0:
        freshness = "FRESH"
    elif vehicle_age_seconds <= stale_threshold_seconds:
        freshness = "AGING"
    else:
        freshness = "STALE"

    # If stale or unavailable, live weight drops to 0.0 (ADR 005)
    if freshness in ("STALE", "UNAVAILABLE"):
        return {
            "estimated_travel_time_s": round(t_hist, 1),
            "weight_live": 0.0,
            "provenance": "HISTORICAL",
            "freshness_state": freshness,
            "variance": round(max(var_hist, variance_floor), 2)
        }

    # 2. Positive Variance Floor Enforcement (Correction 1)
    v_live = max(var_live, variance_floor)
    v_hist = max(var_hist, variance_floor)

    # 3. Evidence Quality Functions
    # q_live scaled by distinct physical live buses; q_hist by independent historical trips
    q_live = min(1.0, n_live_vehicles / 3.0)
    q_hist = min(1.0, n_hist_trips / 30.0)

    # 4. Precision-Weighted Fusion
    prec_live = q_live / v_live
    prec_hist = q_hist / v_hist

    total_prec = prec_live + prec_hist
    if total_prec <= 0:
        w_live = 0.0
    else:
        w_live = prec_live / total_prec

    t_fused = w_live * t_live + (1.0 - w_live) * t_hist
    
    # Fused variance (inverse total precision)
    fused_var = max(variance_floor, 1.0 / max(total_prec, 0.001))

    provenance = "LIVE + HISTORICAL" if w_live > 0.05 else "HISTORICAL"

    return {
        "estimated_travel_time_s": round(t_fused, 1),
        "weight_live": round(w_live, 4),
        "provenance": provenance,
        "freshness_state": freshness,
        "variance": round(fused_var, 2)
    }
