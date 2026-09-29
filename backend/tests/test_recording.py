"""Video recording of live runs: clips around events, one clip per visit,
whole-run segments, timing, overlay."""

from __future__ import annotations

import cv2
import numpy as np

from pathscope.domain.recording import RecordingSettings, recording_settings
from pathscope.domain.scene import SceneDocument
from pathscope.vision.recording import RunRecorder, draw_overlay, overlay_header
from pathscope.vision.types import Track

FPS = 10.0


def frame(i: int) -> np.ndarray:
    img = np.full((240, 320, 3), 40, np.uint8)
    cv2.putText(img, str(i), (20, 120), cv2.FONT_HERSHEY_SIMPLEX, 2, (255, 255, 255), 3)
    return img


def record(settings: RecordingSettings, times: list[float], triggers: dict[float, int] | None = None, tmp_path=None) -> list[dict]:
    files: list[dict] = []
    rec = RunRecorder(settings, tmp_path, FPS, files.append)
    for i, t in enumerate(times):
        rec.add_frame(frame(i), t, 1_000_000.0 + t, wait=True)
        for _ in range((triggers or {}).get(round(t, 1), 0)):
            rec.trigger(t, {"type": "zone_entry", "label": "Room entry", "track_id": 1, "media_time_s": t})
    rec.close()
    assert rec.dropped == 0 and rec.error is None
    return files


def frames_in(path: str) -> int:
    cap = cv2.VideoCapture(path)
    n = 0
    while cap.read()[0]:
        n += 1
    cap.release()
    return n


def ticks(start: float, end: float) -> list[float]:
    return [round(start + i / FPS, 3) for i in range(int(round((end - start) * FPS)))]


def test_clips_start_before_the_event_and_end_after_the_last_one(tmp_path):
    s = RecordingSettings(mode="events", pre_s=3, post_s=4)
    files = record(s, ticks(0, 30), {8.0: 1, 9.0: 1, 25.0: 1}, tmp_path)
    assert [f["kind"] for f in files] == ["event", "event"]
    first, second = files
    # 3 s before the first event to 4 s after the second, both events in one clip
    assert first["media_start_s"] == 5.0 and abs(first["media_end_s"] - 13.1) < 1e-6
    assert first["frames"] == 81 and first["trigger_count"] == 2
    assert second["media_start_s"] == 22.0 and second["frames"] == 71
    for f in files:
        assert frames_in(f["path"]) == f["frames"]
        assert f["mime"] in ("video/mp4", "video/webm", "video/x-msvideo")


def test_a_clip_never_grows_past_its_maximum(tmp_path):
    s = RecordingSettings(mode="events", pre_s=0, post_s=5, max_clip_s=10)
    triggers = {round(t, 1): 1 for t in ticks(1, 40) if abs(t - round(t)) < 1e-6}  # an event every second
    files = record(s, ticks(0, 40), triggers, tmp_path)
    assert len(files) >= 3
    assert all(f["media_end_s"] - f["media_start_s"] <= 10.2 for f in files)


def test_continuous_recording_splits_at_a_pause(tmp_path):
    s = RecordingSettings(mode="continuous")
    files = record(s, ticks(0, 10) + ticks(20, 25), None, tmp_path)
    assert [(f["kind"], f["media_start_s"], f["frames"]) for f in files] == [("continuous", 0.0, 100), ("continuous", 20.0, 50)]


def test_video_time_follows_media_time_when_frames_are_missing(tmp_path):
    # 10 fps, then every third frame missing, like a busy pipeline; the last frame is at 5.8 s
    times = ticks(0, 3) + [t for i, t in enumerate(ticks(3, 6)) if i % 3 != 2]
    files = record(RecordingSettings(mode="continuous"), times, None, tmp_path)
    assert len(files) == 1
    f = files[0]
    assert f["frames"] == 59  # missing frames are repeated: the video lasts as long as the run
    assert abs(f["media_end_s"] - 5.9) < 1e-6


