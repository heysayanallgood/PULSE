"""
PULSE Analytics & Traffic Intelligence Endpoints (app/api/v1/analytics.py)
"""
from fastapi import APIRouter, Query, HTTPException, status
from typing import List, Dict, Any, Optional

from app.services.prediction_service import prediction_service

router = APIRouter(prefix="/analytics", tags=["Analytics"])


@router.get("/time-comparison", response_model=List[Dict[str, Any]])
def compare_travel_times(
    route_id: str = Query(..., description="Route ID"),
    shape_id: str = Query(..., description="Shape ID"),
    from_dist: float = Query(0.0, ge=0.0, description="Start distance in meters"),
    to_dist: float = Query(10000.0, ge=100.0, description="End distance in meters"),
    is_weekend: int = Query(0, ge=0, le=1, description="0 for weekday, 1 for weekend")
):
    """
    Compares travel times across key periods of the day for a route corridor:
    Morning Peak (08:30), Midday (11:00), Afternoon (14:00), Evening Peak (18:30), Late Night (23:00).
    """
    return prediction_service.compare_departure_times(
        route_id=route_id,
        shape_id=shape_id,
        start_dist_m=from_dist,
        end_dist_m=to_dist,
        is_weekend=is_weekend
    )
