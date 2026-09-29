"""BoT-SORT: camera motion compensation, appearance fusion, lifecycle and settings.

Scenes are drawn procedurally so the tests do not depend on sample videos.
"""

from __future__ import annotations

import cv2
import numpy as np
import pytest

from pathscope.spatial.geometry import box_iou_matrix
from pathscope.vision.trackers import create_tracker, tracker_catalog, validate_tracker_settings
from pathscope.vision.trackers.appearance import (
    AppearanceError,
    ColorHistogramEncoder,
    OnnxReidEncoder,
    cnn_weights_installed,
    create_encoder,
)
from pathscope.vision.trackers.botsort import BoTSORT, BoTSORTSettings
from pathscope.vision.trackers.gmc import GlobalMotionCompensation
from pathscope.vision.types import Detection

W, H = 1280, 720


def _background(seed: int = 3) -> np.ndarray:
    """A cluttered static scene with plenty of corners and edges."""
    rng = np.random.default_rng(seed)
    img = np.full((H + 200, W + 200, 3), 90, dtype=np.uint8)
    for _ in range(260):
        x, y = int(rng.integers(0, W + 200)), int(rng.integers(0, H + 200))
        w, h = int(rng.integers(8, 120)), int(rng.integers(8, 120))
        color = tuple(int(c) for c in rng.integers(0, 255, 3))
        cv2.rectangle(img, (x, y), (x + w, y + h), color, -1 if rng.random() < 0.6 else 2)
    for _ in range(80):
        p1 = tuple(int(v) for v in rng.integers(0, W + 200, 2))
        p2 = tuple(int(v) for v in rng.integers(0, H + 200, 2))
        cv2.line(img, p1, p2, tuple(int(c) for c in rng.integers(0, 255, 3)), 2)
    return cv2.GaussianBlur(img, (3, 3), 0.8)


BG = _background()


def _view(dx: float = 0.0, dy: float = 0.0) -> np.ndarray:
    """The camera image after the camera moved by (dx, dy) pixels."""
    m = np.float32([[1, 0, dx - 100], [0, 1, dy - 100]])
    return cv2.warpAffine(BG, m, (W, H))


def _person(img: np.ndarray, box, top, bottom) -> None:
    x1, y1, x2, y2 = (int(round(v)) for v in box)
    mid = (y1 + y2) // 2
    cv2.rectangle(img, (x1, y1), (x2, mid), top, -1)
    cv2.rectangle(img, (x1, mid), (x2, y2), bottom, -1)


def _run(tracker, frames):
    """Run a tracker; map each ground-truth object to the id of the best-overlapping live track."""
    seq = []
    for i, (img, dets, truth) in enumerate(frames):
        u = tracker.update(dets, i, i / 25.0, frame=img)
        live = [t for t in u.tracks if t.state == "tracked"]
        row = {}
        if live:
            iou = box_iou_matrix([t.box for t in live], truth)
            for j in range(len(truth)):
                k = int(iou[:, j].argmax())
                if iou[k, j] > 0.3:
                    row[j] = live[k].track_id
        seq.append(row)
    return seq


def _id_changes(seq) -> int:
    n = max(len(r) for r in seq)
    changes = 0
    for j in range(n):
        ids = [r[j] for r in seq if j in r]
        changes += sum(1 for a, b in zip(ids, ids[1:], strict=False) if a != b)
    return changes


# ---------------------------------------------------------------- camera motion
@pytest.mark.parametrize("method", ["sparseOptFlow", "orb", "ecc"])
@pytest.mark.parametrize("shift", [(12.0, -7.0), (40.0, 25.0), (0.6, -0.4)])
def test_gmc_recovers_camera_translation(method, shift):
    g = GlobalMotionCompensation(method)
    g.apply(_view(0, 0), [(600, 300, 660, 450)])
    warp = g.apply(_view(*shift), [(600, 300, 660, 450)])
    assert np.allclose(warp[:, 2], shift, atol=1.0), warp
    assert np.allclose(warp[:, :2], np.eye(2), atol=0.02)


