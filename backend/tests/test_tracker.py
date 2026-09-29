from pathscope.vision.trackers import create_tracker
from pathscope.vision.trackers.bytetrack import ByteTrack, ByteTrackSettings
from pathscope.vision.types import Detection


def _det(x: float, y: float, conf: float = 0.9, cls: str = "person") -> Detection:
    return Detection(cls, conf, (x, y, x + 40, y + 80), 0)


def test_track_is_confirmed_and_keeps_id_through_occlusion():
    tr = ByteTrack(ByteTrackSettings(min_hits=2, track_buffer=10))
    ids = []
    for i in range(6):
        upd = tr.update([_det(100 + i * 5, 200)], i, i / 10)
        ids.append([t.track_id for t in upd.tracks])
    assert ids[0] == []  # tentative on the first frame
    assert ids[1] == [1]
    assert all(x == [1] for x in ids[1:])
    # Occlusion: no detections for 3 frames, then the object reappears near the prediction
    for i in range(6, 9):
        upd = tr.update([], i, i / 10)
        assert upd.tracks[0].state == "lost"
    upd = tr.update([_det(100 + 9 * 5, 200)], 9, 0.9)
    assert upd.tracks[0].track_id == 1 and upd.tracks[0].state == "tracked"
    assert len(upd.reacquired) == 1
    assert tr.stats().reacquisitions == 1


def test_lost_track_is_removed_after_buffer():
    tr = ByteTrack(ByteTrackSettings(min_hits=1, track_buffer=3, min_track_buffer=3))
    tr.update([_det(50, 50)], 0, 0.0)
    removed = []
    for i in range(1, 8):
        upd = tr.update([], i, i / 10)
        removed.extend(upd.removed)
    assert len(removed) == 1 and removed[0].track_id == 1
    assert tr.stats().removed_tracks == 1
    assert tr.stats().lifetimes_frames == [1]


def test_two_objects_keep_distinct_ids():
    tr = ByteTrack(ByteTrackSettings(min_hits=1))
    for i in range(5):
        upd = tr.update([_det(0 + i * 3, 0), _det(500 - i * 3, 300)], i, i / 10)
    ids = sorted(t.track_id for t in upd.tracks)
    assert ids == [1, 2]
    by_id = {t.track_id: t for t in upd.tracks}
    assert by_id[1].box[0] < 100 and by_id[2].box[0] > 400


def test_low_confidence_detection_continues_track_but_does_not_start_one():
    tr = ByteTrack(ByteTrackSettings(min_hits=1, track_thresh=0.5, low_thresh=0.1))
    upd = tr.update([_det(10, 10, conf=0.3)], 0, 0.0)
    assert upd.tracks == []
    tr.update([_det(10, 10, conf=0.9)], 1, 0.1)
    upd = tr.update([_det(12, 10, conf=0.3)], 2, 0.2)
    assert len(upd.tracks) == 1 and upd.tracks[0].state == "tracked"


def test_registry():
    assert create_tracker("bytetrack", {"track_buffer": 5}).settings.track_buffer == 5
