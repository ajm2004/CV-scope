"""Face components: alignment, quality, matcher, buffer, guidance and the per-track pipeline with stand-ins."""

from __future__ import annotations

import os

import numpy as np
import pytest

os.environ.setdefault("PATHSCOPE_RECOGNITION_ALLOW_STUB", "1")

from pathscope.domain.entities import STATUS_INSUFFICIENT, STATUS_UNKNOWN  # noqa: E402
from pathscope.recognition.common.buffer import ObservationBuffer  # noqa: E402
from pathscope.recognition.common.types import (  # noqa: E402
    POSSIBLE_MATCH,
    RECOGNIZED,
    UNKNOWN,
    FaceDetection,
)
from pathscope.recognition.face.alignment import (  # noqa: E402
    ARCFACE_TEMPLATE,
    FivePointAligner,
    similarity_transform,
)
from pathscope.recognition.face.embeddings.base import FaceEmbedder, l2_normalize  # noqa: E402
from pathscope.recognition.face.enrollment import guidance_for, view_pose_ok  # noqa: E402
from pathscope.recognition.face.matcher import FaceMatcher, IdentityTemplates  # noqa: E402
from pathscope.recognition.face.pipeline import (  # noqa: E402
    FacePipelineConfig,
    FaceRecognitionPipeline,
)
from pathscope.recognition.face.quality import (  # noqa: E402
    FaceQualityAssessor,
    pose_from_landmarks,
)
from pathscope.recognition.face.stack import (  # noqa: E402
    FaceStack,
    StubFaceDetector,
    StubFaceEmbedder,
    create_face_stack,
)
from pathscope.vision.types import Track  # noqa: E402


def textured(h: int, w: int, mean: int, seed: int, std: int = 25) -> np.ndarray:
    rng = np.random.default_rng(seed)
    img = np.clip(rng.normal(mean, std, size=(h, w, 3)), 0, 255).astype(np.uint8)
    return img


# ----------------------------------------------------------------------------- alignment
def test_similarity_transform_recovers_scale_rotation_translation():
    src = ARCFACE_TEMPLATE.copy()
    theta = np.deg2rad(20)
    rot = np.array([[np.cos(theta), -np.sin(theta)], [np.sin(theta), np.cos(theta)]], dtype=np.float32)
    dst = (src @ rot.T) * 1.7 + np.array([30.0, -12.0], dtype=np.float32)
    m = similarity_transform(dst, src)  # map the transformed points back onto the template
    back = (np.hstack([dst, np.ones((5, 1), dtype=np.float32)]) @ m.T)
    assert np.allclose(back, src, atol=1e-3)
    aligner = FivePointAligner(112)
    face = textured(200, 160, 120, 1)
    out = aligner.align(face, dst + 40)
    assert out.shape == (112, 112, 3)


# ----------------------------------------------------------------------------- quality and pose
def test_quality_scores_and_reasons():
    q = FaceQualityAssessor(min_face_px=40, good_face_px=100, min_quality=0.45)
    frame = textured(300, 300, 120, 2)
    lm = np.array([[110, 120], [190, 120], [150, 160], [120, 200], [180, 200]], dtype=np.float32)
    good = q.assess(frame, FaceDetection((90, 80, 210, 240), 0.95, lm), 300, 300)
    assert good.usable and good.score > 0.6 and good.reasons == []
    tiny = q.assess(frame, FaceDetection((140, 140, 160, 165), 0.95, lm), 300, 300)
    assert not tiny.usable and "too_small" in tiny.reasons
    dark = q.assess(np.full((300, 300, 3), 5, dtype=np.uint8), FaceDetection((90, 80, 210, 240), 0.95, lm), 300, 300)
    assert "too_dark" in dark.reasons and not dark.usable
    flat = q.assess(np.full((300, 300, 3), 120, dtype=np.uint8), FaceDetection((90, 80, 210, 240), 0.95, lm), 300, 300)
    assert "blurred" in flat.reasons
    cut = q.assess(frame, FaceDetection((-40, 80, 60, 240), 0.95, lm), 300, 300)
    assert "obstructed" in cut.reasons
    # pose: nose closer to the image-right eye means the subject turned towards image-right (yaw > 0)
    turned = np.array([[110, 120], [190, 120], [182, 160], [120, 200], [180, 200]], dtype=np.float32)
    yaw, pitch = pose_from_landmarks(turned)
    assert yaw > 0.3 and pitch is not None
    yaw0, _ = pose_from_landmarks(lm)
    assert abs(yaw0) < 0.05
    ok, hint = view_pose_ok("left", yaw, pitch)
    assert ok and hint is None
    ok2, hint2 = view_pose_ok("right", yaw, pitch)
    assert not ok2 and "right" in hint2
    ok3, hint3 = view_pose_ok("front", yaw, pitch)
    assert not ok3 and "straight" in hint3
    hints = guidance_for(tiny, "front", 40)
    assert any("closer" in h for h in hints)
    assert guidance_for(None, "front", 40)[0].startswith("No face found")
    assert guidance_for(None, "rear", 40) == []


