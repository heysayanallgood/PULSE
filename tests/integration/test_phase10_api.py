"""
Integration tests for Phase 10: Complete REST API Endpoints & Frontend Serving
"""
from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)

def test_frontend_serving():
    response = client.get("/")
    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]
    assert "PULSE" in response.text
    assert "HopCode" in response.text

def test_stops_search_api():
    response = client.get("/api/v1/stops/search?q=Kashmere&limit=5")
    assert response.status_code == 200
    data = response.json()
    assert len(data) > 0
    assert any("Kashmere" in s["stop_name"] for s in data)

def test_stops_nearby_api():
    response = client.get("/api/v1/stops/nearby?lat=28.6315&lon=77.2167&radius=1000&limit=5")
    assert response.status_code == 200
    data = response.json()
    assert len(data) > 0
    assert data[0]["distance_m"] <= 1000.0

def test_routes_api():
    response = client.get("/api/v1/routes?limit=5")
    assert response.status_code == 200
    data = response.json()
    assert len(data) > 0

    # Specific route 1728
    res_r = client.get("/api/v1/routes/1728")
    assert res_r.status_code == 200
    assert res_r.json()["route_id"] == "1728"

def test_journeys_api():
    response = client.get("/api/v1/journeys?from=Kashmere%20Gate&to=Nehru%20Place&depart_at=08:30:00")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "SUCCESS"
    assert len(data["options"]) > 0
    opt = data["options"][0]
    assert opt["total_duration_minutes"] > 0
    assert opt["in_vehicle_minutes"] > 0
    assert len(opt["legs"]) > 0

def test_analytics_time_comparison_api():
    response = client.get("/api/v1/analytics/time-comparison?route_id=1728&shape_id=shp_3_2436&from_dist=0&to_dist=15000")
    assert response.status_code == 200
    data = response.json()
    assert len(data) >= 5
    # Morning peak must have longer duration than late night!
    am_peak = next(c for c in data if c["hour"] == 8)
    night = next(c for c in data if c["hour"] == 23)
    assert am_peak["duration_minutes"] > night["duration_minutes"]

def test_validation_summary_api():
    response = client.get("/api/v1/validation/summary")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "VALIDATED"
    assert data["metrics"]["mae_pulse_minutes"] < data["metrics"]["mae_timetable_minutes"]
    assert len(data["benchmarks"]) >= 5

def test_vehicles_api():
    response = client.get("/api/v1/vehicles")
    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, list)
