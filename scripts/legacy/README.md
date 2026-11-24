# Superseded pipeline

The pandas prototype pipeline (process_day -> match_to_shapes -> measure_segments ->
train_travel_time_model, build_ground_truth, evaluate_model, build_headways) could not
hold a full day of GPS (~29M rows) in memory and never ran past 500k rows of day 1.
It is kept for reference only. Use `scripts/build_traffic_model.py` (see docs/TRAFFIC_MODEL.md).
