"""Live camera preview outside of runs.

A USB camera can be used by one process at a time: a second process opens it
but receives no frames. RTSP cameras often limit the number of viewers too.
This manager is therefore the single owner of live cameras inside the API
process:

* it opens a camera while at least one viewer is watching (Scene Builder,
  Cameras page, snapshot and frame-info requests), shares the frames among
  viewers, and releases the device a few seconds after the last viewer leaves;
* it never opens a camera that a run is using, and a camera is released
  before a run's worker process opens it (see ``run_launcher``).

Video files are not handled here; they are previewed with snapshots.
"""

from __future__ import annotations

import threading
import time
from collections import deque
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass

from pathscope.logging_setup import get_logger
from pathscope.vision.preprocessing import (
    PreprocessConfig,
    apply_preprocess,
    encode_jpeg,
    resize_for_preview,
)
from pathscope.vision.sources import FrameSource, SourceError, create_source

log = get_logger(__name__)

LIVE_SOURCE_TYPES = ("usb", "rtsp", "http")


class PreviewUnavailable(RuntimeError):
    """The camera cannot be previewed right now (a run is using it)."""


def device_key(source_type: str, uri: str | None) -> tuple[str, str]:
    """Identity of the physical device: USB cameras by index, streams by address."""
    uri = (uri or "").strip()
    if source_type == "usb":
        try:
            return ("usb", str(int(uri or 0)))
        except ValueError:
            return ("usb", uri)
    return (source_type, uri)


@dataclass(frozen=True)
class PreviewConfig:
    camera_id: int
    source_type: str
    source_uri: str
    width: int | None = None
    height: int | None = None
    fps: float | None = None
    rotation: int = 0
    crop: tuple[float, float, float, float] | None = None

    @classmethod
    def from_camera(cls, cam) -> PreviewConfig:
        crop = cam.crop or None
        crop_t = (
            tuple(float(crop.get(k, d)) for k, d in (("x", 0.0), ("y", 0.0), ("w", 1.0), ("h", 1.0)))
            if crop else None
        )
        return cls(
            camera_id=int(cam.id),
            source_type=cam.source_type,
            source_uri=device_key(cam.source_type, cam.source_uri)[1] if cam.source_type == "usb" else (cam.source_uri or ""),
            width=cam.width if cam.source_type == "usb" else None,
            height=cam.height if cam.source_type == "usb" else None,
            fps=cam.requested_fps if cam.source_type == "usb" else None,
            rotation=int(cam.rotation or 0),
            crop=crop_t,  # type: ignore[arg-type]
        )

    @property
    def device(self) -> tuple[str, str]:
        return device_key(self.source_type, self.source_uri)

    def preprocess(self) -> PreprocessConfig:
        crop = dict(zip(("x", "y", "w", "h"), self.crop, strict=True)) if self.crop else None
        return PreprocessConfig(rotation=self.rotation, crop=crop)


def _rtsp_transport() -> str:
    try:
        from pathscope.db.session import get_session_factory
        from pathscope.settings_store import get_setting

        session = get_session_factory()()
        try:
            return str(get_setting(session, "rtsp_transport", "tcp") or "tcp")
        finally:
            session.close()
    except Exception:  # noqa: BLE001 - fall back to the default when the database is unavailable
        return "tcp"


def _default_factory(cfg: PreviewConfig) -> FrameSource:
    transport = _rtsp_transport() if cfg.source_type == "rtsp" else "tcp"
    return create_source(cfg.source_type, cfg.source_uri, width=cfg.width, height=cfg.height, fps=cfg.fps, reconnect={"enabled": False}, transport=transport)


