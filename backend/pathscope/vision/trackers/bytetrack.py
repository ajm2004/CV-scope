"""ByteTrack multi-object tracker (Zhang et al., 2022) implemented in numpy.

Two-stage association: high-confidence detections are matched against all
live tracks first; low-confidence detections are then matched against the
still-unmatched tracks, which keeps occluded objects alive. Unmatched
high-confidence detections start new tracks that must be confirmed before they
are reported; tracks that disappear are kept in a ``lost`` state for
``track_buffer`` frames so they can be reacquired with the same id.

The association loop is written with small hook methods so BoT-SORT
(``botsort.py``) can reuse it and add camera motion compensation, appearance
matching and its own Kalman state without duplicating the skeleton.
"""

from __future__ import annotations

import typing
from dataclasses import asdict, dataclass, fields

import numpy as np
from scipy.optimize import linear_sum_assignment

from pathscope.spatial.geometry import box_iou_matrix
from pathscope.vision.trackers.base import Tracker, TrackerStats, TrackerUpdate
from pathscope.vision.trackers.kalman import KalmanBoxFilter
from pathscope.vision.types import Detection, Track


def _coerce(name: str, value, hint):
    """Coerce a JSON value to the annotated type of a settings field."""
    args = typing.get_args(hint)
    if value is None:
        if type(None) in args:
            return None
        raise ValueError(f"tracker setting '{name}' cannot be empty")
    base = next((a for a in args if a is not type(None)), hint) if args else hint
    try:
        if base is bool:
            if isinstance(value, str):
                return value.strip().lower() in ("1", "true", "yes", "on")
            return bool(value)
        if base is int:
            if isinstance(value, float) and not value.is_integer():
                raise ValueError
            return int(value)
        if base is float:
            return float(value)
        if base is str:
            return str(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"tracker setting '{name}' has an invalid value: {value!r}") from exc
    return value


@dataclass
class ByteTrackSettings:
    track_thresh: float = 0.5  # detections above this start / continue tracks in stage 1
    match_thresh: float = 0.8  # max IoU cost (1 - IoU) accepted in stage 1
    low_thresh: float = 0.1  # minimum score for stage-2 detections
    track_buffer: int = 30  # frames a lost track is kept before removal
    min_hits: int = 2  # frames before a new track is reported (1 = immediately)
    min_box_area: float = 10.0
    # Lower bound: even when the stream FPS drops, keep lost tracks at least this many frames
    min_track_buffer: int = 10

    @classmethod
    def from_dict(cls, d: dict | None):
        """Build settings from a JSON dict: unknown keys are ignored, values are
        coerced to the field types and validated (``ValueError`` on bad input)."""
        d = d or {}
        hints = typing.get_type_hints(cls)
        known = {f.name for f in fields(cls)}
        values = {k: _coerce(k, v, hints[k]) for k, v in d.items() if k in known}
        obj = cls(**values)
        obj.validate()
        return obj

    def validate(self) -> None:
        for name in ("track_thresh", "match_thresh", "low_thresh"):
            v = getattr(self, name)
            if not 0.0 <= v <= 1.0:
                raise ValueError(f"tracker setting '{name}' must be between 0 and 1")
        if self.low_thresh > self.track_thresh:
            raise ValueError("tracker setting 'low_thresh' must not exceed 'track_thresh'")
        if self.track_buffer < 1 or self.min_track_buffer < 1:
            raise ValueError("tracker setting 'track_buffer' must be at least 1 frame")
        if self.min_hits < 1:
            raise ValueError("tracker setting 'min_hits' must be at least 1")
        if self.min_box_area < 0:
            raise ValueError("tracker setting 'min_box_area' must not be negative")


