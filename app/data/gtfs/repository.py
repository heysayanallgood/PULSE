"""
PULSE GTFS Repository (app/data/gtfs/repository.py)
Provides high-performance query access to the static GTFS DuckDB database,
coupled with an in-memory spatial KD-Tree for nearest-stop queries.
"""
from pathlib import Path
from typing import List, Dict, Any, Optional
import duckdb

from app.core.config import settings
from app.core.logging import logger
from app.geo.spatial_index import StopSpatialIndex


class GTFSRepository:
    """Analytical repository for querying routes, stops, trips, and shapes from DuckDB."""

    def __init__(self, db_path: Optional[Path] = None):
        self.db_path = db_path or (settings.DATABASE_ROOT / "gtfs.duckdb")
        self._con: Optional[duckdb.DuckDBPyConnection] = None
        self._spatial_index: Optional[StopSpatialIndex] = None
        self._init_repository()

    def _get_connection(self) -> duckdb.DuckDBPyConnection:
        if self._con is None:
            # Connect in read-only mode to prevent database locks
            self._con = duckdb.connect(str(self.db_path), read_only=True)
            self._con.execute("SET temp_directory = 'E:/Pulse/data/cache/duckdb';")
        return self._con

    def _init_repository(self):
        """Initializes connection and builds in-memory spatial index for all stops."""
        if not self.db_path.exists():
            logger.warning(f"GTFS database not found at {self.db_path}. Run scripts/ingest_gtfs.py first.")
            return

        con = self._get_connection()
        stops = con.execute("""
            SELECT stop_id, stop_code, stop_name, stop_lat, stop_lon
            FROM stops
            ORDER BY stop_name;
        """).fetchdf().to_dict(orient="records")

        self._spatial_index = StopSpatialIndex(stops)
        logger.info(f"Loaded {len(stops)} stops into StopSpatialIndex.")

    def search_stops(self, query: str, limit: int = 15) -> List[Dict[str, Any]]:
        """
        Searches stops by name or stop_id across all 6,862 Delhi stops.
        Applies case-insensitive pattern matching, prefix ranking, and duplicate disambiguation.
        """
        con = self._get_connection()
        clean_q = query.strip()
        q_like = f"%{clean_q}%"
        q_prefix = f"{clean_q}%"
        df = con.execute("""
            SELECT stop_id, stop_code, stop_name, stop_lat, stop_lon
            FROM stops
            WHERE stop_name ILIKE ? OR stop_id = ?
            ORDER BY 
                CASE 
                    WHEN LOWER(stop_name) = LOWER(?) THEN 1
                    WHEN stop_name ILIKE ? THEN 2
                    WHEN stop_id = ? THEN 3
                    ELSE 4
                END,
                LENGTH(stop_name) ASC,
                stop_name ASC
            LIMIT ?;
        """, [q_like, clean_q, clean_q, q_prefix, clean_q, limit]).fetchdf()
        
        records = df.to_dict(orient="records")
        for r in records:
            r["stop_lat"] = round(float(r["stop_lat"]), 6)
            r["stop_lon"] = round(float(r["stop_lon"]), 6)
            r["display_name"] = f"{r['stop_name']} [{r['stop_id']}]"
        return records

    def get_clipped_shape_coordinates(
        self,
        shape_id: Optional[str],
        board_lat: float,
        board_lon: float,
        alight_lat: float,
        alight_lon: float
    ) -> List[List[float]]:
        """
        Retrieves ordered real GTFS road coordinates for a bus corridor segment between
        boarding and alighting stops, clipping the route shape points.
        """
        fallback = [[round(board_lat, 6), round(board_lon, 6)], [round(alight_lat, 6), round(alight_lon, 6)]]
        if not shape_id:
            return fallback

        con = self._get_connection()
        pts = con.execute("""
            SELECT shape_pt_lat, shape_pt_lon
            FROM shapes
            WHERE shape_id = ?
            ORDER BY shape_pt_sequence ASC;
        """, [shape_id]).fetchall()

        if not pts or len(pts) < 2:
            return fallback

        def dist_sq(p, lat, lon):
            return (p[0] - lat)**2 + (p[1] - lon)**2

        idx_board = min(range(len(pts)), key=lambda i: dist_sq(pts[i], board_lat, board_lon))
        idx_alight = min(range(len(pts)), key=lambda i: dist_sq(pts[i], alight_lat, alight_lon))

        if idx_board > idx_alight:
            idx_board, idx_alight = idx_alight, idx_board

        clipped = [[round(float(p[0]), 6), round(float(p[1]), 6)] for p in pts[idx_board:idx_alight + 1]]
        if len(clipped) < 2:
            return fallback
        return clipped

    def get_stop_by_id(self, stop_id: str) -> Optional[Dict[str, Any]]:
        """Retrieves stop details by stop_id."""
        con = self._get_connection()
        df = con.execute("""
            SELECT stop_id, stop_code, stop_name, stop_lat, stop_lon
            FROM stops
            WHERE stop_id = ?;
        """, [stop_id]).fetchdf()
        if len(df) == 0:
            return None
        return df.iloc[0].to_dict()

    def find_nearby_stops(self, lat: float, lon: float, radius_m: float = 1000.0, limit: int = 5) -> List[Dict[str, Any]]:
        """Finds nearest stops within radius_m using the KD-Tree spatial index."""
        if self._spatial_index is None:
            return []
        return self._spatial_index.find_nearest_stops(lat, lon, max_distance_m=radius_m, k=limit)

    def get_route_by_id(self, route_id: str) -> Optional[Dict[str, Any]]:
        """Retrieves route metadata by route_id."""
        con = self._get_connection()
        df = con.execute("""
            SELECT route_id, agency_id, route_short_name, route_long_name, route_desc, route_type
            FROM routes
            WHERE route_id = ?;
        """, [route_id]).fetchdf()
        if len(df) == 0:
            return None
        return df.iloc[0].to_dict()

    def list_routes(self, limit: int = 50, agency_id: Optional[str] = None) -> List[Dict[str, Any]]:
        """Lists routes with optional agency filter."""
        con = self._get_connection()
        if agency_id:
            df = con.execute("""
                SELECT route_id, agency_id, route_short_name, route_long_name, route_desc
                FROM routes
                WHERE agency_id = ?
                ORDER BY route_short_name
                LIMIT ?;
            """, [agency_id, limit]).fetchdf()
        else:
            df = con.execute("""
                SELECT route_id, agency_id, route_short_name, route_long_name, route_desc
                FROM routes
                ORDER BY route_short_name
                LIMIT ?;
            """, [limit]).fetchdf()
        return df.to_dict(orient="records")

    def get_trips_for_route(self, route_id: str, limit: int = 20) -> List[Dict[str, Any]]:
        """Retrieves scheduled trips associated with a route."""
        con = self._get_connection()
        df = con.execute("""
            SELECT trip_id, route_id, service_id, trip_headsign, shape_id, direction_id
            FROM trips
            WHERE route_id = ?
            LIMIT ?;
        """, [route_id, limit]).fetchdf()
        return df.to_dict(orient="records")

    def get_trip_stop_sequence(self, trip_id: str) -> List[Dict[str, Any]]:
        """Retrieves the complete ordered sequence of stops and scheduled times for a trip."""
        con = self._get_connection()
        df = con.execute("""
            SELECT 
                st.trip_id,
                st.stop_sequence,
                st.stop_id,
                s.stop_name,
                s.stop_lat,
                s.stop_lon,
                st.arrival_time,
                st.departure_time,
                st.stop_dist
            FROM stop_times st
            JOIN stops s ON st.stop_id = s.stop_id
            WHERE st.trip_id = ?
            ORDER BY st.stop_sequence ASC;
        """, [trip_id]).fetchdf()
        return df.to_dict(orient="records")

    def get_shape_points(self, shape_id: str) -> List[Dict[str, Any]]:
        """Retrieves the ordered polyline coordinates defining a route shape."""
        con = self._get_connection()
        df = con.execute("""
            SELECT shape_id, shape_pt_lat, shape_pt_lon, shape_pt_sequence, shape_dist_traveled
            FROM shapes
            WHERE shape_id = ?
            ORDER BY shape_pt_sequence ASC;
        """, [shape_id]).fetchdf()
        return df.to_dict(orient="records")

    def get_network_summary(self) -> Dict[str, Any]:
        """Returns verified record counts and summary metrics for the GTFS network."""
        con = self._get_connection()
        res = {}
        for tbl in ["agency", "calendar", "routes", "stops", "trips", "stop_times", "shapes"]:
            res[tbl] = con.execute(f"SELECT COUNT(*) FROM {tbl}").fetchone()[0]
        return res


# Global singleton instance
gtfs_repo = GTFSRepository()