class PreviewSession:
    """One open camera, read continuously on a background thread."""

    def __init__(
        self,
        cfg: PreviewConfig,
        factory: Callable[[PreviewConfig], FrameSource],
        is_busy: Callable[[PreviewConfig], bool],
        max_width: int = 1280,
        preview_fps: float = 15.0,
        quality: int = 80,
    ) -> None:
        self.cfg = cfg
        self._factory = factory
        self._is_busy = is_busy
        self.max_width = max_width
        self._interval = 1.0 / max(preview_fps, 1.0)
        self.quality = quality
        self.state = "opening"  # opening | live | error | stopped
        self.error: str | None = None
        self.jpeg: bytes | None = None
        self.seq = 0
        self.preview_width = self.preview_height = 0
        self.frame_width = self.frame_height = 0  # geometry frame: after rotation and crop
        self.source_width = self.source_height = 0
        self.source_fps = 0.0
        self.fps = 0.0
        self.backend = ""
        self.first_frame_at: float | None = None
        self.subscribers = 0
        self.idle_since: float | None = time.time()
        self._stop = threading.Event()
        self._cond = threading.Condition()
        self._thread = threading.Thread(target=self._run, daemon=True, name=f"preview-camera-{cfg.camera_id}")

    # ------------------------------------------------------------------ control
    def start(self) -> None:
        self._thread.start()

    def stop(self, wait: bool = True, timeout: float = 6.0) -> None:
        self._stop.set()
        with self._cond:
            self._cond.notify_all()
        if wait and self._thread.is_alive() and threading.current_thread() is not self._thread:
            self._thread.join(timeout)

    @property
    def alive(self) -> bool:
        return self._thread.is_alive() and not self._stop.is_set()

    def wait_for_frame(self, timeout: float, min_live_s: float = 0.0) -> bool:
        """Block until a frame is available (and the camera has been live ``min_live_s``)."""
        deadline = time.time() + timeout
        with self._cond:
            while True:
                ready = self.seq > 0 and self.first_frame_at is not None and time.time() - self.first_frame_at >= min_live_s
                if ready:
                    return True
                if self._stop.is_set() or self.state == "stopped":
                    return self.seq > 0
                if self.state == "error" and self.seq == 0 and time.time() > deadline - timeout + 1.5:
                    return False  # opening failed; do not wait for the retry
                remaining = deadline - time.time()
                if remaining <= 0:
                    return self.seq > 0
                self._cond.wait(min(remaining, 0.25))

    def status(self) -> dict:
        return {
            "state": self.state,
            "error": self.error,
            "fps": self.fps,
            "backend": self.backend,
            "frame_width": self.frame_width,
            "frame_height": self.frame_height,
            "source_width": self.source_width,
            "source_height": self.source_height,
            "source_fps": self.source_fps,
            "viewers": self.subscribers,
        }

    # ------------------------------------------------------------------ thread
    def _set(self, **values) -> None:
        with self._cond:
            for k, v in values.items():
                setattr(self, k, v)
            self._cond.notify_all()

    def _run(self) -> None:
        delay = 1.0
        pre = self.cfg.preprocess()
        while not self._stop.is_set():
            if self._is_busy(self.cfg):
                self._set(state="stopped", error="A run is using this camera.")
                return
            try:
                src = self._factory(self.cfg)
                info = src.open()
            except Exception as exc:  # noqa: BLE001 - reported to viewers, retried
                self._set(state="error", error=str(exc))
                if self._stop.wait(delay):
                    break
                delay = min(delay * 2, 8.0)
                continue
            delay = 1.0
            self._set(backend=info.backend, source_width=info.width, source_height=info.height, source_fps=info.fps)
            log.info("preview opened", camera_id=self.cfg.camera_id, source=self.cfg.source_type, size=f"{info.width}x{info.height}", backend=info.backend)
            arrivals: deque[float] = deque(maxlen=30)
            last_emit = 0.0
            last_busy_check = time.perf_counter()
            misses = 0
            try:
                while not self._stop.is_set():
                    if time.perf_counter() - last_busy_check >= 0.25:
                        last_busy_check = time.perf_counter()
                        if self._is_busy(self.cfg):
                            self._stop.set()  # a run is taking the device over
                            break
                    packet = src.read()
                    if packet is None:
                        misses += 1
                        if misses >= 3:
                            raise SourceError("The camera stopped delivering frames.")
                        continue
                    misses = 0
                    now = time.perf_counter()
                    arrivals.append(now)
                    # 20 % slack: a 30 fps camera delivers every other frame a hair
                    # before the 15 fps interval, which would halve the rate.
                    if now - last_emit < self._interval * 0.8:
                        continue
                    last_emit = now
                    frame = apply_preprocess(packet.frame, pre)
                    small = resize_for_preview(frame, self.max_width)
                    jpeg = encode_jpeg(small, self.quality)
                    fps = (len(arrivals) - 1) / (arrivals[-1] - arrivals[0]) if len(arrivals) > 1 and arrivals[-1] > arrivals[0] else 0.0
                    with self._cond:
                        self.jpeg = jpeg
                        self.seq += 1
                        self.preview_width, self.preview_height = int(small.shape[1]), int(small.shape[0])
                        self.frame_width, self.frame_height = int(frame.shape[1]), int(frame.shape[0])
                        self.fps = round(fps, 1)
                        if self.first_frame_at is None:
                            self.first_frame_at = time.time()
                        self.state = "live"
                        self.error = None
                        self._cond.notify_all()
            except Exception as exc:  # noqa: BLE001
                self._set(state="error", error=str(exc))
                log.warning("preview interrupted", camera_id=self.cfg.camera_id, error=str(exc))
            finally:
                try:
                    src.close()
                except Exception:  # noqa: BLE001
                    pass
            if self._stop.wait(delay):
                break
        self._set(state="stopped")
        log.info("preview closed", camera_id=self.cfg.camera_id)