# ----------------------------------------------------------------------------- matcher
def _vec(*vals: float, dim: int = 8) -> np.ndarray:
    v = np.zeros(dim, dtype=np.float32)
    for i, x in enumerate(vals):
        v[i] = x
    return l2_normalize(v)


def test_matcher_thresholds_margin_and_validity():
    a = IdentityTemplates("a", "Alice", np.stack([_vec(1, 0), _vec(0.95, 0.1)]))
    b = IdentityTemplates("b", "Bob", np.stack([_vec(0, 1)]))
    from datetime import date

    c = IdentityTemplates("c", "Carol", np.stack([_vec(0, 0, 1)]), valid_until=date(2020, 1, 1))
    d = IdentityTemplates("d", "Dan", np.stack([_vec(0, 0, 0, 1)]), active=False)
    m = FaceMatcher([a, b, c, d], match_threshold=0.8, possible_threshold=0.5, margin=0.1)
    assert m.n_identities == 4 and m.n_templates == 5
    r = m.match(_vec(1, 0.05))
    assert r.status == RECOGNIZED and r.best.identity_id == "a" and r.second_similarity < 0.2
    r2 = m.match(_vec(1, 1))  # equally close to Alice and Bob: possible only (margin)
    assert r2.status == POSSIBLE_MATCH and r2.best is not None
    r3 = m.match(_vec(0.6, 0, 0, 0, 1))
    assert r3.status == POSSIBLE_MATCH
    r4 = m.match(_vec(0, 0, 0, 0, 0, 1))
    assert r4.status == UNKNOWN and r4.best is None
    assert m.match(_vec(0, 0, 1)).status == UNKNOWN  # Carol's validity ended
    assert m.match(_vec(0, 0, 0, 1)).status == UNKNOWN  # Dan is disabled
    with pytest.raises(ValueError):
        m.match(np.ones(3, dtype=np.float32))
    empty = FaceMatcher([], 0.8, 0.5)
    assert empty.match(_vec(1)).status == UNKNOWN


def test_observation_buffer_keeps_best_and_aggregates():
    class Obs:
        def __init__(self, frame_index, emb):
            self.frame_index = frame_index
            self.embedding = emb

    buf = ObservationBuffer(capacity=3)
    assert buf.add(Obs(1, _vec(1, 0)), 0.5, True)
    assert not buf.add(Obs(2, None), 0.9, False, ["blurred"])
    buf.add(Obs(3, _vec(0.9, 0.1)), 0.9, True)
    buf.add(Obs(4, _vec(0.8, 0.2)), 0.7, True)
    buf.add(Obs(5, _vec(0.7, 0.3)), 0.6, True)
    s = buf.summary()
    assert s == {"observations": 5, "usable": 4, "kept": 3, "best_frame": 3, "best_quality": 0.9, "rejected": {"blurred": 1}}
    agg = buf.aggregate_embeddings()
    assert abs(float(np.linalg.norm(agg)) - 1.0) < 1e-5 and agg[0] > 0.9
    buf.reset(keep_best=1)
    assert buf.n_kept == 1 and buf.best.frame_index == 3


