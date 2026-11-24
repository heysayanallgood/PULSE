"""
PULSE Phase 3b — Observed Headway Service (app/services/headway_service.py)

Loads stop_headways.parquet once at process startup and answers expected-wait
queries via a hierarchical dict lookup:

  L1: (stop_id, route_id, bucket, is_weekend)  → STOP_ROUTE_BUCKET
  L2: (route_id, bucket, is_weekend)            → ROUTE_BUCKET  (fallback)
  L3: (bucket, is_weekend)                      → NETWORK_BUCKET (fallback)

If no data at all, falls back to Delhi-network default of 900 s / 2 = 450 s.

Public API:
  headway_service.expected_wait_s(stop_id, route_id, bucket, is_weekend)
      → dict with keys: wait_s, median_gap_s, source_level, sample_count
"""
from __future__ import annotations

import time
from pathlib import Path
from typing import Any, Dict, Optional

from app.core.config import settings
from app.core.logging import logger

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
_HEADWAY_PARQUET = settings.MODEL_ROOT / "traffic_model" / "stop_headways.parquet"

# Delhi-wide safe default: ~15-min headway → 7.5-min wait
_DEFAULT_GAP_S = 900
_ROUTE_FALLBACK_KEY = "__ROUTE_FALLBACK__"
_NETWORK_FALLBACK_KEY = "__NETWORK_FALLBACK__"
_ALL_ROUTES_KEY = "__ALL__"


# ---------------------------------------------------------------------------
# In-memory index
# ---------------------------------------------------------------------------

class _HeadwayIndex:
    """
    Three-level lookup dict built from stop_headways.parquet at startup.
    """

    def __init__(self):
        self._l1: dict = {}   # (stop_id, route_id, bucket, is_weekend) → rec
        self._l2: dict = {}   # (route_id, bucket, is_weekend)           → rec
        self._l3: dict = {}   # (bucket, is_weekend)                     → rec
        self._loaded = False

    def load(self, parquet_path: Path = _HEADWAY_PARQUET) -> None:
        if self._loaded:
            return

        if not parquet_path.exists():
            logger.warning(
                f"stop_headways.parquet not found at {parquet_path}. "
                "Headway service will use network default. "
                "Run scripts/build_headways.py to populate observed headways."
            )
            self._loaded = True
            return

        try:
            import pandas as pd
            t0 = time.time()
            df = pd.read_parquet(str(parquet_path))
            logger.info(
                f"Loading headway index from {parquet_path} "
                f"({len(df):,} rows) …"
            )

            for row in df.to_dict(orient="records"):
                stop_id  = str(row["stop_id"])
                route_id = str(row["route_id"])
                bucket   = (int(row["time_bucket_15min"]) // 4) * 4   # stored per hour
                is_w     = int(row["is_weekend"])

                rec = {
                    "median_gap_s":  float(row["median_gap_s"]),
                    "p25_gap_s":     float(row.get("p25_gap_s") or row["median_gap_s"]),
                    "p75_gap_s":     float(row.get("p75_gap_s") or row["median_gap_s"]),
                    "sample_count":  int(row["sample_count"]),
                    "source_level":  str(row["source_level"]),
                }

                if stop_id == _NETWORK_FALLBACK_KEY:
                    # Network-level fallback row
                    self._l3[(bucket, is_w)] = rec
                elif stop_id == _ROUTE_FALLBACK_KEY:
                    # Route-level fallback row
                    self._l2[(route_id, bucket, is_w)] = rec
                else:
                    # Stop+route level
                    self._l1[(stop_id, route_id, bucket, is_w)] = rec
                    # Also contribute to route-level (keep highest sample count)
                    rk = (route_id, bucket, is_w)
                    existing = self._l2.get(rk)
                    if existing is None or rec["sample_count"] > existing["sample_count"]:
                        self._l2[rk] = rec

            self._loaded = True
            logger.info(
                f"Headway index loaded: {len(self._l1):,} stop-route entries, "
                f"{len(self._l2):,} route entries, {len(self._l3):,} network entries "
                f"in {time.time() - t0:.2f}s"
            )

        except Exception as exc:
            logger.error(f"Failed to load headway index: {exc}")
            self._loaded = True  # prevent retry loops

    def lookup(
        self,
        stop_id: str,
        route_id: str,
        bucket: int,
        is_weekend: int,
    ) -> tuple[dict, str]:
        """
        Returns (record, source_level) with hierarchical fallback.
        record always contains at least: median_gap_s, sample_count, source_level
        """
        b = (max(0, min(95, int(bucket))) // 4) * 4
        w = int(is_weekend)

        rec = self._l1.get((str(stop_id), str(route_id), b, w))
        if rec:
            return rec, "STOP_ROUTE_BUCKET"

        rec = self._l2.get((str(route_id), b, w))
        if rec:
            return rec, "ROUTE_BUCKET"

        rec = self._l3.get((b, w))
        if rec:
            return rec, "NETWORK_BUCKET"

        return None, "DEFAULT"


# Singleton
_headway_index = _HeadwayIndex()


# ---------------------------------------------------------------------------
# Public service
# ---------------------------------------------------------------------------

class HeadwayService:
    """
    Returns expected waiting time given stop, route, and time of day.

    expected_wait_s = median_gap_s / 2  (uniform headway assumption).
    """

    def load(self) -> None:
        _headway_index.load()

    def expected_wait_s(
        self,
        stop_id: str,
        route_id: str,
        bucket: int,
        is_weekend: int,
    ) -> Dict[str, Any]:
        """
        Returns:
            wait_s         — expected wait seconds (median_gap / 2)
            median_gap_s   — median inter-arrival gap
            source_level   — where data came from
            sample_count   — number of observed gaps
        """
        _headway_index.load()
        rec, source = _headway_index.lookup(stop_id, route_id, bucket, is_weekend)

        if rec is None:
            gap_s = float(_DEFAULT_GAP_S)
            return {
                "wait_s":        gap_s / 2.0,
                "median_gap_s":  gap_s,
                "source_level":  "NETWORK_DEFAULT",
                "sample_count":  0,
            }

        gap_s = float(rec["median_gap_s"])
        return {
            "wait_s":        gap_s / 2.0,
            "median_gap_s":  gap_s,
            "source_level":  source,
            "sample_count":  int(rec["sample_count"]),
        }

    def route_expected_wait_s(
        self,
        route_id: str,
        bucket: int,
        is_weekend: int,
    ) -> Dict[str, Any]:
        """Shortcut: route-level lookup (skips stop-level L1)."""
        _headway_index.load()
        b   = (max(0, min(95, int(bucket))) // 4) * 4
        w   = int(is_weekend)
        rec = _headway_index._l2.get((str(route_id), b, w))
        if rec is None:
            rec = _headway_index._l3.get((b, w))
            source = "NETWORK_BUCKET" if rec else "NETWORK_DEFAULT"
        else:
            source = "ROUTE_BUCKET"

        gap_s = float(rec["median_gap_s"]) if rec else float(_DEFAULT_GAP_S)
        return {
            "wait_s":        gap_s / 2.0,
            "median_gap_s":  gap_s,
            "source_level":  source,
            "sample_count":  int(rec["sample_count"]) if rec else 0,
        }


# Global singleton
headway_service = HeadwayService()
