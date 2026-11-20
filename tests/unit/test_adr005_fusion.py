"""
Unit tests for ADR 005: Live & Historical Precision-Weighted Bayesian Fusion
Validates consecutive vehicle movement, variance-weighted fusion with floor,
freshness decay (Fresh <= 60s, Aging <= 90s, Stale > 90s), and fail-safe historical fallback.
"""
import math

def calculate_consecutive_movement_speed(dist_start_m: float, dist_end_m: float, t_start_s: int, t_end_s: int) -> float:
    delta_t = t_end_s - t_start_s
    if delta_t <= 0 or delta_t > 120:
        raise ValueError("Invalid time delta for consecutive observation")
    delta_d = dist_end_m - dist_start_m
    if delta_d < 0:
        raise ValueError("Negative distance progression along shape")
    return delta_d / delta_t

def compute_bayesian_fusion(t_live: float, var_live: float, age_s: float, n_live_veh: int,
                            t_hist: float, var_hist: float, n_hist_trips: int,
                            stale_cutoff_s: float = 90.0) -> dict:
    """
    Computes precision-weighted fused travel time and data provenance.
    Formula:
        w_live = (q_live / V_live) / ((q_live / V_live) + (q_hist / V_hist))
        T_fused = w_live * T_live + (1 - w_live) * T_hist
    """
    # Freshness state machine (Correction 2)
    if age_s is None or n_live_veh <= 0:
        freshness = "UNAVAILABLE"
    elif age_s <= 60.0:
        freshness = "FRESH"
    elif age_s <= stale_cutoff_s:
        freshness = "AGING"
    else:
        freshness = "STALE"

    if freshness in ("STALE", "UNAVAILABLE"):
        return {
            "fused_travel_time": t_hist,
            "weight_live": 0.0,
            "provenance": "HISTORICAL",
            "freshness_state": freshness
        }

    # Variance floor enforcement (Correction 1)
    variance_floor = 4.0  # seconds squared
    v_live = max(var_live, variance_floor)
    v_hist = max(var_hist, variance_floor)

    # Configurable evidence quality functions
    # q_live based on distinct physical vehicles; q_hist based on independent historical trips
    q_live = min(1.0, n_live_veh / 3.0)
    q_hist = min(1.0, n_hist_trips / 30.0)

    # Precision-weighted fusion
    prec_live = q_live / v_live
    prec_hist = q_hist / v_hist

    if (prec_live + prec_hist) <= 0:
        w_live = 0.0
    else:
        w_live = prec_live / (prec_live + prec_hist)

    t_fused = w_live * t_live + (1.0 - w_live) * t_hist
    provenance = "LIVE + HISTORICAL" if w_live > 0.05 else "HISTORICAL"

    return {
        "fused_travel_time": round(t_fused, 2),
        "weight_live": round(w_live, 4),
        "provenance": provenance,
        "freshness_state": freshness
    }

def test_consecutive_vehicle_speed():
    # Bus travels 300 meters in 30 seconds
    speed = calculate_consecutive_movement_speed(100.0, 400.0, 1000, 1030)
    assert speed == 10.0  # 10 m/s = 36 km/h

def test_fresh_live_fusion():
    # Fresh observation (age 25s <= 60s), low live variance
    res = compute_bayesian_fusion(
        t_live=120.0, var_live=16.0, age_s=25.0, n_live_veh=2,
        t_hist=180.0, var_hist=64.0, n_hist_trips=40
    )
    assert res["freshness_state"] == "FRESH"
    assert res["provenance"] == "LIVE + HISTORICAL"
    assert res["weight_live"] > 0.5
    assert 120.0 < res["fused_travel_time"] < 180.0

def test_aging_live_fusion():
    # Aging observation (age 75s, between 60s and 90s)
    res = compute_bayesian_fusion(
        t_live=120.0, var_live=16.0, age_s=75.0, n_live_veh=2,
        t_hist=180.0, var_hist=64.0, n_hist_trips=40
    )
    assert res["freshness_state"] == "AGING"
    assert res["provenance"] == "LIVE + HISTORICAL"

def test_stale_live_fusion_cutoff():
    # Stale observation (age 95s > 90s cutoff) -> Must drop live weight to 0.0
    res = compute_bayesian_fusion(
        t_live=120.0, var_live=16.0, age_s=95.0, n_live_veh=2,
        t_hist=180.0, var_hist=64.0, n_hist_trips=40
    )
    assert res["freshness_state"] == "STALE"
    assert res["weight_live"] == 0.0
    assert res["provenance"] == "HISTORICAL"
    assert res["fused_travel_time"] == 180.0

def test_variance_floor_enforcement():
    # Extreme zero variance reported in live feed -> Variance floor (4.0) prevents div by zero
    res = compute_bayesian_fusion(
        t_live=100.0, var_live=0.0, age_s=30.0, n_live_veh=1,
        t_hist=150.0, var_hist=0.0, n_hist_trips=5
    )
    assert res["freshness_state"] == "FRESH"
    assert res["weight_live"] > 0.0
    assert 100.0 <= res["fused_travel_time"] <= 150.0