# ----------------------------------------------------------------------------- pipeline with stand-ins
class BinEmbedder(FaceEmbedder):
    """Embeds the aligned crop by the intensity bin of its mean gray level."""

    id = "bins"
    model_version = "bins"
    dim = 8
    default_match_threshold = 0.8
    default_possible_threshold = 0.5

    def embed(self, aligned_bgr):
        mean = float(aligned_bgr.mean())
        v = np.zeros(8, dtype=np.float32)
        v[min(7, int(mean // 32))] = 1.0
        return v


def person_track(tid, x1, y1, x2, y2, frame, t):
    return Track(track_id=tid, class_name="person", confidence=0.9, box=(x1, y1, x2, y2), state="tracked", hits=10, age=10, first_frame=0, last_frame=frame, first_time=0.0, last_time=t, mean_confidence=0.9)


def paint(frame, box, mean, seed, pad=60):
    """Texture the person box and a margin around it, so the aligned face crop
    (which reaches a little beyond the stand-in face box) sees only the texture."""
    h, w = frame.shape[:2]
    x1, y1, x2, y2 = (int(v) for v in box)
    x1, y1, x2, y2 = max(0, x1 - pad), max(0, y1 - pad), min(w, x2 + pad), min(h, y2 + pad)
    frame[y1:y2, x1:x2] = textured(y2 - y1, x2 - x1, mean, seed)


def make_pipeline(identities, **cfg):
    stack = FaceStack("test", StubFaceDetector(), FivePointAligner(112), FaceQualityAssessor(min_face_px=40, good_face_px=100, min_quality=0.45), BinEmbedder())
    matcher = FaceMatcher(identities, 0.8, 0.5, 0.1)
    return FaceRecognitionPipeline(stack, matcher, FacePipelineConfig(interval_s=0.4, min_observations=3, revalidate_s=3.0, decision_timeout_s=2.0, **cfg))


def bin_identity(identity_id, name, mean):
    v = np.zeros(8, dtype=np.float32)
    v[min(7, int(mean // 32))] = 1.0
    return IdentityTemplates(identity_id, name, v[None, :])


def test_pipeline_recognizes_enrolled_person_and_leaves_unknown_anonymous():
    pipe = make_pipeline([bin_identity("emp-001", "Employee 001", 80), bin_identity("emp-002", "Employee 002", 200)])
    frame = np.zeros((480, 640, 3), dtype=np.uint8)
    box1 = (100, 60, 220, 400)
    box2 = (400, 60, 520, 400)
    events = []
    fps = 10.0
    for i in range(40):
        t = i / fps
        paint(frame, box1, 80, 7)  # enrolled person 1
        paint(frame, box2, 40, 8)  # nobody enrolled has a mean near 40
        tracks = [person_track(1, *box1, i, t), person_track(2, *box2, i, t)]
        events.extend(pipe.observe(frame, tracks, t, i, 1000.0 + t).events)
    rec = [e for e in events if e["kind"] == "recognized"]
    assert len(rec) == 1 and rec[0]["person_id"] == "emp-001" and rec[0]["track_id"] == 1
    assert rec[0]["usable_observations"] >= 3 and rec[0]["model_version"] == "stub+bins" and rec[0]["similarity"] >= 0.8
    assert abs(rec[0]["media_time_s"] - 0.8) < 1e-6  # the third attempt, at 0.4 s intervals
    ent = pipe.resolve(1, "person")
    assert ent.kind == "enrolled_person" and ent.identity_id == "emp-001" and ent.display_name == "Employee 001" and ent.settled
    unknown = pipe.resolve(2, "person")
    assert unknown.kind == "anonymous_person" and unknown.status == STATUS_UNKNOWN and unknown.settled
    assert pipe.stats["recognized"] == 1 and pipe.stats["unknown"] >= 1
    diag = pipe.diagnostics()
    t1 = next(tr for tr in diag["tracks"] if tr["track_id"] == 1)
    assert t1["identity"] == "Employee 001" and t1["face_detected"] and t1["usable"] >= 3 and t1["history"]
    assert pipe.overlay(1) == {"status": "recognized", "identity": "Employee 001", "identity_id": "emp-001", "confidence": 1.0}
    pipe.forget(1)
    assert pipe.resolve(1, "person").kind == "anonymous_person"


def test_pipeline_marks_tracks_without_a_usable_face_as_insufficient():
    pipe = make_pipeline([bin_identity("emp-001", "Employee 001", 80)])
    frame = np.full((480, 640, 3), 120, dtype=np.uint8)  # flat: every crop is 'blurred'
    box = (100, 60, 220, 400)
    for i in range(30):
        t = i / 10.0
        pipe.observe(frame, [person_track(1, *box, i, t)], t, i)
    ent = pipe.resolve(1, "person")
    assert ent.status == STATUS_INSUFFICIENT and ent.settled and not ent.recognized
    assert pipe.stats["faces_detected"] > 0 and pipe.stats["usable"] == 0


def test_pipeline_switches_identity_after_repeated_disagreement():
    pipe = make_pipeline([bin_identity("emp-001", "Employee 001", 80), bin_identity("emp-002", "Employee 002", 200)])
    frame = np.zeros((480, 640, 3), dtype=np.uint8)
    box = (100, 60, 220, 400)
    events = []
    for i in range(120):
        t = i / 10.0
        paint(frame, box, 80 if t < 3.0 else 200, 9)  # the tracker joined two people at t = 3 s
        events.extend(pipe.observe(frame, [person_track(1, *box, i, t)], t, i).events)
    kinds = [e["kind"] for e in events]
    assert kinds[0] == "recognized" and "identity_changed" in kinds
    changed = next(e for e in events if e["kind"] == "identity_changed")
    assert changed["person_id"] == "emp-002" and changed["context"]["previous_identity_id"] == "emp-001"
    assert pipe.resolve(1, "person").identity_id == "emp-002"


def test_stub_stack_is_gated_and_deterministic(monkeypatch):
    stack = create_face_stack("stub", {}, cfg={"min_face_px": 40})
    img = textured(160, 160, 110, 3)
    det = stack.detector.detect(img)[0]
    aligned = stack.aligner.align(img, det.landmarks)
    e1 = stack.embedder.embed(aligned)
    e2 = stack.embedder.embed(stack.aligner.align(textured(160, 160, 110, 4), det.landmarks))
    e3 = stack.embedder.embed(stack.aligner.align(textured(160, 160, 190, 5), det.landmarks))
    assert float(e1 @ e2) > 0.9 and float(e1 @ e3) < 0.6
    monkeypatch.setenv("PATHSCOPE_RECOGNITION_ALLOW_STUB", "0")
    with pytest.raises(RuntimeError):
        create_face_stack("stub", {})
    with pytest.raises(ValueError):
        create_face_stack("cloud", {})
    assert isinstance(StubFaceEmbedder().embed(img), np.ndarray)
