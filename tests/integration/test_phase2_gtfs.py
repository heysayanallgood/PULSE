"""
Integration tests for Phase 2: Static GTFS Network Ingestion & Repository
Validates real GTFS data in E:/Pulse/data/database/gtfs.duckdb.
"""
from app.data.gtfs.repository import gtfs_repo

def test_gtfs_network_counts():
    summary = gtfs_repo.get_network_summary()
    assert summary["stops"] == 6862
    assert summary["routes"] == 2574
    assert summary["trips"] == 80357
    assert summary["stop_times"] == 2737136
    assert summary["shapes"] == 965607

def test_stop_search():
    # Search for Kashmere Gate
    results = gtfs_repo.search_stops("Kashmere Gate", limit=5)
    assert len(results) > 0
    names = [s["stop_name"] for s in results]
    assert any("Kashmere Gate" in name for name in names)

    # Search for Nehru Place
    results_np = gtfs_repo.search_stops("Nehru Place", limit=5)
    assert len(results_np) > 0
    names_np = [s["stop_name"] for s in results_np]
    assert any("Nehru Place" in name for name in names_np)

def test_nearby_stops_spatial_search():
    # Connaught Place coordinates (lat: 28.6315, lon: 77.2167)
    nearby = gtfs_repo.find_nearby_stops(lat=28.6315, lon=77.2167, radius_m=1000.0, limit=5)
    assert len(nearby) > 0
    assert nearby[0]["distance_m"] <= nearby[-1]["distance_m"]
    # Check that distances are realistic (< 1000m)
    for s in nearby:
        assert s["distance_m"] <= 1000.0
        assert 28.3 <= s["stop_lat"] <= 28.9
        assert 76.8 <= s["stop_lon"] <= 77.5

def test_route_and_trip_retrieval():
    # Test route 1728 (227AUP)
    route = gtfs_repo.get_route_by_id("1728")
    assert route is not None
    assert route["route_short_name"] == "227AUP"
    assert route["agency_id"] == "DTC"

    # Test trips for route 1728
    trips = gtfs_repo.get_trips_for_route("1728", limit=10)
    assert len(trips) > 0
    trip_id = trips[0]["trip_id"]
    shape_id = trips[0]["shape_id"]
    assert "1728" in trip_id
    assert shape_id == "shp_3_2436"

    # Test stop sequence for this trip
    stop_seq = gtfs_repo.get_trip_stop_sequence(trip_id)
    assert len(stop_seq) > 5
    sequences = [s["stop_sequence"] for s in stop_seq]
    assert sequences == sorted(sequences), "Stop sequences must be strictly non-decreasing"

    # Test shape points for shape_id
    shape_points = gtfs_repo.get_shape_points(shape_id)
    assert len(shape_points) > 10
    for pt in shape_points:
        assert 28.3 <= pt["shape_pt_lat"] <= 28.9
        assert 76.8 <= pt["shape_pt_lon"] <= 77.5
