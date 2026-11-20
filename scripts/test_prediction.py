import sys
sys.path.insert(0, "E:/Pulse")
from app.services.prediction_service import prediction_service

def test_prediction():
    print("Testing Spatiotemporal Travel-Time Model on Route 1728 (shape shp_3_2436, 15 km corridor):")
    comps = prediction_service.compare_departure_times('1728', 'shp_3_2436', 0.0, 15000.0, is_weekend=0)
    for c in comps:
        print(f"  {c['time_label']:26s}: {c['duration_minutes']:5.1f} min ({c['speed_kmh']:4.1f} km/h) | Bounds: {c['lower_bound_minutes']} - {c['upper_bound_minutes']} min | {c['provenance']}")

if __name__ == "__main__":
    test_prediction()
