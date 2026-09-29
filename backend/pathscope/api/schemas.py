"""Pydantic request/response schemas for the HTTP API."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

from pathscope.anomaly.config import AnomalySettings, anomaly_settings
from pathscope.domain.recording import RecordingSettings, recording_settings
from pathscope.domain.rules import Rule
from pathscope.domain.scene import SceneDocument
from pathscope.relationships.rules import RelationExperimentSettings, relation_settings


class ORMModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


# ----------------------------------------------------------------- projects
class ProjectIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    description: str = ""
    tags: list[str] = Field(default_factory=list)


class ProjectOut(ORMModel):
    id: int
    name: str
    description: str
    tags: list[str]
    created_at: datetime
    updated_at: datetime
    camera_count: int = 0
    experiment_count: int = 0
    site_count: int = 0


class SiteIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    description: str = ""


class SiteOut(ORMModel):
    id: int
    project_id: int
    name: str
    description: str
    created_at: datetime


# ----------------------------------------------------------------- videos / cameras
class VideoOut(ORMModel):
    id: int
    filename: str
    path: str
    size_bytes: int
    duration_s: float | None
    fps: float | None
    width: int | None
    height: int | None
    frame_count: int | None
    created_at: datetime


class CameraIn(BaseModel):
    project_id: int
    site_id: int | None = None
    name: str = Field(min_length=1, max_length=200)
    location: str = ""
    source_type: str = Field(pattern="^(file|usb|rtsp|http)$")
    source_uri: str = ""
    video_id: int | None = None
    width: int | None = None
    height: int | None = None
    requested_fps: float | None = None
    processing_fps: float | None = None
    rotation: int = Field(default=0)
    crop: dict[str, float] | None = None
    inference_size: int | None = None
    reconnect: dict[str, Any] = Field(default_factory=dict)
    enabled: bool = True
    notes: str = ""
    # Video files: when the recording started (runs date results by it)
    recorded_at: datetime | None = None


class CameraUpdate(BaseModel):
    project_id: int | None = None
    site_id: int | None = None
    name: str | None = None
    location: str | None = None
    source_type: str | None = Field(default=None, pattern="^(file|usb|rtsp|http)$")
    source_uri: str | None = None
    video_id: int | None = None
    width: int | None = None
    height: int | None = None
    requested_fps: float | None = None
    processing_fps: float | None = None
    rotation: int | None = None
    crop: dict[str, float] | None = None
    inference_size: int | None = None
    reconnect: dict[str, Any] | None = None
    enabled: bool | None = None
    notes: str | None = None
    recorded_at: datetime | None = None


class CameraOut(ORMModel):
    id: int
    project_id: int
    site_id: int | None
    name: str
    location: str
    source_type: str
    source_uri: str
    video_id: int | None
    width: int | None
    height: int | None
    requested_fps: float | None
    processing_fps: float | None
    rotation: int
    crop: dict[str, Any] | None
    inference_size: int | None
    reconnect: dict[str, Any]
    enabled: bool
    notes: str
    recorded_at: datetime | None = None
    created_at: datetime
    updated_at: datetime
    video: VideoOut | None = None
    latest_scene_id: int | None = None
    latest_scene_version: int | None = None
    active_run_id: int | None = None


class ConnectionTestIn(BaseModel):
    source_type: str
    source_uri: str = ""


# ----------------------------------------------------------------- scenes
class SceneIn(BaseModel):
    name: str = ""
    document: SceneDocument
    new_version: bool = False


class SceneOut(ORMModel):
    id: int
    camera_id: int
    version: int
    name: str
    document: dict[str, Any]
    frozen: bool
    created_from_id: int | None
    created_at: datetime


# ----------------------------------------------------------------- experiments
class InferenceSettings(BaseModel):
    preset: str = Field(default="auto", pattern="^(auto|fast|balanced|accurate|custom)$")
    provider: str = "auto"
    device: str = "auto"
    image_size: int | None = None
    confidence: float = Field(default=0.25, ge=0.01, le=0.99)
    iou: float = Field(default=0.5, ge=0.05, le=0.95)
    half: bool | None = None
    processing_fps: float | None = None
    frame_skip: int = Field(default=0, ge=0)
    realtime: bool = False


class ExperimentIn(BaseModel):
    project_id: int
    camera_id: int | None = None
    scene_config_id: int | None = None
    name: str = Field(min_length=1, max_length=200)
    description: str = ""
    notes: str = ""
    condition_notes: str = ""
    tags: list[str] = Field(default_factory=list)
    object_classes: list[str] = Field(default_factory=lambda: ["person"])
    model_id: str = ""
    tracker_id: str = "bytetrack"
    inference: InferenceSettings = Field(default_factory=InferenceSettings)
    tracker_settings: dict[str, Any] = Field(default_factory=dict)
    rules: list[Rule] = Field(default_factory=list)
    recording: RecordingSettings = Field(default_factory=RecordingSettings)
    anomaly: AnomalySettings = Field(default_factory=AnomalySettings)
    relations: RelationExperimentSettings = Field(default_factory=RelationExperimentSettings)


class ExperimentUpdate(BaseModel):
    camera_id: int | None = None
    scene_config_id: int | None = None
    name: str | None = None
    description: str | None = None
    notes: str | None = None
    condition_notes: str | None = None
    tags: list[str] | None = None
    object_classes: list[str] | None = None
    model_id: str | None = None
    tracker_id: str | None = None
    inference: InferenceSettings | None = None
    tracker_settings: dict[str, Any] | None = None
    rules: list[Rule] | None = None
    recording: RecordingSettings | None = None
    anomaly: AnomalySettings | None = None
    relations: RelationExperimentSettings | None = None
    status: str | None = None


class RunOut(ORMModel):
    id: int
    experiment_id: int
    camera_id: int | None
    scene_config_id: int | None
    status: str
    started_at: datetime | None
    ended_at: datetime | None
    error: str | None
    snapshot: dict[str, Any]
    stats: dict[str, Any]
    created_at: datetime
    live: dict[str, Any] | None = None


class ExperimentOut(ORMModel):
    id: int
    project_id: int
    camera_id: int | None
    scene_config_id: int | None
    name: str
    description: str
    notes: str
    condition_notes: str
    tags: list[str]
    object_classes: list[str]
    model_id: str
    tracker_id: str
    inference: dict[str, Any]
    tracker_settings: dict[str, Any]
    rules: list[dict[str, Any]]
    recording: RecordingSettings = Field(default_factory=RecordingSettings)
    anomaly: AnomalySettings = Field(default_factory=AnomalySettings)
    relations: RelationExperimentSettings = Field(default_factory=RelationExperimentSettings)
    status: str
    created_at: datetime
    updated_at: datetime
    run_count: int = 0
    last_run: RunOut | None = None
    camera_name: str | None = None

    @field_validator("recording", mode="before")
    @classmethod
    def _stored_recording(cls, v):
        if isinstance(v, RecordingSettings):
            return v
        return recording_settings(v if isinstance(v, dict) else None)

    @field_validator("anomaly", mode="before")
    @classmethod
    def _stored_anomaly(cls, v):
        if isinstance(v, AnomalySettings):
            return v
        return anomaly_settings(v if isinstance(v, dict) else None)

    @field_validator("relations", mode="before")
    @classmethod
    def _stored_relations(cls, v):
        if isinstance(v, RelationExperimentSettings):
            return v
        return relation_settings(v if isinstance(v, dict) else None)


class RecordingOut(BaseModel):
    id: int
    run_id: int
    experiment_id: int | None
    camera_id: int | None
    kind: str
    mime: str
    codec: str
    width: int
    height: int
    fps: float
    frames: int
    media_start_s: float
    media_end_s: float
    duration_s: float
    started_at: datetime
    ended_at: datetime
    size_bytes: int
    overlay: bool
    triggers: list[dict[str, Any]]
    trigger_count: int
    playable: bool
    url: str


class StartRunIn(BaseModel):
    scene_config_id: int | None = None
    realtime: bool | None = None
    loop: bool = False


# ----------------------------------------------------------------- events
class EventOut(ORMModel):
    id: int
    run_id: int
    experiment_id: int
    camera_id: int | None
    track_id: int
    object_class: str
    event_type: str
    rule_id: str | None
    rule_name: str | None
    route: str | None
    object_id: str | None
    object_name: str | None
    direction: str | None
    frame_index: int
    media_time_s: float
    wall_time: datetime
    entered_at_s: float | None
    completed_at_s: float | None
    duration_s: float | None
    avg_speed: float | None
    speed_unit: str | None
    confidence: float | None
    context: dict[str, Any]


class Page(BaseModel):
    items: list[Any]
    total: int
    page: int
    page_size: int


class TrackSummaryOut(ORMModel):
    id: int
    run_id: int
    track_id: int
    object_class: str
    first_seen_s: float
    last_seen_s: float
    first_seen_at: datetime | None
    last_seen_at: datetime | None
    n_frames: int
    path_length: float | None
    path_unit: str
    avg_speed: float | None
    speed_unit: str | None
    mean_confidence: float | None
    final_state: str
    route_result: str | None
    lost_count: int


# ----------------------------------------------------------------- evaluation
class EvaluationIn(BaseModel):
    run_id: int
    event_id: int | None = None
    track_id: int | None = None
    verdict: str = Field(pattern="^(correct|incorrect|missed|wrong_route|wrong_class|tracking_error)$")
    expected: str | None = None
    note: str = ""


class EvaluationOut(ORMModel):
    id: int
    run_id: int
    event_id: int | None
    track_id: int | None
    verdict: str
    expected: str | None
    note: str
    created_at: datetime


class GroundTruthIn(BaseModel):
    run_id: int
    object_id: str
    label: str = ""
    count: int = Field(ge=0)
    note: str = ""


class GroundTruthOut(ORMModel):
    id: int
    run_id: int
    object_id: str
    label: str
    count: int
    note: str
    created_at: datetime


# ----------------------------------------------------------------- models / hardware
class BenchmarkIn(BaseModel):
    device: str = "auto"
    image_size: int | None = None
    video_id: int | None = None
    tracker_id: str = "bytetrack"
    tracker_settings: dict[str, Any] = Field(default_factory=dict)


class LoadEstimateIn(BaseModel):
    streams: list[dict[str, Any]]


class SettingsIn(BaseModel):
    values: dict[str, Any]
