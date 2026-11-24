import sys
sys.path.insert(0, ".")
from app.services.journey_service import journey_service

def test_journey():
    print("=== Testing Journey Planner: Coordinates Kashmere Gate (28.6675, 77.2281) to Nehru Place (28.5492, 77.2526) ===")
    res = journey_service.plan_journey("28.6675, 77.2281", "28.5492, 77.2526", departure_time_str="08:30:00")
    print(f"Status: {res['status']} | Found {res['journey_options_count']} options")
    for opt in res["options"]:
        print(f"\nOption #{opt['option_id']}: Total {opt['total_duration_minutes']} min (In-Vehicle: {opt['in_vehicle_minutes']} min, Walk: {opt['walking_minutes']} min, Transfers: {opt['transfers']}) | Confidence: {opt['confidence']}")
        for leg in opt["legs"]:
            if leg["type"] == "BUS":
                print(f"  -> BUS {leg['route_name']}: {leg['boarding_stop']} to {leg['alighting_stop']} ({leg['predicted_duration_minutes']} min, {leg['distance_km']} km)")
            elif leg["type"] == "TRANSFER":
                print(f"  -> TRANSFER at {leg['transfer_stop']}: Buffer {leg['buffer_minutes']} min, Wait {leg['expected_wait_minutes']} min")
            elif leg["type"] == "WALK":
                print(f"  -> WALK: {leg['instruction']} ({leg['distance_m']}m, {leg['duration_minutes']} min)")

    if res.get("off_peak_comparison"):
        c = res["off_peak_comparison"]
        print(f"\n[Comparative Intelligence]: {c['insight']}")

if __name__ == "__main__":
    test_journey()
