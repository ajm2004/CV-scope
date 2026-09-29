"""Network reconnects keep the stream clock; run previews for MJPEG viewers get boxes."""

from __future__ import annotations

import time

import cv2
import numpy as np

from pathscope.vision.overlay import annotate_jpeg
from pathscope.vision.sources import network_source as ns
from pathscope.vision.sources.base import ReconnectPolicy


class FakeCapture:
    """Delivers small frames; stops after ``fail_after`` reads, like a dropped stream."""

    def __init__(self, fail_after: int | None = None) -> None:
        self.reads = 0
        self.fail_after = fail_after

    def read(self):
        self.reads += 1
        if self.fail_after is not None and self.reads > self.fail_after:
            return False, None
        return True, np.zeros((48, 64, 3), np.uint8)

    def get(self, _prop):
        return 10.0

    def isOpened(self):  # noqa: N802 - OpenCV's name
        return True

    def release(self):
        pass


def test_a_network_reconnect_keeps_the_stream_clock(monkeypatch):
    captures = [FakeCapture(fail_after=3), FakeCapture()]
    src = ns.NetworkSource("rtsp://camera/stream", ReconnectPolicy(initial_delay_s=0.01, max_delay_s=0.01))
    monkeypatch.setattr(src, "_open_capture", lambda: captures.pop(0))
    src.open()  # reads one frame to check the stream
    before = [src.read(), src.read()]
    time.sleep(0.05)
    after = src.read()  # the stream drops, CV-Scope reconnects and reads on
    assert after is not None and src.reconnect_count == 1
    assert after.frame_index == before[-1].frame_index + 1  # numbering continues
    assert after.media_time_s > before[-1].media_time_s + 0.04  # time kept running


def test_run_previews_for_mjpeg_viewers_get_boxes():
    img = np.full((180, 320, 3), 90, np.uint8)
    ok, buf = cv2.imencode(".jpg", img)
    assert ok
    plain = buf.tobytes()
    tracks = [{"id": 3, "cls": "person", "state": "tracked", "box": [100, 60, 300, 340]}]
    out = cv2.imdecode(np.frombuffer(annotate_jpeg(plain, tracks, preview_w=320, source_w=640), np.uint8), cv2.IMREAD_COLOR)
    assert out.shape == img.shape
    # the box is scaled to the preview: its left edge runs down x=50 from y=40 to y=160
    assert np.abs(out[40:160, 50].astype(int) - 90).max() > 60
    assert np.abs(out[100, 200:300].astype(int) - 90).max() < 20  # outside the box stays as it was
    assert annotate_jpeg(plain, [], 320, 640) == plain
    lost_only = [{"id": 4, "cls": "person", "state": "lost", "box": [0, 0, 100, 100]}]
    assert np.abs(cv2.imdecode(np.frombuffer(annotate_jpeg(plain, lost_only, 320, 640), np.uint8), cv2.IMREAD_COLOR).astype(int) - 90).max() < 20


def _processed_per_second(processing_fps: float, source_fps: float, jitter_s: float, seconds: float = 20.0) -> float:
    import random

    from pathscope.vision.detectors import DetectorConfig
    from pathscope.vision.pipeline import Pipeline, PipelineConfig
    from pathscope.vision.types import FramePacket

    rng = random.Random(7)
    pipe = Pipeline(PipelineConfig("usb", "0", DetectorConfig("none", "", "none"), processing_fps=processing_fps))
    frame = np.zeros((4, 4, 3), np.uint8)
    n = int(seconds * source_fps)
    done = sum(
        pipe._should_process(FramePacket(frame, i, i / source_fps + rng.uniform(-jitter_s, jitter_s), 0.0, 4, 4))
        for i in range(n)
    )
    return done / seconds


def test_processing_fps_is_kept_with_jittery_camera_frames():
    """10 fps from a 30 fps webcam was every 4th frame (7.5 fps) when frames came a little early."""
    assert abs(_processed_per_second(10, 30, 0.004) - 10) < 0.3
    assert abs(_processed_per_second(5, 30, 0.004) - 5) < 0.3
    assert abs(_processed_per_second(5, 12, 0.0) - 5) < 0.3  # a 12 fps video file
    assert abs(_processed_per_second(30, 30, 0.004) - 30) < 0.5  # asking for the source rate keeps every frame
