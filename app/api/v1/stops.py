"""
PULSE Stops API Endpoints (app/api/v1/stops.py)
"""
from fastapi import APIRouter, Query, HTTPException, status
from typing import List, Dict, Any, Optional

from app.data.gtfs.repository import gtfs_repo

router = APIRouter(prefix="/stops", tags=["Stops"])


@router.get("/search", response_model=List[Dict[str, Any]])
def search_stops(
    q: str = Query(..., min_length=1, description="Stop name substring or stop_id"),
    limit: int = Query(10, ge=1, le=50, description="Max results")
):
    """Searches bus stops by name or identifier."""
    results = gtfs_repo.search_stops(q, limit=limit)
    return results


@router.get("/nearby", response_model=List[Dict[str, Any]])
def get_nearby_stops(
    lat: float = Query(..., ge=28.0, le=29.5, description="WGS84 Latitude"),
    lon: float = Query(..., ge=76.5, le=77.8, description="WGS84 Longitude"),
    radius: float = Query(1000.0, ge=100.0, le=5000.0, description="Search radius in meters"),
    limit: int = Query(5, ge=1, le=20, description="Max results")
):
    """Finds nearest bus stops to coordinates within search radius using KD-Tree."""
    return gtfs_repo.find_nearby_stops(lat, lon, radius_m=radius, limit=limit)


@router.get("/{stop_id}", response_model=Dict[str, Any])
def get_stop_by_id(stop_id: str):
    """Retrieves stop details by stop_id."""
    stop = gtfs_repo.get_stop_by_id(stop_id)
    if not stop:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Stop with ID '{stop_id}' not found"
        )
    return stop
