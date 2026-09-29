"""Guided live enrollment: head-pose maths, the relative baseline and the session state machine."""

from __future__ import annotations

import os
from math import radians

import numpy as np
import pytest

os.environ.setdefault("PATHSCOPE_RECOGNITION_ALLOW_STUB", "1")

from pathscope.recognition.common.types import QualityReport  # noqa: E402
from pathscope.recognition.face.enrollment.guidance import (  # noqa: E402
    PoseBaseline,
    live_pose_hint,
    pose_direction,
    relative_pose,
    view_pose_ok,
)
from pathscope.recognition.face.enrollment.live import (  # noqa: E402
    GUIDED_PLAN,
    GuidedSession,
    LiveObservation,
    observe_frame,
)
from pathscope.recognition.face.quality import pose_from_landmarks  # noqa: E402
from pathscope.recognition.face.stack import create_face_stack  # noqa: E402

# A head as five landmarks in units of the interocular distance: the eyes on
# the face plane, the nose tip sticking out towards the camera, the mouth
# corners below. Enough to check what the pose measure does when a head turns.
NOSE_DEPTH = 0.35
NOSE_DROP = 0.57
MOUTH_DROP = 1.16
MOUTH_HALF = 0.24


def landmarks(yaw: float = 0.0, pitch: float = 0.0, scale: float = 60.0, center: tuple[float, float] = (160.0, 120.0)) -> np.ndarray:
    """Project the five landmarks of a head turned by ``yaw`` and tilted by
    ``pitch`` (radians). Positive yaw turns the face towards the image right
    (the person's own left); positive pitch lowers the chin."""
    pts = np.array(
        [
            [-0.5, 0.0, 0.0],  # image-left eye (the person's right eye)
            [0.5, 0.0, 0.0],  # image-right eye
            [0.0, NOSE_DROP, NOSE_DEPTH],  # nose tip, towards the camera
            [-MOUTH_HALF, MOUTH_DROP, 0.0],
            [MOUTH_HALF, MOUTH_DROP, 0.0],
        ]
    )
    cy, sy = np.cos(yaw), np.sin(yaw)
    cp, sp = np.cos(pitch), np.sin(pitch)
    x = pts[:, 0] * cy + pts[:, 2] * sy
    y = pts[:, 1] * cp + pts[:, 2] * sp
    return np.stack([x * scale + center[0], y * scale + center[1]], axis=1).astype(np.float32)


def measured(yaw_deg: float = 0.0, pitch_deg: float = 0.0) -> tuple[float, float]:
    y, p = pose_from_landmarks(landmarks(radians(yaw_deg), radians(pitch_deg)))
    return float(y), float(p)


# ----------------------------------------------------------------------------- pose measure
def test_pose_measure_follows_a_turning_head():
    yaw0, pitch0 = measured()
    assert abs(yaw0) < 0.02
    # turning towards the person's own left is positive, and grows with the angle
    assert measured(10)[0] < measured(30)[0] < measured(50)[0]
    assert measured(30)[0] > 0.2 and measured(-30)[0] < -0.2
    assert abs(measured(30)[0] + measured(-30)[0]) < 1e-6  # symmetric
    # lowering the chin raises the pitch measure, raising it lowers it
    assert measured(0, 15)[1] - pitch0 > 0.12
    assert measured(0, -15)[1] - pitch0 < -0.12
    assert abs(measured(0, 5)[1] - pitch0) < 0.12  # a small nod is not a view of its own
    # turning does not pretend to be a nod
    assert abs(measured(30)[1] - pitch0) < 0.1


