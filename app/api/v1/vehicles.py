"""
PULSE Live Vehicles API Endpoints (app/api/v1/vehicles.py)
"""
from fastapi import APIRouter, HTTPException, Query, status
from typing import List, Dict, Any, Optional

from app.core.config import settings
from app.services.realtime_service import realtime_service

router = APIRouter(prefix="/vehicles", tags=["Vehicles"])


@router.get("", response_model=List[Dict[str, Any]])
async def get_live_vehicles(
    route_id: Optional[str] = Query(None, description="Filter by route_id"),
    limit: int = Query(1500, ge=1, le=5000, description="Max vehicles to return"),
    fresh: bool = Query(False, description="Poll the feed first if the last poll is older than 10 s"),
):
    """
    Returns authentic active live vehicle positions from the Delhi OTD GTFS-RT feed.
    Each record includes vehicle_id, coordinates, speed, and freshness state.
    """
    if len(realtime_service.active_vehicles) == 0 and settings.LIVE_FEED_ENABLED and settings.OTD_API_KEY:
        await realtime_service.poll_once()
    elif fresh:
        await realtime_service.poll_if_older(10)

    return realtime_service.get_live_vehicles(route_id=route_id, max_count=limit)


@router.post("/refresh", response_model=Dict[str, Any])
async def refresh_live_feed():
    """Triggers an immediate on-demand poll of the live GTFS-RT feed."""
    parsed = await realtime_service.poll_once()
    health = realtime_service.get_feed_health()
    return {
        "status": "SUCCESS" if parsed > 0 else "NO_DATA",
        "parsed_count": parsed,
        "health": health
    }


@router.get("/health", response_model=Dict[str, Any])
def get_live_feed_health():
    """Returns live GTFS-RT feed connectivity, freshness counts, and polling statistics."""
    return realtime_service.get_feed_health()


@router.get("/{vehicle_id}", response_model=Dict[str, Any])
async def get_vehicle(vehicle_id: str, fresh: bool = Query(True, description="Poll the feed first if older than 8 s")):
    """One bus, as fresh as the feed allows (used to follow a bus on the map)."""
    if fresh:
        await realtime_service.poll_if_older(8)
    v = realtime_service.get_vehicle(vehicle_id)
    if not v:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Vehicle '{vehicle_id}' is not in the live feed")
    return v
