# PULSE — Architectural Decision Records (ADR Log)
## Project: Predictive Urban Mobility & Live Spatiotemporal Engine (PULSE)
**Team:** HopCode | **Hackathon:** Transport Stack Hackathon 2026 (Problem 1)  
**Fixed Workspace:** `E:\Pulse` | **Primary Storage:** SanDisk 2 TB Portable SSD (Drive `E:`, exFAT)  
**Operating System:** Windows 11 Desktop  
**Authoritative Version:** 2.1 (Post-Senior Engineering Review & Final Pre-Implementation Corrections)  

---

## Record of Architecture Decisions

| ADR # | Title | Status | Primary Focus |
|---|---|---|---|
| **ADR 001** | Storage & Virtual Environment Isolation | **ACCEPTED WITH ADDITIONAL REQUIREMENTS** | `E:\Pulse` workspace isolation; pip, DuckDB swap, and temp caching locked to `E:`; host drive `C:` protected. |
| **ADR 002** | Historical Analytics & Storage Architecture | **AMENDED — APPROVED WITH CORRECTIONS** | Strict `sqlite3` read-only (`mode=ro`) batched extraction into DuckDB; exFAT immutability; Snappy Parquet; dual distributions: **speed (m/s) AND travel-time (s)**; non-double-counted dwell accounting; manifests. |
| **ADR 003** | Coordinate System & Metric Projections | **ACCEPTED WITH IMPLEMENTATION PRECISIONS** | Standardized on **EPSG:32643** (UTM Zone 43N) via PyProj (`always_xy=True`); raw lat/lng preserved; 300m–500m shape segments; **configurable GPS quality thresholds** (50m offset, 25 m/s speed) with quality flags and rejection reporting. |
| **ADR 004** | Public Transit Routing Engine | **AMENDED — MULTI-CRITERIA RAPTOR** | **Multi-Criteria RAPTOR** Pareto-optimizing across (1) Arrival Time, (2) Transfers, (3) Walking Duration; modelled in-vehicle duration; GTFS service times $> 24\text{h}$; **realistic transfer buffer** (configurable 3m baseline + walking between distinct stops); explicit `APPROXIMATED_WALK` labelling. |
| **ADR 005** | Live and Historical Data Fusion | **AMENDED — UNCERTAINTY-AWARE FUSION** | Live velocity from **consecutive pings of the same bus** ($\Delta s / \Delta t$); individual vehicle timestamps; **precision-weighted Bayesian fusion** ($w_{\text{live}} = \frac{q_L / V_L}{q_L / V_L + q_H / V_H}$); positive variance floor; separate freshness state machine (Fresh $\le 60$s, Aging $61$–$90$s, Stale $> 90$s); zero synthetic data. |
| **ADR 006** | Raw Data Immutability & Lineage Provenance | **ACCEPTED** | Raw archives (16 GB), daily SQLite databases (115.5 GB), and GTFS files treated as strictly read-only; atomic staging writes; full lineage manifest tracking (`data/manifests/`). |

---

## ADR 001: Storage & Virtual Environment Isolation

### Status
**ACCEPTED WITH ADDITIONAL REQUIREMENTS**

### Context
The development workstation runs Windows 11 with two distinct storage volumes:
1. **Host Operating System Drive (`C:`)**: Fixed internal SSD with only **4.02 GB free disk space** remaining. Writing virtual environments, package download caches, large intermediate data frames, or DuckDB swap buffers to `C:` will exhaust disk space, causing system instability and process crashes.
2. **Workspace Drive (`E:`)**: SanDisk 2 TB external USB 3 Portable SSD formatted with exFAT, possessing **793.22 GB free disk space** out of 1.82 TB.

### Decision
All project source code, local virtual environments, package caches, temporary files, raw and processed datasets, model files, and database indexes must reside strictly within `E:\Pulse`.

