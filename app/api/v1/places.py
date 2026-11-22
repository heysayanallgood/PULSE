"""
PULSE Places API Endpoints (app/api/v1/places.py)
"""
from fastapi import APIRouter, Query
from typing import Dict, Any

from app.services.places_service import places_service

router = APIRouter(prefix="/places", tags=["Places"])


@router.get("/autocomplete", response_model=Dict[str, Any])
async def autocomplete_places(
    q: str = Query(..., min_length=2, description="Place, address, stop name, or coordinates"),
    limit: int = Query(10, ge=1, le=20, description="Max results")
):
    """
    Returns search suggestions for places, addresses, landmarks, or bus stops in Delhi.
    Uses Geoapify if configured, with unified fallback to the 6,862 DTC GTFS stop index.
    """
    return await places_service.autocomplete(query=q, limit=limit)
