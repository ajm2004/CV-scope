"""Live preview manager and endpoints, with a fake live camera (no real device is opened)."""

from __future__ import annotations

import time

import numpy as np
import pytest

from pathscope.services import preview as preview_mod
from pathscope.services.preview import PreviewConfig, PreviewManager, PreviewUnavailable
from pathscope.vision.sources.base import FrameSource, SourceError, SourceInfo
from pathscope.vision.types import FramePacket


class FakeCamera(FrameSource):
    """Delivers 320x240 frames at ~60 fps; records opens and closes."""

    opened: list[str] = []
    closed: list[str] = []
    fail_open = False

    def __init__(self, cfg: PreviewConfig) -> None:
        self.cfg = cfg
        self.source_type = cfg.source_type
        self._info: SourceInfo | None = None
        self._i = 0

    def open(self) -> SourceInfo:
        if FakeCamera.fail_open:
            raise SourceError("USB camera 5 could not be opened or delivered no frame.")
        FakeCamera.opened.append(self.cfg.source_uri)
        self._info = SourceInfo("usb", self.cfg.source_uri, 320, 240, 30.0, is_live=True, backend="fake")
        return self._info

    @property
    def info(self) -> SourceInfo:
        assert self._info is not None
        return self._info

    def read(self) -> FramePacket | None:
        time.sleep(1 / 60)
        self._i += 1
        frame = np.full((240, 320, 3), (self._i * 5) % 255, dtype=np.uint8)
        return FramePacket(frame, self._i, self._i / 60, time.time(), 320, 240)

    def close(self) -> None:
        FakeCamera.closed.append(self.cfg.source_uri)


def _cfg(camera_id=1, uri="5", rotation=0) -> PreviewConfig:
    return PreviewConfig(camera_id=camera_id, source_type="usb", source_uri=uri, rotation=rotation)


@pytest.fixture()
def manager():
    FakeCamera.opened.clear()
    FakeCamera.closed.clear()
    FakeCamera.fail_open = False
    busy: set[int] = set()
    m = PreviewManager(lambda cfg: cfg.camera_id in busy, factory=FakeCamera, grace_s=0.3)
    m.busy = busy  # type: ignore[attr-defined]
    yield m
    m.stop_all()


def test_viewers_share_one_open_camera_and_it_is_released_after_the_last(manager):
    a = manager.acquire(_cfg())
    b = manager.acquire(_cfg())
    assert a is b and a.subscribers == 2
    assert a.wait_for_frame(5.0)
    assert a.state == "live" and a.jpeg and (a.frame_width, a.frame_height) == (320, 240)
    assert FakeCamera.opened == ["5"]  # opened once for both viewers
    manager.release(a)
    time.sleep(0.6)
    assert manager.get(1) is not None  # one viewer is still watching
    manager.release(b)
    deadline = time.time() + 3
    while (manager.get(1) is not None or not FakeCamera.closed) and time.time() < deadline:
        time.sleep(0.05)
    assert manager.get(1) is None and FakeCamera.closed == ["5"]


def test_a_camera_used_by_a_run_is_never_opened(manager):
    manager.busy.add(1)
    with pytest.raises(PreviewUnavailable):
        manager.acquire(_cfg())
    assert FakeCamera.opened == []


def test_handing_the_device_to_a_run_releases_it(manager):
    s = manager.acquire(_cfg())
    assert s.wait_for_frame(5.0)
    manager.stop_device("usb", "5")
    assert manager.get(1) is None and FakeCamera.closed == ["5"]


def test_viewers_cannot_reopen_a_camera_while_it_is_handed_to_a_run(manager):
    s = manager.acquire(_cfg())
    assert s.wait_for_frame(5.0)
    with manager.handing_over(1, "usb", "5"):
        assert manager.get(1) is None and FakeCamera.closed == ["5"]
        with pytest.raises(PreviewUnavailable):
            manager.acquire(_cfg())
        with pytest.raises(PreviewUnavailable):
            manager.acquire(_cfg(camera_id=2, uri="5"))  # same device, other entry
    again = manager.acquire(_cfg())  # the handover ended (for example the run failed to start)
    assert again.wait_for_frame(5.0)


