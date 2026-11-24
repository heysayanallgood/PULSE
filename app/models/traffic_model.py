"""
PULSE per-stretch traffic model (app/models/traffic_model.py)

Loads the arrays written by `scripts/build_traffic_model.py train` (memory-
mapped, so startup is instant) and answers:

  - predict_leg(shape, d0, d1, depart, weekend): travel time along a shape,
    advancing the clock stretch by stretch through the 15-min buckets
  - congestion(hour, weekend): every stretch's congestion index for a map layer

All fallbacks are computed from measured GPS at coarser levels (see
SOURCE_LEVELS); there are no typed-in speed tables.
"""
from __future__ import annotations

import json
import math
import threading
from collections import Counter
from pathlib import Path
from typing import Any, Dict, Optional

import numpy as np

MODEL_DIR_NAME = "traffic_model"

SOURCE_LEVELS = [
    "HISTORICAL",       # direct measurement: this stretch, this 15-min bucket, this day type
    "SEGMENT_HOUR",     # this stretch, same hour
    "SEGMENT_PROFILE",  # this stretch's all-day speed × network time-of-day shape
    "ROUTE_LEVEL",      # this route, this bucket
    "NETWORK_LEVEL",    # whole network, this bucket
]

_Z90 = 1.2816  # one-sided z for a p10–p90 band


