"""Video file source (uploaded or local files) through OpenCV."""

from __future__ import annotations

import time
from pathlib import Path

import cv2

from pathscope.vision.sources.base import FrameSource, SourceError, SourceInfo
from pathscope.vision.types import FramePacket


class FileSource(FrameSource):
    source_type = "file"

    def __init__(self, path: str, realtime: bool = False, loop: bool = False, recorded_at: float | None = None) -> None:
        self.path = str(path)
        self.realtime = realtime
        self.loop = loop
        # Epoch seconds the recording started: frames are dated start + position
        # (their recording time), not the time they were read.
        self.recorded_at = recorded_at
        self._cap: cv2.VideoCapture | None = None
        self._info: SourceInfo | None = None
        self._frame_index = -1
        self._start_wall = 0.0

    def open(self) -> SourceInfo:
        if not Path(self.path).exists():
            raise SourceError(f"video file not found: {self.path}")
        cap = cv2.VideoCapture(self.path)
        if not cap.isOpened():
            raise SourceError(f"could not open video file: {self.path}")
        fps = cap.get(cv2.CAP_PROP_FPS) or 0.0
        if not fps or fps != fps or fps > 240:
            fps = 25.0
        width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        frame_count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT)) or None
        duration = frame_count / fps if frame_count else None
        self._cap = cap
        self._info = SourceInfo(
            source_type="file",
            uri=self.path,
            width=width,
            height=height,
            fps=float(fps),
            frame_count=frame_count,
            duration_s=duration,
            is_live=False,
            backend=cap.getBackendName() if hasattr(cap, "getBackendName") else "",
        )
        self._frame_index = -1
        self._start_wall = time.time()
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
            if self.loop:
                self._cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
                self._frame_index = -1
                ok, frame = self._cap.read()
                if not ok or frame is None:
                    return None
            else:
                return None
        self._frame_index += 1
        media_t = self._frame_index / self._info.fps
        if self.realtime:
            target = self._start_wall + media_t
            delay = target - time.time()
            if delay > 0:
                time.sleep(min(delay, 1.0))
        return FramePacket(
            frame=frame,
            frame_index=self._frame_index,
            media_time_s=media_t,
            wall_time=self.recorded_at + media_t if self.recorded_at is not None else time.time(),
            width=self._info.width,
            height=self._info.height,
        )

    def seek(self, media_time_s: float) -> bool:
        if self._cap is None:
            self.open()
        assert self._cap is not None and self._info is not None
        target = max(0, int(round(media_time_s * self._info.fps)))
        ok = self._cap.set(cv2.CAP_PROP_POS_FRAMES, target)
        if ok:
            self._frame_index = target - 1
            self._start_wall = time.time() - media_time_s
        return bool(ok)

    def close(self) -> None:
        if self._cap is not None:
            self._cap.release()
            self._cap = None


def probe_video_file(path: str) -> SourceInfo:
    src = FileSource(path)
    try:
        return src.open()
    finally:
        src.close()


def read_frame_at(path: str, media_time_s: float = 0.0):
    """Return (frame_bgr, info) for a single frame at the requested time."""
    src = FileSource(path)
    info = src.open()
    try:
        if media_time_s > 0:
            src.seek(media_time_s)
        packet = src.read()
        if packet is None and media_time_s > 0:
            src.seek(0)
            packet = src.read()
        return (packet.frame if packet else None), info
    finally:
        src.close()
