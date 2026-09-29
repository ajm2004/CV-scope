"""Operator and subject guidance during enrollment.

Two audiences:

* ``guidance_for`` writes the list of problems with a picture an operator
  uploaded or captured ("Move closer to the camera", "Lighting too low").
* ``live_hint`` writes the single short instruction the guided live capture
  shows to the person in front of the camera ("Turn your head slightly to
  your left"), together with the direction the interface points at.

Pose is judged **relative to the person's own front view** whenever a
baseline exists, because the absolute yaw and pitch a detector reports for a
frontal face differ between models: YuNet reports a pitch near 0 for the same
face for which SCRFD reports about +0.3. Only differences are comparable.
"""

from __future__ import annotations

from dataclasses import dataclass

from pathscope.recognition.common.types import QualityReport

VIEW_LABELS: dict[str, str] = {
    "front": "Straight / front view",
    "left": "Turned slightly to the left",
    "right": "Turned slightly to the right",
    "above": "Camera slightly above",
    "below": "Camera slightly below",
    "lighting": "Different lighting",
    "rear": "Rear / back view (appearance reference only, no face)",
}

# Short instructions for the guided live capture, in the subject's own frame
# of reference ("your left"). "above" means the camera looks down on the face,
# which a person sitting at a fixed camera produces by lowering the chin.
VIEW_INSTRUCTIONS: dict[str, str] = {
    "front": "Look straight at the camera",
    "left": "Turn your head slightly to your left",
    "right": "Turn your head slightly to your right",
    "above": "Lower your chin a little",
    "below": "Raise your chin a little",
    "lighting": "Change the lighting, then look at the camera",
    "rear": "Turn around so the camera sees the back of your head",
}

# yaw > 0: the subject turned towards the image's right side (their left).
# pitch grows when the chin goes down (the camera then looks at the face from above).
_YAW_FRONT = 0.15
_YAW_MIN = 0.18
_YAW_MAX = 0.85
_PITCH_FRONT = 0.35
_PITCH_MIN = 0.12
_PITCH_MAX = 0.70
# How straight the face must be for the views that only vary pitch or lighting
_YAW_NEAR_FRONT = 0.30


@dataclass(frozen=True)
class PoseBaseline:
    """The person's own front view: the zero point of the relative pose."""

    yaw: float = 0.0
    pitch: float = 0.0
    brightness: float | None = None

    @classmethod
    def from_quality(cls, quality: QualityReport | dict | None) -> PoseBaseline | None:
        if quality is None:
            return None
        d = quality.to_dict() if isinstance(quality, QualityReport) else dict(quality)
        if d.get("yaw") is None:
            return None
        return cls(float(d["yaw"]), float(d.get("pitch") or 0.0), d.get("brightness"))

    def to_dict(self) -> dict:
        return {"yaw": round(self.yaw, 3), "pitch": round(self.pitch, 3), "brightness": round(self.brightness, 3) if self.brightness is not None else None}


def relative_pose(yaw: float | None, pitch: float | None, baseline: PoseBaseline | None) -> tuple[float | None, float | None]:
    """Yaw and pitch measured from the baseline (the person's front view)."""
    if yaw is None:
        return None, None
    ry = yaw - (baseline.yaw if baseline else 0.0)
    rp = None if pitch is None else pitch - (baseline.pitch if baseline else 0.0)
    return ry, rp


