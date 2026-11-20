"""
PULSE Live Vehicles API Endpoints (app/api/v1/vehicles.py)
"""
from fastapi import APIRouter, Query
from typing import List, Dict, Any, Optional

from app.services.realtime_service import realtime_service

router = APIRouter(prefix="/vehicles", tags=["Vehicles"])


@router.get("", response_model=List[Dict[str, Any]])
def get_live_vehicles(
    route_id: Optional[str] = Query(None, description="Filter by route_id"),
    limit: int = Query(100, ge=1, le=500, description="Max vehicles to return")
):
    """
    Returns authentic active live vehicle positions from the Delhi OTD GTFS-RT feed.
    Each record includes vehicle_id, coordinates, speed, and freshness state.
    """
    return realtime_service.get_live_vehicles(route_id=route_id, max_count=limit)


@router.get("/health", response_model=Dict[str, Any])
def get_live_feed_health():
    """Returns live GTFS-RT feed connectivity, freshness counts, and polling statistics."""
    return realtime_service.get_feed_health()
