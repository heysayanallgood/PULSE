"""
PULSE validation endpoints (app/api/v1/validation.py)

Serves results computed by `scripts/build_traffic_model.py evaluate`
(data/validation/results.json) and, when present, the Google Routes benchmark
from `scripts/compare_google.py` (data/validation/google_comparison.json).
Nothing here is typed by hand: with no files the endpoint says NOT_RUN.
"""
import json
from typing import Any, Dict

from fastapi import APIRouter

from app.core.config import settings

router = APIRouter(prefix="/validation", tags=["Validation"])

VALID_DIR = settings.DATA_ROOT / "validation"


def _read(name: str):
    f = VALID_DIR / name
    if not f.exists():
        return None
    with open(f, "r", encoding="utf-8") as fh:
        return json.load(fh)


@router.get("/summary", response_model=Dict[str, Any])
def get_validation_summary():
    """Held-out accuracy of the traffic model plus the Google Maps benchmark, if run."""
    try:
        data = _read("results.json")
    except Exception as e:
        return {"status": "ERROR", "message": f"Could not read results file: {e}"}
    if data is None:
        return {"status": "NOT_RUN", "message": "Run scripts/build_traffic_model.py all to generate validation results."}
    try:
        google = _read("google_comparison.json")
    except Exception:
        google = None
    if google:
        data["google"] = {k: v for k, v in google.items() if k != "rows"}
    return data