class _STrack:
    __slots__ = (
        "track_id", "kf", "mean", "cov", "score", "class_name", "class_id", "state", "hits", "age",
        "frames_since_update", "first_frame", "last_frame", "first_time", "last_time",
        "score_sum", "score_n", "lost_count", "class_votes", "feature",
    )

    def __init__(self, det: Detection, kf: KalmanBoxFilter, frame_index: int, t: float) -> None:
        self.kf = kf
        self.mean, self.cov = kf.initiate(kf.measure(det.box))
        self.track_id = 0
        self.score = det.confidence
        self.class_name = det.class_name
        self.class_id = det.class_id
        self.state = "tentative"
        self.hits = 1
        self.age = 1
        self.frames_since_update = 0
        self.first_frame = frame_index
        self.last_frame = frame_index
        self.first_time = t
        self.last_time = t
        self.score_sum = det.confidence
        self.score_n = 1
        self.lost_count = 0
        self.class_votes: dict[str, float] = {det.class_name: det.confidence}
        # Smoothed appearance vector (BoT-SORT only). In memory only; never persisted.
        self.feature: np.ndarray | None = None

    @property
    def box(self) -> tuple[float, float, float, float]:
        return self.kf.to_box(self.mean)

    def update_with(self, det: Detection, frame_index: int, t: float) -> None:
        self.mean, self.cov = self.kf.update(self.mean, self.cov, self.kf.measure(det.box))
        self.score = det.confidence
        self.hits += 1
        self.frames_since_update = 0
        self.last_frame = frame_index
        self.last_time = t
        self.score_sum += det.confidence
        self.score_n += 1
        self.class_votes[det.class_name] = self.class_votes.get(det.class_name, 0.0) + det.confidence
        # Majority (confidence-weighted) class keeps a track stable when the detector flickers
        self.class_name = max(self.class_votes.items(), key=lambda kv: kv[1])[0]
        self.class_id = det.class_id if det.class_name == self.class_name else self.class_id

    @property
    def mean_confidence(self) -> float:
        return self.score_sum / max(self.score_n, 1)


