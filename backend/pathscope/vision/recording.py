"""Video recording of live runs, for review and audit.

Two modes, chosen per experiment (``pathscope.domain.recording``):

* ``continuous``: the whole run, in files of ``segment_minutes``.
* ``events``: clips around events. The last seconds are kept in memory as
  JPEG; an event starts a clip with those seconds, and the clip runs until
  ``post_s`` after the last event, at most ``max_clip_s`` long.

The worker hands every processed frame to ``RunRecorder.add_frame``; a
background thread encodes, so a slow encoder never stalls the analysis (when
its queue is full a frame is dropped and counted). Each file follows the run's
media time: a frame is repeated or skipped so that the file's start plus the
video time is the media time, and the review player can jump to an event. A
pause of more than ``GAP_S`` (a reconnect, the computer sleeping) ends the
file. Finished files are reported through ``on_file``.

The optional overlay shows boxes with anonymous track numbers, the scene
objects, the clock time and the events of the moment. It never shows
identities or plates from the licensed recognition modules.
"""

from __future__ import annotations

import queue
import sys
import threading
import time
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

import cv2
import numpy as np

from pathscope.domain.recording import RecordingSettings
from pathscope.domain.scene import SceneDocument
from pathscope.logging_setup import get_logger

log = get_logger(__name__)

GAP_S = 3.0  # a longer pause between frames ends the current file
MAX_WIDTH = 1280  # wider pictures are scaled down for the video
WARMUP_S = 2.0  # the whole-run mode measures the frame rate this long before its first file
EVENT_DELAY_S = 30.0  # events can describe a moment this long ago (a visit reported after its minimum length)
RING_MAX_BYTES = 200 * 1024 * 1024
BANNER_S = 3.0
# "From entry to exit": events that end a visit rather than starting one. Every
# other recorded event of a track opens or refreshes its visit.
CLOSING_EVENTS = {"zone_exit", "route"}

# (fourcc, extension, OpenCV backend, MIME type). H.264 through Windows Media
# Foundation and VP8 WebM through OpenCV's FFmpeg both play in browsers; Motion
# JPEG is the last resort and can only be downloaded. OpenCV gives the Windows
# H.264 encoder about one bit per pixel and frame, so its files are about three
# times larger than VP8's; VP8 costs processor time instead (about 15 ms per
# 640 x 480 frame). Clips prefer H.264, the whole run prefers the smaller VP8.
FORMATS = {
    "h264": ("avc1", ".mp4", "msmf", "video/mp4"),
    "vp8": ("VP80", ".webm", "ffmpeg", "video/webm"),
    "mjpeg": ("MJPG", ".avi", "ffmpeg", "video/x-msvideo"),
}
PREFERENCE = {"events": ["h264", "vp8", "mjpeg"], "continuous": ["vp8", "h264", "mjpeg"]}
_unavailable: set[str] = set()  # formats that failed to open in this process


def open_writer(stem: Path, fps: float, size: tuple[int, int], mode: str = "events") -> tuple[cv2.VideoWriter, Path, str, str]:
    """Open a video writer with the first available format for the mode. Returns (writer, path, mime, fourcc)."""
    for key in PREFERENCE.get(mode, PREFERENCE["events"]):
        if key in _unavailable:
            continue
        fourcc, ext, backend, mime = FORMATS[key]
        if backend == "msmf" and (sys.platform != "win32" or not hasattr(cv2, "CAP_MSMF")):
            continue
        path = stem.with_suffix(ext)
        api = cv2.CAP_MSMF if backend == "msmf" else cv2.CAP_FFMPEG
        writer = cv2.VideoWriter(str(path), api, cv2.VideoWriter_fourcc(*fourcc), float(fps), size)
        if writer.isOpened():
            return writer, path, mime, fourcc
        writer.release()
        path.unlink(missing_ok=True)
        _unavailable.add(key)
    raise RuntimeError("No video encoder is available (tried H.264, VP8 and Motion JPEG).")


def _even(frame: np.ndarray) -> np.ndarray:
    """Encoders want even sizes: drop a last odd row or column."""
    h, w = frame.shape[:2]
    return frame[: h - (h % 2), : w - (w % 2)]