@pytest.mark.parametrize("method", ["sparseOptFlow", "orb", "ecc"])
def test_gmc_rejects_scene_cut(method):
    g = GlobalMotionCompensation(method)
    g.apply(_view(0, 0))
    other = cv2.warpAffine(_background(seed=11), np.float32([[1, 0, -100], [0, 1, -100]]), (W, H))
    assert np.allclose(g.apply(other), np.eye(2, 3))


def test_gmc_static_camera_is_identity():
    g = GlobalMotionCompensation("sparseOptFlow")
    g.apply(_view())
    warp = g.apply(_view())
    assert np.allclose(warp, np.eye(2, 3), atol=1e-3)
    assert g.stats()["camera_motion_mean_px"] < 0.05


def _jolt_frames():
    world = [(300, 300, 360, 450), (620, 280, 680, 430), (900, 320, 960, 470)]
    colors = [((40, 40, 200), (200, 120, 30)), ((40, 180, 40), (30, 30, 30)), ((200, 200, 40), (120, 40, 160))]
    offsets = [(0, 0)] * 12 + [(45, 30)] * 3 + [(-40, 20)] * 3 + [(10, -35)] * 8
    frames = []
    for dx, dy in offsets:
        img = _view(dx, dy)
        boxes = [(x1 + dx, y1 + dy, x2 + dx, y2 + dy) for x1, y1, x2, y2 in world]
        for b, (top, bottom) in zip(boxes, colors, strict=True):
            _person(img, b, top, bottom)
        frames.append((img, [Detection("person", 0.9, b) for b in boxes], boxes))
    return frames


def test_camera_jolt_breaks_iou_tracking_without_compensation():
    frames = _jolt_frames()
    assert _id_changes(_run(create_tracker("bytetrack"), frames)) >= 6
    assert _id_changes(_run(create_tracker("botsort", {"gmc_method": "none"}), frames)) >= 6


@pytest.mark.parametrize("method", ["sparseOptFlow", "orb", "ecc"])
def test_botsort_keeps_ids_through_camera_jolts(method):
    tracker = create_tracker("botsort", {"gmc_method": method})
    seq = _run(tracker, _jolt_frames())
    assert _id_changes(seq) == 0
    assert sorted({v for r in seq for v in r.values()}) == [1, 2, 3]
    stats = tracker.stats().to_dict()
    assert stats["camera_motion_method"] == method
    assert stats["camera_motion_max_px"] > 40  # the jolts were measured, not just absorbed


# ---------------------------------------------------------------- appearance
def _reversal_frames(v=6.0, d=10.0, w=60, h=150, n_in=25, n_out=15):
    """A (in front) and B walk towards each other, meet almost overlapping, and turn back.

    A constant-velocity prediction carries each track into the other person, so
    IoU-only association swaps the ids; A's clean appearance prevents it.
    """
    frames = []
    xa0 = 400.0
    xb0 = xa0 + d + 2 * v * n_in
    for i in range(n_in + n_out):
        k = i if i <= n_in else 2 * n_in - i
        xa, xb = xa0 + v * k, xb0 - v * k
        a = (xa, 300.0, xa + w, 300.0 + h)
        b = (xb, 300.0, xb + w, 300.0 + h)
        img = _view()
        _person(img, b, (40, 180, 40), (30, 30, 30))
        _person(img, a, (40, 40, 200), (200, 120, 30))
        frames.append((img, [Detection("person", 0.9, a), Detection("person", 0.9, b)], [a, b]))
    return frames


def test_iou_only_association_swaps_ids_on_reversal():
    frames = _reversal_frames()
    assert _id_changes(_run(create_tracker("bytetrack"), frames)) > 0
    assert _id_changes(_run(create_tracker("botsort", {"gmc_method": "none"}), frames)) > 0


def test_histogram_appearance_prevents_the_swap():
    tracker = create_tracker("botsort", {"gmc_method": "none", "appearance": "histogram"})
    seq = _run(tracker, _reversal_frames())
    assert _id_changes(seq) == 0
    stats = tracker.stats().to_dict()
    assert stats["appearance_method"] == "histogram" and stats["appearance_assisted_matches"] > 0


