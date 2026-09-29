"""Messages exchanged between the API process and camera worker processes.

Everything here must be picklable (multiprocessing with the spawn start
method on every platform).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class WorkerSpec:
    """Everything a worker needs to run one camera for one run."""

    run_id: int
    camera_id: int
    experiment_id: int
    source_type: str
    source_uri: str
    scene: dict  # SceneDocument as dict
    rules: list[dict]
    tracked_classes: list[str]
    model_id: str
    weights_path: str
    provider: str
    family: str
    device: str
    image_size: int
    confidence: float
    iou: float
    half: bool
    tracker_id: str = "bytetrack"
    tracker_settings: dict = field(default_factory=dict)
    rotation: int = 0
    crop: dict | None = None
    processing_fps: float | None = None
    frame_skip: int = 0
    source_width: int | None = None
    source_height: int | None = None
    source_fps: float | None = None
    reconnect: dict = field(default_factory=dict)
    rtsp_transport: str = "tcp"
    realtime: bool = False
    loop: bool = False
    # Video files: epoch seconds the recording started (wall time = start + position)
    recorded_at: float | None = None
    store_trajectories: bool = True
    webhooks_enabled: bool = True
    preview_fps: float = 12.0
    preview_max_width: int = 1280
    preview_jpeg_quality: int = 75
    log_level: str = "info"
    log_format: str = "console"
    models_dir: str = ""
    # Video recording of the run (pathscope.domain.recording as dict); None = off.
    # Files go to recordings_dir.
    recording: dict | None = None
    recordings_dir: str = ""
    # Licensed recognition modules: run payload (model paths, settings, the
    # enrolled identities' templates, the vehicle registry). None in the core.
    # Never exposed through the API or written to logs.
    recognition: dict | None = None
    # Anomaly Assistant: {"settings": AnomalySettings as dict, "zones": {id: polygon},
    # "ignore": [polygon]} (normalized points); None = off. Evidence goes to anomaly_dir.
    anomaly: dict | None = None
    anomaly_dir: str = ""
    # Relationship engine: {"analysis_id", "settings", "rules", "plate_salt", "modules",
    # "scene_version"} (pathscope.relationships.service.prepare_run); None = off
    relations: dict | None = None


@dataclass
class Command:
    kind: str  # pause | resume | stop | seek | set_preview | anomaly_rebaseline
    payload: dict = field(default_factory=dict)


@dataclass
class StatusMessage:
    state: str  # starting | running | paused | finished | failed | stopped
    frame_index: int = 0
    media_time_s: float = 0.0
    processed_frames: int = 0
    read_frames: int = 0
    pipeline_fps: float = 0.0
    source_fps: float = 0.0
    timings_ms: dict = field(default_factory=dict)
    counters: list[dict] = field(default_factory=list)
    tracker: dict = field(default_factory=dict)
    rule_stats: dict = field(default_factory=dict)
    active_tracks: int = 0
    routes_in_progress: int = 0
    zone_occupancy: dict = field(default_factory=dict)
    detector: dict = field(default_factory=dict)
    source: dict = field(default_factory=dict)
    error: str | None = None
    progress: float | None = None  # 0..1 for file sources
    wall_time: float = 0.0
    reconnects: int = 0
    recognition: dict = field(default_factory=dict)  # per-module counters (no identities)
    recording: dict = field(default_factory=dict)  # mode, active, files, bytes, dropped, error
    anomaly: dict = field(default_factory=dict)  # state (learning | watching), zones, counters
    relations: dict = field(default_factory=dict)  # relationship engine counters


@dataclass
class PreviewMessage:
    frame_index: int
    media_time_s: float
    width: int  # preview image size
    height: int
    source_width: int  # geometry frame size (for scaling overlays)
    source_height: int
    jpeg: bytes
    tracks: list[dict]
    interactions: list[dict]
    events: list[dict]
    processed: bool


@dataclass
class OutMessage:
    kind: str  # status | snapshot | events | track_ended | recognition_events | recognition_diag | recording | anomalies | relations
    payload: Any
