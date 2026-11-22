"""
Tests for Advanced Map Experience, Citywide Search, Coordinates & Route Geometries
(tests/integration/test_advanced_map_search.py)
"""
import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.core.config import settings
from app.data.gtfs.repository import gtfs_repo
from app.services.journey_service import journey_service

client = TestClient(app)


def test_public_config_no_secret_leaks():
    """Verifies that /api/v1/config returns map keys but NEVER leaks OTD private API key."""
    response = client.get("/api/v1/config")
    assert response.status_code == 200
    data = response.json()
    assert "carto_api_key" in data
    assert "maptiler_api_key" in data
    assert "geoapify_enabled" in data
    assert "live_feed_enabled" in data
    # Critical invariant: private OTD key must never be exposed to frontend
    assert "otd_api_key" not in data
    assert "OTD_API_KEY" not in data


def test_places_autocomplete_stops():
    """Verifies citywide stop autocomplete across 6,862 GTFS stops."""
    response = client.get("/api/v1/places/autocomplete?q=AIIMS&limit=5")
    assert response.status_code == 200
    data = response.json()
    assert "suggestions" in data
    assert len(data["suggestions"]) > 0
    first = data["suggestions"][0]
    assert "stop_id" in first
    assert "lat" in first
    assert "lon" in first
    assert first["type"] == "STOP"
    assert "AIIMS" in first["name"].upper()


def test_places_autocomplete_coordinates():
    """Verifies arbitrary coordinate recognition and nearest-stop attachment."""
    response = client.get("/api/v1/places/autocomplete?q=28.6139,%2077.2090&limit=5")
    assert response.status_code == 200
    data = response.json()
    assert data["provider"] == "COORDINATE"
    first = data["suggestions"][0]
    assert first["type"] == "COORDINATE"
    assert round(first["lat"], 3) == 28.614
    assert round(first["lon"], 3) == 77.209
    assert first["is_valid_service_area"] is True


def test_stop_disambiguation():
    """Verifies that duplicate stop names are disambiguated with stop_id."""
    stops = gtfs_repo.search_stops("Kashmere", limit=5)
    assert len(stops) > 0
    for s in stops:
        assert "display_name" in s
        assert f"[{s['stop_id']}]" in s["display_name"]


def test_clipped_shape_geometry():
    """Verifies that GTFS shape points are clipped accurately along road corridors."""
    # Test on a known shape
    coords = gtfs_repo.get_clipped_shape_coordinates(
        shape_id="shp_3_1186",
        board_lat=28.6675,
        board_lon=28.2281,
        alight_lat=28.5492,
        alight_lon=77.2526
    )
    assert isinstance(coords, list)
    assert len(coords) >= 2
    # Ensure all items are [lat, lon] pairs
    for pt in coords:
        assert len(pt) == 2
        assert 28.0 <= pt[0] <= 29.5
        assert 76.5 <= pt[1] <= 78.0


def test_journey_with_coordinates_and_shape_geometry():
    """Verifies end-to-end journey planning with coordinate input and shape geometries."""
    # Central Delhi coordinate to South Delhi coordinate
    res = journey_service.plan_journey("28.6139, 77.2090", "28.5492, 77.2526", "08:30:00")
    assert res["status"] == "SUCCESS"
    assert len(res["options"]) > 0
    
    first_opt = res["options"][0]
    legs = first_opt["legs"]
    assert len(legs) >= 1
    
    # Check that bus leg contains real GTFS shape points
    bus_legs = [l for l in legs if l["type"] == "BUS"]
    assert len(bus_legs) >= 1
    for bl in bus_legs:
        assert "geometry" in bl
        assert len(bl["geometry"]) >= 2
        assert "boarding_lat" in bl
        assert "alighting_lat" in bl


def test_live_vehicles_fields():
    """Verifies live vehicle records include bearing, speed, and freshness."""
    response = client.get("/api/v1/vehicles?limit=10")
    assert response.status_code == 200
    vehicles = response.json()
    assert isinstance(vehicles, list)
    if vehicles:
        v = vehicles[0]
        assert "vehicle_id" in v
        assert "lat" in v
        assert "lon" in v
        assert "freshness" in v
        assert "bearing" in v
        assert "speed_kmh" in v
