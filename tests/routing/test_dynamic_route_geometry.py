"""
Tests for Dynamic Journey Geometry & Landmark Resolution (tests/routing/test_dynamic_route_geometry.py)
Validates the 6 required test scenarios, geometry clipping, and error contracts.
"""
import pytest
from fastapi.testclient import TestClient
import math

from app.main import app
from app.services.journey_service import journey_service

client = TestClient(app)


def haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Computes great-circle distance in meters between two lat/lon pairs."""
    r = 6371000.0
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2.0) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2.0) ** 2
    c = 2.0 * math.atan2(math.sqrt(a), math.sqrt(1.0 - a))
    return r * c


def test_corridor_1_anand_vihar_to_nehru_place():
    """Scenario 1: Anand Vihar ISBT -> Nehru Place."""
    res = journey_service.plan_journey("Anand Vihar ISBT", "Nehru Place", "08:30:00")
    assert res["status"] == "SUCCESS"
    assert len(res["options"]) > 0
    first = res["options"][0]
    assert "journey_id" in first
    assert "legs" in first
    
    bus_legs = [l for l in first["legs"] if l["type"] == "BUS"]
    assert len(bus_legs) >= 1
    for b in bus_legs:
        assert len(b["geometry"]) >= 2
        # Check start & end close to boarding & alighting stops
        dist_start = haversine_m(b["boarding_lat"], b["boarding_lon"], b["geometry"][0][0], b["geometry"][0][1])
        dist_end = haversine_m(b["alighting_lat"], b["alighting_lon"], b["geometry"][-1][0], b["geometry"][-1][1])
        assert dist_start <= 400.0
        assert dist_end <= 400.0


def test_corridor_2_anand_vihar_to_badarpur_border():
    """Scenario 2: Anand Vihar ISBT -> Badarpur Border."""
    res = journey_service.plan_journey("Anand Vihar ISBT", "Badarpur Border", "08:30:00")
    assert res["status"] == "SUCCESS"
    assert len(res["options"]) > 0
    first = res["options"][0]
    assert "journey_id" in first


def test_geometry_distinction_anand_vihar_destinations():
    """Verifies that Anand Vihar -> Nehru Place and Anand Vihar -> Badarpur produce completely distinct alighting coordinates."""
    res_np = journey_service.plan_journey("Anand Vihar ISBT", "Nehru Place", "08:30:00")
    res_bb = journey_service.plan_journey("Anand Vihar ISBT", "Badarpur Border", "08:30:00")
    
    opt_np = res_np["options"][0]
    opt_bb = res_bb["options"][0]
    
    last_bus_np = [l for l in opt_np["legs"] if l["type"] == "BUS"][-1]
    last_bus_bb = [l for l in opt_bb["legs"] if l["type"] == "BUS"][-1]
    
    # Alighting coordinates must be far apart (Nehru Place vs Badarpur Border is > 6 km apart)
    dist_alight = haversine_m(
        last_bus_np["alighting_lat"], last_bus_np["alighting_lon"],
        last_bus_bb["alighting_lat"], last_bus_bb["alighting_lon"]
    )
    assert dist_alight > 4000.0  # At least 4 km distinct alighting coordinates
    
    # Shape points must differ significantly
    assert opt_np["legs"][-1]["geometry"][-1] != opt_bb["legs"][-1]["geometry"][-1]


def test_corridor_3_kashmere_gate_to_nehru_place():
    """Scenario 3: Kashmere Gate -> Nehru Place."""
    res = journey_service.plan_journey("Kashmere Gate", "Nehru Place", "08:30:00")
    assert res["status"] == "SUCCESS"
    assert len(res["options"]) > 0
    first = res["options"][0]
    assert first["total_duration_minutes"] > 0


def test_corridor_4_india_gate_to_nehru_place():
    """Scenario 4: India Gate (Landmark Resolution) -> Nehru Place."""
    res = journey_service.plan_journey("India Gate", "Nehru Place", "08:30:00")
    assert res["status"] == "SUCCESS"
    assert len(res["options"]) > 0
    first = res["options"][0]
    # Landmark origin should have a walking access leg from India Gate coords
    walk_legs = [l for l in first["legs"] if l["type"] == "WALK"]
    assert len(walk_legs) >= 1
    # Check that India Gate walking leg starts near (28.6129, 77.2295)
    first_walk = walk_legs[0]
    dist_india_gate = haversine_m(28.6129, 77.2295, first_walk["geometry"][0][0], first_walk["geometry"][0][1])
    assert dist_india_gate <= 50.0  # Exactly at India Gate landmark coordinates


def test_corridor_5_connaught_place_to_aiims():
    """Scenario 5: Connaught Place -> AIIMS."""
    res = journey_service.plan_journey("Connaught Place", "AIIMS", "08:30:00")
    assert res["status"] == "SUCCESS"
    assert len(res["options"]) > 0
    first = res["options"][0]
    assert first["total_duration_minutes"] > 0


def test_corridor_6_anand_vihar_to_dhaula_kuan():
    """Scenario 6: Anand Vihar ISBT -> Dhaula Kuan."""
    res = journey_service.plan_journey("Anand Vihar ISBT", "Dhaula Kuan", "08:30:00")
    assert res["status"] == "SUCCESS"
    assert len(res["options"]) > 0


def test_journey_api_standardized_json_error():
    """Verifies that an unresolvable stop returns standardized JSON error and NOT plain text."""
    response = client.get("/api/v1/journeys?from=UnknownNonexistentPlaceXYZ123&to=Nehru%20Place")
    assert response.status_code == 404
    assert response.headers["content-type"].startswith("application/json")
    data = response.json()
    assert "error" in data
    assert data["error"]["status_code"] == 404
    assert "request_id" in data["error"]
    assert "UnknownNonexistentPlaceXYZ123" in data["error"]["message"]