The explicit directory contract is:
```text
E:\Pulse\
├── .venv\                     # Project-local Python 3.12 virtual environment
├── data\
│   ├── raw\                   # Read-only references to raw archives and SQLite dbs
│   ├── staging\               # Ephemeral staging for daily extractions
│   ├── processed\             # Partitioned Parquet stores
│   ├── database\              # DuckDB / SQLite application databases
│   ├── models\                # Trained spatiotemporal model artefacts
│   ├── cache\
│   │   ├── pip\               # Explicit PIP_CACHE_DIR
│   │   ├── temp\              # Explicit TEMP / TMP directory
│   │   └── duckdb\            # Explicit DuckDB spill/swap directory
│   ├── manifests\             # Daily ingestion and processing manifests
│   └── validation\            # Evaluation splits, holdout trips, Google Maps benchmarks
└── logs\                      # Structured application and pipeline logs
```

### Technical Consequences & Implementation
1. **Environment Variables**: Configure the execution environment to prevent standard libraries from defaulting to `C:\Users\User\AppData\Local\Temp`:
   ```powershell
   $env:TEMP = "E:\Pulse\data\cache\temp"
   $env:TMP = "E:\Pulse\data\cache\temp"
   $env:PIP_CACHE_DIR = "E:\Pulse\data\cache\pip"
   ```
2. **Pip Invocations**: All package installations via pip specify `--cache-dir E:\Pulse\data\cache\pip`.
3. **DuckDB Temporary Directory**: Configure DuckDB database connections with:
   ```sql
   SET temp_directory = 'E:/Pulse/data/cache/duckdb';
   ```
4. **Safety & Diagnostic Checks**: Implement a pre-run diagnostic (`app/core/storage.py`) that checks write access on `E:\Pulse` and asserts remaining disk space (> 20 GB threshold). If `E:` is disconnected, the system must fail gracefully with a descriptive error instead of silently falling back to `C:`.

---

## ADR 002: Historical Analytics & Storage Architecture

### Status
**AMENDED — APPROVED WITH CORRECTIONS**

### Context
The historical DTC GPS dataset consists of 31 daily SQLite databases (`bus_movements_2026_10_01.db` through `bus_movements_2026_10_31.db`) covering October 1–31, 2026, totaling **115.50 GB** (124 GB uncompressed) and approximately **900 million GPS observations**.
Because the SanDisk SSD uses the **exFAT filesystem**, NTFS ACL permissions cannot be used to lock files. Source immutability must be strictly enforced via code and connection protocols.

### Decision
1. **Strict Read-Only Connection Protocol**:
   Source SQLite databases are accessed strictly through Python's standard `sqlite3` library in read-only mode:
   ```python
   conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
   ```
   Direct execution of `INSERT`, `UPDATE`, `DELETE`, `CREATE`, `DROP`, or `ALTER` statements against source databases is prohibited and rejected by the SQLite engine.
2. **Batched Extraction to DuckDB**:
   Stream records in manageable batches (e.g. 250,000 records per batch) from the read-only SQLite cursor, projecting and passing batches directly to DuckDB for columnar transformations and Parquet serialization.
3. **Storage Format**: Store cleaned observations in Snappy-compressed, date-partitioned Parquet files:
   ```text
   data/processed/historical/year=2026/month=10/day=DD/part-*.parquet
   ```
4. **Distributions Stored**: Store **both** segment speed distributions (m/s) and segment travel-time distributions (s).
5. **Dwell Accounting Semantics**:
   To strictly eliminate double counting:
   - **Running Time**: Time elapsed from vehicle departure at Stop $i$ to vehicle arrival at Stop $i+1$, including transit corridor speed variations and signal delays.
   - **Stop Dwell**: Time spent stationary at Stop $i$ ($\text{speed} < 0.5\text{ m/s}$ within 30m of stop coordinate), measured separately where available.
   - In-vehicle travel time between stops is calculated as:
     $$T_{\text{in\_vehicle}}(S_i \to S_{i+1}) = \sum_{s \in \text{segments}} T_{\text{running}}(s) + T_{\text{dwell}}(S_i)$$
   - Dwell is **never** added twice if the segment travel-time aggregation already encompasses the stop area traversal.
6. **Time Bucketing & Hierarchical Fallback**:
   - Primary: 15-minute time bucket (96 buckets per day) by day-type.
   - Fallback 1: 1-hour time bucket for the same segment.
   - Fallback 2: Route-level median travel-time rate (s/m) for the corresponding time bucket.
   - Fallback 3: Network corridor prior with explicit low-confidence flag.

---

## ADR 003: Coordinate System & Metric Projections

### Status
**ACCEPTED WITH IMPLEMENTATION PRECISIONS**

