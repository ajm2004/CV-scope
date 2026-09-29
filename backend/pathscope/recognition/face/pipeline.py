"""Per-track face recognition.

The core tracker gives anonymous person tracks. For each of them this
pipeline, at a throttled rate, looks for a face in the head region, scores its
quality, aligns and embeds it, keeps the best observations in a buffer and,
once enough usable observations exist, matches the aggregated embedding
against the enrolled identities. A sufficiently confident match associates
the identity with the track; the association is re-validated periodically
and dropped or switched after repeated disagreement. Recognition is never
recomputed every frame.
"""

from __future__ import annotations

import time
from collections import deque
from dataclasses import dataclass, field
from datetime import date

import cv2
import numpy as np

from pathscope.domain.entities import (
    STATUS_INSUFFICIENT,
    STATUS_POSSIBLE,
    STATUS_RECOGNIZED,
    STATUS_UNKNOWN,
    STATUS_UNRESOLVED,
    EntityRef,
    anonymous_entity,
)
from pathscope.recognition.common.buffer import ObservationBuffer
from pathscope.recognition.common.quality import crop_with_margin
from pathscope.recognition.common.types import (
    POSSIBLE_MATCH,
    RECOGNIZED,
    FaceObservation,
    MatchResult,
)
from pathscope.recognition.face.matcher import FaceMatcher
from pathscope.recognition.face.stack import FaceStack
from pathscope.vision.types import Track


@dataclass
class FacePipelineConfig:
    min_face_px: float = 40.0
    min_quality: float = 0.45
    min_observations: int = 3
    max_observations: int = 12
    interval_s: float = 0.4
    revalidate_s: float = 15.0
    decision_timeout_s: float = 8.0
    max_per_frame: int = 4
    min_person_px: float = 60.0  # person box height below which no face can be big enough
    store_crops: bool = False

    @classmethod
    def from_settings(cls, cfg: dict) -> FacePipelineConfig:
        c = cls()
        for k in ("min_face_px", "min_quality", "interval_s", "revalidate_s", "decision_timeout_s"):
            if cfg.get(k) is not None:
                setattr(c, k, float(cfg[k]))
        for k in ("min_observations", "max_observations", "max_per_frame"):
            if cfg.get(k) is not None:
                setattr(c, k, int(cfg[k]))
        c.min_person_px = max(40.0, c.min_face_px * 1.5)
        c.store_crops = bool(cfg.get("store_crops", False))
        return c


@dataclass
class TrackFaceState:
    track_id: int
    first_seen_t: float
    buffer: ObservationBuffer
    last_attempt_t: float = -1e9
    face_seen: bool = False
    last_quality: dict | None = None
    identity_id: str | None = None
    display_name: str | None = None
    confidence: float | None = None
    status: str = STATUS_UNRESOLVED
    settled: bool = False
    resolved_at: float | None = None
    revalidate_at: float = 0.0
    disagreements: int = 0
    decisions: int = 0
    possible_reported: bool = False
    last_result: MatchResult | None = None
    recognition_event_id: int | None = None
    history: deque = field(default_factory=lambda: deque(maxlen=8))


@dataclass
class FaceStepResult:
    events: list[dict]
    attempts: int
    faces: int