def view_pose_ok(view: str, yaw: float | None, pitch: float | None, baseline: PoseBaseline | None = None) -> tuple[bool, str | None]:
    """Whether the pose fits the requested view; else the instruction to give.

    Without a baseline the pitch of a face cannot be compared between models,
    so the views that differ only in pitch (``above``, ``below``) ask for a
    reasonably straight face and nothing more."""
    if view == "rear":
        return True, None
    if yaw is None:
        return False, "Face the camera so that the eyes, nose and mouth are visible."
    ry, rp = relative_pose(yaw, pitch, baseline)
    if view == "front":
        if abs(ry) > _YAW_FRONT:
            return False, "Turn to face the camera straight."
        if rp is not None and baseline is not None and abs(rp) > _PITCH_FRONT:
            return False, "Keep the head level and look at the camera."
        return True, None
    if view == "left":
        if ry < _YAW_MIN:
            return False, "Turn slightly left."
        if ry > _YAW_MAX:
            return False, "Turned too far; turn back a little towards the camera."
        return True, None
    if view == "right":
        if ry > -_YAW_MIN:
            return False, "Turn slightly right."
        if ry < -_YAW_MAX:
            return False, "Turned too far; turn back a little towards the camera."
        return True, None
    if view in ("above", "below"):
        if baseline is None or rp is None:
            if abs(ry) > _YAW_MAX:
                return False, "Face the camera more directly."
            return True, None
        if abs(ry) > _YAW_NEAR_FRONT:
            return False, "Face the camera more directly."
        if view == "above":
            if rp < _PITCH_MIN:
                return False, "Lower the chin slightly."
            if rp > _PITCH_MAX:
                return False, "Chin too low; raise it a little."
            return True, None
        if rp > -_PITCH_MIN:
            return False, "Raise the chin slightly."
        if rp < -_PITCH_MAX:
            return False, "Chin too high; lower it a little."
        return True, None
    if view == "lighting":
        if abs(ry) > (_YAW_NEAR_FRONT if baseline is not None else _YAW_MAX):
            return False, "Face the camera more directly."
        return True, None
    return True, None


def pose_direction(view: str, yaw: float | None, pitch: float | None, baseline: PoseBaseline | None = None) -> str | None:
    """Which way the interface should point: left, right, up, down or back."""
    if yaw is None or view in ("rear", "front", "lighting"):
        return None
    ry, rp = relative_pose(yaw, pitch, baseline)
    if view == "left":
        return "left" if ry < _YAW_MIN else ("center" if ry > _YAW_MAX else None)
    if view == "right":
        return "right" if ry > -_YAW_MIN else ("center" if ry < -_YAW_MAX else None)
    if rp is None or baseline is None:
        return None
    if view == "above":
        return "down" if rp < _PITCH_MIN else ("up" if rp > _PITCH_MAX else None)
    if view == "below":
        return "up" if rp > -_PITCH_MIN else ("down" if rp < -_PITCH_MAX else None)
    return None


def live_pose_hint(view: str, yaw: float | None, pitch: float | None, baseline: PoseBaseline | None = None) -> tuple[bool, str, str | None]:
    """(pose fits, instruction, direction) for the guided live capture."""
    ok, _ = view_pose_ok(view, yaw, pitch, baseline)
    if ok:
        return True, "", None
    direction = pose_direction(view, yaw, pitch, baseline)
    if yaw is None:
        return False, "Look at the camera", None
    if direction == "center":
        return False, "Turn a little back towards the camera", "center"
    return False, VIEW_INSTRUCTIONS.get(view, "Follow the instruction"), direction


def view_pose_ok_for(view: str, quality: QualityReport | None, baseline: PoseBaseline | None = None) -> bool:
    if quality is None:
        return view == "rear"
    return view_pose_ok(view, quality.yaw, quality.pitch, baseline)[0]


def guidance_for(quality: QualityReport | None, view: str, min_face_px: float, baseline: PoseBaseline | None = None) -> list[str]:
    """Instructions for the operator / subject. Empty means the image is acceptable."""
    if quality is None:
        return ["No face found. Face the camera and make sure the face is well lit."] if view != "rear" else []
    hints: list[str] = []
    if "too_small" in quality.reasons or quality.size_px < min_face_px:
        hints.append("Move closer to the camera.")
    if "too_dark" in quality.reasons:
        hints.append("Lighting too low.")
    if "too_bright" in quality.reasons:
        hints.append("Too bright or backlit; move away from the light source.")
    if "blurred" in quality.reasons or quality.blur < 0.35:
        hints.append("Hold still; the picture is blurred.")
    if "obstructed" in quality.reasons:
        hints.append("Face partially obstructed or cut off by the frame.")
    if "low_contrast" in quality.reasons:
        hints.append("The face has too little contrast; improve the lighting.")
    ok, pose_hint = view_pose_ok(view, quality.yaw, quality.pitch, baseline)
    if not ok and pose_hint:
        hints.append(pose_hint)
    return hints
