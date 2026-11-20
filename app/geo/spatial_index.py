"""
PULSE Spatial Indexing (app/geo/spatial_index.py)
Provides sub-millisecond nearest-stop spatial indexing using SciPy KDTree
projected into EPSG:32643 (UTM Zone 43N) coordinates.
"""
from typing import List, Dict, Any, Tuple
import numpy as np
from pyproj import Transformer
from scipy.spatial import KDTree

# Metric UTM Zone 43N transformer
transformer = Transformer.from_crs("EPSG:4326", "EPSG:32643", always_xy=True)


class StopSpatialIndex:
    """Fast spatial index over GTFS bus stops in projected metric space."""

    def __init__(self, stops: List[Dict[str, Any]]):
        """
        Initializes KDTree from a list of stop dictionaries.
        Each stop dict must contain 'stop_id', 'stop_name', 'stop_lat', 'stop_lon'.
        """
        self.stops = stops
        self.stop_map = {s["stop_id"]: s for s in stops}
        
        # Project all coordinates to EPSG:32643 (easting, northing)
        coords = []
        for s in stops:
            east, north = transformer.transform(s["stop_lon"], s["stop_lat"])
            coords.append([east, north])
            
        self.projected_coords = np.array(coords, dtype=np.float64)
        self.tree = KDTree(self.projected_coords)

    def find_nearest_stops(self, lat: float, lon: float, max_distance_m: float = 1000.0, k: int = 5) -> List[Dict[str, Any]]:
        """
        Finds up to k nearest stops within max_distance_m of given WGS84 coordinate.
        Returns list of stops sorted by distance in meters, with 'distance_m' attached.
        """
        east, north = transformer.transform(lon, lat)
        distances, indices = self.tree.query([east, north], k=min(k, len(self.stops)), distance_upper_bound=max_distance_m)
        
        results = []
        # When k == 1, SciPy returns scalars; when k > 1, arrays
        if np.isscalar(distances):
            distances = [distances]
            indices = [indices]
            
        for dist, idx in zip(distances, indices):
            if idx < len(self.stops) and not np.isinf(dist):
                stop_data = dict(self.stops[idx])
                stop_data["distance_m"] = round(float(dist), 1)
                results.append(stop_data)
                
        return sorted(results, key=lambda x: x["distance_m"])
