"""BoT-SORT multi-object tracker (Aharon, Orfaig, Bobrovsky, 2022).

BoT-SORT is ByteTrack's association scheme plus three changes:

1. **Kalman state (cx, cy, w, h)** with width/height-proportional noise, which
   fits boxes better than ByteTrack's aspect-ratio state.
2. **Camera motion compensation (GMC)**: the affine motion between frames is
   estimated from background keypoints and applied to predicted track states
   before matching, so camera shake or panning does not break IoU matching.
3. **IoU-appearance fusion (optional)**: for pairs that are already close
   (IoU distance below ``proximity_thresh``) and look alike (similarity at
   least ``appearance_thresh``), the cost is the smaller of the IoU cost and
   the appearance cost. Appearance can make a close match cheaper; it can
   never create a match between far-apart boxes.

Stage-1 and stage-3 IoU costs are fused with the detection score, as in the
reference implementation, and tracks that duplicate an older lost track are
removed. Defaults follow the reference (appearance off, sparse optical flow
GMC); thresholds follow CV-Scope's ByteTrack defaults so the two trackers are
directly comparable.

Privacy: appearance vectors are held in memory only while a track is alive,
used only to keep its anonymous id within the current run, and discarded when
the track ends. They are never stored or compared across runs or cameras.
"""

from __future__ import annotations

import time
from dataclasses import asdict, dataclass

import numpy as np

from pathscope.spatial.geometry import box_iou_matrix
from pathscope.vision.trackers.appearance import AppearanceEncoder, create_encoder
from pathscope.vision.trackers.base import TrackerStats
from pathscope.vision.trackers.bytetrack import ByteTrack, ByteTrackSettings, _STrack
from pathscope.vision.trackers.gmc import GMC_METHODS, GlobalMotionCompensation
from pathscope.vision.trackers.kalman import KalmanFilterXYWH, warp_state
from pathscope.vision.types import Detection

APPEARANCE_CHOICES = ("none", "histogram", "cnn")


@dataclass
class BoTSORTSettings(ByteTrackSettings):
    new_track_thresh: float = 0.6  # minimum score for an unmatched detection to start a track
    fuse_score: bool = True  # weight IoU similarity by detection score (stages 1 and 3)
    proximity_thresh: float = 0.5  # appearance is only considered when IoU distance is below this
    gmc_method: str = "sparseOptFlow"  # sparseOptFlow | orb | ecc | none
    appearance: str = "none"  # none | histogram | cnn | onnx:<file in models/reid>
    appearance_thresh: float | None = None  # minimum similarity (0..1); None = encoder default
    feature_momentum: float = 0.9  # EMA weight of the previous appearance vector
    remove_duplicates: bool = True

    def validate(self) -> None:
        super().validate()
        for name in ("new_track_thresh", "proximity_thresh"):
            v = getattr(self, name)
            if not 0.0 <= v <= 1.0:
                raise ValueError(f"tracker setting '{name}' must be between 0 and 1")
        if self.gmc_method not in GMC_METHODS:
            raise ValueError(f"camera motion compensation must be one of: {', '.join(GMC_METHODS)}")
        if self.appearance not in APPEARANCE_CHOICES and not self.appearance.startswith("onnx:"):
            raise ValueError("appearance must be 'none', 'histogram', 'cnn' or 'onnx:<model file>'")
        if self.appearance_thresh is not None and not 0.0 <= self.appearance_thresh <= 1.0:
            raise ValueError("tracker setting 'appearance_thresh' must be between 0 and 1")
        if not 0.0 <= self.feature_momentum < 1.0:
            raise ValueError("tracker setting 'feature_momentum' must be in [0, 1)")


