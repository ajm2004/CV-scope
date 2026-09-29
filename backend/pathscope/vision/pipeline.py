"""Frame pipeline: source -> preprocessing -> detector -> tracker -> spatial -> rules.

Used by the camera worker and by tests. The pipeline itself is synchronous; the
worker drives it and handles commands, previews and persistence.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field

import numpy as np

from pathscope.domain.rules import Rule
from pathscope.domain.scene import SceneDocument, empty_scene
from pathscope.logging_setup import get_logger
from pathscope.rules.engine import EventRecord, RuleEngine
from pathscope.spatial.engine import Interaction, SpatialEngine
from pathscope.vision.detectors import Detector, DetectorConfig, create_detector
from pathscope.vision.preprocessing import PreprocessConfig, apply_preprocess
from pathscope.vision.sources import FrameSource, SourceInfo, create_source
from pathscope.vision.trackers import Tracker, create_tracker
from pathscope.vision.trackers.base import TrackerUpdate
from pathscope.vision.types import FramePacket, Track

log = get_logger(__name__)


@dataclass
class PipelineConfig:
    source_type: str
    source_uri: str
    detector: DetectorConfig
    scene: SceneDocument | None = None
    rules: list[Rule] = field(default_factory=list)
    tracked_classes: list[str] = field(default_factory=list)
    tracker_id: str = "bytetrack"
    tracker_settings: dict = field(default_factory=dict)
    preprocess: PreprocessConfig = field(default_factory=PreprocessConfig)
    processing_fps: float | None = None  # None = every frame
    frame_skip: int = 0  # additional frames to skip after each processed frame
    source_width: int | None = None
    source_height: int | None = None
    source_fps: float | None = None
    reconnect: dict = field(default_factory=dict)
    rtsp_transport: str = "tcp"
    realtime: bool = False  # pace file playback at source FPS
    loop: bool = False
    # Video files: epoch seconds the recording started; frames are then dated
    # start + position instead of the time they were read
    recorded_at: float | None = None
    trajectory_sample_s: float = 0.1
    models_dir: str | None = None  # appearance models for BoT-SORT
    # Licensed recognition modules: the run payload built by
    # pathscope.recognition.service (None in the open-source core)
    recognition: dict | None = None
    # The relationship engine runs for this run (rules may use HAS RELATIONSHIP)
    relations_enabled: bool = False


@dataclass
class StepResult:
    packet: FramePacket
    frame: np.ndarray  # preprocessed frame the geometry refers to
    processed: bool  # False when the frame was skipped (no detection/tracking)
    tracks: list[Track]
    interactions: list[Interaction]
    events: list[EventRecord]
    update: TrackerUpdate | None
    timings_ms: dict[str, float]
    recognition_events: list[dict] = field(default_factory=list)


class Pipeline:
    def __init__(self, cfg: PipelineConfig) -> None:
        self.cfg = cfg
        self.source: FrameSource | None = None
        self.info: SourceInfo | None = None
        self.detector: Detector | None = None
        self.tracker: Tracker | None = None
        self.spatial: SpatialEngine | None = None
        self.rules: RuleEngine | None = None
        self.recognition = None  # RecognitionRuntime when a licensed module is active for this run
        self.frame_width = 0
        self.frame_height = 0
        self.processed_frames = 0
        self.read_frames = 0
        self._last_processed_t = -1e9
        self._next_due: float | None = None  # media time the next frame is due (processing FPS)
        self._skip_left = 0
        self._last_tracks: list[Track] = []
        self._fps_window: list[float] = []

    # ------------------------------------------------------------------ lifecycle
    def open(self) -> SourceInfo:
        cfg = self.cfg
        self.source = create_source(
            cfg.source_type, cfg.source_uri, width=cfg.source_width, height=cfg.source_height,
            fps=cfg.source_fps, reconnect=cfg.reconnect, realtime=cfg.realtime, loop=cfg.loop,
            transport=cfg.rtsp_transport, recorded_at=cfg.recorded_at,
        )
        self.info = self.source.open()
        self.frame_width, self.frame_height = cfg.preprocess.output_size(self.info.width, self.info.height)
        scene = cfg.scene or empty_scene(self.frame_width, self.frame_height)
        self.spatial = SpatialEngine(scene, self.frame_width, self.frame_height, cfg.tracked_classes, cfg.trajectory_sample_s)
        det_cfg = cfg.detector
        grace_s = 5.0
        if cfg.recognition and (cfg.recognition.get("face") or cfg.recognition.get("plate")):
            # Imported only when a licensed module is active for this run
            from pathscope.recognition.runtime import RecognitionRuntime

            self.recognition = RecognitionRuntime.from_payload(cfg.recognition, device=det_cfg.device)
            grace_s = self.recognition.subject_grace_s
        self.rules = RuleEngine(scene, cfg.rules, self.spatial, cfg.tracked_classes, entities=self.recognition, subject_grace_s=grace_s, relations_available=cfg.relations_enabled)
        self.tracker = create_tracker(cfg.tracker_id, cfg.tracker_settings, device=det_cfg.device, models_dir=cfg.models_dir)
        if cfg.tracked_classes and not det_cfg.classes:
            det_cfg.classes = list(cfg.tracked_classes)
        self.detector = create_detector(det_cfg)
        self.detector.load()
        self.detector.warmup(self.frame_width, self.frame_height, iterations=1)
        log.info(
            "pipeline opened", source=cfg.source_type, size=f"{self.frame_width}x{self.frame_height}",
            fps=self.info.fps, detector=self.detector.describe(), tracker=self.tracker.describe(),
            spatial=self.spatial.describe(), rules=self.rules.describe(),
        )
        return self.info

    def close(self) -> None:
        if self.source is not None:
            self.source.close()
            self.source = None
        if self.detector is not None:
            self.detector.close()
        if self.tracker is not None:
            self.tracker.close()
        if self.recognition is not None:
            self.recognition.close()

    # ------------------------------------------------------------------ stepping
    def _should_process(self, packet: FramePacket) -> bool:
        if self._skip_left > 0:
            self._skip_left -= 1
            return False
        fps = self.cfg.processing_fps
        if fps and fps > 0:
            interval = 1.0 / fps
            t = packet.media_time_s
            # Keep a fixed schedule and accept a frame a little early: camera frames
            # arrive with jitter, and waiting a full interval after the last processed
            # frame turned 10 fps from a 30 fps camera into every 4th frame (7.5 fps).
            if self._next_due is not None and t < self._next_due - 0.2 * interval:
                return False
            if self._next_due is None or t - self._next_due > interval:
                self._next_due = t + interval  # first frame, or after a stall
            else:
                self._next_due += interval
        return True

    def step(self) -> StepResult | None:
        assert self.source and self.detector and self.tracker and self.spatial and self.rules
        t_read0 = time.perf_counter()
        packet = self.source.read()
        if packet is None:
            return None
        self.read_frames += 1
        t_read = (time.perf_counter() - t_read0) * 1000.0

        t0 = time.perf_counter()
        frame = apply_preprocess(packet.frame, self.cfg.preprocess)
        t_pre = (time.perf_counter() - t0) * 1000.0

        if not self._should_process(packet):
            return StepResult(packet, frame, False, self._last_tracks, [], [], None, {"read": t_read, "preprocess": t_pre})

        self._last_processed_t = packet.media_time_s
        self._skip_left = max(0, self.cfg.frame_skip)
        self.processed_frames += 1

        t1 = time.perf_counter()
        detections = self.detector.detect(frame)
        detections = self.spatial.filter_detections(detections)
        t_det = (time.perf_counter() - t1) * 1000.0

        t2 = time.perf_counter()
        update = self.tracker.update(detections, packet.frame_index, packet.media_time_s, frame=frame)
        t_trk = (time.perf_counter() - t2) * 1000.0

        # Recognition runs on the tracks before the rules see this frame, so an
        # identity found now can satisfy a rule in the same step.
        recognition_events: list[dict] = []
        t_rec = 0.0
        if self.recognition is not None:
            tr0 = time.perf_counter()
            rec = self.recognition.observe(frame, update.tracks, packet.media_time_s, packet.frame_index, packet.wall_time)
            recognition_events = rec.events
            t_rec = (time.perf_counter() - tr0) * 1000.0

        t3 = time.perf_counter()
        interactions = self.spatial.update(update, packet.media_time_s, packet.frame_index)
        t_sp = (time.perf_counter() - t3) * 1000.0

        t4 = time.perf_counter()
        events = self.rules.process(interactions, packet.media_time_s, packet.frame_index, packet.wall_time)
        t_rules = (time.perf_counter() - t4) * 1000.0

        self._last_tracks = update.tracks
        total = (time.perf_counter() - t_read0) * 1000.0
        self._fps_window.append(time.perf_counter())
        if len(self._fps_window) > 60:
            self._fps_window.pop(0)
        timings = {
            "read": t_read, "preprocess": t_pre + self.detector.last_preprocess_ms,
            "detect": t_det, "track": t_trk, "spatial": t_sp, "rules": t_rules, "total": total,
        }
        if self.recognition is not None:
            timings["recognition"] = t_rec
        return StepResult(packet, frame, True, update.tracks, interactions, events, update, timings, recognition_events)

    def pipeline_fps(self) -> float:
        if len(self._fps_window) < 2:
            return 0.0
        span = self._fps_window[-1] - self._fps_window[0]
        return (len(self._fps_window) - 1) / span if span > 0 else 0.0

    def seek(self, media_time_s: float) -> bool:
        if self.source is None:
            return False
        ok = self.source.seek(media_time_s)
        if ok:
            self._last_processed_t = -1e9
            self._next_due = None
        return ok