def test_views_are_judged_against_the_person_own_front_view():
    yaw30, _ = measured(30)
    yaw10, _ = measured(10)
    assert view_pose_ok("left", yaw30, 0.0)[0]
    ok, hint = view_pose_ok("left", yaw10, 0.0)
    assert not ok and "left" in hint
    assert view_pose_ok("right", -yaw30, 0.0)[0]
    assert not view_pose_ok("left", 1.2, 0.0)[0]  # turned too far
    assert view_pose_ok("left", 1.2, 0.0)[1].startswith("Turned too far")

    # A detector that reads +0.31 pitch for a face looking straight ahead (SCRFD
    # does, YuNet reads about 0) must not make every frontal face a "camera
    # above" view: the baseline is the person's own front picture.
    _, neutral_pitch = measured(0, 0)
    offset = 0.31
    baseline = PoseBaseline(yaw=0.0, pitch=neutral_pitch + offset)
    assert view_pose_ok("front", 0.0, neutral_pitch + offset, baseline)[0]
    assert not view_pose_ok("above", 0.0, neutral_pitch + offset, baseline)[0]
    chin_down = measured(0, 15)[1] + offset
    assert view_pose_ok("above", 0.0, chin_down, baseline)[0]
    assert view_pose_ok("below", 0.0, measured(0, -15)[1] + offset, baseline)[0]
    assert not view_pose_ok("below", 0.0, chin_down, baseline)[0]
    # without a baseline the pitch of a face cannot be compared between models,
    # so those views only ask for a reasonably straight face
    assert view_pose_ok("above", 0.0, neutral_pitch)[0]
    ry, rp = relative_pose(0.5, 0.4, PoseBaseline(0.1, 0.3))
    assert ry == pytest.approx(0.4) and rp == pytest.approx(0.1)


def test_direction_and_live_hint():
    assert pose_direction("left", 0.0, 0.0) == "left"
    assert pose_direction("right", 0.0, 0.0) == "right"
    assert pose_direction("left", 1.2, 0.0) == "center"
    assert pose_direction("left", 0.3, 0.0) is None
    base = PoseBaseline(0.0, 0.0)
    assert pose_direction("above", 0.0, 0.0, base) == "down"
    assert pose_direction("below", 0.0, 0.0, base) == "up"
    ok, instruction, direction = live_pose_hint("left", 0.0, 0.0)
    assert not ok and instruction == "Turn your head slightly to your left" and direction == "left"
    ok, instruction, direction = live_pose_hint("left", 1.2, 0.0)
    assert not ok and instruction == "Turn a little back towards the camera" and direction == "center"
    assert live_pose_hint("front", 0.0, 0.0)[0]


# ----------------------------------------------------------------------------- session
def quality(score: float = 0.85, size: float = 200.0, yaw: float = 0.0, pitch: float = 0.0, blur: float = 0.8, reasons=(), usable: bool = True, brightness: float = 0.45) -> QualityReport:
    return QualityReport(score, usable, size, blur, 0.9, 0.6, yaw, pitch, 0.0, list(reasons), brightness)


def observation(t: float = 0.0, q: QualityReport | None = None, box=(220.0, 120.0, 420.0, 360.0), n_faces: int = 1, payload: str = "frame") -> LiveObservation:
    return LiveObservation(t=t, seq=int(t * 10), width=640, height=480, n_faces=n_faces if q else 0, box=box if q else None, quality=q, payload=payload)


def session(**kw) -> GuidedSession:
    return GuidedSession(min_face_px=80.0, min_quality=0.6, hold_frames=3, hold_min_s=0.45, **kw)


def test_session_says_what_to_change():
    s = session()
    assert s.feed(observation()).instruction == "Position your face in the circle"
    assert s.feed(observation(q=quality())).instruction == "Ready when you are"
    s.set_target("front", now=0.0)
    assert s.feed(observation(0.1)).instruction == "Look at the camera"
    assert s.feed(observation(0.2, quality(), n_faces=2)).instruction.startswith("Only one person")
    far_left = observation(0.3, quality(), box=(0.0, 120.0, 120.0, 360.0))
    assert s.feed(far_left).instruction == "Move into the circle" and s.feed(far_left).direction == "center"
    assert s.feed(observation(0.4, quality(size=50.0))).instruction == "Move a little closer"
    assert s.feed(observation(0.5, quality(size=460.0))).instruction == "Move back a little"
    assert s.feed(observation(0.6, quality(reasons=["too_dark"], usable=False))).instruction.startswith("More light")
    assert s.feed(observation(0.7, quality(reasons=["too_bright"], usable=False))).instruction.startswith("Too bright")
    assert s.feed(observation(0.8, quality(blur=0.2))).instruction == "Hold still"
    assert s.feed(observation(0.9, quality(score=0.4))).instruction.startswith("Keep your whole face")
    # a turned head is told to come back; a straight one is fine
    turned = s.feed(observation(1.0, quality(yaw=0.5)))
    assert turned.instruction == "Look straight at the camera" and not turned.ok
    assert s.feed(observation(1.1, quality())).ok