def video_size(width: int, height: int) -> tuple[int, int]:
    """Size of the video for a picture: at most MAX_WIDTH wide, even on both sides."""
    if width > MAX_WIDTH:
        height = round(height * MAX_WIDTH / width)
        width = MAX_WIDTH
    return width - width % 2, height - height % 2


# ---------------------------------------------------------------- overlay
_OBJECT_COLORS = {"line": "#f2b632", "gate": "#29c4e6", "zone": "#52d273", "checkpoint": "#e77df5", "ignore": "#9aa3a0"}
_TRACK_COLORS = ["#ff5e5e", "#ffb347", "#f9f871", "#7bed9f", "#70d6ff", "#c39bff", "#ff8fd8", "#a0e7a0"]


def _bgr(hex_color: str | None, fallback: str = "#ffffff") -> tuple[int, int, int]:
    s = (hex_color or fallback).lstrip("#")
    try:
        r, g, b = int(s[0:2], 16), int(s[2:4], 16), int(s[4:6], 16)
    except (ValueError, IndexError):
        return _bgr(fallback)
    return (b, g, r)


def _ascii(text: str) -> str:
    return "".join(c if 32 <= ord(c) < 127 else "?" for c in text)


def _label(img: np.ndarray, text: str, x: int, y: int, color: tuple[int, int, int], scale: float, thick: int) -> None:
    """Text on a dark box; (x, y) is the box's bottom-left corner."""
    text = _ascii(text)
    (tw, th), base = cv2.getTextSize(text, cv2.FONT_HERSHEY_SIMPLEX, scale, thick)
    h, w = img.shape[:2]
    x = max(0, min(x, w - tw - 6))
    y = max(th + base + 4, min(y, h - 1))
    cv2.rectangle(img, (x, y - th - base - 4), (x + tw + 6, y), (22, 23, 20), -1)
    cv2.putText(img, text, (x + 3, y - base - 2), cv2.FONT_HERSHEY_SIMPLEX, scale, color, thick, cv2.LINE_AA)


def draw_overlay(frame: np.ndarray, tracks, scene: SceneDocument | None, header: str, banners: list[str]) -> np.ndarray:
    """Draw scene objects, tracked boxes with anonymous numbers, the time and recent events."""
    img = frame.copy()
    h, w = img.shape[:2]
    scale = min(1.2, max(0.4, h / 1000.0))
    thick = 1 if h < 720 else 2
    if scene is not None:
        for o in scene.objects:
            if not o.visible or not o.enabled:
                continue
            color = _bgr(o.color, _OBJECT_COLORS.get(o.type, "#ffffff"))
            pts = np.array([[int(p.x * w), int(p.y * h)] for p in o.points], np.int32)
            closed = o.type in ("zone", "checkpoint", "ignore")
            cv2.polylines(img, [pts], closed, color, thick + 1, cv2.LINE_AA)
            if o.name:
                _label(img, o.name, int(pts[0][0]) + 4, int(pts[0][1]) - 4, color, scale * 0.9, thick)
    for t in tracks:
        if t.state != "tracked":
            continue
        color = _bgr(_TRACK_COLORS[t.track_id % len(_TRACK_COLORS)])
        x1, y1, x2, y2 = (int(v) for v in t.box)
        cv2.rectangle(img, (x1, y1), (x2, y2), color, thick + 1)
        _label(img, f"#{t.track_id} {t.class_name}", x1, y1 - 2, color, scale, thick)
    _label(img, header, 0, int(28 * scale / 0.45), (255, 255, 255), scale, thick)
    cv2.circle(img, (w - int(18 * scale / 0.45), int(16 * scale / 0.45)), max(4, int(7 * scale / 0.45)), (40, 40, 230), -1, cv2.LINE_AA)
    y = h - 6
    for text in reversed(banners[-3:]):
        _label(img, text, 6, y, (120, 230, 255), scale, thick)
        y -= int(30 * scale / 0.45)
    return img


