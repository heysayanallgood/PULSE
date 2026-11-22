"""
PULSE Places & Geocoding Service (app/services/places_service.py)
Provides server-side address/place autocomplete via Geoapify and curated Delhi landmarks,
with robust local fallback to the complete Delhi GTFS bus stop index (6,862 stops).
Enforces strict secret isolation (GEOAPIFY_API_KEY is never exposed to clients).
"""
import time
import re
from typing import List, Dict, Any, Optional, Tuple
import httpx

from app.core.config import settings
from app.core.logging import logger
from app.data.gtfs.repository import gtfs_repo


# Curated Delhi Landmark Coordinates (WGS84 lat, lon)
# Ensures instant, reliable resolution for major Delhi destinations even offline
DELHI_LANDMARKS: Dict[str, Tuple[float, float, str]] = {
    "india gate": (28.6129, 77.2295, "Rajpath / Kartavya Path, Central Delhi"),
    "connaught place": (28.6328, 77.2197, "Rajiv Chowk / CP Inner Circle, Central Delhi"),
    "cp": (28.6328, 77.2197, "Connaught Place, Central Delhi"),
    "red fort": (28.6562, 77.2410, "Netaji Subhash Marg, Lal Qila, Old Delhi"),
    "lal qila": (28.6562, 77.2410, "Lal Qila, Old Delhi"),
    "lotus temple": (28.5535, 77.2588, "Bahapur, Kalkaji, South Delhi"),
    "qutub minar": (28.5245, 77.1855, "Mehrauli, South West Delhi"),
    "humayun tomb": (28.5933, 77.2507, "Mathura Road, Nizamuddin East"),
    "humayun's tomb": (28.5933, 77.2507, "Mathura Road, Nizamuddin East"),
    "akshardham": (28.6127, 77.2773, "Noida Link Road, East Delhi"),
    "akshardham temple": (28.6127, 77.2773, "Swaminarayan Akshardham, East Delhi"),
    "aiims": (28.5672, 77.2100, "Sri Aurobindo Marg, Ansari Nagar"),
    "aiims hospital": (28.5672, 77.2100, "All India Institute of Medical Sciences"),
    "safdarjung hospital": (28.5701, 77.2078, "Ring Road, Safdarjung Enclave"),
    "dhaula kuan": (28.5921, 77.1616, "Ring Road / Vande Mataram Marg Interchange"),
    "kashmere gate": (28.6675, 77.2281, "Maharana Pratap ISBT, North Delhi"),
    "kashmere gate isbt": (28.6675, 77.2281, "Maharana Pratap ISBT, North Delhi"),
    "anand vihar": (28.6469, 77.3160, "Swami Vivekanand ISBT, East Delhi"),
    "anand vihar isbt": (28.6469, 77.3160, "Swami Vivekanand ISBT, East Delhi"),
    "sarai kale khan": (28.5912, 77.2575, "Vir Hakikat Rai ISBT, Ring Road"),
    "new delhi railway station": (28.6429, 77.2191, "Pahar Ganj / Ajmeri Gate, NDLS"),
    "ndls": (28.6429, 77.2191, "New Delhi Railway Station"),
    "old delhi railway station": (28.6575, 77.2300, "Chandni Chowk, DLI"),
    "dli": (28.6575, 77.2300, "Old Delhi Railway Station"),
    "hazrat nizamuddin": (28.5888, 77.2533, "Nizamuddin Railway Station, South Delhi"),
    "nizamuddin railway station": (28.5888, 77.2533, "Hazrat Nizamuddin Railway Station"),
    "delhi airport": (28.5562, 77.1000, "Indira Gandhi International Airport"),
    "igi airport": (28.5562, 77.1000, "Indira Gandhi International Airport"),
    "delhi airport terminal 3": (28.5562, 77.1000, "IGI Airport Terminal 3"),
    "igi t3": (28.5562, 77.1000, "IGI Airport Terminal 3"),
    "delhi airport terminal 1": (28.5911, 77.1206, "IGI Airport Terminal 1"),
    "jantar mantar": (28.6271, 77.2166, "Sansad Marg, Connaught Place"),
    "rashtrapati bhavan": (28.6143, 77.1995, "President's Estate, Central Delhi"),
    "supreme court": (28.6225, 77.2395, "Tilak Marg, New Delhi"),
    "delhi high court": (28.6111, 77.2384, "Shershah Road, New Delhi"),
    "lodhi garden": (28.5931, 77.2197, "Lodhi Road, New Delhi"),
    "chandni chowk": (28.6506, 77.2303, "Old Delhi Market Area"),
    "karol bagh": (28.6514, 77.1907, "Central-West Delhi Shopping District"),
    "hauz khas": (28.5494, 77.2001, "Hauz Khas Village / Deer Park"),
    "select citywalk": (28.5283, 77.2193, "Saket District Centre, South Delhi"),
    "nehru place": (28.5492, 77.2526, "Nehru Place Commercial Hub, South Delhi"),
    "badarpur border": (28.4912, 77.3005, "Mathura Road, Delhi-Haryana Border"),
    "khan market": (28.6002, 77.2270, "Rabindra Nagar, New Delhi"),
    "lajpat nagar": (28.5700, 77.2400, "Central Market, South Delhi"),
    "rajouri garden": (28.6425, 77.1200, "West Delhi Commercial Hub"),
    "janakpuri west": (28.6294, 77.0782, "District Centre, West Delhi"),
    "dwarka sector 21": (28.5523, 77.0583, "Dwarka Transportation Hub"),
    "rohini west": (28.7150, 77.1147, "Sector 10, Rohini, North West Delhi")
}


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
            oldest_keys = sorted(self._cache.keys(), key=lambda k: self._cache[k][0])[:200]
            for k in oldest_keys:
                self._cache.pop(k, None)
        self._cache[key] = (time.time(), res)

    def resolve_landmark(self, name: str) -> Optional[Tuple[str, float, float, str]]:
        """Resolves known Delhi landmarks case-insensitively."""
        clean = name.strip().lower()
        if clean in DELHI_LANDMARKS:
            lat, lon, desc = DELHI_LANDMARKS[clean]
            return clean.title(), lat, lon, desc
        # Substring search
        for lm_name, (lat, lon, desc) in DELHI_LANDMARKS.items():
            if clean in lm_name or lm_name in clean:
                return lm_name.title(), lat, lon, desc
        return None

    async def autocomplete(self, query: str, limit: int = 10) -> Dict[str, Any]:
        """
        Unified autocomplete endpoint:
        1. Validates coordinate patterns (lat, lon)
        2. Searches GTFS bus stop index (6,862 stops)
        3. Matches curated Delhi landmarks
        4. Queries Geoapify if configured (biased to Delhi NCR)
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
            nearest_stop_id = nearest[0]["stop_id"] if nearest else None
            
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
                        "stop_id": nearest_stop_id,
                        "nearest_stop_id": nearest_stop_id,
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
        seen_names = set()

        # 1. Search GTFS stops (instant, local DuckDB, zero latency, guaranteed Delhi transit stops)
        gtfs_stops = gtfs_repo.search_stops(q, limit=limit)
        for s in gtfs_stops:
            s_name = s["stop_name"]
            suggestions.append({
                "id": f"stop_{s['stop_id']}",
                "name": s_name,
                "formatted_address": f"DTC Bus Stop (ID: {s['stop_id']})",
                "lat": s["stop_lat"],
                "lon": s["stop_lon"],
                "stop_id": s["stop_id"],
                "nearest_stop_id": s["stop_id"],
                "type": "STOP",
                "category": "bus_stop",
                "attribution": "Delhi Transport Corporation (DTC) Static GTFS"
            })
            seen_names.add(s_name.lower())

        # 2. Check Curated Delhi Landmarks (e.g. India Gate, Connaught Place)
        lm_match = self.resolve_landmark(q)
        if lm_match:
            lm_title, lm_lat, lm_lon, lm_desc = lm_match
            if lm_title.lower() not in seen_names:
                nearest = gtfs_repo.find_nearby_stops(lm_lat, lm_lon, radius_m=1500.0, limit=1)
                nearest_id = nearest[0]["stop_id"] if nearest else None
                nearest_name = nearest[0]["stop_name"] if nearest else "Nearby Transit"
                suggestions.append({
                    "id": f"landmark_{lm_title.lower().replace(' ', '_')}",
                    "name": lm_title,
                    "formatted_address": f"{lm_desc} (Near {nearest_name})",
                    "lat": lm_lat,
                    "lon": lm_lon,
                    "stop_id": nearest_id,
                    "nearest_stop_id": nearest_id,
                    "type": "PLACE",
                    "category": "landmark",
                    "attribution": "Delhi City Landmarks"
                })
                seen_names.add(lm_title.lower())

        # 3. Query Geoapify Address Autocomplete if configured
        provider_used = "GTFS_STOPS"
        if settings.GEOAPIFY_API_KEY and len(suggestions) < limit:
            try:
                geo_limit = limit - len(suggestions)
                geo_results = await self._query_geoapify(q, limit=geo_limit)
                for g in geo_results:
                    if g["name"].lower() not in seen_names:
                        # Attach nearest bus stop
                        nearest = gtfs_repo.find_nearby_stops(g["lat"], g["lon"], radius_m=1500.0, limit=1)
                        nearest_id = nearest[0]["stop_id"] if nearest else None
                        g["stop_id"] = nearest_id
                        g["nearest_stop_id"] = nearest_id
                        suggestions.append(g)
                        seen_names.add(g["name"].lower())
                provider_used = "GEOAPIFY" if geo_results else "GTFS_STOPS"
            except Exception as e:
                logger.warning(f"Geoapify autocomplete failed: {e}. Falling back to GTFS index.")

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
