"""Guided live enrollment: one instruction at a time, capture by itself.

The person stands in front of a live camera and follows short instructions
("Look straight at the camera", "Turn your head slightly to your left").
This module holds the logic that turns a stream of observed frames into those
instructions and decides when a frame is good enough to keep, so the operator
never has to press a button per view.

    frame -> face detection -> quality and pose -> instruction / hold -> capture

``GuidedSession`` is pure state: it consumes observations and returns
decisions, which makes the behaviour testable without a camera. The
WebSocket layer (``recognition/api/live.py``) does the input and output.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

import cv2
import numpy as np

from pathscope.recognition.common.types import QualityReport
from pathscope.recognition.face.enrollment.guidance import (
    VIEW_INSTRUCTIONS,
    PoseBaseline,
    live_pose_hint,
    relative_pose,
)
from pathscope.recognition.face.stack import FaceStack

# The views the guided capture walks through, and the ones offered afterwards.
GUIDED_PLAN: tuple[str, ...] = ("front", "left", "right", "above", "below")
GUIDED_EXTRAS: tuple[str, ...] = ("lighting", "rear")

# How far the face may sit from the middle of the picture, as a fraction of
# half the shorter frame side: the guided view is a circle around the centre.
MAX_CENTER_OFFSET = 0.62
# A face taller than this fraction of the shorter frame side is too close.
MAX_FACE_FRACTION = 0.85
# Mean brightness change that counts as "different lighting"
LIGHTING_DELTA = 0.05


@dataclass
class LiveObservation:
    """What one analysed frame showed."""

    t: float = field(default_factory=time.time)
    seq: int = 0
    width: int = 0
    height: int = 0
    n_faces: int = 0
    box: tuple[float, float, float, float] | None = None
    quality: QualityReport | None = None
    payload: Any = field(default=None, repr=False)  # the decoded frame, kept for the capture

    @property
    def face_found(self) -> bool:
        return self.box is not None and self.quality is not None

    @property
    def center_offset(self) -> float:
        """Distance of the face centre from the picture centre, where 1.0 is
        half the shorter side of the frame."""
        if self.box is None or not self.width or not self.height:
            return 0.0
        cx, cy = (self.box[0] + self.box[2]) / 2.0, (self.box[1] + self.box[3]) / 2.0
        half = min(self.width, self.height) / 2.0
        return float(np.hypot(cx - self.width / 2.0, cy - self.height / 2.0) / max(half, 1.0))

    def to_dict(self) -> dict:
        return {
            "seq": self.seq,
            "width": self.width,
            "height": self.height,
            "n_faces": self.n_faces,
            "box": [round(float(v), 1) for v in self.box] if self.box else None,
            "center_offset": round(self.center_offset, 3),
            "quality": self.quality.to_dict() if self.quality else None,
        }


@dataclass
class Decision:
    """What to show now, and whether a frame should be kept."""

    view: str | None
    instruction: str
    direction: str | None = None  # left | right | up | down | center | closer | back
    ok: bool = False  # the frame fits the requested view
    hold: int = 0
    hold_needed: int = 3
    capture: bool = False
    frame: Any = field(default=None, repr=False)
    quality: float | None = None

    def to_dict(self) -> dict:
        """The wire form. ``hold_quality`` is the score of the frame that would
        be kept; the picture's own quality report travels with the observation."""
        return {
            "view": self.view,
            "instruction": self.instruction,
            "direction": self.direction,
            "ok": self.ok,
            "hold": self.hold,
            "hold_needed": self.hold_needed,
            "hold_quality": round(self.quality, 3) if self.quality is not None else None,
        }