def overlay_header(run_id: int, media_t: float, wall: float) -> str:
    m, s = divmod(max(0.0, media_t), 60.0)
    return f"{time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(wall))}  run {run_id}  {int(m):02d}:{s:04.1f}"


# ---------------------------------------------------------------- recorder
@dataclass
class _File:
    writer: cv2.VideoWriter
    path: Path
    mime: str
    fourcc: str
    kind: str  # continuous | event | presence
    size: tuple[int, int]
    fps: float
    start_t: float
    start_wall: float
    written: int = 0
    last_t: float = 0.0
    until: float = 0.0  # event clips: keep writing until this media time
    triggers: list[dict] = field(default_factory=list)
    trigger_count: int = 0


class RunRecorder:
    def __init__(
        self,
        settings: RecordingSettings,
        out_dir: Path,
        fps: float,
        on_file: Callable[[dict], None],
    ) -> None:
        self.s = settings
        self.dir = Path(out_dir)
        self.nominal_fps = float(min(max(fps or 10.0, 1.0), 60.0))  # expected rate of add_frame
        self._times: deque = deque(maxlen=32)  # media times of recent frames, to measure the real rate
        self.on_file = on_file
        self._q: queue.Queue = queue.Queue(maxsize=int(self.nominal_fps * 4) + 8)
        self._ring: deque = deque()  # (media_t, wall, jpeg) waiting for an event
        self._ring_bytes = 0
        self._file: _File | None = None
        self._pending: dict | None = None  # an event clip waiting for its first frame
        # "From entry to exit": track id -> {object_id, label, last_seen}
        self._visits: dict[int, dict] = {}
        self._last_t = -1e9
        self._seq = 0
        self.dropped = 0
        self.files = 0
        self.bytes = 0
        self.error: str | None = None
        self._thread = threading.Thread(target=self._loop, name="recorder", daemon=True)
        self._thread.start()

    # ------------------------------------------------------------ worker side
    def add_frame(self, frame: np.ndarray, media_t: float, wall: float, wait: bool = False, active_ids: set[int] | None = None) -> None:
        """Queue a frame; a full queue drops it (``wait`` blocks instead, for tests).

        ``active_ids`` are the tracks still followed on this frame. "From entry
        to exit" uses them to end a visit when the object is gone and no exit
        event ever arrives."""
        payload = (wall, active_ids)
        try:
            if wait:
                self._q.put(("frame", frame, media_t, payload), timeout=30.0)
            else:
                self._q.put_nowait(("frame", frame, media_t, payload))
        except queue.Full:
            self.dropped += 1

    def trigger(self, media_t: float, info: dict) -> None:
        if not self.s.event_driven:
            return
        try:
            self._q.put(("trigger", None, media_t, info), timeout=2.0)
        except queue.Full:
            log.warning("recording trigger lost: encoder queue full")

    def close(self, timeout_s: float = 20.0) -> None:
        """Finish the open file and stop the thread (reports the last file)."""
        try:
            self._q.put(("close", None, 0.0, None), timeout=timeout_s)
        except queue.Full:
            pass
        self._thread.join(timeout_s)

    @property
    def state(self) -> dict:
        return {
            "mode": self.s.mode,
            "active": self._file is not None,
            "files": self.files,
            "bytes": self.bytes,
            "dropped": self.dropped,
            "error": self.error,
        }

    # ------------------------------------------------------------ encoder thread
    def _loop(self) -> None:
        while True:
            kind, frame, t, extra = self._q.get()
            try:
                if kind == "close":
                    self._finish()
                    return
                if kind == "frame":
                    wall, active = extra if isinstance(extra, tuple) else (extra, None)
                    self._on_frame(frame, t, wall, active)
                elif kind == "trigger":
                    self._on_trigger(t, extra)
            except Exception as exc:  # noqa: BLE001 - recording must never end the run
                self.error = f"{type(exc).__name__}: {exc}"
                log.warning("recording failed", error=self.error)
                self._finish()

    def _on_frame(self, frame: np.ndarray, t: float, wall: float, active_ids: set[int] | None = None) -> None:
        f = self._file
        if f is not None and t - f.last_t > GAP_S:
            self._finish()  # the camera paused: the file ends where the picture stopped
            f = None
        if t - self._last_t > GAP_S:
            # after a pause the old frames and the old frame rate no longer apply
            self._times.clear()
            self._ring.clear()
            self._ring_bytes = 0
        self._last_t = t
        self._times.append(t)
        if self.s.mode == "continuous":
            if f is None and self._measured_rate() is None and (not self._ring or t - self._ring[0][0] < WARMUP_S):
                self._buffer(frame, t, wall)  # measure the frame rate before the first file
                return
            if f is None:
                f = self._open_from_ring("continuous", frame, t, wall)
            self._write(f, frame, t)
            if t - f.start_t >= self.s.segment_minutes * 60.0:
                self._finish()
            return
        if self.s.mode == "presence":
            self._age_visits(t, active_ids)
        if f is None and self._pending is not None:
            f = self._open("presence" if self.s.mode == "presence" else "event", frame, t, wall)
            f.until, f.triggers, f.trigger_count = self._pending["until"], self._pending["triggers"], self._pending["count"]
            self._pending = None
        if f is None:
            self._buffer(frame, t, wall)
            horizon = self.s.pre_s + EVENT_DELAY_S
            while self._ring and (t - self._ring[0][0] > horizon or self._ring_bytes > RING_MAX_BYTES):
                self._ring_bytes -= len(self._ring.popleft()[2])
            return
        self._write(f, frame, t)
        if self._visits:
            # Someone is still inside: the clip runs on, and the tail after the
            # last exit is the same post_s as an event clip.
            f.until = max(f.until, t + self.s.post_s)
        if t - f.start_t >= self.s.max_clip_s:
            # A long visit is kept whole, in files of max_clip_s that follow on
            # from each other, rather than cut short.
            carry = list(f.triggers)
            count = f.trigger_count
            self._finish()
            if self._visits:
                nxt = self._open("presence", frame, t, wall)
                nxt.until = t + self.s.post_s
                nxt.triggers = [*carry[-3:], {"type": "continued", "label": "visit continues", "track_id": 0, "media_time_s": round(t, 3)}]
                nxt.trigger_count = count + 1
                self._write(nxt, frame, t)
            return
        if t >= f.until:
            self._finish()

    def _age_visits(self, t: float, active_ids: set[int] | None) -> None:
        """End visits whose object is no longer tracked (no exit event came)."""
        if active_ids is None:
            return
        grace = float(getattr(self.s, "presence_grace_s", 3.0))
        for track_id, visit in list(self._visits.items()):
            if track_id in active_ids:
                visit["last_seen"] = t
            elif t - visit["last_seen"] > grace:
                del self._visits[track_id]

    def _on_trigger(self, t_event: float, info: dict) -> None:
        if self.s.mode == "presence":
            track_id = int(info.get("track_id") or 0)
            if track_id:
                visit = self._visits.get(track_id)
                closes = info.get("type") in CLOSING_EVENTS and (visit is None or not visit.get("object_id") or visit["object_id"] == info.get("object_id"))
                if closes:
                    self._visits.pop(track_id, None)
                else:
                    self._visits[track_id] = {"object_id": info.get("object_id"), "label": info.get("label"), "last_seen": max(t_event, self._last_t)}
        until = max(t_event, self._last_t) + self.s.post_s
        f = self._file
        if f is not None:
            f.until = max(f.until, until)
            self._note(f, info)
            return
        if self._pending is not None:
            self._pending["until"] = max(self._pending["until"], until)
            self._pending["count"] += 1
            if len(self._pending["triggers"]) < 100:
                self._pending["triggers"].append(info)
            return
        start = t_event - self.s.pre_s
        buffered = [e for e in self._ring if e[0] >= start - 1e-6]
        self._ring.clear()
        self._ring_bytes = 0
        if not buffered:
            self._pending = {"until": until, "triggers": [info], "count": 1}
            return
        t0, wall0, jpeg0 = buffered[0]
        first = cv2.imdecode(np.frombuffer(jpeg0, np.uint8), cv2.IMREAD_COLOR)
        f = self._open("presence" if self.s.mode == "presence" else "event", first, t0, wall0)
        f.until = until
        self._note(f, info)
        self._write(f, first, t0)
        for t, _wall, jpeg in buffered[1:]:
            self._write(f, cv2.imdecode(np.frombuffer(jpeg, np.uint8), cv2.IMREAD_COLOR), t)

    def _buffer(self, frame: np.ndarray, t: float, wall: float) -> None:
        jpeg = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 85])[1].tobytes()
        self._ring.append((t, wall, jpeg))
        self._ring_bytes += len(jpeg)

    def _open_from_ring(self, kind: str, frame: np.ndarray, t: float, wall: float) -> _File:
        """Open a file that starts with the buffered frames, then the current one."""
        buffered = list(self._ring)
        self._ring.clear()
        self._ring_bytes = 0
        if not buffered:
            return self._open(kind, frame, t, wall)
        t0, wall0, jpeg0 = buffered[0]
        first = cv2.imdecode(np.frombuffer(jpeg0, np.uint8), cv2.IMREAD_COLOR)
        f = self._open(kind, first, t0, wall0)
        self._write(f, first, t0)
        for tt, _wall, jpeg in buffered[1:]:
            self._write(f, cv2.imdecode(np.frombuffer(jpeg, np.uint8), cv2.IMREAD_COLOR), tt)
        return f

    def _measured_rate(self) -> float | None:
        """Frames per second actually arriving (network cameras often report a wrong rate)."""
        if len(self._times) < 9 or self._times[-1] - self._times[0] <= 0:
            return None
        return (len(self._times) - 1) / (self._times[-1] - self._times[0])

    @staticmethod
    def _note(f: _File, info: dict) -> None:
        f.trigger_count += 1
        if len(f.triggers) < 100:
            f.triggers.append(info)

    def _open(self, kind: str, frame: np.ndarray, t: float, wall: float) -> _File:
        size = video_size(frame.shape[1], frame.shape[0])
        # At most the chosen video rate, and no faster than frames really arrive
        fps = round(min(float(self.s.fps), self._measured_rate() or self.nominal_fps), 2)
        self.dir.mkdir(parents=True, exist_ok=True)
        self._seq += 1
        stem = self.dir / f"{kind}-{time.strftime('%Y%m%d-%H%M%S', time.localtime(wall))}-{self._seq:03d}"
        writer, path, mime, fourcc = open_writer(stem, fps, size, self.s.mode)
        self._file = _File(writer, path, mime, fourcc, kind, size, fps, t, wall, last_t=t)
        return self._file

    def _write(self, f: _File, frame: np.ndarray, t: float) -> None:
        # Frame number this media time falls on; repeat a frame to fill a short
        # gap, skip one that arrives ahead of the clock.
        target = int(round((t - f.start_t) * f.fps))
        if target < f.written:
            return
        if (frame.shape[1], frame.shape[0]) != f.size:
            frame = cv2.resize(_even(frame), f.size, interpolation=cv2.INTER_AREA)
        for _ in range(min(target - f.written + 1, int(f.fps * GAP_S) + 1)):
            f.writer.write(frame)
            f.written += 1
        f.last_t = t

    def _finish(self) -> None:
        f = self._file
        self._file = None
        if f is None:
            return
        f.writer.release()
        size = f.path.stat().st_size if f.path.exists() else 0
        if f.written == 0 or size == 0:
            f.path.unlink(missing_ok=True)
            return
        self.files += 1
        self.bytes += size
        duration = f.written / f.fps
        self.on_file({
            "kind": f.kind, "path": str(f.path), "mime": f.mime, "codec": f.fourcc,
            "width": f.size[0], "height": f.size[1], "fps": f.fps, "frames": f.written,
            "media_start_s": f.start_t, "media_end_s": f.start_t + duration,
            "wall_start": f.start_wall, "wall_end": f.start_wall + duration,
            "size_bytes": size, "overlay": self.s.overlay,
            "triggers": f.triggers, "trigger_count": f.trigger_count,
        })