### Context
Raw GPS data and GTFS coordinates use WGS 84 (EPSG:4326). Euclidean distance formulas applied to degrees produce severe metric distortion in Delhi (~28.6° N).

### Decision
1. **Projected Reference System**: Standardize on **EPSG:32643** (WGS 84 / UTM Zone 43N) as the project's metric Cartesian coordinate system.
2. **Transformation Protocol**: Utilize PyProj with explicit axis order:
   ```python
   from pyproj import Transformer
   transformer = Transformer.from_crs("EPSG:4326", "EPSG:32643", always_xy=True)
   easting, northing = transformer.transform(longitude, latitude)
   ```
3. **Metric Segmentation**: Divide each continuous GTFS route shape into stable metric segments of approximately **300m–500m**, snapped to GTFS bus stops.
4. **Configurable GPS Quality Thresholds (Correction 4)**:
   The 50-metre shape-distance threshold and 25 m/s speed threshold are **configurable initial quality filters**, not silent deletion rules:
   - Points are evaluated and assigned quality flags: `VALID`, `SPEED_OUTLIER` ($v > 25\text{ m/s}$), `OFF_SHAPE_OFFSET` ($d_{\text{offset}} > 50\text{ m}$), `TEMPORAL_JUMP`, `DETOUR_SUSPECTED`.
   - Trajectory continuity and elapsed time plausibility checks are applied.
   - All rejected records are retained in daily data-quality summary manifests with explicit rejection reasons.
   - Match confidence score: $C_{\text{match}} = \max\left(0.0, 1.0 - \frac{d_{\text{offset}}}{50.0}\right)$.

---

## ADR 004: Public Transit Routing Engine

### Status
**AMENDED — MULTI-CRITERIA RAPTOR**

### Context
Timetable stop times in Delhi are rough estimates. A journey planner must provide realistic bus journey options accounting for walking, waiting, transfers, and congestion.

### Decision
1. **Routing Algorithm**: Implement **Multi-Criteria RAPTOR** (Round-Based Public Transit Routing), evaluating a Pareto set of journeys across:
   - Criterion 1: **Predicted Arrival Time** ($\tau_{\text{arr}}$)
   - Criterion 2: **Number of Transfers** ($k \in \{0, 1, 2\}$)
   - Criterion 3: **Total Walking Duration** ($T_{\text{walk}}$)
2. **Multi-Criteria Journey Label**:
   $$\mathcal{L} = \left( \tau_{\text{arr}}, k, T_{\text{walk}}, T_{\text{in\_vehicle}}, T_{\text{wait}}, T_{\text{transfer\_walk}}, C_{\text{confidence}}, S_{\text{provenance}}, \text{path} \right)$$
   Pareto dominance: $\mathcal{L}_A$ strictly dominates $\mathcal{L}_B$ iff $\tau_{\text{arr}}(A) \le \tau_{\text{arr}}(B)$, $k(A) \le k(B)$, $T_{\text{walk}}(A) \le T_{\text{walk}}(B)$, with at least one strict inequality.
3. **PULSE Travel-Time Integration**: In-vehicle running durations are supplied by the PULSE spatiotemporal prediction model, replacing static timetable durations.
4. **Transfer and Walking Realism (Correction 6)**:
   - Minimum transfer buffer: Configurable baseline of **3 minutes** when changing buses at the same stop.
   - When transferring between distinct stops: Compute walking duration between stops + add interchange buffer (minimum 2 minutes) + verify next service predicted feasibility.
   - Walking routing: Use pedestrian-network routing where available. Straight-line estimates are explicitly tagged `APPROXIMATED_WALK` with reduced confidence, and rejected when physical obstacles (e.g. Yamuna river crossing without bridge) make the approximation invalid.
5. **GTFS Service Times $> 24:00:00$**: Normalized to continuous seconds from service midnight (e.g., 25:15:00 = 90,900s), preserving service-calendar integrity.

---

## ADR 005: Live and Historical Data Fusion

### Status
**AMENDED — UNCERTAINTY-AWARE FUSION**

### Context
Real-time vehicle positions from Delhi's GTFS-RT feed provide instantaneous pings. A single isolated GPS ping provides no distance-over-time delta, and live feeds can experience network jitter.

