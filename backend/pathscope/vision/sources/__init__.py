"""Frame source factory."""

from __future__ import annotations

from pathscope.vision.sources.base import FrameSource, ReconnectPolicy, SourceError, SourceInfo
from pathscope.vision.sources.file_source import FileSource, probe_video_file, read_frame_at
from pathscope.vision.sources.network_source import NetworkSource, test_network_stream
from pathscope.vision.sources.usb_source import UsbSource, enumerate_usb_cameras

SOURCE_TYPES = [
    {"id": "file", "label": "Video file", "live": False},
    {"id": "usb", "label": "USB / built-in camera", "live": True},
    {"id": "rtsp", "label": "RTSP stream", "live": True},
    {"id": "http", "label": "HTTP / IP camera stream", "live": True},
]


def create_source(
    source_type: str,
    uri: str,
    *,
    width: int | None = None,
    height: int | None = None,
    fps: float | None = None,
    reconnect: dict | None = None,
    realtime: bool = False,
    loop: bool = False,
    transport: str = "tcp",
    recorded_at: float | None = None,
) -> FrameSource:
    if source_type == "file":
        return FileSource(uri, realtime=realtime, loop=loop, recorded_at=recorded_at)
    if source_type == "usb":
        try:
            index = int(uri or 0)
        except ValueError as exc:
            raise SourceError(f"USB camera index must be a number, got '{uri}'") from exc
        return UsbSource(index, width=width, height=height, fps=fps, reconnect=ReconnectPolicy.from_dict(reconnect))
    if source_type in ("rtsp", "http"):
        return NetworkSource(uri, ReconnectPolicy.from_dict(reconnect), transport=transport, source_type=source_type)
    raise SourceError(f"unsupported source type '{source_type}'")


__all__ = [
    "FrameSource",
    "ReconnectPolicy",
    "SourceError",
    "SourceInfo",
    "FileSource",
    "UsbSource",
    "NetworkSource",
    "SOURCE_TYPES",
    "create_source",
    "probe_video_file",
    "read_frame_at",
    "enumerate_usb_cameras",
    "test_network_stream",
]
