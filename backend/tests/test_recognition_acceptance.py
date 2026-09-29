"""Acceptance scenarios through the real engines: synthetic frames -> recognition
runtime -> spatial engine -> rule engine (spec sections 21 and 22)."""

from __future__ import annotations

import os

import numpy as np

os.environ.setdefault("PATHSCOPE_RECOGNITION_ALLOW_STUB", "1")

from pathscope.domain.rules import Rule, RuleSubject, RuleTrigger  # noqa: E402
from pathscope.domain.scene import SceneDocument  # noqa: E402
from pathscope.recognition.common.types import PlateRead  # noqa: E402
from pathscope.recognition.face.stack import create_face_stack  # noqa: E402
from pathscope.recognition.runtime import RecognitionRuntime  # noqa: E402
from pathscope.rules.engine import RuleEngine  # noqa: E402
from pathscope.spatial.engine import SpatialEngine  # noqa: E402
from pathscope.vision.trackers.base import TrackerUpdate  # noqa: E402
from pathscope.vision.types import Track  # noqa: E402

W, H, FPS = 640, 480, 10.0


def textured(h, w, mean, seed, std=25):
    rng = np.random.default_rng(seed)
    return np.clip(rng.normal(mean, std, size=(h, w, 3)), 0, 255).astype(np.uint8)


def track(tid, box, frame, t, cls="person"):
    return Track(track_id=tid, class_name=cls, confidence=0.9, box=box, state="tracked", hits=10, age=10, first_frame=0, last_frame=frame, first_time=0.0, last_time=t, mean_confidence=0.9)


def enroll_stub(stack, mean, seed) -> np.ndarray:
    """What the enrollment service does: detect, align, embed one enrollment image."""
    img = textured(240, 200, mean, seed)
    det = stack.detector.detect(img)[0]
    return stack.embedder.embed(stack.aligner.align(img, det.landmarks))


def test_enrolled_person_enters_zone_a_and_remains_thirty_seconds():
    """Spec 21. Zone A covers the right half; the enrolled person walks in and stays."""
    stack = create_face_stack("stub", {}, cfg={"min_face_px": 40, "min_quality": 0.45})
    templates = np.stack([enroll_stub(stack, 110, s) for s in (1, 2, 3)])
    runtime = RecognitionRuntime.from_payload(
        {"grace_s": 5.0, "face": {"stack": "stub", "models": {}, "config": {"min_face_px": 40, "interval_s": 0.4, "min_observations": 3},
                                   "identities": [{"id": "emp-001", "name": "Employee 001", "templates": templates.tolist()}]}}
    )
    scene = SceneDocument.model_validate({"frame_width": W, "frame_height": H, "objects": [
        {"id": "zone_a", "type": "zone", "name": "Zone A", "points": [{"x": 0.5, "y": 0.0}, {"x": 1.0, "y": 0.0}, {"x": 1.0, "y": 1.0}, {"x": 0.5, "y": 1.0}], "classes": ["person"]}], "routes": []})
    rule = Rule(name="Employee 001 in Zone A", classes=["person"], subject=RuleSubject(mode="specific", identity_ids=["emp-001"]),
                trigger=RuleTrigger(kind="enters", object_id="zone_a"), remains_for_s=30.0, record_as="Extended Zone A presence")
    spatial = SpatialEngine(scene, W, H, ["person"])
    rules = RuleEngine(scene, [rule], spatial, ["person"], entities=runtime, subject_grace_s=runtime.subject_grace_s)
    assert rules.inactive_rules == [] and rules.describe()["recognition_modules"] == ["face"]
    frame = np.zeros((H, W, 3), dtype=np.uint8)
    events, rec_events = [], []
    for i in range(int(40 * FPS)):
        t = i / FPS
        x = 380 if t >= 1.0 else 200  # in Zone A from t = 1 s (its bottom centre crosses x = 320)
        box = (x - 60, 60, x + 60, 420)
        frame[:] = 0
        frame[:, x - 120 : x + 120] = textured(H, 240, 110, 5)  # the person and a margin, so the aligned crop sees only texture
        tracks = [track(1, box, i, t)]
        rec = runtime.observe(frame, tracks, t, i, 1000.0 + t)
        rec_events.extend(rec.events)
        upd = TrackerUpdate(tracks=tracks, started=[], reacquired=[], lost=[], removed=[])
        events.extend(rules.process(spatial.update(upd, t, i), t, i, 1000.0 + t))
    assert [e["kind"] for e in rec_events] == ["recognized"] and rec_events[0]["person_id"] == "emp-001"
    dwell = [e for e in events if e.event_type == "dwell"]
    assert len(dwell) == 1
    ev = dwell[0]
    assert ev.label == "Extended Zone A presence" and ev.duration_s >= 30.0 and ev.context["entity"]["identity_id"] == "emp-001"
    assert ev.context["entity"]["kind"] == "enrolled_person" and "Employee" not in str(ev.context)
    assert runtime.overlay(1, "person")["identity"] == "Employee 001"
    diag = runtime.diagnostics()["face"]
    assert diag["matcher"]["identities"] == 1 and diag["tracks"][0]["identity_id"] == "emp-001"