class BoTSORT(ByteTrack):
    id = "botsort"
    name = "BoT-SORT"
    settings_cls = BoTSORTSettings

    def __init__(
        self,
        settings: BoTSORTSettings | None = None,
        device: str = "cpu",
        models_dir: str | None = None,
        encoder: AppearanceEncoder | None = None,
    ) -> None:
        super().__init__(settings)
        s: BoTSORTSettings = self.settings  # type: ignore[assignment]
        self.gmc = GlobalMotionCompensation(s.gmc_method) if s.gmc_method != "none" else None
        self.encoder = encoder if encoder is not None else create_encoder(s.appearance, device=device, models_dir=models_dir)
        self.min_similarity = (
            s.appearance_thresh if s.appearance_thresh is not None
            else (self.encoder.default_min_similarity if self.encoder else None)
        )
        self._warp = np.eye(2, 3)
        self._feats: dict[int, np.ndarray] = {}
        self._last_parts: tuple[np.ndarray, np.ndarray] | None = None
        self._assisted = 0
        self._duplicates = 0
        self._feat_calls = 0
        self._feat_ms = 0.0

    def reset(self) -> None:
        super().reset()
        if self.gmc is not None:
            self.gmc.reset()
        self._feats = {}
        self._assisted = self._duplicates = self._feat_calls = 0
        self._feat_ms = 0.0

    def close(self) -> None:
        if self.encoder is not None:
            self.encoder.close()

    def describe(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "settings": asdict(self.settings),
            "camera_motion": self.gmc.method if self.gmc else "none",
            "appearance": self.encoder.describe() if self.encoder else None,
            "min_appearance_similarity": self.min_similarity,
        }

    def stats(self) -> TrackerStats:
        st = super().stats()
        extra: dict = {"camera_motion_method": "none"}
        if self.gmc is not None:
            extra.update(self.gmc.stats())
        extra["appearance_method"] = self.encoder.id if self.encoder else "none"
        if self.encoder is not None:
            extra["appearance_assisted_matches"] = self._assisted
            extra["appearance_ms_mean"] = round(self._feat_ms / max(self._feat_calls, 1), 2)
        extra["duplicate_tracks_removed"] = self._duplicates
        st.extra = extra
        return st

    # ------------------------------------------------------------------ hooks
    def _make_kf(self) -> KalmanFilterXYWH:
        return KalmanFilterXYWH()

    def _prepare(self, frame: np.ndarray | None, high: list[Detection], detections: list[Detection]) -> None:
        self._warp = self.gmc.apply(frame, [d.box for d in detections]) if self.gmc is not None else np.eye(2, 3)
        self._feats = {}
        if self.encoder is not None and frame is not None and high:
            t0 = time.perf_counter()
            feats = self.encoder.encode(frame, [d.box for d in high])
            self._feat_ms += (time.perf_counter() - t0) * 1000.0
            self._feat_calls += 1
            for d, f in zip(high, feats, strict=True):
                if f is not None:
                    self._feats[id(d)] = f

    def _compensate(self, tracks: list[_STrack]) -> None:
        if not tracks or np.allclose(self._warp, np.eye(2, 3), atol=1e-9):
            return
        for tr in tracks:
            tr.mean, tr.cov = warp_state(tr.mean, tr.cov, self._warp)

    def _cost(self, tracks: list[_STrack], dets: list[Detection], stage: int) -> np.ndarray:
        s: BoTSORTSettings = self.settings  # type: ignore[assignment]
        cost = 1.0 - box_iou_matrix([tr.box for tr in tracks], [d.box for d in dets])
        if stage == 2:  # low-score detections: plain IoU, as in the reference
            return cost
        far = cost > s.proximity_thresh
        if s.fuse_score:
            scores = np.array([d.confidence for d in dets], dtype=np.float64)[None, :]
            cost = 1.0 - (1.0 - cost) * scores
        if self.encoder is None or self.min_similarity is None:
            return cost
        emb = np.ones_like(cost)
        t_idx = [i for i, tr in enumerate(tracks) if tr.feature is not None]
        d_idx = [j for j, d in enumerate(dets) if id(d) in self._feats]
        if t_idx and d_idx:
            tf = np.stack([tracks[i].feature for i in t_idx])
            df = np.stack([self._feats[id(dets[j])] for j in d_idx])
            emb[np.ix_(t_idx, d_idx)] = np.clip((1.0 - tf @ df.T) / 2.0, 0.0, 1.0)  # cosine distance / 2
        emb[emb > 1.0 - self.min_similarity] = 1.0
        emb[far] = 1.0
        self._last_parts = (cost, emb)
        return np.minimum(cost, emb)

    def _match(self, tracks, dets, cost_thresh, stage=1):
        self._last_parts = None
        matches, u_t, u_d = super()._match(tracks, dets, cost_thresh, stage)
        if self._last_parts is not None:
            iou_cost, emb = self._last_parts
            self._assisted += sum(1 for ti, di in matches if emb[ti, di] < iou_cost[ti, di])
            self._last_parts = None
        return matches, u_t, u_d

    def _on_matched(self, tr: _STrack, det: Detection, stage: int) -> None:
        f = self._feats.get(id(det))
        if f is None:
            return
        if tr.feature is None:
            tr.feature = f
            return
        m = self.settings.feature_momentum  # type: ignore[attr-defined]
        v = m * tr.feature + (1.0 - m) * f
        n = float(np.linalg.norm(v))
        tr.feature = (v / n).astype(np.float32) if n > 1e-12 else f

    def _on_created(self, tr: _STrack, det: Detection) -> None:
        tr.feature = self._feats.get(id(det))

    def _can_start(self, det: Detection) -> bool:
        return det.confidence >= self.settings.new_track_thresh  # type: ignore[attr-defined]

    def _before_expire(self) -> None:
        """Drop the younger of a live track and a lost track that overlap almost completely."""
        if not self.settings.remove_duplicates:  # type: ignore[attr-defined]
            return
        live = [tr for tr in self._tracks if tr.state in ("tracked", "tentative")]
        lost = [tr for tr in self._tracks if tr.state == "lost"]
        if not live or not lost:
            return
        iou = box_iou_matrix([tr.box for tr in live], [tr.box for tr in lost])
        for p, q in zip(*np.nonzero(iou > 0.85), strict=True):
            a, b = live[p], lost[q]
            if a.state == "removed" or b.state == "removed":
                continue
            if (a.last_frame - a.first_frame) > (b.last_frame - b.first_frame):
                b.state = "removed"
            else:
                a.state = "removed"
            self._duplicates += 1


__all__ = ["BoTSORT", "BoTSORTSettings", "APPEARANCE_CHOICES"]