class GuidedSession:
    """Decides the instruction for the current view and when to capture."""

    def __init__(
        self,
        min_face_px: float = 80.0,
        min_quality: float = 0.6,
        baseline: PoseBaseline | None = None,
        captured: set[str] | None = None,
        hold_frames: int = 3,
        hold_min_s: float = 0.45,
        rear_delay_s: float = 2.5,
        rear_clear_s: float = 1.2,
    ) -> None:
        self.min_face_px = float(min_face_px)
        self.min_quality = float(min_quality)
        self.baseline = baseline
        self.captured: set[str] = set(captured or ())
        self.hold_frames = int(hold_frames)
        self.hold_min_s = float(hold_min_s)
        self.rear_delay_s = float(rear_delay_s)
        self.rear_clear_s = float(rear_clear_s)
        self.target: str | None = None
        self._target_t: float = 0.0
        self._streak: int = 0
        self._streak_t: float = 0.0
        self._best: LiveObservation | None = None
        self._face_gone_since: float | None = None

    # ------------------------------------------------------------- targets
    def set_target(self, view: str | None, now: float | None = None) -> None:
        self.target = view
        self._target_t = now if now is not None else time.time()
        self._reset_streak()

    def _reset_streak(self) -> None:
        self._streak = 0
        self._streak_t = 0.0
        self._best = None
        self._face_gone_since = None

    def on_captured(self, view: str, quality: QualityReport | dict | None = None) -> None:
        """Record a stored view; the front view becomes the pose baseline."""
        self.captured.add(view)
        if view == "front":
            baseline = PoseBaseline.from_quality(quality)
            if baseline is not None:
                self.baseline = baseline
        self.set_target(None)

    def plan_state(self) -> dict:
        return {"captured": sorted(self.captured), "baseline": self.baseline.to_dict() if self.baseline else None}

    # ------------------------------------------------------------- decisions
    def feed(self, obs: LiveObservation) -> Decision:
        view = self.target
        if view is None:
            if obs.face_found and obs.center_offset <= MAX_CENTER_OFFSET:
                return self._idle(obs, "Ready when you are")
            return self._idle(obs, "Position your face in the circle")
        if view == "rear":
            return self._rear(obs)
        problem = self._problem(obs, view)
        if problem is not None:
            instruction, direction = problem
            self._reset_streak()
            return Decision(view, instruction, direction, hold_needed=self.hold_frames, quality=self._score(obs))
        # everything fits: hold still for a moment, then keep the best frame
        if self._streak == 0:
            self._streak_t = obs.t
        self._streak += 1
        if self._best is None or self._score(obs) >= (self._score(self._best) or 0.0):
            self._best = obs
        held_long_enough = (obs.t - self._streak_t) >= self.hold_min_s
        capture = self._streak >= self.hold_frames and held_long_enough
        best = self._best or obs
        decision = Decision(
            view,
            "Hold still…" if not capture else "Captured",
            None,
            ok=True,
            hold=self._streak,
            hold_needed=self.hold_frames,
            capture=capture,
            frame=best.payload if capture else None,
            quality=self._score(best),
        )
        if capture:
            self._reset_streak()
        return decision

    # ------------------------------------------------------------- internals
    @staticmethod
    def _score(obs: LiveObservation | None) -> float | None:
        return obs.quality.score if obs is not None and obs.quality is not None else None

    def _idle(self, obs: LiveObservation, instruction: str) -> Decision:
        return Decision(None, instruction, hold_needed=self.hold_frames, quality=self._score(obs))

    def _rear(self, obs: LiveObservation) -> Decision:
        """The back of the head: no face may be visible, and the person needs a
        moment to turn around."""
        now = obs.t
        if obs.face_found:
            self._face_gone_since = None
            return Decision("rear", VIEW_INSTRUCTIONS["rear"], "center", hold_needed=self.hold_frames)
        if self._face_gone_since is None:
            self._face_gone_since = now
        waited = now - self._target_t
        clear = now - self._face_gone_since
        if waited >= self.rear_delay_s and clear >= self.rear_clear_s:
            self._reset_streak()
            return Decision("rear", "Captured", None, ok=True, hold=self.hold_frames, hold_needed=self.hold_frames, capture=True, frame=obs.payload)
        return Decision("rear", "Hold still…", None, ok=True, hold=1, hold_needed=self.hold_frames)

    def _problem(self, obs: LiveObservation, view: str) -> tuple[str, str | None] | None:
        """The first thing in the way, as an instruction and a direction."""
        if not obs.face_found:
            return "Look at the camera", None
        q = obs.quality
        assert q is not None
        if obs.n_faces > 1:
            return "Only one person in front of the camera, please", None
        if obs.center_offset > MAX_CENTER_OFFSET:
            return "Move into the circle", "center"
        if q.size_px < self.min_face_px:
            return "Move a little closer", "closer"
        short_side = min(obs.width, obs.height) or 1
        if q.size_px > MAX_FACE_FRACTION * short_side or "obstructed" in q.reasons:
            return "Move back a little", "back"
        if "too_dark" in q.reasons or "low_contrast" in q.reasons:
            return "More light on the face, please", None
        if "too_bright" in q.reasons:
            return "Too bright: move away from the light", None
        pose_ok, pose_instruction, direction = live_pose_hint(view, q.yaw, q.pitch, self.baseline)
        if not pose_ok:
            return pose_instruction, direction
        if view == "lighting" and not self._lighting_changed(q):
            return "Change the lighting: switch a lamp on or off, or turn towards a window", None
        if "blurred" in q.reasons or q.blur < 0.35:
            return "Hold still", None
        if not q.usable or q.score < self.min_quality:
            return "Keep your whole face in view and hold still", None
        return None

    def _lighting_changed(self, q: QualityReport) -> bool:
        if self.baseline is None or self.baseline.brightness is None or q.brightness is None:
            return True  # nothing to compare against
        return abs(q.brightness - self.baseline.brightness) >= LIGHTING_DELTA

    def describe(self, obs: LiveObservation, decision: Decision) -> dict:
        """The analysis message sent to the browser."""
        q = obs.quality
        ry, rp = relative_pose(q.yaw if q else None, q.pitch if q else None, self.baseline)
        return {
            **obs.to_dict(),
            **decision.to_dict(),
            "rel_yaw": round(ry, 3) if ry is not None else None,
            "rel_pitch": round(rp, 3) if rp is not None else None,
            "captured_views": sorted(self.captured),
        }


# ----------------------------------------------------------------------------- analysis
def decode_frame(jpeg: bytes) -> np.ndarray | None:
    img = cv2.imdecode(np.frombuffer(jpeg, dtype=np.uint8), cv2.IMREAD_COLOR)
    return img if img is not None and img.size else None


def observe_frame(stack: FaceStack, img: np.ndarray, seq: int = 0, t: float | None = None, keep_frame: bool = True) -> LiveObservation:
    """Detect the largest face in a live frame and score it."""
    h, w = img.shape[:2]
    obs = LiveObservation(t=t if t is not None else time.time(), seq=seq, width=int(w), height=int(h), payload=img if keep_frame else None)
    with stack.lock:
        dets = stack.detector.detect(img)
        if not dets:
            return obs
        det = dets[0]
        obs.box = tuple(float(v) for v in det.box)  # type: ignore[assignment]
        obs.n_faces = 1 + sum(1 for d in dets[1:] if d.height > 0.5 * det.height)
        obs.quality = stack.quality.assess(img, det, w, h)
    return obs
