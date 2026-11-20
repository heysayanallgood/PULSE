"""
PULSE Live GTFS-RT Feed Client & Vehicle State Tracker (app/services/realtime_service.py)
Implements ADR 005 and Pre-Implementation Correction 2.
Decodes Google Protocol Buffers vehicle positions from Delhi Open Transit Data (OTD),
tracks consecutive observation displacement, calculates real-time corridor velocity,
and safely manages credential privacy and fail-safe historical fallback.
"""
import time
import asyncio
from datetime import datetime, timezone
from typing import Dict, Any, List, Optional, Tuple
from collections import defaultdict
import httpx
from google.transit import gtfs_realtime_pb2

from app.core.config import settings
from app.core.logging import logger
from app.models.live_fusion import fuse_live_and_historical


class LiveVehiclePosition:
    def __init__(
        self,
        vehicle_id: str,
        lat: float,
        lon: float,
        timestamp: int,
        route_id: Optional[str] = None,
        trip_id: Optional[str] = None,
        speed_mps: Optional[float] = None,
        bearing: Optional[float] = None
    ):
        self.vehicle_id = vehicle_id
        self.lat = lat
        self.lon = lon
        self.timestamp = timestamp
        self.route_id = route_id
        self.trip_id = trip_id
        self.speed_mps = speed_mps
        self.bearing = bearing
        self.received_at = time.time()

    @property
    def age_seconds(self) -> float:
        """Evaluates observation age from the vehicle timestamp (Correction 2)."""
        now_epoch = time.time()
        # Some feeds use local or UTC timestamps
        if self.timestamp > 0 and abs(now_epoch - self.timestamp) < 86400:
            return max(0.0, now_epoch - self.timestamp)
        return max(0.0, now_epoch - self.received_at)

    @property
    def freshness_state(self) -> str:
        age = self.age_seconds
        if age <= 60.0:
            return "FRESH"
        elif age <= settings.LIVE_MAX_STALENESS_SECONDS:
            return "AGING"
        return "STALE"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "vehicle_id": self.vehicle_id,
            "route_id": self.route_id,
            "trip_id": self.trip_id,
            "lat": round(self.lat, 6),
            "lon": round(self.lon, 6),
            "speed_kmh": round(self.speed_mps * 3.6, 1) if self.speed_mps is not None else None,
            "bearing": self.bearing,
            "timestamp": self.timestamp,
            "age_seconds": round(self.age_seconds, 1),
            "freshness": self.freshness_state
        }


