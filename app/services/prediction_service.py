"""
PULSE travel-time prediction service (app/services/prediction_service.py)

Thin service over app.models.traffic_model.TrafficModel — the per-stretch
model trained from real DTC GPS by scripts/build_traffic_model.py.

If the model has not been built, predictions fall back to a straight
distance at 15 km/h and are labelled UNTRAINED so nobody mistakes them for
model output.
"""
from __future__ import annotations

import math
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from app.core.config import settings
from app.core.logging import logger
from app.models.traffic_model import MODEL_DIR_NAME, TrafficModel

MODEL_DIR = settings.MODEL_ROOT / MODEL_DIR_NAME
_UNTRAINED_SPEED_MPS = 15 / 3.6


class TravelTimePredictionService:
    def __init__(self, model_dir: Optional[Path] = None):
        self.model = TrafficModel(model_dir or MODEL_DIR)
        self._stop_dist: Optional[Dict[Tuple[str, str], float]] = None
        self._warned = False

    # ── loading ──────────────────────────────────────────────────────────────
    def ensure_loaded(self) -> bool:
        if self.model.ready:
            return True
        ok = self.model.load()
        if not ok and not self._warned:
            logger.warning(f"Traffic model not found in {MODEL_DIR}. Run scripts/build_traffic_model.py all.")
            self._warned = True
        return ok

    def stop_position(self, shape_id: str, stop_id: str) -> Optional[float]:
        """Distance (m) of a stop along a shape, or None."""
        if self._stop_dist is None:
            self._stop_dist = {}
            f = MODEL_DIR / "stop_shape_dist.parquet"
            if f.exists():
                try:
                    import pyarrow.parquet as pq
                    t = pq.read_table(f, columns=["shape_id", "stop_id", "dist_m"]).to_pydict()
                    self._stop_dist = {(s, st): float(d) for s, st, d in zip(t["shape_id"], t["stop_id"], t["dist_m"])}
                except Exception as exc:  # pragma: no cover
                    logger.error(f"Could not read stop positions: {exc}")
        return self._stop_dist.get((str(shape_id), str(stop_id)))

    def status(self) -> Dict[str, Any]:
        ready = self.ensure_loaded()
        if not ready:
            return {"status": "UNTRAINED", "model_dir": str(MODEL_DIR)}
        m = self.model.meta
        return {
            "status": "READY",
            "built_at": m.get("built_at"),
            "train_days": m.get("train_days"),
            "segments": m.get("segments"),
            "segments_with_any_gps": m.get("segments_with_any_gps"),
            "cells_measured_pct": m.get("cells_measured_pct"),
            "cells_by_source": m.get("cells_by_source"),
            "estimator": m.get("estimator"),
        }

    # ── prediction ───────────────────────────────────────────────────────────
    def predict_leg_travel_time(
        self,
        route_id: str,
        shape_id: str,
        start_dist_m: float,
        end_dist_m: float,
        departure_time_seconds: int,
        is_weekend: int = 0,
    ) -> Dict[str, Any]:
        if self.ensure_loaded():
            return self.model.predict_leg(str(shape_id), float(start_dist_m), float(end_dist_m),
                                          int(departure_time_seconds), int(is_weekend))
        dist = max(100.0, abs(end_dist_m - start_dist_m))
        tt = dist / _UNTRAINED_SPEED_MPS
        return {
            "total_travel_time_s": round(tt, 1), "total_distance_m": round(dist, 1), "segment_count": 0,
            "confidence": "NONE", "provenance": "UNTRAINED", "source_mix": {"UNTRAINED": 1.0},
            "measured_share": 0.0, "lower_bound_s": round(tt * 0.7, 1), "upper_bound_s": round(tt * 1.5, 1),
            "variance": round((0.3 * tt) ** 2, 1), "free_flow_s": round(tt, 1), "congestion_index": 1.0,
            "median_samples": 0,
        }

    def leg_heat(self, shape_id: str, d0: float, d1: float, depart_s: int, weekend: int) -> list:
        if not self.ensure_loaded():
            return []
        from app.data.gtfs.repository import gtfs_repo
        return self.model.leg_heat(str(shape_id), float(d0), float(d1), int(depart_s), int(weekend),
                                   gtfs_repo.get_shape_points(str(shape_id)))

    def compare_departure_times(self, route_id: str, shape_id: str, start_dist_m: float, end_dist_m: float,
                                is_weekend: int = 0) -> List[Dict[str, Any]]:
        out = []
        for h in range(24):
            dep = h * 3600 + 30 * 60
            p = self.predict_leg_travel_time(route_id, shape_id, start_dist_m, end_dist_m, dep, is_weekend)
            tt = p["total_travel_time_s"]; dist = max(p["total_distance_m"], 1.0)
            out.append({
                "hour": h, "time_label": f"{h:02d}:30",
                "duration_seconds": tt, "duration_minutes": round(tt / 60.0, 1),
                "speed_kmh": round(dist / max(tt, 1.0) * 3.6, 1),
                "lower_bound_minutes": round(p["lower_bound_s"] / 60.0, 1),
                "upper_bound_minutes": round(p["upper_bound_s"] / 60.0, 1),
                "confidence": p["confidence"], "provenance": p["provenance"],
                "congestion_index": p["congestion_index"],
            })
        return out

    def congestion(self, hour: int, is_weekend: int, bbox=None) -> Dict[str, Any]:
        if not self.ensure_loaded():
            return {"status": "UNTRAINED", "features": [], "fields": [], "summary": {}}
        data = self.model.congestion(hour, is_weekend, bbox=bbox)
        data["status"] = "OK"
        data["cells_measured_pct"] = self.model.meta.get("cells_measured_pct")
        return data


prediction_service = TravelTimePredictionService()