def test_session_holds_still_then_captures_the_best_frame():
    s = session()
    s.set_target("front", now=0.0)
    first = s.feed(observation(0.0, quality(score=0.7), payload="a"))
    assert first.ok and first.hold == 1 and not first.capture and first.hold_needed == 3
    assert s.feed(observation(0.2, quality(score=0.95), payload="best")).hold == 2
    third = s.feed(observation(0.5, quality(score=0.8), payload="c"))
    assert third.capture and third.frame == "best" and third.quality == 0.95
    # the streak starts again afterwards, and a wobble resets it
    assert s.feed(observation(0.7, quality(), payload="d")).hold == 1
    assert s.feed(observation(0.8, quality(yaw=0.6))).hold == 0
    assert s.feed(observation(0.9, quality(), payload="e")).hold == 1
    # three good frames within too short a time are not enough
    quick = session()
    quick.set_target("front", now=0.0)
    for t in (0.0, 0.05, 0.1):
        d = quick.feed(observation(t, quality()))
    assert d.hold == 3 and not d.capture


def test_front_capture_becomes_the_baseline_for_the_other_views():
    s = session()
    s.set_target("front", now=0.0)
    s.on_captured("front", quality(yaw=0.04, pitch=0.30, brightness=0.45).to_dict())
    assert s.captured == {"front"} and s.target is None
    assert s.baseline is not None and abs(s.baseline.pitch - 0.30) < 1e-6
    s.set_target("above", now=1.0)
    flat = s.feed(observation(1.1, quality(yaw=0.04, pitch=0.30)))
    assert flat.instruction == "Lower your chin a little" and flat.direction == "down"
    assert s.feed(observation(1.2, quality(yaw=0.04, pitch=0.62))).ok
    s.set_target("below", now=2.0)
    assert s.feed(observation(2.1, quality(yaw=0.04, pitch=-0.05))).ok
    # the plan the interface walks through, and what is done so far
    assert GUIDED_PLAN[0] == "front" and s.plan_state()["captured"] == ["front"]


def test_lighting_view_asks_for_a_change_and_rear_view_waits_for_the_turn():
    s = session(baseline=PoseBaseline(0.0, 0.0, brightness=0.45))
    s.set_target("lighting", now=0.0)
    same = s.feed(observation(0.1, quality(brightness=0.46)))
    assert same.instruction.startswith("Change the lighting")
    assert s.feed(observation(0.2, quality(brightness=0.60))).ok

    s.set_target("rear", now=10.0)
    with_face = s.feed(observation(10.1, quality()))
    assert with_face.instruction.startswith("Turn around") and not with_face.capture
    assert not s.feed(observation(11.0)).capture  # turning around takes a moment
    assert not s.feed(observation(12.0)).capture  # the camera has only just lost the face
    done = s.feed(observation(12.6, payload="back"))
    assert done.capture and done.frame == "back"


def test_observe_frame_reads_a_picture_through_the_stack():
    stack = create_face_stack("stub", {}, cfg={"min_face_px": 40, "min_quality": 0.45})
    rng = np.random.default_rng(3)
    img = np.clip(rng.normal(110, 25, size=(240, 320, 3)), 0, 255).astype(np.uint8)
    obs = observe_frame(stack, img, seq=7)
    assert obs.face_found and obs.seq == 7 and obs.n_faces == 1 and obs.quality is not None
    assert obs.width == 320 and obs.height == 240 and obs.center_offset < 0.1
    assert obs.payload is img and obs.to_dict()["quality"]["size_px"] > 80
    blank = observe_frame(stack, np.zeros((10, 10, 3), dtype=np.uint8))
    assert not blank.face_found and blank.center_offset == 0.0
    stack.close()