def test_an_event_before_the_first_frame_waits_for_it(tmp_path):
    files: list[dict] = []
    rec = RunRecorder(RecordingSettings(mode="events", pre_s=2, post_s=1), tmp_path, FPS, files.append)
    rec.trigger(0.0, {"type": "crossing"})
    for i, t in enumerate(ticks(0, 5)):
        rec.add_frame(frame(i), t, 1000.0 + t, wait=True)
    rec.close()
    assert len(files) == 1 and files[0]["media_start_s"] == 0.0 and abs(files[0]["media_end_s"] - 1.1) < 1e-6


def test_overlay_draws_boxes_scene_and_time_but_leaves_the_frame_alone():
    scene = SceneDocument.model_validate({"frame_width": 320, "frame_height": 240, "objects": [
        {"id": "z", "type": "zone", "name": "Room", "points": [{"x": 0.1, "y": 0.1}, {"x": 0.9, "y": 0.1}, {"x": 0.9, "y": 0.9}, {"x": 0.1, "y": 0.9}]}]})
    tr = Track(track_id=3, class_name="person", confidence=0.9, box=(100, 60, 160, 200), state="tracked", hits=5, age=5,
               first_frame=0, last_frame=5, first_time=0.0, last_time=0.5, mean_confidence=0.9)
    lost = Track(track_id=4, class_name="person", confidence=0.9, box=(200, 60, 260, 200), state="lost", hits=5, age=5,
                 first_frame=0, last_frame=5, first_time=0.0, last_time=0.5, mean_confidence=0.9)
    src = np.full((240, 320, 3), 40, np.uint8)
    out = draw_overlay(src, [tr, lost], scene, overlay_header(2, 65.4, 1_790_000_000.0), ["Room entry #3"])
    assert np.array_equal(src, np.full((240, 320, 3), 40, np.uint8))  # a copy is drawn on
    assert np.abs(out[130, 100].astype(int) - 40).max() > 60  # the tracked box's left edge
    assert np.abs(out[130, 200].astype(int) - 40).max() < 10  # no box for a lost track
    assert "01:05.4" in overlay_header(2, 65.4, 1_790_000_000.0)


def test_the_video_rate_is_measured_and_capped(tmp_path):
    # frames really arrive at 12 per second although the camera claims 25
    times = [round(i / 12, 4) for i in range(12 * 6)]
    files: list[dict] = []
    rec = RunRecorder(RecordingSettings(mode="continuous", fps=30), tmp_path, 25.0, files.append)
    for i, t in enumerate(times):
        rec.add_frame(frame(i), t, 1000.0 + t, wait=True)
    rec.close()
    assert len(files) == 1 and abs(files[0]["fps"] - 12.0) < 0.05 and files[0]["media_start_s"] == 0.0
    assert abs(files[0]["frames"] - 72) <= 1  # every frame once, none repeated
    capped: list[dict] = []
    rec = RunRecorder(RecordingSettings(mode="continuous", fps=5), tmp_path, 25.0, capped.append)
    for i, t in enumerate(times):
        rec.add_frame(frame(i), t, 1000.0 + t, wait=True)
    rec.close()
    assert capped[0]["fps"] == 5.0 and abs(capped[0]["frames"] - 30) <= 1  # half the frames, same length


def test_wide_pictures_are_scaled_down():
    from pathscope.vision.recording import video_size

    assert video_size(1920, 1080) == (1280, 720)
    assert video_size(641, 481) == (640, 480)


def test_stored_settings_are_read_tolerantly():
    assert recording_settings(None).mode == "off"
    assert recording_settings({"mode": "events", "pre_s": 2}).pre_s == 2
    assert recording_settings({"mode": "sometimes"}).mode == "off"


def visit(settings: RecordingSettings, times: list[float], events: dict[float, list[dict]], alive: dict[float, set[int]], tmp_path) -> list[dict]:
    """Play a run where ``events`` fire at media times and ``alive`` says which
    tracks are still followed from that time on (entry to exit mode)."""
    files: list[dict] = []
    rec = RunRecorder(settings, tmp_path, FPS, files.append)
    active: set[int] = set()
    for i, t in enumerate(times):
        key = round(t, 1)
        if key in alive:
            active = alive[key]
        rec.add_frame(frame(i), t, 1_000_000.0 + t, wait=True, active_ids=set(active))
        for info in events.get(key, []):
            rec.trigger(t, info)
    rec.close()
    assert rec.dropped == 0 and rec.error is None
    return files