class FaceRecognitionPipeline:
    module = "face"

    def __init__(self, stack: FaceStack, matcher: FaceMatcher, cfg: FacePipelineConfig | None = None) -> None:
        self.stack = stack
        self.matcher = matcher
        self.cfg = cfg or FacePipelineConfig()
        self.states: dict[int, TrackFaceState] = {}
        self.stats = {"attempts": 0, "faces_detected": 0, "usable": 0, "decisions": 0, "recognized": 0, "possible": 0, "unknown": 0, "insufficient": 0, "identity_changed": 0, "identity_cleared": 0, "detect_ms": 0.0, "embed_ms": 0.0}

    # ------------------------------------------------------------- entity interface
    def resolve(self, track_id: int, object_class: str) -> EntityRef:
        st = self.states.get(track_id)
        if st is None:
            return anonymous_entity(track_id, object_class)
        if st.identity_id is not None:
            return EntityRef(
                "enrolled_person", track_id, object_class, identity_id=st.identity_id, display_name=st.display_name,
                confidence=st.confidence, status=STATUS_RECOGNIZED, settled=True, resolved_at=st.resolved_at,
                recognition_event_id=st.recognition_event_id,
            )
        return anonymous_entity(track_id, object_class, status=st.status, settled=st.settled)

    def forget(self, track_id: int) -> None:
        self.states.pop(track_id, None)

    def overlay(self, track_id: int) -> dict | None:
        st = self.states.get(track_id)
        if st is None:
            return None
        d: dict = {"status": st.status}
        if st.identity_id is not None:
            d["identity"] = st.display_name
            d["identity_id"] = st.identity_id
            d["confidence"] = round(st.confidence or 0.0, 3)
        return d

    # ------------------------------------------------------------- main step
    def observe(self, frame: np.ndarray, tracks: list[Track], t: float, frame_index: int, wall_time: float | None = None) -> FaceStepResult:
        wall = wall_time or time.time()
        fh, fw = frame.shape[:2]
        events: list[dict] = []
        candidates: list[tuple[int, float, Track]] = []
        for tr in tracks:
            if tr.class_name != "person" or tr.state != "tracked" or not tr.updated:
                continue
            if (tr.box[3] - tr.box[1]) < self.cfg.min_person_px:
                continue
            st = self.states.get(tr.track_id)
            if st is None:
                st = self.states[tr.track_id] = TrackFaceState(tr.track_id, t, ObservationBuffer(self.cfg.max_observations))
            if t - st.last_attempt_t < self.cfg.interval_s:
                continue
            if st.identity_id is not None and t < st.revalidate_at:
                continue
            priority = 0 if st.identity_id is None else 1
            candidates.append((priority, -(tr.box[3] - tr.box[1]), tr))
        candidates.sort(key=lambda c: (c[0], c[1]))
        attempts = 0
        faces = 0
        for _, _, tr in candidates[: self.cfg.max_per_frame]:
            st = self.states[tr.track_id]
            st.last_attempt_t = t
            attempts += 1
            self.stats["attempts"] += 1
            obs = self._observe_track(frame, tr, st, t, frame_index, fw, fh)
            if obs is not None:
                faces += 1
            events.extend(self._decide(st, t, frame_index, wall, tr.class_name))
        # tracks seen for too long without a usable face are settled as insufficient
        for tr in tracks:
            st = self.states.get(tr.track_id)
            if st is None or st.identity_id is not None or st.settled:
                continue
            if st.buffer.usable_seen == 0 and t - st.first_seen_t >= self.cfg.decision_timeout_s:
                st.status = STATUS_INSUFFICIENT
                st.settled = True
                self.stats["insufficient"] += 1
                st.history.append({"t": round(t, 2), "result": STATUS_INSUFFICIENT, "reason": "no usable face"})
        return FaceStepResult(events, attempts, faces)

    def _head_region(self, tr: Track, fw: int, fh: int) -> tuple[float, float, float, float]:
        x1, y1, x2, y2 = tr.box
        w, h = x2 - x1, y2 - y1
        hx1 = max(0.0, x1 - 0.15 * w)
        hx2 = min(float(fw), x2 + 0.15 * w)
        hy1 = max(0.0, y1 - 0.05 * h)
        hy2 = min(float(fh), y1 + 0.5 * h)
        return hx1, hy1, hx2, hy2

    def _observe_track(self, frame: np.ndarray, tr: Track, st: TrackFaceState, t: float, frame_index: int, fw: int, fh: int) -> FaceObservation | None:
        region = self._head_region(tr, fw, fh)
        crop, (ox, oy) = crop_with_margin(frame, region, margin=0.0, min_size=24)
        if crop is None:
            st.face_seen = False
            return None
        t0 = time.perf_counter()
        dets = self.stack.detector.detect(crop)
        self.stats["detect_ms"] += (time.perf_counter() - t0) * 1000.0
        if not dets:
            st.face_seen = False
            st.last_quality = None
            return None
        det = dets[0]  # largest
        # back to frame coordinates
        det.box = (det.box[0] + ox, det.box[1] + oy, det.box[2] + ox, det.box[3] + oy)
        if det.landmarks is not None:
            det.landmarks = det.landmarks + np.array([ox, oy], dtype=np.float32)
        st.face_seen = True
        self.stats["faces_detected"] += 1
        quality = self.stack.quality.assess(frame, det, fw, fh)
        st.last_quality = quality.to_dict()
        obs = FaceObservation(tr.track_id, frame_index, t, det, quality)
        if quality.usable and det.landmarks is not None:
            aligned = self.stack.aligner.align(frame, det.landmarks)
            t1 = time.perf_counter()
            emb = self.stack.embedder.embed(aligned)
            self.stats["embed_ms"] += (time.perf_counter() - t1) * 1000.0
            if emb is None:
                quality.usable = False
                quality.reasons.append("embedding_failed")
            else:
                obs.embedding = emb
                if self.cfg.store_crops:
                    obs.aligned = aligned
                self.stats["usable"] += 1
        st.buffer.add(obs, quality.score, obs.embedding is not None, quality.reasons)
        return obs

    def _decide(self, st: TrackFaceState, t: float, frame_index: int, wall: float, object_class: str) -> list[dict]:
        buf = st.buffer
        if buf.n_kept < self.cfg.min_observations:
            return []
        emb = buf.aggregate_embeddings()
        if emb is None:
            return []
        result = self.matcher.match(emb, date.today())
        st.last_result = result
        st.decisions += 1
        self.stats["decisions"] += 1
        st.history.append({"t": round(t, 2), "frame": frame_index, **result.to_dict(), "kept": buf.n_kept, "best_quality": round(buf.best_quality, 3)})
        events: list[dict] = []
        if result.status == RECOGNIZED and result.best is not None:
            cand = result.best
            if st.identity_id is None:
                st.identity_id, st.display_name, st.confidence = cand.identity_id, cand.display_name, cand.similarity
                st.status, st.settled, st.resolved_at = STATUS_RECOGNIZED, True, t
                st.disagreements = 0
                self.stats["recognized"] += 1
                events.append(self._event("recognized", st, result, t, frame_index, wall, object_class))
            elif st.identity_id == cand.identity_id:
                st.confidence = max(st.confidence or 0.0, cand.similarity)
                st.disagreements = 0
            else:
                st.disagreements += 1
                if st.disagreements >= 2:
                    previous = st.identity_id
                    st.identity_id, st.display_name, st.confidence = cand.identity_id, cand.display_name, cand.similarity
                    st.resolved_at = t
                    st.disagreements = 0
                    self.stats["identity_changed"] += 1
                    events.append(self._event("identity_changed", st, result, t, frame_index, wall, object_class, extra={"previous_identity_id": previous}))
            self._schedule_revalidation(st, t)
            buf.reset()  # decide again only on fresh evidence
        elif result.status == POSSIBLE_MATCH:
            if st.identity_id is None:
                st.status = STATUS_POSSIBLE
                # keep collecting; after twice the required observations the module has decided: possible only
                if buf.usable_seen >= 2 * self.cfg.min_observations:
                    st.settled = True
                if not st.possible_reported:
                    st.possible_reported = True
                    self.stats["possible"] += 1
                    events.append(self._event("possible_match", st, result, t, frame_index, wall, object_class))
                buf.reset(keep_best=self.cfg.min_observations - 1)
            else:
                st.disagreements = 0  # a weak re-check neither confirms nor contradicts
                self._schedule_revalidation(st, t)
                buf.reset()
        else:  # UNKNOWN
            if st.identity_id is None:
                st.status = STATUS_UNKNOWN
                st.settled = True
                self.stats["unknown"] += 1
                buf.reset(keep_best=self.cfg.min_observations - 1)
            else:
                st.disagreements += 1
                if st.disagreements >= 2:
                    previous, previous_name = st.identity_id, st.display_name
                    st.identity_id, st.display_name, st.confidence = None, None, None
                    st.status, st.settled = STATUS_UNKNOWN, True
                    st.recognition_event_id = None
                    self.stats["identity_cleared"] += 1
                    events.append(self._event("identity_cleared", st, result, t, frame_index, wall, object_class, extra={"previous_identity_id": previous, "previous_display_name": previous_name}))
                self._schedule_revalidation(st, t)
                buf.reset()
        return events

    def _schedule_revalidation(self, st: TrackFaceState, t: float) -> None:
        """Re-check a recognized track after ``revalidate_s``; sooner while a
        disagreement is open, so a tracker id switch is corrected quickly."""
        interval = self.cfg.revalidate_s / 3.0 if st.disagreements else self.cfg.revalidate_s
        st.revalidate_at = t + interval

    def _event(self, kind: str, st: TrackFaceState, result: MatchResult, t: float, frame_index: int, wall: float, object_class: str, extra: dict | None = None) -> dict:
        buf = st.buffer
        best = buf.best
        crop_jpeg = None
        if self.cfg.store_crops and best is not None and getattr(best, "aligned", None) is not None:
            ok, enc = cv2.imencode(".jpg", best.aligned, [cv2.IMWRITE_JPEG_QUALITY, 85])
            crop_jpeg = enc.tobytes() if ok else None
        summary = buf.summary()
        return {
            "module": "face",
            "kind": kind,
            "track_id": st.track_id,
            "object_class": object_class,
            "person_id": st.identity_id if kind != "identity_cleared" else None,
            "display_name": st.display_name if kind != "identity_cleared" else None,
            "candidate_id": result.best.identity_id if result.best else None,
            "candidate_name": result.best.display_name if result.best else None,
            "similarity": round(result.best.similarity, 4) if result.best else None,
            "second_similarity": round(result.second_similarity, 4),
            "status": result.status,
            "quality": summary.get("best_quality"),
            "n_observations": summary.get("observations"),
            "usable_observations": summary.get("usable"),
            "best_frame_index": summary.get("best_frame"),
            "model_version": f"{self.stack.detector.model_version}+{self.stack.embedder.model_version}",
            "frame_index": frame_index,
            "media_time_s": round(t, 3),
            "wall_time": wall,
            "context": {"threshold": result.threshold, "possible_threshold": result.possible_threshold, "rejected": summary.get("rejected"), **(extra or {})},
            "crop_jpeg": crop_jpeg,
        }

    # ------------------------------------------------------------- diagnostics
    def diagnostics(self) -> dict:
        tracks = []
        for tid, st in self.states.items():
            last = st.last_result.to_dict() if st.last_result else {}
            tracks.append(
                {
                    "track_id": tid,
                    "face_detected": st.face_seen,
                    "quality": st.last_quality,
                    **st.buffer.summary(),
                    "candidate": last.get("candidate"),
                    "similarity": last.get("similarity"),
                    "second_similarity": last.get("second_similarity"),
                    "result": st.status,
                    "identity": st.display_name,
                    "identity_id": st.identity_id,
                    "settled": st.settled,
                    "revalidate_at": round(st.revalidate_at, 2) if st.identity_id else None,
                    "history": list(st.history),
                }
            )
        return {
            "module": "face",
            "model": self.stack.describe(),
            "matcher": self.matcher.describe(),
            "stats": {k: (round(v, 1) if isinstance(v, float) else v) for k, v in self.stats.items()},
            "tracks": tracks,
        }

    def describe(self) -> dict:
        return {"stack": self.stack.describe(), "matcher": self.matcher.describe(), "config": self.cfg.__dict__}

    def close(self) -> None:
        self.stack.close()