class PreviewManager:
    def __init__(
        self,
        is_busy: Callable[[PreviewConfig], bool],
        factory: Callable[[PreviewConfig], FrameSource] | None = None,
        grace_s: float = 4.0,
        max_width: int = 1280,
        preview_fps: float = 15.0,
    ) -> None:
        self._is_busy = is_busy
        self._factory = factory or _default_factory
        self.grace_s = grace_s
        self.max_width = max_width
        self.preview_fps = preview_fps
        self._sessions: dict[int, PreviewSession] = {}
        self._lock = threading.RLock()
        self._reaper: threading.Thread | None = None
        self._closed = threading.Event()
        # Cameras being handed to a run: camera ids / device keys -> count. A
        # separate lock: session threads ask ``_busy`` while ``acquire`` may
        # hold ``_lock`` and wait for one of them to finish.
        self._handover_lock = threading.Lock()
        self._handover_ids: dict[int, int] = {}
        self._handover_devices: dict[tuple[str, str], int] = {}

    def _busy(self, cfg: PreviewConfig) -> bool:
        with self._handover_lock:
            if self._handover_ids.get(cfg.camera_id) or self._handover_devices.get(cfg.device):
                return True
        return self._is_busy(cfg)

    # ------------------------------------------------------------------ viewers
    def acquire(self, cfg: PreviewConfig) -> PreviewSession:
        if cfg.source_type not in LIVE_SOURCE_TYPES:
            raise ValueError("video files are previewed with snapshots, not a live preview")
        with self._lock:
            if self._busy(cfg):
                raise PreviewUnavailable("A run is using this camera; its live view is shown instead.")
            session = self._sessions.get(cfg.camera_id)
            if session is not None and (session.cfg != cfg or not session.alive):
                del self._sessions[cfg.camera_id]
                session.stop(wait=True)  # configuration changed (rotation, resolution...)
                session = None
            for other_id, other in list(self._sessions.items()):
                if other_id != cfg.camera_id and other.cfg.device == cfg.device:
                    del self._sessions[other_id]  # another camera entry for the same device
                    other.stop(wait=True)
            if session is None:
                session = PreviewSession(cfg, self._factory, self._busy, self.max_width, self.preview_fps)
                session.start()
                self._sessions[cfg.camera_id] = session
            session.subscribers += 1
            session.idle_since = None
            self._ensure_reaper()
            return session

    def release(self, session: PreviewSession) -> None:
        with self._lock:
            session.subscribers = max(0, session.subscribers - 1)
            if session.subscribers == 0:
                session.idle_since = time.time()

    # ------------------------------------------------------------------ queries
    def get(self, camera_id: int) -> PreviewSession | None:
        with self._lock:
            s = self._sessions.get(camera_id)
            return s if s is not None and s.alive else None

    def holding(self, source_type: str, uri: str | None) -> PreviewSession | None:
        key = device_key(source_type, uri)
        with self._lock:
            return next((s for s in self._sessions.values() if s.alive and s.cfg.device == key), None)

    def sessions(self) -> list[PreviewSession]:
        with self._lock:
            return [s for s in self._sessions.values() if s.alive]

    # ------------------------------------------------------------------ stopping
    def stop_camera(self, camera_id: int) -> None:
        with self._lock:
            session = self._sessions.pop(camera_id, None)
        if session is not None:
            session.stop(wait=True)

    def stop_device(self, source_type: str, uri: str | None) -> None:
        """Release a physical device before a run's worker opens it."""
        key = device_key(source_type, uri)
        with self._lock:
            victims = [cid for cid, s in self._sessions.items() if s.cfg.device == key]
            sessions = [self._sessions.pop(cid) for cid in victims]
        for s in sessions:
            s.stop(wait=True)

    @contextmanager
    def handing_over(self, camera_id: int, source_type: str, uri: str | None) -> Iterator[None]:
        """Release a camera for a run and keep viewers from reopening it meanwhile.

        Start the run inside the block. Once the run is registered, the run
        itself keeps the preview away from the device.
        """
        key = device_key(source_type, uri) if source_type in LIVE_SOURCE_TYPES else None
        with self._handover_lock:
            self._handover_ids[camera_id] = self._handover_ids.get(camera_id, 0) + 1
            if key is not None:
                self._handover_devices[key] = self._handover_devices.get(key, 0) + 1
        try:
            self.stop_camera(camera_id)
            if key is not None:
                self.stop_device(source_type, uri)
            yield
        finally:
            with self._handover_lock:
                self._handover_ids[camera_id] -= 1
                if not self._handover_ids[camera_id]:
                    del self._handover_ids[camera_id]
                if key is not None:
                    self._handover_devices[key] -= 1
                    if not self._handover_devices[key]:
                        del self._handover_devices[key]

    def stop_all(self) -> None:
        self._closed.set()
        with self._lock:
            sessions = list(self._sessions.values())
            self._sessions.clear()
        for s in sessions:
            s.stop(wait=True)

    def _ensure_reaper(self) -> None:
        if self._reaper is None or not self._reaper.is_alive():
            self._closed.clear()
            self._reaper = threading.Thread(target=self._reap, daemon=True, name="preview-reaper")
            self._reaper.start()

    def _reap(self) -> None:
        while not self._closed.wait(0.5):
            now = time.time()
            idle: list[PreviewSession] = []
            with self._lock:
                for cid, s in list(self._sessions.items()):
                    expired = s.subscribers == 0 and s.idle_since is not None and now - s.idle_since >= self.grace_s
                    if expired or not s.alive or self._busy(s.cfg):
                        idle.append(self._sessions.pop(cid))
            for s in idle:
                s.stop(wait=True)


def _run_is_using(cfg: PreviewConfig) -> bool:
    from pathscope.workers.supervisor import get_supervisor

    for h in get_supervisor().active():
        if h.spec.camera_id == cfg.camera_id:
            return True
        if device_key(h.spec.source_type, h.spec.source_uri) == cfg.device:
            return True
    return False


_manager: PreviewManager | None = None


def get_preview_manager() -> PreviewManager:
    global _manager
    if _manager is None:
        _manager = PreviewManager(_run_is_using)
    return _manager
