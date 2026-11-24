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
    assert len(data) == 24
    # Time of day must matter: the evening peak (17-20h) of this corridor is
    # slower than its early morning (05-06h). Values come from the trained model.
    by_hour = {c["hour"]: c["duration_minutes"] for c in data}
    if all(c["provenance"] != "UNTRAINED" for c in data):
        assert max(by_hour[h] for h in (17, 18, 19)) > min(by_hour[h] for h in (5, 6)) * 1.2

def test_validation_summary_api():
    response = client.get("/api/v1/validation/summary")
    assert response.status_code == 200
    data = response.json()
    # Results are computed by scripts/build_traffic_model.py evaluate; never hand-typed.
    assert data["status"] in ("OK", "NOT_RUN")
    if data["status"] == "OK":
        pulse = data["overall"]["pulse"]
        assert pulse["n"] > 0 and pulse["mae_min"] >= 0
        assert data["method"]["test_days"] and data["method"]["train_days"]
        assert not set(data["method"]["test_days"]) & set(data["method"]["train_days"])

def test_vehicles_api():
    response = client.get("/api/v1/vehicles")
    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, list)