def test_cnn_appearance_prevents_the_swap():
    from pathscope.config import REPO_ROOT

    models = REPO_ROOT / "data" / "models"
    if not cnn_weights_installed("resnet18", models):
        pytest.skip("ResNet-18 appearance weights are not installed")
    tracker = BoTSORT(BoTSORTSettings(gmc_method="none", appearance="cnn"), device="cpu", models_dir=str(models))
    assert _id_changes(_run(tracker, _reversal_frames())) == 0


def test_appearance_cannot_join_far_apart_boxes():
    """Appearance is gated by proximity: identical-looking objects far apart stay separate."""
    s = BoTSORTSettings(gmc_method="none", appearance="histogram", min_hits=1)
    tracker = BoTSORT(s)
    img = _view()
    a = (100.0, 300.0, 160.0, 450.0)
    _person(img, a, (40, 40, 200), (200, 120, 30))
    tracker.update([Detection("person", 0.9, a)], 0, 0.0, frame=img)
    img2 = _view()
    b = (900.0, 300.0, 960.0, 450.0)  # same colours, far away
    _person(img2, b, (40, 40, 200), (200, 120, 30))
    u = tracker.update([Detection("person", 0.9, b)], 1, 0.04, frame=img2)
    ids = {t.track_id for t in u.tracks if t.state == "tracked"}
    assert 1 not in ids and ids == {2}


def test_appearance_vectors_are_discarded_with_the_track():
    tracker = BoTSORT(BoTSORTSettings(gmc_method="none", appearance="histogram", track_buffer=2, min_track_buffer=2))
    img = _view()
    box = (500.0, 300.0, 560.0, 450.0)
    _person(img, box, (40, 40, 200), (200, 120, 30))
    for i in range(3):
        u = tracker.update([Detection("person", 0.9, box)], i, i / 25, frame=img)
    assert tracker._tracks[0].feature is not None
    assert not hasattr(u.tracks[0], "feature")  # never leaves the tracker
    for i in range(3, 8):
        u = tracker.update([], i, i / 25, frame=img)
    assert tracker._tracks == [] and u.tracks == []


# ---------------------------------------------------------------- lifecycle / parity
def _det(x, y, conf=0.9):
    return Detection("person", conf, (x, y, x + 40, y + 80), 0)


def test_botsort_lifecycle_matches_bytetrack_semantics():
    tr = create_tracker("botsort", {"gmc_method": "none", "track_buffer": 10})
    ids = []
    for i in range(6):
        u = tr.update([_det(100 + i * 5, 200)], i, i / 10)
        ids.append([t.track_id for t in u.tracks])
    assert ids[0] == [] and all(x == [1] for x in ids[1:])
    for i in range(6, 9):
        u = tr.update([], i, i / 10)
        assert u.tracks[0].state == "lost"
    u = tr.update([_det(100 + 9 * 5, 200)], 9, 0.9)
    assert [t.track_id for t in u.tracks] == [1] and len(u.reacquired) == 1


def test_low_confidence_detection_cannot_start_a_track():
    tr = create_tracker("botsort", {"gmc_method": "none", "min_hits": 1})
    assert tr.update([_det(10, 10, conf=0.55)], 0, 0.0).tracks == []  # below new_track_thresh 0.6
    assert len(tr.update([_det(10, 10, conf=0.65)], 1, 0.1).tracks) == 1


def test_duplicate_of_an_older_lost_track_is_removed_and_reported():
    tr = BoTSORT(BoTSORTSettings(gmc_method="none", min_hits=1, track_buffer=30))
    for i in range(10):  # an old track at a fixed spot
        tr.update([_det(300, 300)], i, i / 10)
    old = tr._tracks[0]
    old.state = "lost"  # force: the old track is lost while a new one appears on top of it
    from pathscope.vision.trackers.bytetrack import _STrack

    newcomer = _STrack(_det(300, 300), tr.kf, 10, 1.0)
    newcomer.state = "tracked"
    tr._assign_id(newcomer)
    tr._tracks.append(newcomer)
    tr._before_expire()
    assert newcomer.state == "removed" and old.state == "lost"
    assert tr.stats().to_dict()["duplicate_tracks_removed"] == 1