def test_registered_plate_crosses_the_entrance_gate():
    """Spec 22. Reads are combined across frames; the normalized plate matches ABC12345."""
    reads = [PlateRead(list("ABC12345"), [0.9, 0.9, 0.9, 0.9, 0.35, 0.9, 0.9, 0.9]), PlateRead(list("ABC12345"), [0.95] * 8), PlateRead(list("ABC12345"), [0.95] * 8)]
    runtime = RecognitionRuntime.from_payload(
        {"grace_s": 5.0, "plate": {"stack": "stub", "models": {"scripted_reads": reads}, "config": {"interval_s": 0.25, "min_observations": 2},
                                    "vehicles": [{"id": "veh-1", "plate": "ABC12345", "label": "Site car", "groups": ["Staff"]}],
                                    "formats": [{"id": "generic", "name": "Generic", "pattern": r"^(?P<number>[A-Z0-9]{2,10})$"}]}}
    )
    scene = SceneDocument.model_validate({"frame_width": W, "frame_height": H, "objects": [
        {"id": "gate", "type": "gate", "name": "Entrance Gate", "points": [{"x": 0.6, "y": 0.0}, {"x": 0.6, "y": 1.0}], "classes": ["car", "truck"]}], "routes": []})
    rule = Rule(name="Vehicle Entry", classes=["car", "truck"], subject=RuleSubject(mode="specific", plates=["ABC12345"]), trigger=RuleTrigger(kind="crosses", object_id="gate"), record_as="Vehicle Entry")
    spatial = SpatialEngine(scene, W, H, ["car", "truck"])
    rules = RuleEngine(scene, [rule], spatial, ["car", "truck"], entities=runtime, subject_grace_s=5.0)
    rng = np.random.default_rng(3)
    frame = np.clip(rng.normal(120, 30, size=(H, W, 3)), 0, 255).astype(np.uint8)
    events, rec_events = [], []
    for i in range(50):
        t = i / FPS
        x = 100 + i * 8  # the car approaches the gate at x = 384 and crosses it around frame 36
        box = (x - 90, 220, x + 90, 400)
        tracks = [track(9, box, i, t, cls="car")]
        rec_events.extend(runtime.observe(frame, tracks, t, i, 1000.0 + t).events)
        upd = TrackerUpdate(tracks=tracks, started=[], reacquired=[], lost=[], removed=[])
        events.extend(rules.process(spatial.update(upd, t, i), t, i, 1000.0 + t))
    assert [e["kind"] for e in rec_events] == ["registered_vehicle"] and rec_events[0]["plate_normalized"] == "ABC12345"
    rule_events = [e for e in events if e.event_type == "rule"]
    assert len(rule_events) == 1 and rule_events[0].label == "Vehicle Entry" and rule_events[0].object_name == "Entrance Gate"
    assert rule_events[0].context["entity"] == {"kind": "registered_vehicle", "vehicle_id": "veh-1", "confidence": rule_events[0].context["entity"]["confidence"], "status": "recognized"}
    crossing = next(e for e in events if e.event_type == "crossing")
    assert crossing.context["entity"]["vehicle_id"] == "veh-1" and "ABC12345" not in str(crossing.context)
    assert runtime.overlay(9, "car") == {"status": "recognized", "plate": "ABC12345", "confidence": runtime.overlay(9, "car")["confidence"], "vehicle": "Site car", "vehicle_id": "veh-1"}
