"""
Integration tests for Phase 1: FastAPI Application Core & Diagnostic Endpoints
"""
from fastapi.testclient import TestClient
from app.main import app
from app.core.config import settings

client = TestClient(app)

def test_root_endpoint():
    response = client.get("/api")
    assert response.status_code == 200
    data = response.json()
    assert data["service"] == "PULSE"
    assert "HopCode" in data["team"]

def test_html_index_endpoint():
    response = client.get("/")
    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]
    assert "PULSE" in response.text

def test_health_endpoint():
    response = client.get("/api/v1/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "HEALTHY"
    assert "uptime_seconds" in data
    assert data["version"] == settings.APP_VERSION

def test_ready_endpoint():
    response = client.get("/api/v1/ready")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "READY"
    assert data["storage"]["drive"] == "E:"
    assert data["storage"]["free_gb"] > 50.0

def test_system_status_endpoint():
    response = client.get("/api/v1/system/status")
    assert response.status_code == 200
    data = response.json()
    assert data["storage"]["status"] == "HEALTHY"
    assert data["datasets"]["historical_sqlite"]["database_count"] == 31
    assert data["datasets"]["historical_sqlite"]["status"] == "READY"
    assert data["datasets"]["static_gtfs"]["status"] == "READY"
    # Ensure raw API key is never exposed
    assert data["live_feed"]["api_key_status"] != settings.OTD_API_KEY or settings.OTD_API_KEY is None

def test_data_sources_endpoint():
    response = client.get("/api/v1/data/sources")
    assert response.status_code == 200
    data = response.json()
    assert len(data["sources"]) >= 3
    ids = [s["id"] for s in data["sources"]]
    assert "delhi_dtc_historical_gps_2026_10" in ids
    assert "delhi_buses_static_gtfs_v1" in ids
    assert "delhi_otd_live_vehicle_positions" in ids