class TrafficModel:
    def __init__(self, model_dir: Path):
        self.model_dir = Path(model_dir)
        self.ready = False
        self.meta: Dict[str, Any] = {}
        self._lock = threading.Lock()
        self._shape_range: Dict[str, tuple[int, int]] = {}

    def load(self) -> bool:
        with self._lock:
            if self.ready:
                return True
            d = self.model_dir
            if not (d / "tt.npy").exists():
                return False
            mm = dict(mmap_mode="r")
            self.tt = np.load(d / "tt.npy", **mm)
            self.var = np.load(d / "var.npy", **mm)
            self.samples = np.load(d / "samples.npy", **mm)
            self.source = np.load(d / "source.npy", **mm)
            self.ff_tt = np.load(d / "ff_tt.npy")
            self.length = np.load(d / "length.npy")
            self.net_pace = np.load(d / "net_pace.npy")
            self.segment_ids = np.load(d / "segment_ids.npy")
            self.shape_ids = np.load(d / "shape_ids.npy")
            self.route_ids = np.load(d / "route_ids.npy")
            self.start_dist = np.load(d / "start_dist.npy")
            self.end_dist = np.load(d / "end_dist.npy")
            self.geom = np.load(d / "geom.npy")
            gps = d / "gps_distance_m.npy"
            self.gps_distance = np.load(gps) if gps.exists() else None
            meta = d / "meta.json"
            self.meta = json.loads(meta.read_text(encoding="utf-8")) if meta.exists() else {}
            # Segments are stored sorted by (shape, sequence): index contiguous ranges.
            change = np.flatnonzero(self.shape_ids[1:] != self.shape_ids[:-1]) + 1
            starts = np.concatenate([[0], change])
            ends = np.concatenate([change, [len(self.shape_ids)]])
            self._shape_range = {str(self.shape_ids[s]): (int(s), int(e)) for s, e in zip(starts, ends)}
            self.ready = True
            return True

    # ── Prediction ───────────────────────────────────────────────────────────
    @staticmethod
    def _bucket(clock_s: float) -> int:
        return int((clock_s % 86400) // 900)

    def network_speed_mps(self, bucket: int, weekend: int) -> float:
        return 1.0 / float(self.net_pace[bucket % 96, int(bool(weekend))])

    def predict_leg(self, shape_id: str, d0: float, d1: float, depart_s: int, weekend: int) -> Dict[str, Any]:
        w = int(bool(weekend))
        lo_d, hi_d = (d0, d1) if d1 >= d0 else (d1, d0)
        rng = self._shape_range.get(str(shape_id))
        clock = float(depart_s)
        if not rng:
            dist = max(50.0, hi_d - lo_d)
            tt = dist / self.network_speed_mps(self._bucket(clock), w)
            sd = 0.35 * tt
            return self._result(tt, dist, sd * sd, 0, ["NETWORK_LEVEL"], [0], [])
        s, e = rng
        sd_ = self.start_dist[s:e]; ed_ = self.end_dist[s:e]
        sel = np.flatnonzero((ed_ > lo_d) & (sd_ < hi_d)) + s
        total_tt = 0.0; total_var = 0.0; total_dist = 0.0; sum_sd = 0.0
        sources: list[str] = []; samples: list[int] = []; per_seg = []
        for i in sel:
            seg_len = float(self.end_dist[i] - self.start_dist[i]) or float(self.length[i])
            ov = max(0.0, min(hi_d, self.end_dist[i]) - max(lo_d, self.start_dist[i]))
            if ov <= 0:
                continue
            frac = ov / max(seg_len, 1.0)
            b = self._bucket(clock)
            t = float(self.tt[i, b, w]) * frac
            v = float(self.var[i, b, w]) * frac * frac
            total_tt += t; total_var += v; total_dist += ov; clock += t; sum_sd += math.sqrt(v)
            src = SOURCE_LEVELS[int(self.source[i, b, w])]
            sources.append(src); samples.append(int(self.samples[i, b, w]))
            per_seg.append(i)
        if total_dist <= 0:
            dist = max(50.0, hi_d - lo_d)
            tt = dist / self.network_speed_mps(self._bucket(depart_s), w)
            return self._result(tt, dist, (0.35 * tt) ** 2, 0, ["NETWORK_LEVEL"], [0], [])
        # Stretches of one trip are positively correlated (a slow day is slow
        # everywhere): combine half independent, half fully correlated.
        sd = 0.5 * math.sqrt(total_var) + 0.5 * sum_sd
        return self._result(total_tt, total_dist, sd * sd, len(per_seg), sources, samples, per_seg)

    def _result(self, tt, dist, var, nseg, sources, samples, per_seg) -> Dict[str, Any]:
        sd = math.sqrt(max(var, 1.0))
        counts = Counter(sources)
        measured_share = counts.get("HISTORICAL", 0) / max(len(sources), 1)
        local_share = (counts.get("HISTORICAL", 0) + counts.get("SEGMENT_HOUR", 0) + counts.get("SEGMENT_PROFILE", 0)) / max(len(sources), 1)
        conf = "HIGH" if measured_share >= 0.6 else "MEDIUM" if local_share >= 0.6 else "LOW"
        ff = float(sum(float(self.ff_tt[i]) for i in per_seg)) if per_seg else tt
        return {
            "total_travel_time_s": round(tt, 1),
            "total_distance_m": round(dist, 1),
            "segment_count": nseg,
            "confidence": conf,
            "provenance": counts.most_common(1)[0][0] if counts else "NETWORK_LEVEL",
            "source_mix": {k: round(v / max(len(sources), 1), 3) for k, v in counts.items()},
            "measured_share": round(measured_share, 3),
            "lower_bound_s": round(max(dist / 25.0, tt - _Z90 * sd), 1),
            "upper_bound_s": round(tt + _Z90 * sd, 1),
            "variance": round(var, 1),
            "free_flow_s": round(ff, 1),
            "congestion_index": round(tt / ff, 2) if ff > 0 else 1.0,
            "median_samples": int(np.median(samples)) if samples else 0,
        }

    def leg_heat(self, shape_id: str, d0: float, d1: float, depart_s: int, weekend: int,
                 shape_points: list) -> list:
        """The leg's road geometry split into stretches, each with the congestion
        index at the moment the bus is predicted to be there (clock advanced
        stretch by stretch, as in predict_leg)."""
        rng = self._shape_range.get(str(shape_id))
        if not rng or not shape_points:
            return []
        w = int(bool(weekend))
        lo_d, hi_d = (d0, d1) if d1 >= d0 else (d1, d0)
        s, e = rng
        clock = float(depart_s)
        seg_info = {}
        for i in range(s, e):
            if self.end_dist[i] <= lo_d or self.start_dist[i] >= hi_d:
                continue
            b = self._bucket(clock)
            tt_full = float(self.tt[i, b, w])
            seg_len = float(self.end_dist[i] - self.start_dist[i]) or float(self.length[i])
            ov = max(0.0, min(hi_d, self.end_dist[i]) - max(lo_d, self.start_dist[i]))
            seg_info[i] = {
                "ci": round(tt_full / max(float(self.ff_tt[i]), 1e-3), 2),
                "speed_kmh": round(float(self.length[i]) / max(tt_full, 1e-3) * 3.6, 1),
                "measured": int(self.source[i, b, w]) == 0,
                "at": int(clock),
            }
            clock += tt_full * ov / max(seg_len, 1.0)
        starts = self.start_dist[s:e]
        runs: list = []
        cur = None
        pts = [(float(p["shape_pt_lat"]), float(p["shape_pt_lon"]), float(p.get("shape_dist_traveled") or 0.0)) for p in shape_points]
        for k in range(len(pts) - 1):
            a, b2 = pts[k], pts[k + 1]
            mid = (a[2] + b2[2]) / 2
            if mid < lo_d or mid > hi_d:
                continue
            i = s + int(max(0, np.searchsorted(starts, mid, side="right") - 1))
            info = seg_info.get(i)
            if info is None:
                continue
            if cur is None or cur["seg"] != i:
                if cur:
                    runs.append(cur)
                cur = {"seg": i, "coords": [[round(a[0], 6), round(a[1], 6)]], **info}
            cur["coords"].append([round(b2[0], 6), round(b2[1], 6)])
        if cur:
            runs.append(cur)
        for r in runs:
            r.pop("seg", None)
            t = r.pop("at") % 86400
            r["time"] = f"{t // 3600:02d}:{(t % 3600) // 60:02d}"
        return runs

    # ── Map layer ────────────────────────────────────────────────────────────
    def congestion(self, hour: int, weekend: int, min_gps_m: float = 4000.0,
                   bbox: Optional[tuple[float, float, float, float]] = None,
                   max_features: int = 12000) -> Dict[str, Any]:
        """Congestion index per stretch for one hour. Only stretches with real GPS
        coverage are returned, de-duplicated across overlapping shapes."""
        w = int(bool(weekend)); h = int(hour) % 24
        tt_h = np.asarray(self.tt[:, h * 4:(h + 1) * 4, w], dtype=np.float32).mean(axis=1)
        src_h = np.asarray(self.source[:, h * 4:(h + 1) * 4, w]).min(axis=1)
        ci = tt_h / np.maximum(self.ff_tt, 1e-3)
        speed = self.length / np.maximum(tt_h, 1e-3) * 3.6
        keep = np.ones(len(ci), dtype=bool)
        if self.gps_distance is not None:
            keep &= self.gps_distance >= min_gps_m
        g = self.geom
        if bbox:
            s, wl, n, e = bbox
            keep &= (g[:, 0] >= s) & (g[:, 0] <= n) & (g[:, 1] >= wl) & (g[:, 1] <= e)
        idx = np.flatnonzero(keep)
        # De-duplicate stretches drawn on the same road by several routes (~60 m grid key).
        key = np.round(g[idx, :2] * 550).astype(np.int64)
        key2 = np.round(g[idx, 2:] * 550).astype(np.int64)
        combo = key[:, 0] * 10_000_000_000 + key[:, 1] * 100_000 + (key2[:, 0] % 1000) * 100 + (key2[:, 1] % 100)
        order = np.argsort(-(self.gps_distance[idx] if self.gps_distance is not None else np.zeros(len(idx))))
        _, first = np.unique(combo[order], return_index=True)
        idx = idx[order[first]]
        if len(idx) > max_features:
            idx = idx[np.argsort(-self.gps_distance[idx])[:max_features]] if self.gps_distance is not None else idx[:max_features]
        feats = [[round(float(g[i, 0]), 5), round(float(g[i, 1]), 5), round(float(g[i, 2]), 5), round(float(g[i, 3]), 5),
                  round(float(ci[i]), 2), round(float(speed[i]), 1), int(src_h[i] == 0)] for i in idx]
        net_speed = [round(3.6 / float(np.mean(self.net_pace[x * 4:(x + 1) * 4, w])), 1) for x in range(24)]
        return {
            "hour": h, "is_weekend": w,
            "fields": ["lat0", "lon0", "lat1", "lon1", "congestion_index", "speed_kmh", "measured"],
            "features": feats,
            "summary": {
                "stretches": len(feats),
                "median_speed_kmh": round(float(np.median(speed[idx])), 1) if len(idx) else None,
                "share_slowed_2x": round(float(np.mean(ci[idx] >= 2.0)), 3) if len(idx) else None,
                "share_measured": round(float(np.mean(src_h[idx] == 0)), 3) if len(idx) else None,
            },
            "network_speed_kmh_by_hour": net_speed,
        }