def entry(track: int = 1, object_id: str = "room") -> dict:
    return {"type": "zone_entry", "label": "Room entry", "track_id": track, "object_id": object_id, "media_time_s": 0.0}


def leave(track: int = 1, object_id: str = "room") -> dict:
    return {"type": "zone_exit", "label": "Room exit", "track_id": track, "object_id": object_id, "media_time_s": 0.0}


def test_one_clip_covers_the_whole_visit_including_the_dwell(tmp_path):
    """Entry at 8 s, exit at 40 s: one file holds the visit and the dwell
    between them, where the event mode would have written two clips."""
    s = RecordingSettings(mode="presence", pre_s=3, post_s=4)
    files = visit(
        s,
        ticks(0, 50),
        {8.0: [entry()], 40.0: [leave()]},
        {0.0: set(), 7.0: {1}, 41.0: set()},
        tmp_path,
    )
    assert [f["kind"] for f in files] == ["presence"]
    f = files[0]
    assert f["media_start_s"] == 5.0  # pre_s before the entry
    assert abs(f["media_end_s"] - 44.1) < 0.2  # post_s after the exit
    assert f["frames"] == frames_in(f["path"]) and f["frames"] > 380
    assert f["trigger_count"] == 2

    # the same run in event mode: two clips with a hole between them
    clips = record(RecordingSettings(mode="events", pre_s=3, post_s=4), ticks(0, 50), {8.0: 1, 40.0: 1}, tmp_path)
    assert len(clips) == 2 and sum(c["frames"] for c in clips) < f["frames"] / 2


def test_a_visit_ends_when_the_object_is_gone_without_an_exit_event(tmp_path):
    """No exit event ever arrives: the visit ends when the track has been out
    of the picture longer than the grace period."""
    s = RecordingSettings(mode="presence", pre_s=1, post_s=2, presence_grace_s=3)
    files = visit(s, ticks(0, 30), {5.0: [entry()]}, {0.0: set(), 4.0: {1}, 12.0: set()}, tmp_path)
    assert len(files) == 1
    f = files[0]
    # gone at 12 s, +3 s grace, +2 s tail
    assert 16.0 <= f["media_end_s"] <= 18.5, f["media_end_s"]


def test_two_visitors_share_one_clip_until_the_last_one_leaves(tmp_path):
    s = RecordingSettings(mode="presence", pre_s=1, post_s=2)
    files = visit(
        s,
        ticks(0, 40),
        {5.0: [entry(1)], 9.0: [entry(2, "hall")], 15.0: [leave(1)], 30.0: [leave(2, "hall")]},
        {0.0: set(), 4.0: {1}, 8.0: {1, 2}, 16.0: {2}, 31.0: set()},
        tmp_path,
    )
    assert len(files) == 1 and files[0]["trigger_count"] == 4
    assert abs(files[0]["media_end_s"] - 32.1) < 0.3  # the second visitor keeps it open


def test_a_long_visit_continues_in_the_next_file(tmp_path):
    """max_clip_s caps one file; the visit carries on in the next, so nothing
    of the stay is lost."""
    s = RecordingSettings(mode="presence", pre_s=0, post_s=1, max_clip_s=10)
    files = visit(s, ticks(0, 40), {2.0: [entry()], 35.0: [leave()]}, {0.0: set(), 1.0: {1}, 36.0: set()}, tmp_path)
    assert len(files) >= 3
    assert all(f["kind"] == "presence" for f in files)
    # the files follow on from each other, with no gap in the middle
    for a, b in zip(files, files[1:], strict=False):
        assert b["media_start_s"] - a["media_end_s"] < 0.5, (a["media_end_s"], b["media_start_s"])
    assert files[-1]["media_end_s"] >= 35.0
    assert any("continues" in str(t.get("label", "")) for f in files[1:] for t in f["triggers"])
