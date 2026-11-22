# PULSE — GPS & GTFS Shape Matching Specification (`docs/GPS_AND_GTFS_SHAPE_MATCHING.md`)

## 1. Overview
Transit journey visualization requires road-following polylines rather than straight lines between stops. PULSE parses 965,607 static GTFS shape points across 3,498 route shapes to construct authentic road corridors.

## 2. Shape Slicing Algorithm (`get_clipped_shape_coordinates`)
Given a `shape_id`, boarding coordinate $(lat_{board}, lon_{board})$, and alighting coordinate $(lat_{alight}, lon_{alight})$:

1. **Shape Retrieval**: All ordered shape points $(lat_i, lon_i, seq_i)$ belonging to `shape_id` are loaded from DuckDB.
2. **Metric Projection (ADR 003)**: Coordinates are transformed from WGS84 (EPSG:4326) to UTM Zone 43N (EPSG:32643) using `pyproj.Transformer(always_xy=True)` to obtain planar metric $(x, y)$ coordinates in meters.
3. **Nearest Vertex Snapping**:
   - Boarding index $i_{board} = \arg\min_i \text{dist}(P_{board}, S_i)$
   - Alighting index $i_{alight} = \arg\min_i \text{dist}(P_{alight}, S_i)$
4. **Sequence Direction Ordering**:
   - If $i_{board} < i_{alight}$: Polyline slice is $S[i_{board} : i_{alight} + 1]$.
   - If $i_{board} > i_{alight}$: Shape points run in reverse sequence; slice is inverted to ensure forward traversal.
5. **Coordinate Formatting**: Sliced vertices are exported as an array of `[lat, lon]` pairs, averaging 180 to 360+ road points per leg.

## 3. Visual Distinction Between Legs
- **Walking Legs**: Plotted with grey dashed stroke (`#64748b`, `weight: 3.5`, `dashArray: '6, 8'`), connecting origin centroids to bus stops or interchange transfer points.
- **Bus Legs**: Plotted with thick solid lines (`weight: 5.5`, opacity `0.95`) using distinctive palette colors (`#0284c7`, `#7c3aed`, `#059669`) for multi-leg journeys.
- **Boarding/Alighting Pins**: Green ringed markers for boarding, amber for transfer hubs, red for alighting.
