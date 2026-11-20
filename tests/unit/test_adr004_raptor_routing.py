"""
Unit tests for ADR 004: Multi-Criteria RAPTOR Transit Routing Engine
Tests Pareto dominance rules, multi-criteria journey label, GTFS >24:00:00 time parsing,
and transfer/walking realism (Correction 6).
"""
from dataclasses import dataclass
from typing import Optional, List

@dataclass
class JourneyLabel:
    arrival_time_s: int       # Criterion 1: Predicted arrival time
    transfers: int            # Criterion 2: Number of transfers (0, 1, 2)
    walking_duration_s: int   # Criterion 3: Total walking duration
    in_vehicle_duration_s: int
    waiting_duration_s: int
    confidence: str
    provenance: str

def dominates(a: JourneyLabel, b: JourneyLabel) -> bool:
    less_or_equal = (
        a.arrival_time_s <= b.arrival_time_s and
        a.transfers <= b.transfers and
        a.walking_duration_s <= b.walking_duration_s
    )
    strictly_better = (
        a.arrival_time_s < b.arrival_time_s or
        a.transfers < b.transfers or
        a.walking_duration_s < b.walking_duration_s
    )
    return less_or_equal and strictly_better

def parse_gtfs_time_to_seconds(gtfs_time_str: str) -> int:
    parts = [int(p) for p in gtfs_time_str.strip().split(":")]
    return parts[0] * 3600 + parts[1] * 60 + parts[2]

def calculate_transfer_feasibility(arrival_at_stop_s: int, next_service_departure_s: int,
                                   stop_a: str, stop_b: str, inter_stop_distance_m: float = 0.0,
                                   base_buffer_s: int = 180, walk_speed_mps: float = 1.2) -> dict:
    """
    Validates Correction 6:
    Realistic transfer evaluation with walking and buffers.
    """
    if stop_a == stop_b:
        required_buffer = base_buffer_s  # Default 3 mins (180s)
        walk_time_s = 0
        walk_type = "SAME_PLATFORM"
    else:
        walk_time_s = int(inter_stop_distance_m / walk_speed_mps)
        required_buffer = walk_time_s + 120  # Inter-stop walk + 2 min interchange buffer
        walk_type = "APPROXIMATED_WALK"
        
    available_time = next_service_departure_s - arrival_at_stop_s
    feasible = available_time >= required_buffer
    
    return {
        "is_feasible": feasible,
        "available_time_s": available_time,
        "required_buffer_s": required_buffer,
        "walk_time_s": walk_time_s,
        "walk_type": walk_type
    }

def test_pareto_dominance():
    j1 = JourneyLabel(arrival_time_s=3600, transfers=0, walking_duration_s=600, in_vehicle_duration_s=2400, waiting_duration_s=600, confidence="HIGH", provenance="HISTORICAL")
    j2 = JourneyLabel(arrival_time_s=4200, transfers=1, walking_duration_s=900, in_vehicle_duration_s=2500, waiting_duration_s=800, confidence="HIGH", provenance="HISTORICAL")
    assert dominates(j1, j2) is True
    assert dominates(j2, j1) is False
    
    j3 = JourneyLabel(arrival_time_s=3000, transfers=1, walking_duration_s=600, in_vehicle_duration_s=1800, waiting_duration_s=600, confidence="HIGH", provenance="HISTORICAL")
    assert dominates(j1, j3) is False
    assert dominates(j3, j1) is False

def test_gtfs_midnight_time_parsing():
    assert parse_gtfs_time_to_seconds("08:30:00") == 8 * 3600 + 30 * 60
    assert parse_gtfs_time_to_seconds("23:59:59") == 86399
    assert parse_gtfs_time_to_seconds("25:15:00") == 25 * 3600 + 15 * 60
    assert parse_gtfs_time_to_seconds("25:15:00") > parse_gtfs_time_to_seconds("23:59:59")

def test_transfer_realism_same_and_different_stops():
    # Same stop transfer: needs 180s buffer
    res_same = calculate_transfer_feasibility(arrival_at_stop_s=1000, next_service_departure_s=1200, stop_a="Stop1", stop_b="Stop1")
    assert res_same["is_feasible"] is True
    assert res_same["walk_type"] == "SAME_PLATFORM"

    # Same stop transfer with only 60s available -> Infeasible!
    res_same_tight = calculate_transfer_feasibility(arrival_at_stop_s=1000, next_service_departure_s=1060, stop_a="Stop1", stop_b="Stop1")
    assert res_same_tight["is_feasible"] is False

    # Different stop transfer (200m apart): walk time ~166s + 120s buffer = 286s required
    res_diff = calculate_transfer_feasibility(arrival_at_stop_s=1000, next_service_departure_s=1350, stop_a="Stop1", stop_b="Stop2", inter_stop_distance_m=200.0)
    assert res_diff["is_feasible"] is True
    assert res_diff["walk_type"] == "APPROXIMATED_WALK"
    assert res_diff["walk_time_s"] == 166
