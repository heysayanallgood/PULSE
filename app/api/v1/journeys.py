"""
PULSE Journeys API Endpoints (app/api/v1/journeys.py)
"""
from fastapi import APIRouter, Query, HTTPException, status, Body
from typing import Dict, Any, Optional
from pydantic import BaseModel, Field

from app.services.journey_service import journey_service

router = APIRouter(prefix="/journeys", tags=["Journeys"])


class JourneyRequest(BaseModel):
    origin: str = Field(..., description="Stop name or coordinates (lat, lon)")
    destination: str = Field(..., description="Stop name or coordinates (lat, lon)")
    departure_time: Optional[str] = Field(None, description="Departure time HH:MM:SS")
    date: Optional[str] = Field(None, description="Departure date YYYY-MM-DD")


@router.get("", response_model=Dict[str, Any])
def plan_journey_get(
    origin: str = Query(..., alias="from", description="Origin stop name or lat,lon coordinates"),
    destination: str = Query(..., alias="to", description="Destination stop name or lat,lon coordinates"),
    depart_at: Optional[str] = Query(None, description="Departure time in HH:MM:SS (e.g. 08:30:00)"),
    date: Optional[str] = Query(None, description="Departure date in YYYY-MM-DD")
):
    """
    Computes Pareto-optimal bus journey options between origin and destination.
    In-vehicle travel times are predicted by the PULSE Spatiotemporal Traffic Model.
    """
    res = journey_service.plan_journey(
        origin=origin,
        destination=destination,
        departure_time_str=depart_at,
        date_str=date
    )
    if res["status"] == "NO_STOPS_FOUND":
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=res["error"])
    return res


@router.post("", response_model=Dict[str, Any])
def plan_journey_post(request: JourneyRequest = Body(...)):
    """Computes bus journey options via JSON POST body."""
    res = journey_service.plan_journey(
        origin=request.origin,
        destination=request.destination,
        departure_time_str=request.departure_time,
        date_str=request.date
    )
    if res["status"] == "NO_STOPS_FOUND":
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=res["error"])
    return res
