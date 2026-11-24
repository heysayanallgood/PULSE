"""
PULSE analytics endpoints (app/api/v1/analytics.py)
"""
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Query, status

from app.data.gtfs.repository import gtfs_repo
from app.services.prediction_service import prediction_service

router = APIRouter(prefix="/analytics", tags=["Analytics"])


@router.get("/congestion", response_model=Dict[str, Any])
def congestion_layer(
    hour: int = Query(8, ge=0, le=23, description="Hour of day (IST)"),
    is_weekend: int = Query(0, ge=0, le=1, description="0 weekday, 1 weekend/holiday"),
    bbox: Optional[str] = Query(None, description="south,west,north,east to clip the layer"),
):
    """
    Congestion index per road stretch for one hour of the day.
    congestion_index = expected travel time ÷ the stretch's own free-flow time.
    Features are compact arrays: [lat0, lon0, lat1, lon1, congestion_index, speed_kmh, measured].
    Only stretches with real GPS coverage are returned.
    """
    box = None
    if bbox:
        try:
            s, w, n, e = (float(x) for x in bbox.split(","))
            box = (s, w, n, e)
        except ValueError:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="bbox must be south,west,north,east")
    return prediction_service.congestion(hour, is_weekend, bbox=box)


@router.get("/model", response_model=Dict[str, Any])
def model_status():
    """Training provenance and coverage of the per-stretch traffic model."""
    return prediction_service.status()


@router.get("/time-comparison", response_model=List[Dict[str, Any]])
def compare_travel_times(
    route_id: str = Query(..., description="Route ID"),
    shape_id: Optional[str] = Query(None, description="Shape ID (defaults to the route's first shape)"),
    from_dist: float = Query(0.0, ge=0.0, description="Start distance along the shape in metres"),
    to_dist: Optional[float] = Query(None, ge=100.0, description="End distance in metres (default: whole shape)"),
    is_weekend: int = Query(0, ge=0, le=1, description="0 for weekday, 1 for weekend"),
):
    """Predicted travel time for one corridor at every hour of the day (departing hh:30)."""
    if not shape_id:
        trips = gtfs_repo.get_trips_for_route(route_id, limit=1)
        if not trips or not trips[0].get("shape_id"):
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"No shape for route '{route_id}'")
        shape_id = trips[0]["shape_id"]
    if to_dist is None:
        pts = gtfs_repo.get_shape_points(shape_id)
        to_dist = float(max((p.get("shape_dist_traveled") or 0.0) for p in pts)) if pts else 10000.0
    return prediction_service.compare_departure_times(
        route_id=route_id, shape_id=shape_id, start_dist_m=from_dist, end_dist_m=to_dist, is_weekend=is_weekend,
    )
