"""
PULSE Routes API Endpoints (app/api/v1/routes.py)
"""
from fastapi import APIRouter, Query, HTTPException, status
from typing import List, Dict, Any, Optional

from app.data.gtfs.repository import gtfs_repo

router = APIRouter(prefix="/routes", tags=["Routes"])


@router.get("", response_model=List[Dict[str, Any]])
def list_routes(
    limit: int = Query(50, ge=1, le=200, description="Max routes to return"),
    agency: Optional[str] = Query(None, description="Filter by agency (DTC or DIMTS)")
):
    """Lists bus routes with optional agency filter."""
    return gtfs_repo.list_routes(limit=limit, agency_id=agency)


@router.get("/{route_id}", response_model=Dict[str, Any])
def get_route(route_id: str):
    """Retrieves route metadata by route_id."""
    r = gtfs_repo.get_route_by_id(route_id)
    if not r:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Route with ID '{route_id}' not found"
        )
    return r


@router.get("/{route_id}/trips", response_model=List[Dict[str, Any]])
def get_route_trips(
    route_id: str,
    limit: int = Query(20, ge=1, le=100)
):
    """Retrieves scheduled trips associated with route_id."""
    return gtfs_repo.get_trips_for_route(route_id, limit=limit)


@router.get("/{route_id}/shape", response_model=List[Dict[str, Any]])
def get_route_shape(route_id: str):
    """Retrieves the physical shape points (lat/lon) for the primary trip of route_id."""
    trips = gtfs_repo.get_trips_for_route(route_id, limit=1)
    if not trips or not trips[0].get("shape_id"):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No shape geometry found for route '{route_id}'"
        )
    shape_id = trips[0]["shape_id"]
    pts = gtfs_repo.get_shape_points(shape_id)
    return pts
