"""USB / built-in webcam source through OpenCV.

Backend choice matters for frame rate. On Windows, DirectShow often keeps a
webcam in uncompressed YUY2, which USB 2.0 limits to about 5 fps at 720p and
above; Media Foundation negotiates a compressed format and delivers the
camera's full rate (measured: Logitech Brio 100, 4.8 fps with DirectShow vs
31 fps with Media Foundation at 1280x720). CV-Scope therefore tries Media
Foundation first and falls back to DirectShow. On Linux, V4L2 is asked for
MJPG for the same reason.
"""

from __future__ import annotations

import platform
import time

import cv2

from pathscope.logging_setup import get_logger
from pathscope.vision.sources.base import FrameSource, ReconnectPolicy, SourceError, SourceInfo
from pathscope.vision.types import FramePacket

log = get_logger(__name__)


def _backends() -> list[int]:
    system = platform.system()
    if system == "Windows":
        return [cv2.CAP_MSMF, cv2.CAP_DSHOW]
    if system == "Darwin":
        return [cv2.CAP_AVFOUNDATION]
    return [cv2.CAP_V4L2]


def _open_capture(index: int, width: int | None, height: int | None, fps: float | None):
    """Open a device with the first backend that delivers a frame. Returns (cap, first_frame)."""
    for backend in [*_backends(), cv2.CAP_ANY]:
        cap = cv2.VideoCapture(index, backend)
        if not cap.isOpened():
            cap.release()
            continue
        if backend == cv2.CAP_V4L2:
            cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*"MJPG"))
        if width and height:
            cap.set(cv2.CAP_PROP_FRAME_WIDTH, width)
            cap.set(cv2.CAP_PROP_FRAME_HEIGHT, height)
        if fps:
            cap.set(cv2.CAP_PROP_FPS, fps)
        ok, frame = cap.read()
        if ok and frame is not None:
            return cap, frame
        cap.release()
    return None, None


class UsbSource(FrameSource):
    source_type = "usb"

    def __init__(
        self,
        device_index: int = 0,
        width: int | None = None,
        height: int | None = None,
        fps: float | None = None,
        reconnect: ReconnectPolicy | None = None,
        read_retries: int = 10,
    ) -> None:
        self.device_index = int(device_index)
        self.req_width = width
        self.req_height = height
        self.req_fps = fps
        self.reconnect = reconnect or ReconnectPolicy()
        self.read_retries = max(1, read_retries)
        self.reconnect_count = 0
        self._cap: cv2.VideoCapture | None = None
        self._info: SourceInfo | None = None
        self._frame_index = -1
        self._t0 = 0.0

    def open(self) -> SourceInfo:
        cap, frame = _open_capture(self.device_index, self.req_width, self.req_height, self.req_fps)
        if cap is None:
            raise SourceError(
                f"USB camera {self.device_index} could not be opened or delivered no frame. "
                "Check that no other application is using it."
            )
        fps = cap.get(cv2.CAP_PROP_FPS) or 0.0
        if not fps or fps != fps or fps > 240:
            fps = self.req_fps or 30.0
        self._cap = cap
        self._info = SourceInfo(
            source_type="usb",
            uri=str(self.device_index),
            width=int(frame.shape[1]),
            height=int(frame.shape[0]),
            fps=float(fps),
            is_live=True,
            backend=cap.getBackendName() if hasattr(cap, "getBackendName") else "",
        )
        self._frame_index = -1
        self._t0 = time.time()
        return self._info

    @property
    def info(self) -> SourceInfo:
        if self._info is None:
            return self.open()
        return self._info

    def read(self) -> FramePacket | None:
        """Next frame. Short glitches are retried; a camera that stops delivering
        is reopened according to the reconnect policy. ``None`` means it is gone."""
        if self._cap is None:
            self.open()
        assert self._cap is not None and self._info is not None
        failures = 0
        while True:
            ok, frame = self._cap.read()
            if ok and frame is not None:
                break
            failures += 1
            if failures < self.read_retries:
                time.sleep(0.05)
                continue
            if not self._reopen():
                return None
            failures = 0
        self._frame_index += 1
        now = time.time()
        return FramePacket(
            frame=frame,
            frame_index=self._frame_index,
            media_time_s=now - self._t0,
            wall_time=now,
            width=self._info.width,
            height=self._info.height,
        )

    def _reopen(self) -> bool:
        policy = self.reconnect
        if not policy.enabled:
            return False
        if self._cap is not None:
            self._cap.release()
            self._cap = None
        delay = policy.initial_delay_s
        attempt = 0
        while policy.max_attempts == 0 or attempt < policy.max_attempts:
            attempt += 1
            log.warning("USB camera stopped delivering frames; reopening", index=self.device_index, attempt=attempt, delay=delay)
            time.sleep(delay)
            cap, _frame = _open_capture(self.device_index, self.req_width, self.req_height, self.req_fps)
            if cap is not None:
                self._cap = cap
                self.reconnect_count += 1
                log.info("USB camera reopened", index=self.device_index, attempt=attempt)
                return True
            delay = min(delay * 2, policy.max_delay_s)
        return False

    def warm_up(self, seconds: float = 0.6, max_frames: int = 20) -> FramePacket | None:
        """Read frames for a short while so auto-exposure settles; return the last one."""
        last = None
        t_end = time.time() + seconds
        for _ in range(max_frames):
            p = self.read()
            if p is not None:
                last = p
            if time.time() >= t_end:
                break
        return last

    def close(self) -> None:
        if self._cap is not None:
            self._cap.release()
            self._cap = None


def enumerate_usb_cameras(max_index: int = 6, known: dict[int, dict] | None = None) -> list[dict]:
    """Best-effort probe of camera indices 0..max_index-1 with the preferred backend.

    ``known`` lists devices that are already open (live preview or a run); they
    are reported as given instead of being opened a second time, which would fail.
    """
    known = known or {}
    found: list[dict] = []
    backend = _backends()[0]
    misses = 0
    log_api = getattr(getattr(cv2, "utils", None), "logging", None)
    previous = log_api.getLogLevel() if log_api else None
    if log_api:  # empty slots make OpenCV print a warning per index; not useful here
        log_api.setLogLevel(log_api.LOG_LEVEL_ERROR)
    try:
        return _probe(found, backend, max_index, misses, known)
    finally:
        if log_api and previous is not None:
            log_api.setLogLevel(previous)


def _probe(found: list[dict], backend: int, max_index: int, misses: int, known: dict[int, dict]) -> list[dict]:
    for idx in range(max_index):
        if idx in known:
            found.append({"index": idx, **known[idx]})
            misses = 0
            continue
        cap = cv2.VideoCapture(idx, backend)
        try:
            if cap.isOpened():
                ok, frame = cap.read()
                if ok and frame is not None:
                    found.append(
                        {
                            "index": idx,
                            "width": int(frame.shape[1]),
                            "height": int(frame.shape[0]),
                            "fps": float(cap.get(cv2.CAP_PROP_FPS) or 0.0),
                            "backend": cap.getBackendName() if hasattr(cap, "getBackendName") else "",
                        }
                    )
                    misses = 0
                    continue
        finally:
            cap.release()
        misses += 1
        if found and misses >= 2:  # indices are contiguous; stop after two empty slots
            break
    return found
