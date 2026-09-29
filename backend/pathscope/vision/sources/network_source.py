"""RTSP / HTTP network camera source with reconnect handling."""

from __future__ import annotations

import os
import threading
import time

import cv2

from pathscope.logging_setup import get_logger
from pathscope.vision.sources.base import FrameSource, ReconnectPolicy, SourceError, SourceInfo
from pathscope.vision.types import FramePacket

log = get_logger(__name__)


class NetworkSource(FrameSource):
    source_type = "rtsp"

    def __init__(
        self,
        uri: str,
        reconnect: ReconnectPolicy | None = None,
        transport: str = "tcp",
        source_type: str = "rtsp",
    ) -> None:
        self.uri = uri
        self.reconnect = reconnect or ReconnectPolicy()
        self.transport = transport
        self.source_type = source_type
        self._cap: cv2.VideoCapture | None = None
        self._info: SourceInfo | None = None
        self._frame_index = -1
        self._t0 = 0.0
        self._attempts = 0
        self._consecutive_failures = 0
        self.last_error: str | None = None
        self.reconnect_count = 0

    def _open_capture(self) -> cv2.VideoCapture:
        if self.uri.lower().startswith("rtsp://"):
            # Prefer TCP for RTSP: avoids packet loss artefacts on wifi/VPN links.
            transport = self.transport if self.transport in ("tcp", "udp") else "tcp"
            os.environ["OPENCV_FFMPEG_CAPTURE_OPTIONS"] = (
                f"rtsp_transport;{transport}|stimeout;{int(self.reconnect.read_timeout_s * 1e6)}"
            )
        cap = cv2.VideoCapture(self.uri, cv2.CAP_FFMPEG)
        if not cap.isOpened():
            cap.release()
            raise SourceError(f"could not connect to stream: {self.uri}")
        return cap

    def open(self) -> SourceInfo:
        cap = self._open_capture()
        ok, frame = _read_with_timeout(cap, self.reconnect.read_timeout_s)
        if not ok or frame is None:
            cap.release()
            raise SourceError(f"connected to {self.uri} but received no video frame")
        fps = cap.get(cv2.CAP_PROP_FPS) or 0.0
        if not fps or fps != fps or fps > 240:
            fps = 25.0
        self._cap = cap
        self._info = SourceInfo(
            source_type=self.source_type,
            uri=self.uri,
            width=int(frame.shape[1]),
            height=int(frame.shape[0]),
            fps=float(fps),
            is_live=True,
            backend="ffmpeg",
        )
        self._frame_index = -1
        self._t0 = time.time()
        self._consecutive_failures = 0
        self.last_error = None
        return self._info

    @property
    def info(self) -> SourceInfo:
        if self._info is None:
            return self.open()
        return self._info

    def read(self) -> FramePacket | None:
        if self._cap is None:
            self.open()
        assert self._cap is not None and self._info is not None
        ok, frame = self._cap.read()
        if not ok or frame is None:
            self._consecutive_failures += 1
            if self._consecutive_failures < 5:
                return self.read()  # a single corrupted frame; try again
            if not self._try_reconnect():
                return None
            return self.read()
        self._consecutive_failures = 0
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

    def _try_reconnect(self) -> bool:
        if not self.reconnect.enabled:
            return False
        if self._cap is not None:
            self._cap.release()
            self._cap = None
        delay = self.reconnect.initial_delay_s
        attempt = 0
        while self.reconnect.max_attempts == 0 or attempt < self.reconnect.max_attempts:
            attempt += 1
            log.warning("stream lost, reconnecting", uri=self.uri, attempt=attempt, delay=delay)
            time.sleep(delay)
            try:
                frame_index, t0 = self._frame_index, self._t0
                self.open()
                self._frame_index, self._t0 = frame_index, t0  # time keeps running across the gap
                self.reconnect_count += 1
                log.info("stream reconnected", uri=self.uri, attempt=attempt)
                return True
            except SourceError as exc:
                self.last_error = str(exc)
                delay = min(delay * 2, self.reconnect.max_delay_s)
        return False

    def close(self) -> None:
        if self._cap is not None:
            self._cap.release()
            self._cap = None


def _read_with_timeout(cap: cv2.VideoCapture, timeout_s: float):
    result: list = [False, None]

    def _worker():
        ok, frame = cap.read()
        result[0], result[1] = ok, frame

    th = threading.Thread(target=_worker, daemon=True)
    th.start()
    th.join(timeout_s)
    if th.is_alive():
        return False, None
    return result[0], result[1]


def test_network_stream(uri: str, timeout_s: float = 8.0, transport: str = "tcp") -> dict:
    """Connection diagnostic used by the camera setup UI."""
    started = time.time()
    if not (uri.lower().startswith(("rtsp://", "http://", "https://", "rtmp://", "udp://"))):
        return {
            "ok": False,
            "stage": "validate",
            "message": "The address must start with rtsp://, http://, https://, rtmp:// or udp://.",
        }
    src = NetworkSource(uri, ReconnectPolicy(enabled=False, read_timeout_s=timeout_s), transport=transport)
    try:
        try:
            cap = src._open_capture()
        except SourceError:
            return {
                "ok": False,
                "stage": "connect",
                "message": (
                    "Could not connect. Check the address, username/password, that the camera is "
                    "reachable from this computer, and that the RTSP port (usually 554) is open."
                ),
                "elapsed_s": round(time.time() - started, 2),
            }
        ok, frame = _read_with_timeout(cap, timeout_s)
        cap_fps = cap.get(cv2.CAP_PROP_FPS) or 0.0
        cap.release()
        if not ok or frame is None:
            return {
                "ok": False,
                "stage": "read",
                "message": (
                    "Connected, but no video frame arrived within the timeout. The stream path "
                    "may be wrong, the codec unsupported, or the camera may limit concurrent viewers."
                ),
                "elapsed_s": round(time.time() - started, 2),
            }
        return {
            "ok": True,
            "stage": "done",
            "message": "Stream connected and a frame was decoded.",
            "width": int(frame.shape[1]),
            "height": int(frame.shape[0]),
            "fps": float(cap_fps),
            "elapsed_s": round(time.time() - started, 2),
        }
    finally:
        src.close()
