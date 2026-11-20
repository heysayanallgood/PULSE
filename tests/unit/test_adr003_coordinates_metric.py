"""
Unit tests for ADR 003: Coordinate System & Metric Projections
Validates EPSG:32643 (UTM 43N) projection, distance calculation,
and segment generation along polylines.
"""
import math
from pyproj import Transformer
from shapely.geometry import LineString, Point

def test_pyproj_epsg32643_always_xy():
    transformer = Transformer.from_crs("EPSG:4326", "EPSG:32643", always_xy=True)
    
    # India Gate coordinates: (lon, lat)
    lon_ig, lat_ig = 77.2295, 28.6129
    x_ig, y_ig = transformer.transform(lon_ig, lat_ig)
    
    # Red Fort coordinates: (lon, lat)
    lon_rf, lat_rf = 77.2410, 28.6562
    x_rf, y_rf = transformer.transform(lon_rf, lat_rf)
    
    # Calculate Euclidean distance in meters in UTM 43N space
    metric_dist = math.sqrt((x_rf - x_ig)**2 + (y_rf - y_ig)**2)
    
    # India Gate to Red Fort is approximately 4.9 km (~4800 - 5100 m)
    assert 4800 <= metric_dist <= 5200, f"Distance {metric_dist} m is out of expected range"

def test_metric_segmentation_logic():
    # Create a 1500m straight line along Easting in UTM 43N
    transformer = Transformer.from_crs("EPSG:4326", "EPSG:32643", always_xy=True)
    start_x, start_y = transformer.transform(77.22, 28.61)
    
    # 1500 meters line
    line = LineString([(start_x, start_y), (start_x + 1500, start_y)])
    assert line.length == 1500.0
    
    # Slice line into target ~400m segments (300m - 500m rule)
    target_len = 400.0
    num_segs = math.ceil(line.length / target_len)
    seg_len = line.length / num_segs
    
    segments = []
    for i in range(num_segs):
        d_start = i * seg_len
        d_end = min((i + 1) * seg_len, line.length)
        seg_id = f"test_shape_seg_{i+1:03d}"
        segments.append({
            "segment_id": seg_id,
            "start_dist": d_start,
            "end_dist": d_end,
            "length": d_end - d_start
        })
        
    assert len(segments) == 4
    for s in segments:
        assert 300.0 <= s["length"] <= 500.0, f"Segment length {s['length']} violates 300-500m rule"
