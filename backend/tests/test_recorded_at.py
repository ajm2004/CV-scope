"""Video files with a known recording start: results are dated by the recording
time, so the files of several cameras line up for cross-camera correlation."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from pathscope.vision.sources import create_source

SAMPLE = Path(__file__).resolve().parents[2] / "samples" / "videos" / "people-detection.mp4"
pytestmark = pytest.mark.skipif(not SAMPLE.exists(), reason="sample video missing: python scripts/download_samples.py")


def test_frames_of_a_recorded_video_are_dated_by_the_recording():
    start = datetime(2018, 3, 11, 15, 20, 1, tzinfo=UTC).timestamp()
    src = create_source("file", str(SAMPLE), recorded_at=start)
    info = src.open()
    try:
        packets = [src.read() for _ in range(5)]
    finally:
        src.close()
    for p in packets:
        assert abs(p.wall_time - (start + p.media_time_s)) < 1e-6
    assert abs(packets[-1].wall_time - packets[0].wall_time - 4 / info.fps) < 1e-6


def test_without_a_recording_start_frames_are_dated_when_read():
    src = create_source("file", str(SAMPLE))
    src.open()
    try:
        p = src.read()
    finally:
        src.close()
    assert abs(p.wall_time - datetime.now(UTC).timestamp()) < 60


def test_camera_keeps_its_recording_start(client):
    pid = client.post("/api/projects", json={"name": "Recorded video"}).json()["id"]
    cam = client.post("/api/cameras", json={"project_id": pid, "name": "Gate (recorded)", "source_type": "file",
                                            "source_uri": str(SAMPLE), "recorded_at": "2018-03-11T15:20:01Z"}).json()
    assert cam["recorded_at"].startswith("2018-03-11T15:20:01")
    cam = client.put(f"/api/cameras/{cam['id']}", json={"recorded_at": "2018-03-11T15:25:01+00:00"}).json()
    assert cam["recorded_at"].startswith("2018-03-11T15:25:01")
    cam = client.put(f"/api/cameras/{cam['id']}", json={"recorded_at": None}).json()
    assert cam["recorded_at"] is None
