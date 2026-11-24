"""
PULSE Live GTFS-RT Feed Client & Vehicle State Tracker (app/services/realtime_service.py)
Implements ADR 005 and Pre-Implementation Correction 2.
Decodes Google Protocol Buffers vehicle positions from Delhi Open Transit Data (OTD),
tracks consecutive observation displacement, calculates real-time corridor velocity,
and safely manages credential privacy and fail-safe historical fallback.
"""
import math
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
        # Rolling window of consecutive-poll movements per route:
        # (received_epoch, distance_m, dt_s, vehicle_id). Includes standing time,
        # so Σdistance/Σtime is comparable to the historical space-mean pace.
        self.route_live_pairs: Dict[str, List[Tuple[float, float, float, str]]] = defaultdict(list)
        
        self.last_poll_time: Optional[float] = None
        self.last_poll_status: str = "INITIALIZED"
        self.last_feed_timestamp: Optional[int] = None
        self.total_polls_succeeded: int = 0
        self.total_polls_failed: int = 0
        self.last_error: Optional[str] = None
        self._poll_task: Optional[asyncio.Task] = None
        self._poll_lock = asyncio.Lock()
        self._route_names: Optional[Dict[str, str]] = None

    async def fetch_feed_data(self) -> Optional[bytes]:
        """Performs authenticated HTTP request to Delhi OTD endpoint."""
        if not settings.LIVE_FEED_ENABLED or not settings.OTD_API_KEY:
            self.last_poll_status = "DISABLED_NO_CREDENTIALS"
            return None

        url = settings.OTD_VEHICLE_POSITIONS_URL
        params = {settings.OTD_API_KEY_PARAM: settings.OTD_API_KEY}

        try:
            async with httpx.AsyncClient(timeout=20.0) as client:
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
                    # The DTC feed carries no bearing: derive heading from movement,
                    # or keep the last known heading while the bus is standing.
                    if curr_pos.bearing is None:
                        dn = (curr_pos.lat - prev.lat) * 111000.0
                        de = (curr_pos.lon - prev.lon) * 97800.0
                        if (dn * dn + de * de) ** 0.5 >= 20.0:
                            curr_pos.bearing = round((math.degrees(math.atan2(de, dn)) + 360.0) % 360.0, 1)
                        elif prev.bearing is not None:
                            curr_pos.bearing = prev.bearing
                    dt = curr_pos.timestamp - prev.timestamp
                    if 10 <= dt <= 120 and curr_pos.route_id:
                        # Estimate displacement using Haversine / metric approx
                        dlat = (curr_pos.lat - prev.lat) * 111000.0
                        dlon = (curr_pos.lon - prev.lon) * 97800.0
                        dist_m = (dlat**2 + dlon**2)**0.5
                        derived_speed = dist_m / dt
                        if derived_speed <= 25.0:
                            window = self.route_live_pairs[curr_pos.route_id]
                            window.append((time.time(), dist_m, float(dt), vid))
                            cutoff = time.time() - 900
                            while window and window[0][0] < cutoff:
                                window.pop(0)
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
        """Executes a single poll cycle (one at a time)."""
        async with self._poll_lock:
            data = await self.fetch_feed_data()
            if data:
                return self.parse_protobuf_feed(data)
            return 0

    async def poll_if_older(self, max_age_s: float) -> bool:
        """Poll now unless the last successful poll is younger than max_age_s.
        Lets a client following one bus get fresh fixes without hammering the feed."""
        if not settings.LIVE_FEED_ENABLED or not settings.OTD_API_KEY:
            return False
        if self.last_poll_time and time.time() - self.last_poll_time < max_age_s:
            return False
        if self._poll_lock.locked():
            async with self._poll_lock:
                return True
        await self.poll_once()
        return True

    def route_name(self, route_id: Optional[str]) -> Optional[str]:
        """Public route number (GTFS route_short_name) for the feed's internal route_id."""
        if route_id is None:
            return None
        if self._route_names is None:
            try:
                from app.data.gtfs.repository import gtfs_repo
                con = gtfs_repo._get_connection()
                self._route_names = {str(r): str(n) for r, n in con.execute(
                    "SELECT route_id, route_short_name FROM routes").fetchall()}
            except Exception as exc:  # pragma: no cover
                logger.warning(f"Route names unavailable: {exc}")
                self._route_names = {}
        return self._route_names.get(str(route_id))

    def vehicle_dict(self, v: "LiveVehiclePosition") -> Dict[str, Any]:
        d = v.to_dict()
        d["route_name"] = self.route_name(v.route_id)
        return d

    def get_vehicle(self, vehicle_id: str) -> Optional[Dict[str, Any]]:
        v = self.active_vehicles.get(vehicle_id)
        return self.vehicle_dict(v) if v else None

    async def start_background_poller(self):
        """Starts periodic background polling task if live feed is enabled."""
        if not settings.LIVE_FEED_ENABLED or not settings.OTD_API_KEY:
            logger.info("Live feed background poller not active (disabled or missing key).")
            return

        logger.info(f"Starting Live GTFS-RT background poller (interval: {settings.LIVE_POLL_INTERVAL_SECONDS}s)")
        # Immediate first poll
        try:
            count = await self.poll_once()
            logger.info(f"Initial live GTFS-RT poll completed: {count} active vehicles parsed.")
        except Exception as e:
            logger.warning(f"Initial live GTFS-RT poll failed: {e}")

        while True:
            try:
                await asyncio.sleep(settings.LIVE_POLL_INTERVAL_SECONDS)
                count = await self.poll_once()
                logger.debug(f"Live GTFS-RT polled: {count} active vehicles.")
            except asyncio.CancelledError:
                logger.info("Live GTFS-RT background poller cancelled.")
                break
            except Exception as e:
                logger.warning(f"Error in live GTFS-RT poll cycle: {e}")

    def route_live_pace(self, route_id: str, window_s: int = 900) -> Optional[Dict[str, Any]]:
        """Space-mean pace (s/m) of a route's buses over the last window_s seconds."""
        rows = [r for r in self.route_live_pairs.get(str(route_id), []) if r[0] >= time.time() - window_s]
        if not rows:
            return None
        dist = sum(r[1] for r in rows); dt = sum(r[2] for r in rows)
        vehicles = {r[3] for r in rows}
        if dist < 1500 or len(vehicles) < 2:
            return None
        paces = [r[2] / r[1] for r in rows if r[1] > 5]
        mean = dt / dist
        var = (sum((x - mean) ** 2 for x in paces) / max(len(paces) - 1, 1)) if len(paces) > 1 else (0.3 * mean) ** 2
        return {"pace_s_per_m": mean, "pace_var": var, "n_vehicles": len(vehicles), "n_pairs": len(rows),
                "age_s": max(0.0, time.time() - max(r[0] for r in rows))}

    def get_live_vehicles(self, route_id: Optional[str] = None, max_count: int = 1500) -> List[Dict[str, Any]]:
        """Returns list of active, non-expired vehicles."""
        now = time.time()
        result = []
        for vid, v in list(self.active_vehicles.items()):
            # Discard vehicles older than 5 minutes
            if now - v.received_at > 300:
                continue
            if route_id and v.route_id != str(route_id):
                continue
            result.append(self.vehicle_dict(v))
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