class ByteTrack(Tracker):
    id = "bytetrack"
    name = "ByteTrack"
    settings_cls = ByteTrackSettings

    def __init__(self, settings: ByteTrackSettings | None = None) -> None:
        self.settings = settings or self.settings_cls()
        self.kf = self._make_kf()
        self._tracks: list[_STrack] = []
        self._next_id = 1
        self._stats = TrackerStats()

    def reset(self) -> None:
        self._tracks = []
        self._next_id = 1
        self._stats = TrackerStats()

    def stats(self) -> TrackerStats:
        self._stats.active_tracks = sum(1 for t in self._tracks if t.state == "tracked")
        self._stats.lost_tracks = sum(1 for t in self._tracks if t.state == "lost")
        return self._stats

    def describe(self) -> dict:
        return {"id": self.id, "name": self.name, "settings": asdict(self.settings)}

    # ------------------------------------------------------------------ hooks
    def _make_kf(self) -> KalmanBoxFilter:
        return KalmanBoxFilter()

    def _prepare(self, frame: np.ndarray | None, high: list[Detection], detections: list[Detection]) -> None:
        """Called once per frame before association (BoT-SORT: camera motion, features)."""

    def _compensate(self, tracks: list[_STrack]) -> None:
        """Adjust predicted track states for camera motion (BoT-SORT)."""

    def _cost(self, tracks: list[_STrack], dets: list[Detection], stage: int) -> np.ndarray:
        """Association cost for stage 1 (high dets), 2 (low dets) or 3 (tentative tracks)."""
        return 1.0 - box_iou_matrix([tr.box for tr in tracks], [d.box for d in dets])

    def _on_matched(self, tr: _STrack, det: Detection, stage: int) -> None:
        """A track was updated with a detection (BoT-SORT: appearance update)."""

    def _on_created(self, tr: _STrack, det: Detection) -> None:
        """A tentative track was created from a detection."""

    def _can_start(self, det: Detection) -> bool:
        """May an unmatched high-confidence detection start a new track?"""
        return True

    def _before_expire(self) -> None:
        """Last chance to mark tracks removed before the lifecycle cleanup."""

    # ------------------------------------------------------------------
    def update(self, detections: list[Detection], frame_index: int, t: float, frame: np.ndarray | None = None) -> TrackerUpdate:
        s = self.settings
        detections = [d for d in detections if d.area >= s.min_box_area]

        # Predict every live track forward
        for tr in self._tracks:
            tr.mean, tr.cov = self.kf.predict(tr.mean, tr.cov)
            tr.age += 1
            tr.frames_since_update += 1

        high = [d for d in detections if d.confidence >= s.track_thresh]
        low = [d for d in detections if s.low_thresh <= d.confidence < s.track_thresh]
        self._prepare(frame, high, detections)
        self._compensate(self._tracks)

        confirmed = [tr for tr in self._tracks if tr.state in ("tracked", "lost")]
        tentative = [tr for tr in self._tracks if tr.state == "tentative"]

        started: list[Track] = []
        reacquired: list[Track] = []
        lost: list[Track] = []
        removed: list[Track] = []

        # ---- stage 1: high-confidence detections vs confirmed tracks
        m1, u_tracks, u_high = self._match(confirmed, high, s.match_thresh, stage=1)
        for ti, di in m1:
            tr = confirmed[ti]
            was_lost = tr.state == "lost"
            tr.update_with(high[di], frame_index, t)
            self._on_matched(tr, high[di], 1)
            tr.state = "tracked"
            if was_lost:
                self._stats.reacquisitions += 1
                reacquired.append(self._public(tr, frame_index, t))

        # ---- stage 2: low-confidence detections vs remaining *tracked* tracks
        remaining_tracked = [confirmed[i] for i in u_tracks if confirmed[i].state == "tracked"]
        m2, u_tracks2, _u_low = self._match(remaining_tracked, low, 0.5, stage=2)
        for ti, di in m2:
            remaining_tracked[ti].update_with(low[di], frame_index, t)
            self._on_matched(remaining_tracked[ti], low[di], 2)
            remaining_tracked[ti].state = "tracked"
        for i in u_tracks2:
            tr = remaining_tracked[i]
            tr.state = "lost"
            tr.lost_count += 1
            self._stats.lost_events += 1
            lost.append(self._public(tr, frame_index, t))

        # ---- stage 3: tentative tracks vs still-unmatched high detections
        unmatched_high = [high[i] for i in u_high]
        m3, u_tent, u_high3 = self._match(tentative, unmatched_high, 0.7, stage=3)
        for ti, di in m3:
            tr = tentative[ti]
            tr.update_with(unmatched_high[di], frame_index, t)
            self._on_matched(tr, unmatched_high[di], 3)
            if tr.hits >= s.min_hits:
                tr.state = "tracked"
                self._assign_id(tr)
                started.append(self._public(tr, frame_index, t))
        for i in u_tent:
            tentative[i].state = "removed"  # tentative tracks die immediately

        # ---- new tracks
        for i in u_high3:
            det = unmatched_high[i]
            if not self._can_start(det):
                continue
            tr = _STrack(det, self.kf, frame_index, t)
            self._on_created(tr, det)
            if s.min_hits <= 1:
                tr.state = "tracked"
                self._assign_id(tr)
                started.append(self._public(tr, frame_index, t))
            self._tracks.append(tr)

        self._before_expire()

        # ---- expire lost tracks
        buffer = max(s.track_buffer, s.min_track_buffer)
        keep: list[_STrack] = []
        for tr in self._tracks:
            if tr.state == "lost" and tr.frames_since_update > buffer:
                tr.state = "removed"
            if tr.state == "removed":
                if tr.track_id:
                    self._stats.removed_tracks += 1
                    self._stats.lifetimes_frames.append(tr.last_frame - tr.first_frame + 1)
                    removed.append(self._public(tr, frame_index, t))
                tr.feature = None
                continue
            keep.append(tr)
        self._tracks = keep

        tracks = [self._public(tr, frame_index, t) for tr in self._tracks if tr.track_id]
        return TrackerUpdate(tracks, started, reacquired, lost, removed)

    # ------------------------------------------------------------------
    def _assign_id(self, tr: _STrack) -> None:
        if not tr.track_id:
            tr.track_id = self._next_id
            self._next_id += 1
            self._stats.total_tracks += 1

    def _match(
        self, tracks: list[_STrack], dets: list[Detection], cost_thresh: float, stage: int = 1
    ) -> tuple[list[tuple[int, int]], list[int], list[int]]:
        if not tracks or not dets:
            return [], list(range(len(tracks))), list(range(len(dets)))
        cost = self._cost(tracks, dets, stage)
        rows, cols = linear_sum_assignment(cost)
        matches: list[tuple[int, int]] = []
        matched_t: set[int] = set()
        matched_d: set[int] = set()
        for r, c in zip(rows, cols, strict=True):
            if cost[r, c] <= cost_thresh:
                matches.append((int(r), int(c)))
                matched_t.add(int(r))
                matched_d.add(int(c))
        u_t = [i for i in range(len(tracks)) if i not in matched_t]
        u_d = [i for i in range(len(dets)) if i not in matched_d]
        return matches, u_t, u_d

    def _public(self, tr: _STrack, frame_index: int, t: float) -> Track:
        return Track(
            track_id=tr.track_id,
            class_name=tr.class_name,
            confidence=float(tr.score),
            box=tr.box,
            state=tr.state,
            hits=tr.hits,
            age=tr.age,
            first_frame=tr.first_frame,
            last_frame=tr.last_frame,
            first_time=tr.first_time,
            last_time=tr.last_time,
            mean_confidence=float(tr.mean_confidence),
            lost_count=tr.lost_count,
            updated=tr.frames_since_update == 0,
        )


__all__ = ["ByteTrack", "ByteTrackSettings"]
