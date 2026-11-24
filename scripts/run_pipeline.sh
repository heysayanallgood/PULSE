#!/usr/bin/env bash
# Runs the full PULSE traffic-model pipeline (plan.md phase 8).
# Each day is snapped in a fresh process: DuckDB slows down when one process
# attaches many 3 GB SQLite files in a row.
# Usage: PY=path/to/python scripts/run_pipeline.sh
set -u
cd "$(dirname "$0")/.."
PY="${PY:-python}"
export PYTHONIOENCODING=utf-8
mkdir -p logs
for d in $(seq 1 31); do
  "$PY" -u scripts/build_traffic_model.py snap --days "$d" --skip-existing >> logs/pipeline.log 2>&1 \
    || echo "[pipeline] snap day $d FAILED" >> logs/pipeline.log
done
echo "[pipeline] snap finished" >> logs/pipeline.log
"$PY" -u scripts/build_traffic_model.py train --train-days 1-24 >> logs/pipeline.log 2>&1 || echo "[pipeline] train FAILED" >> logs/pipeline.log
"$PY" -u scripts/build_traffic_model.py headways --train-days 1-24 >> logs/pipeline.log 2>&1 || echo "[pipeline] headways FAILED" >> logs/pipeline.log
"$PY" -u scripts/build_traffic_model.py evaluate --test-days 25-31 >> logs/pipeline.log 2>&1 || echo "[pipeline] evaluate FAILED" >> logs/pipeline.log
echo "[pipeline] DONE" >> logs/pipeline.log