### Decision
1. **Live Movement Estimation**:
   - Derive live speeds strictly from **consecutive observations of the same vehicle** matched to the same route shape within $\Delta t \in [10\text{s}, 120\text{s}]$:
     $$v_{\text{live}} = \frac{\Delta d_{\text{shape}}}{\Delta t}$$
   - Segment live travel time is estimated as $T_{\text{live}} = \frac{d_{\text{segment}}}{v_{\text{live}}}$.
2. **Precision-Weighted Fusion Formula (Correction 1)**:
   $$w_{\text{live}} = \frac{\frac{q_{\text{live}}}{V_{\text{live}}}}{\frac{q_{\text{live}}}{V_{\text{live}}} + \frac{q_{\text{hist}}}{V_{\text{hist}}}}$$
   $$T_{\text{fused}} = w_{\text{live}} T_{\text{live}} + (1 - w_{\text{live}}) T_{\text{hist}}$$
   Where:
   - $V_{\text{live}}$ and $V_{\text{hist}}$ represent travel-time estimator uncertainty (variance).
   - A positive variance floor is enforced: $V \ge \max(V_{\text{measured}}, 4.0\text{ s}^2)$ to prevent division by zero or infinite weighting.
   - Higher estimator uncertainty ($V$) automatically reduces its weight.
   - $q_{\text{hist}} = \min\left(1.0, \frac{N_{\text{hist\_trips}}}{30}\right)$ based on independent historical trips.
   - $q_{\text{live}} = \min\left(1.0, \frac{N_{\text{live\_veh}}}{3}\right)$ based on distinct live vehicles traversing the segment.
3. **Freshness State Machine (Correction 2)**:
   Evaluated strictly using the **individual vehicle observation timestamp** (never feed-header timestamp):
   - `FRESH`: Observation age $\le 60$ seconds with valid matching.
   - `AGING`: Observation age $> 60$ seconds and $\le 90$ seconds.
   - `STALE`: Observation age $> 90$ seconds ($w_{\text{live}} = 0.0$; live observation discarded).
   - `UNAVAILABLE`: No usable live observations received.
   - A configurable tolerance up to 120 seconds is permitted only for controlled degraded operation if feed latency measurements justify it.
4. **Fail-Safe Fallback**:
   When live data is unavailable or stale, $w_{\text{live}} = 0.0$. The prediction engine continues operating seamlessly on historical models with explicit `HISTORICAL` provenance badges. Zero synthetic/fake traffic is ever displayed.

---

## ADR 006: Raw Data Immutability & Lineage Provenance

### Status
**ACCEPTED**

### Context
The source datasets (`delhi-dtc-bus-gtfs-rt-2026-10.7z`, 31 daily SQLite databases totaling 115.5 GB, and static GTFS files) are foundational, irreplaceable raw material on an exFAT filesystem.

### Decision
1. **Source Immutability**: All original SQLite databases and GTFS text files are strictly read-only.
2. **Physical Separation of Derived Data**: Derived Parquet partitions reside in `data/processed/`, GTFS DuckDB index in `data/database/`, models in `data/models/`.
3. **Reproducible Lineage & Manifests**: Every ingestion run logs an entry in `data/manifests/` capturing source file size, SHA256 checksum, raw records extracted, records cleaned, records rejected (with breakdown), output Parquet paths, and processing timestamps.
4. **Atomic Staging Pattern**: Pipeline jobs write output files to `data/staging/` before atomically moving them to `data/processed/`.

---

## Acceptance Matrix

- [x] Precision-weighted fusion formula corrected with positive variance floor ($V \ge 4.0$).
- [x] Freshness states separated from evidence quality (Fresh $\le 60$s, Aging $61$–$90$s, Stale $> 90$s).
- [x] Individual vehicle timestamps enforced over feed-header timestamps.
- [x] Python `sqlite3` read-only connection enforced (`mode=ro`).
- [x] exFAT immutability safeguards documented.
- [x] GPS matching thresholds (50m, 25 m/s) defined as configurable quality filters.
- [x] Dwell accounting semantics defined (running time vs. stop dwell) without double counting.
- [x] Multi-criteria RAPTOR transfer buffer realism (3 min baseline + inter-stop walk + buffer) and `APPROXIMATED_WALK` label defined.
- [x] All 6 ADRs tested with automated unit test suite.