class RealtimeFeedService:
    """Manages background polling, vehicle position decoding, and velocity tracking."""

    def __init__(self):
        self.active_vehicles: Dict[str, LiveVehiclePosition] = {}
        # Stores previous ping for consecutive movement calculation (vehicle_id -> LiveVehiclePosition)
        self.previous_pings: Dict[str, LiveVehiclePosition] = {}
        # Derived live velocities by route (route_id -> list of observed velocities m/s)
        self.route_live_speeds: Dict[str, List[float]] = defaultdict(list)
        
        self.last_poll_time: Optional[float] = None
        self.last_poll_status: str = "INITIALIZED"
        self.last_feed_timestamp: Optional[int] = None
        self.total_polls_succeeded: int = 0
        self.total_polls_failed: int = 0
        self.last_error: Optional[str] = None
        self._poll_task: Optional[asyncio.Task] = None

    async def fetch_feed_data(self) -> Optional[bytes]:
        """Performs authenticated HTTP request to Delhi OTD endpoint."""
        if not settings.LIVE_FEED_ENABLED or not settings.OTD_API_KEY:
            self.last_poll_status = "DISABLED_NO_CREDENTIALS"
            return None

        url = settings.OTD_VEHICLE_POSITIONS_URL
        params = {settings.OTD_API_KEY_PARAM: settings.OTD_API_KEY}

        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.get(url, params=params)
                if resp.status_code == 200:
                    return resp.content
                else:
                    self.last_error = f"HTTP {resp.status_code}"
                    self.last_poll_status = f"HTTP_ERROR_{resp.status_code}"
                    self.total_polls_failed += 1
                    logger.warning(f"Live feed returned status {resp.status_code}")
                    return None
        except Exception as e:
            self.last_error = str(e)
            self.last_poll_status = "CONNECTION_FAILED"
            self.total_polls_failed += 1
            logger.warning(f"Failed to poll live feed: {e}")
            return None

    def parse_protobuf_feed(self, pb_bytes: bytes) -> int:
        """Decodes GTFS-RT Protobuf payload and updates vehicle state."""
        feed = gtfs_realtime_pb2.FeedMessage()
        try:
            feed.ParseFromString(pb_bytes)
        except Exception as e:
            self.last_error = f"Protobuf decode error: {e}"
            self.last_poll_status = "PROTOBUF_DECODE_ERROR"
            self.total_polls_failed += 1
            logger.error(self.last_error)
            return 0

        self.last_feed_timestamp = feed.header.timestamp
        parsed_count = 0

        for entity in feed.entity:
            if entity.HasField("vehicle"):
                v = entity.vehicle
                vid = v.vehicle.id if v.HasField("vehicle") and v.vehicle.id else entity.id
                lat = v.position.latitude
                lon = v.position.longitude
                ts = v.timestamp if v.timestamp > 0 else feed.header.timestamp
                
                route_id = v.trip.route_id if v.HasField("trip") and v.trip.route_id else None
                trip_id = v.trip.trip_id if v.HasField("trip") and v.trip.trip_id else None
                speed = v.position.speed if v.position.HasField("speed") else None
                bearing = v.position.bearing if v.position.HasField("bearing") else None

                # Filter invalid coordinates
                if not (28.3 <= lat <= 28.95 and 76.8 <= lon <= 77.55):
                    continue

                curr_pos = LiveVehiclePosition(
                    vehicle_id=vid,
                    lat=lat,
                    lon=lon,
                    timestamp=ts,
                    route_id=route_id,
                    trip_id=trip_id,
                    speed_mps=speed,
                    bearing=bearing
                )

                # Track consecutive pings for speed derivation (ADR 005)
                if vid in self.active_vehicles:
                    prev = self.active_vehicles[vid]
                    dt = curr_pos.timestamp - prev.timestamp
                    if 10 <= dt <= 120 and curr_pos.route_id:
                        # Estimate displacement using Haversine / metric approx
                        dlat = (curr_pos.lat - prev.lat) * 111000.0
                        dlon = (curr_pos.lon - prev.lon) * 97800.0
                        dist_m = (dlat**2 + dlon**2)**0.5
                        derived_speed = dist_m / dt
                        if 0.5 <= derived_speed <= 25.0:  # Valid bus movement
                            self.route_live_speeds[curr_pos.route_id].append(derived_speed)
                            if len(self.route_live_speeds[curr_pos.route_id]) > 50:
                                self.route_live_speeds[curr_pos.route_id].pop(0)

                self.previous_pings[vid] = self.active_vehicles.get(vid, curr_pos)
                self.active_vehicles[vid] = curr_pos
                parsed_count += 1

        self.last_poll_time = time.time()
        self.last_poll_status = "SUCCESS"
        self.total_polls_succeeded += 1
        return parsed_count

    async def poll_once(self) -> int:
        """Executes a single poll cycle."""
        data = await self.fetch_feed_data()
        if data:
            return self.parse_protobuf_feed(data)
        return 0

    def get_live_vehicles(self, route_id: Optional[str] = None, max_count: int = 100) -> List[Dict[str, Any]]:
        """Returns list of active, non-expired vehicles."""
        now = time.time()
        result = []
        for vid, v in list(self.active_vehicles.items()):
            # Discard vehicles older than 5 minutes
            if now - v.received_at > 300:
                continue
            if route_id and v.route_id != str(route_id):
                continue
            result.append(v.to_dict())
            if len(result) >= max_count:
                break
        return result

    def get_feed_health(self) -> Dict[str, Any]:
        """Provides status of the live feed."""
        now = time.time()
        age = round(now - self.last_poll_time, 1) if self.last_poll_time else None
        
        fresh_count = sum(1 for v in self.active_vehicles.values() if v.freshness_state == "FRESH")
        aging_count = sum(1 for v in self.active_vehicles.values() if v.freshness_state == "AGING")
        stale_count = sum(1 for v in self.active_vehicles.values() if v.freshness_state == "STALE")

        return {
            "enabled": settings.LIVE_FEED_ENABLED,
            "status": self.last_poll_status,
            "endpoint": settings.OTD_VEHICLE_POSITIONS_URL,
            "api_key_configured": bool(settings.OTD_API_KEY),
            "last_poll_seconds_ago": age,
            "active_vehicles_total": len(self.active_vehicles),
            "fresh_vehicles": fresh_count,
            "aging_vehicles": aging_count,
            "stale_vehicles": stale_count,
            "total_polls_succeeded": self.total_polls_succeeded,
            "total_polls_failed": self.total_polls_failed,
            "last_error": self.last_error
        }


# Global singleton realtime service
realtime_service = RealtimeFeedService()
