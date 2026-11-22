"""
PULSE Places & Geocoding Service (app/services/places_service.py)
Provides server-side address/place autocomplete via Geoapify,
with robust local fallback to the complete Delhi GTFS bus stop index.
Enforces strict secret isolation (GEOAPIFY_API_KEY is never exposed to clients).
"""
import time
import re
from typing import List, Dict, Any, Optional
import httpx

from app.core.config import settings
from app.core.logging import logger
from app.data.gtfs.repository import gtfs_repo


class PlacesService:
    """Manages address autocomplete, geocoding caching, and GTFS stop disambiguation."""

    def __init__(self):
        # In-memory query cache: {query_lower: (timestamp, results)}
        self._cache: Dict[str, Tuple[float, List[Dict[str, Any]]]] = {}
        self._cache_ttl_seconds = 3600  # 1 hour cache to protect rate limits
        self._max_cache_entries = 1000

    def _get_from_cache(self, key: str) -> Optional[List[Dict[str, Any]]]:
        now = time.time()
        if key in self._cache:
            ts, res = self._cache[key]
            if now - ts < self._cache_ttl_seconds:
                return res
            else:
                del self._cache[key]
        return None

    def _set_cache(self, key: str, res: List[Dict[str, Any]]):
        if len(self._cache) >= self._max_cache_entries:
            # Drop oldest 200 entries
            oldest_keys = sorted(self._cache.keys(), key=lambda k: self._cache[k][0])[:200]
            for k in oldest_keys:
                self._cache.pop(k, None)
        self._cache[key] = (time.time(), res)

    async def autocomplete(self, query: str, limit: int = 10) -> Dict[str, Any]:
        """
        Unified autocomplete endpoint:
        1. Validates coordinate patterns (lat, lon)
        2. Queries Geoapify if configured (biased to Delhi NCR)
        3. Augments/falls back to complete GTFS stop index (6,862 stops)
        """
        q = query.strip()
        if not q or len(q) < 2:
            return {"query": q, "suggestions": [], "provider": "NONE"}

        # Check if direct coordinates (e.g. "28.6139, 77.2090")
        coord_match = re.match(r"^([-+]?\d*\.?\d+)\s*,\s*([-+]?\d*\.?\d+)$", q)
        if coord_match:
            lat = float(coord_match.group(1))
            lon = float(coord_match.group(2))
            is_valid_delhi = (28.2 <= lat <= 28.95 and 76.8 <= lon <= 77.55)
            nearest = gtfs_repo.find_nearby_stops(lat, lon, radius_m=1500.0, limit=1)
            nearest_name = nearest[0]["stop_name"] if nearest else "No bus stop within 1.5 km"
            
            return {
                "query": q,
                "provider": "COORDINATE",
                "suggestions": [
                    {
                        "id": f"coord_{lat:.5f}_{lon:.5f}",
                        "name": f"Coordinate ({lat:.4f}, {lon:.4f})",
                        "formatted_address": f"Near {nearest_name}" if is_valid_delhi else "Location outside Delhi transit service area",
                        "lat": lat,
                        "lon": lon,
                        "type": "COORDINATE",
                        "category": "coordinate",
                        "is_valid_service_area": is_valid_delhi,
                        "attribution": "Direct coordinate input"
                    }
                ]
            }

        cache_key = q.lower()
        cached = self._get_from_cache(cache_key)
        if cached is not None:
            return {
                "query": q,
                "provider": "CACHE",
                "suggestions": cached[:limit]
            }

        suggestions: List[Dict[str, Any]] = []
        provider_used = "GTFS_STOPS"

        # 1. Try Geoapify Address Autocomplete if key is configured
        if settings.GEOAPIFY_API_KEY:
            try:
                geo_results = await self._query_geoapify(q, limit=limit)
                if geo_results:
                    suggestions.extend(geo_results)
                    provider_used = "GEOAPIFY"
            except Exception as e:
                logger.warning(f"Geoapify autocomplete failed: {e}. Falling back to GTFS index.")

        # 2. GTFS Bus Stops Search
        # If Geoapify didn't fill the limit, or as complementary transit options
        gtfs_limit = limit - len(suggestions) if suggestions else limit
        if gtfs_limit > 0:
            gtfs_stops = gtfs_repo.search_stops(q, limit=gtfs_limit)
            for s in gtfs_stops:
                suggestions.append({
                    "id": f"stop_{s['stop_id']}",
                    "name": s["stop_name"],
                    "formatted_address": f"DTC Bus Stop (ID: {s['stop_id']})",
                    "lat": s["stop_lat"],
                    "lon": s["stop_lon"],
                    "stop_id": s["stop_id"],
                    "type": "STOP",
                    "category": "bus_stop",
                    "attribution": "Delhi Transport Corporation (DTC) Static GTFS"
                })

        self._set_cache(cache_key, suggestions)

        return {
            "query": q,
            "provider": provider_used,
            "suggestions": suggestions[:limit]
        }

    async def _query_geoapify(self, query: str, limit: int = 5) -> List[Dict[str, Any]]:
        """Queries the Geoapify autocomplete endpoint biased to Delhi."""
        url = "https://api.geoapify.com/v1/geocode/autocomplete"
        params = {
            "text": query,
            "apiKey": settings.GEOAPIFY_API_KEY,
            "filter": "rect:76.8,28.2,77.55,28.95",  # Bounding box of Delhi NCR
            "bias": "proximity:77.2167,28.6328",    # Central Delhi (Connaught Place)
            "limit": limit,
            "format": "json"
        }

        async with httpx.AsyncClient(timeout=4.0) as client:
            resp = await client.get(url, params=params)
            if resp.status_code != 200:
                logger.warning(f"Geoapify returned HTTP {resp.status_code}")
                return []
            data = resp.json()

        results = []
        for feature in data.get("results", []):
            lat = feature.get("lat")
            lon = feature.get("lon")
            if lat is None or lon is None:
                continue

            results.append({
                "id": f"geo_{feature.get('place_id', str(lat)+'_'+str(lon))}",
                "name": feature.get("name") or feature.get("formatted"),
                "formatted_address": feature.get("formatted"),
                "lat": round(lat, 6),
                "lon": round(lon, 6),
                "type": "PLACE",
                "category": feature.get("category", "place"),
                "attribution": "Powered by Geoapify | © OpenStreetMap contributors"
            })

        return results


# Global singleton instance
places_service = PlacesService()