# ---------------------------------------------------------------- settings
def test_settings_are_coerced_and_validated():
    s = validate_tracker_settings("botsort", {"track_buffer": "45", "fuse_score": "false", "appearance_thresh": None, "unknown": 1})
    assert s["track_buffer"] == 45 and s["fuse_score"] is False and s["appearance_thresh"] is None
    for bad in ({"gmc_method": "sift"}, {"appearance": "faces"}, {"track_thresh": 1.5}, {"track_buffer": 0}, {"appearance_thresh": 2}, {"track_buffer": 2.5}):
        with pytest.raises(ValueError):
            validate_tracker_settings("botsort", bad)
    with pytest.raises(ValueError):
        validate_tracker_settings("deepsort", {})
    assert validate_tracker_settings("bytetrack", {"track_thresh": "0.4"})["track_thresh"] == 0.4


def test_catalog_lists_botsort_as_available_with_choices(tmp_path):
    (tmp_path / "reid").mkdir()
    (tmp_path / "reid" / "osnet_x0_25.onnx").write_bytes(b"not a real model")
    cat = {t["id"]: t for t in tracker_catalog(tmp_path)}
    bot = cat["botsort"]
    assert bot["available"] is True
    settings = {s["key"]: s for s in bot["settings"]}
    values = [o["value"] for o in settings["appearance"]["options"]]
    assert values[:3] == ["none", "histogram", "cnn"] and "onnx:osnet_x0_25.onnx" in values
    cnn = next(o for o in settings["appearance"]["options"] if o["value"] == "cnn")
    assert cnn["available"] is False and "Models page" in cnn["reason"]  # empty models dir
    assert [o["value"] for o in settings["gmc_method"]["options"]] == ["sparseOptFlow", "orb", "ecc", "none"]


# ---------------------------------------------------------------- encoders
def test_histogram_encoder_separates_colours():
    img = _view()
    boxes = [(100, 300, 160, 450), (300, 300, 360, 450), (500, 300, 560, 450)]
    _person(img, boxes[0], (40, 40, 200), (200, 120, 30))
    _person(img, boxes[1], (45, 42, 205), (195, 118, 35))  # nearly the same clothes
    _person(img, boxes[2], (40, 180, 40), (30, 30, 30))
    f = ColorHistogramEncoder().encode(img, boxes)
    same, diff = float(f[0] @ f[1]), float(f[0] @ f[2])
    assert same > 0.95 and diff < 0.6
    assert ColorHistogramEncoder().encode(img, [(5, 5, 7, 7)]) == [None]  # too small to describe


def test_onnx_reid_encoder_runs_a_user_model(tmp_path):
    onnx = pytest.importorskip("onnx")
    from onnx import TensorProto, helper

    # Tiny "re-identification" model: global average pool over an NCHW image -> 3-D vector
    inp = helper.make_tensor_value_info("images", TensorProto.FLOAT, ["N", 3, 64, 32])
    out = helper.make_tensor_value_info("features", TensorProto.FLOAT, ["N", 3])
    graph = helper.make_graph(
        [helper.make_node("GlobalAveragePool", ["images"], ["pooled"]), helper.make_node("Flatten", ["pooled"], ["features"])],
        "tiny_reid", [inp], [out],
    )
    model = helper.make_model(graph, opset_imports=[helper.make_opsetid("", 13)])
    model.ir_version = 8
    (tmp_path / "reid").mkdir()
    onnx.save(model, str(tmp_path / "reid" / "tiny.onnx"))

    enc = create_encoder("onnx:tiny.onnx", models_dir=tmp_path)
    assert isinstance(enc, OnnxReidEncoder) and (enc.h, enc.w) == (64, 32)
    img = np.zeros((200, 200, 3), dtype=np.uint8)
    img[:, :100] = (0, 0, 255)  # red (BGR)
    img[:, 100:] = (255, 0, 0)  # blue
    f = enc.encode(img, [(10, 10, 60, 90), (20, 30, 80, 150), (120, 10, 180, 90)])
    assert float(f[0] @ f[1]) > 0.999 and float(f[0] @ f[2]) < 0.5
    with pytest.raises(AppearanceError, match="inside the models/reid folder"):
        create_encoder("onnx:../escape.onnx", models_dir=tmp_path)