def test_a_live_preview_gives_the_device_up_when_a_run_claims_it(manager):
    s = manager.acquire(_cfg())
    assert s.wait_for_frame(5.0)
    manager.busy.add(1)  # a run registered for this camera
    deadline = time.time() + 3
    while s.alive and time.time() < deadline:
        time.sleep(0.05)
    assert not s.alive and FakeCamera.closed == ["5"]


def test_changed_settings_reopen_the_camera(manager):
    s1 = manager.acquire(_cfg())
    assert s1.wait_for_frame(5.0)
    s2 = manager.acquire(_cfg(rotation=90))
    assert s2 is not s1 and s2.wait_for_frame(5.0)
    assert (s2.frame_width, s2.frame_height) == (240, 320)  # rotated
    assert FakeCamera.closed == ["5"]


def test_two_camera_entries_for_one_device_do_not_open_it_twice(manager):
    s1 = manager.acquire(_cfg(camera_id=1, uri="5"))
    assert s1.wait_for_frame(5.0)
    s2 = manager.acquire(_cfg(camera_id=2, uri="5"))
    assert s2.wait_for_frame(5.0)
    assert manager.get(1) is None  # the first entry gave the device up
    assert FakeCamera.opened == ["5", "5"] and FakeCamera.closed == ["5"]


def test_a_camera_that_cannot_be_opened_reports_why(manager):
    FakeCamera.fail_open = True
    s = manager.acquire(_cfg())
    assert not s.wait_for_frame(3.0)
    assert s.state == "error" and "could not be opened" in s.error


def test_usb_config_normalises_an_empty_device_index():
    class Cam:
        id, source_type, source_uri, width, height, requested_fps, rotation, crop = 3, "usb", "", None, None, None, 0, None

    cfg = PreviewConfig.from_camera(Cam())
    assert cfg.source_uri == "0" and cfg.device == ("usb", "0")


# ---------------------------------------------------------------- endpoints
@pytest.fixture()
def fake_previews(monkeypatch):
    FakeCamera.opened.clear()
    FakeCamera.closed.clear()
    FakeCamera.fail_open = False
    m = PreviewManager(preview_mod._run_is_using, factory=FakeCamera, grace_s=0.3)
    monkeypatch.setattr(preview_mod, "_manager", m)
    yield m
    m.stop_all()


def test_preview_websocket_and_live_snapshot(client, fake_previews):
    p = client.post("/api/projects", json={"name": "Preview"}).json()
    cam = client.post("/api/cameras", json={"project_id": p["id"], "name": "Webcam", "source_type": "usb", "source_uri": "5"}).json()
    with client.websocket_connect(f"/ws/cameras/{cam['id']}/preview") as ws:
        frames = 0
        meta = None
        for _ in range(60):
            msg = ws.receive()
            if msg.get("text"):
                import json

                m = json.loads(msg["text"])
                if m["type"] == "frame":
                    meta = m
            elif msg.get("bytes"):
                frames += 1
                if frames >= 3:
                    break
        assert frames >= 3 and meta["source_width"] == 320 and meta["source_height"] == 240
    info = client.get(f"/api/cameras/{cam['id']}/frame-info").json()
    assert (info["width"], info["height"], info["is_live"]) == (320, 240, True)
    snap = client.get(f"/api/cameras/{cam['id']}/snapshot")
    assert snap.status_code == 200 and snap.headers["content-type"] == "image/jpeg" and snap.headers["x-frame-width"] == "320"
    status = client.get(f"/api/cameras/{cam['id']}/preview/status").json()
    assert status["state"] == "live"
    assert FakeCamera.opened == ["5"]  # the socket, frame info and snapshot shared one open camera
    test = client.post("/api/cameras/test-connection", json={"source_type": "usb", "source_uri": "5"}).json()
    assert test["ok"] and "live preview" in test["message"]
    client.delete(f"/api/projects/{p['id']}")


def test_file_cameras_have_no_live_preview(client, fake_previews):
    p = client.post("/api/projects", json={"name": "Files"}).json()
    cam = client.post("/api/cameras", json={"project_id": p["id"], "name": "Clip", "source_type": "file", "source_uri": "missing.mp4"}).json()
    with client.websocket_connect(f"/ws/cameras/{cam['id']}/preview") as ws:
        import json

        msg = json.loads(ws.receive_text())
        assert msg["type"] == "error" and "no live preview" in msg["message"]
    client.delete(f"/api/projects/{p['id']}")
