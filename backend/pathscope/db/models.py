"""SQLAlchemy ORM models.

Configuration (projects, cameras, scenes, experiments), execution (runs),
research records (events, track summaries, trajectories), validation
(evaluations) and platform state (installed models, benchmarks, settings) are
kept in separate tables. Raw frames are never stored here; video recorded from
live cameras (off unless an experiment turns it on) lives in files listed in
``recordings``.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from pathscope.db.base import Base, UtcDateTime, utcnow


class Project(Base):
    __tablename__ = "projects"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(Text, default="")
    tags: Mapped[list[str]] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime] = mapped_column(UtcDateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(UtcDateTime, default=utcnow, onupdate=utcnow)

    sites: Mapped[list[Site]] = relationship(back_populates="project", cascade="all, delete-orphan")
    cameras: Mapped[list[Camera]] = relationship(
        back_populates="project", cascade="all, delete-orphan"
    )
    experiments: Mapped[list[Experiment]] = relationship(
        back_populates="project", cascade="all, delete-orphan"
    )


class Site(Base):
    __tablename__ = "sites"

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"))
    name: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(UtcDateTime, default=utcnow)

    project: Mapped[Project] = relationship(back_populates="sites")


class Video(Base):
    """Metadata for an uploaded or registered local video file."""

    __tablename__ = "videos"

    id: Mapped[int] = mapped_column(primary_key=True)
    filename: Mapped[str] = mapped_column(String(400))
    path: Mapped[str] = mapped_column(String(1000))
    size_bytes: Mapped[int] = mapped_column(Integer, default=0)
    duration_s: Mapped[float | None] = mapped_column(Float, nullable=True)
    fps: Mapped[float | None] = mapped_column(Float, nullable=True)
    width: Mapped[int | None] = mapped_column(Integer, nullable=True)
    height: Mapped[int | None] = mapped_column(Integer, nullable=True)
    frame_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(UtcDateTime, default=utcnow)


class Camera(Base):
    __tablename__ = "cameras"

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"))
    site_id: Mapped[int | None] = mapped_column(
        ForeignKey("sites.id", ondelete="SET NULL"), nullable=True
    )
    name: Mapped[str] = mapped_column(String(200))
    location: Mapped[str] = mapped_column(String(400), default="")
    # file | usb | rtsp | http
    source_type: Mapped[str] = mapped_column(String(20))
    source_uri: Mapped[str] = mapped_column(String(1000), default="")
    video_id: Mapped[int | None] = mapped_column(
        ForeignKey("videos.id", ondelete="SET NULL"), nullable=True
    )
    width: Mapped[int | None] = mapped_column(Integer, nullable=True)
    height: Mapped[int | None] = mapped_column(Integer, nullable=True)
    requested_fps: Mapped[float | None] = mapped_column(Float, nullable=True)
    processing_fps: Mapped[float | None] = mapped_column(Float, nullable=True)
    rotation: Mapped[int] = mapped_column(Integer, default=0)
    crop: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    inference_size: Mapped[int | None] = mapped_column(Integer, nullable=True)
    reconnect: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    notes: Mapped[str] = mapped_column(Text, default="")
    # Video file cameras: when the recording started. A run of the file then
    # dates what it finds by the recording time (start + position in the video)
    # instead of the time it was analysed, so the files of several cameras line
    # up for cross-camera correlation.
    recorded_at: Mapped[datetime | None] = mapped_column(UtcDateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(UtcDateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(UtcDateTime, default=utcnow, onupdate=utcnow)

    project: Mapped[Project] = relationship(back_populates="cameras")
    video: Mapped[Video | None] = relationship()
    scenes: Mapped[list[SceneConfig]] = relationship(
        back_populates="camera", cascade="all, delete-orphan", order_by="SceneConfig.version"
    )


class SceneConfig(Base):
    """A versioned scene document (normalized geometry, routes, calibration)."""

    __tablename__ = "scene_configs"
    __table_args__ = (UniqueConstraint("camera_id", "version", name="uq_scene_camera_version"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    camera_id: Mapped[int] = mapped_column(ForeignKey("cameras.id", ondelete="CASCADE"))
    version: Mapped[int] = mapped_column(Integer, default=1)
    name: Mapped[str] = mapped_column(String(200), default="")
    document: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    frozen: Mapped[bool] = mapped_column(Boolean, default=False)
    created_from_id: Mapped[int | None] = mapped_column(
        ForeignKey("scene_configs.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(UtcDateTime, default=utcnow)

    camera: Mapped[Camera] = relationship(back_populates="scenes")


class Experiment(Base):
    __tablename__ = "experiments"

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"))
    camera_id: Mapped[int | None] = mapped_column(
        ForeignKey("cameras.id", ondelete="SET NULL"), nullable=True
    )
    scene_config_id: Mapped[int | None] = mapped_column(
        ForeignKey("scene_configs.id", ondelete="SET NULL"), nullable=True
    )
    name: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(Text, default="")
    notes: Mapped[str] = mapped_column(Text, default="")
    condition_notes: Mapped[str] = mapped_column(Text, default="")
    tags: Mapped[list[str]] = mapped_column(JSON, default=list)
    object_classes: Mapped[list[str]] = mapped_column(JSON, default=list)
    model_id: Mapped[str] = mapped_column(String(100), default="")
    tracker_id: Mapped[str] = mapped_column(String(50), default="bytetrack")
    inference: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    tracker_settings: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    rules: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    # Video recording of live runs (pathscope.domain.recording); empty = off
    recording: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True, default=dict)
    # Anomaly Assistant (pathscope.anomaly.config); empty = off
    anomaly: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True, default=dict)
    # Relationship & Event Correlation Engine (pathscope.relationships.rules); empty = off
    relations: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True, default=dict)
    status: Mapped[str] = mapped_column(String(20), default="draft")
    created_at: Mapped[datetime] = mapped_column(UtcDateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(UtcDateTime, default=utcnow, onupdate=utcnow)

    project: Mapped[Project] = relationship(back_populates="experiments")
    camera: Mapped[Camera | None] = relationship()
    scene_config: Mapped[SceneConfig | None] = relationship()
    runs: Mapped[list[Run]] = relationship(
        back_populates="experiment", cascade="all, delete-orphan", order_by="Run.id"
    )


class Run(Base):
    """One execution session of an experiment."""

    __tablename__ = "runs"

    id: Mapped[int] = mapped_column(primary_key=True)
    experiment_id: Mapped[int] = mapped_column(ForeignKey("experiments.id", ondelete="CASCADE"))
    camera_id: Mapped[int | None] = mapped_column(
        ForeignKey("cameras.id", ondelete="SET NULL"), nullable=True
    )
    scene_config_id: Mapped[int | None] = mapped_column(
        ForeignKey("scene_configs.id", ondelete="SET NULL"), nullable=True
    )
    # queued | starting | running | paused | stopping | completed | stopped | failed
    status: Mapped[str] = mapped_column(String(20), default="queued")
    started_at: Mapped[datetime | None] = mapped_column(UtcDateTime, nullable=True)
    ended_at: Mapped[datetime | None] = mapped_column(UtcDateTime, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    snapshot: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    stats: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(UtcDateTime, default=utcnow)

    experiment: Mapped[Experiment] = relationship(back_populates="runs")
    events: Mapped[list[Event]] = relationship(back_populates="run", cascade="all, delete-orphan")


class Event(Base):
    __tablename__ = "events"
    __table_args__ = (
        Index("ix_events_run_time", "run_id", "media_time_s"),
        Index("ix_events_experiment", "experiment_id"),
        Index("ix_events_type_route", "event_type", "route"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("runs.id", ondelete="CASCADE"))
    experiment_id: Mapped[int] = mapped_column(ForeignKey("experiments.id", ondelete="CASCADE"))
    camera_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    track_id: Mapped[int] = mapped_column(Integer)
    object_class: Mapped[str] = mapped_column(String(50))
    # crossing | zone_entry | zone_exit | dwell | route | sequence | custom
    event_type: Mapped[str] = mapped_column(String(40))
    rule_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    rule_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    route: Mapped[str | None] = mapped_column(String(200), nullable=True)
    object_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    object_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    direction: Mapped[str | None] = mapped_column(String(20), nullable=True)
    frame_index: Mapped[int] = mapped_column(Integer, default=0)
    media_time_s: Mapped[float] = mapped_column(Float, default=0.0)
    wall_time: Mapped[datetime] = mapped_column(UtcDateTime, default=utcnow)
    entered_at_s: Mapped[float | None] = mapped_column(Float, nullable=True)
    completed_at_s: Mapped[float | None] = mapped_column(Float, nullable=True)
    duration_s: Mapped[float | None] = mapped_column(Float, nullable=True)
    avg_speed: Mapped[float | None] = mapped_column(Float, nullable=True)
    speed_unit: Mapped[str | None] = mapped_column(String(20), nullable=True)
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    context: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)

    run: Mapped[Run] = relationship(back_populates="events")


class TrackSummary(Base):
    __tablename__ = "track_summaries"
    __table_args__ = (Index("ix_tracks_run", "run_id", "track_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("runs.id", ondelete="CASCADE"))
    track_id: Mapped[int] = mapped_column(Integer)
    object_class: Mapped[str] = mapped_column(String(50))
    first_seen_s: Mapped[float] = mapped_column(Float)
    last_seen_s: Mapped[float] = mapped_column(Float)
    first_seen_at: Mapped[datetime | None] = mapped_column(UtcDateTime, nullable=True)
    last_seen_at: Mapped[datetime | None] = mapped_column(UtcDateTime, nullable=True)
    n_frames: Mapped[int] = mapped_column(Integer, default=0)
    path_length: Mapped[float | None] = mapped_column(Float, nullable=True)
    path_unit: Mapped[str] = mapped_column(String(20), default="frame")
    avg_speed: Mapped[float | None] = mapped_column(Float, nullable=True)
    speed_unit: Mapped[str | None] = mapped_column(String(20), nullable=True)
    mean_confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    final_state: Mapped[str] = mapped_column(String(20), default="removed")
    route_result: Mapped[str | None] = mapped_column(String(200), nullable=True)
    lost_count: Mapped[int] = mapped_column(Integer, default=0)


class Trajectory(Base):
    """Sampled normalized ground-plane positions of one track (optional)."""

    __tablename__ = "trajectories"
    __table_args__ = (Index("ix_traj_run", "run_id", "track_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("runs.id", ondelete="CASCADE"))
    track_id: Mapped[int] = mapped_column(Integer)
    object_class: Mapped[str] = mapped_column(String(50))
    # list of [media_time_s, x, y] with x, y normalized to the source frame
    points: Mapped[list[list[float]]] = mapped_column(JSON, default=list)
    n_points: Mapped[int] = mapped_column(Integer, default=0)


class Recording(Base):
    """A video file recorded from a live camera during a run.

    ``continuous`` files cover the whole run in segments, ``event`` files are
    clips around events. Media times are the run's, so an event at media time t
    is at t - media_start_s in the file."""

    __tablename__ = "recordings"
    __table_args__ = (Index("ix_recordings_run", "run_id", "media_start_s"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("runs.id", ondelete="CASCADE"))
    experiment_id: Mapped[int | None] = mapped_column(ForeignKey("experiments.id", ondelete="CASCADE"), nullable=True)
    camera_id: Mapped[int | None] = mapped_column(ForeignKey("cameras.id", ondelete="SET NULL"), nullable=True)
    kind: Mapped[str] = mapped_column(String(20))  # continuous | event
    path: Mapped[str] = mapped_column(String(1000))
    mime: Mapped[str] = mapped_column(String(50))
    codec: Mapped[str] = mapped_column(String(10), default="")
    width: Mapped[int] = mapped_column(Integer, default=0)
    height: Mapped[int] = mapped_column(Integer, default=0)
    fps: Mapped[float] = mapped_column(Float, default=0.0)
    frames: Mapped[int] = mapped_column(Integer, default=0)
    media_start_s: Mapped[float] = mapped_column(Float, default=0.0)
    media_end_s: Mapped[float] = mapped_column(Float, default=0.0)
    started_at: Mapped[datetime] = mapped_column(UtcDateTime)
    ended_at: Mapped[datetime] = mapped_column(UtcDateTime)
    size_bytes: Mapped[int] = mapped_column(Integer, default=0)
    overlay: Mapped[bool] = mapped_column(Boolean, default=True)
    # events that started or extended a clip: [{type, label, track_id, media_time_s}]
    triggers: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    trigger_count: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(UtcDateTime, default=utcnow)


class Evaluation(Base):
    __tablename__ = "evaluations"

    id: Mapped[int] = mapped_column(primary_key=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("runs.id", ondelete="CASCADE"))
    event_id: Mapped[int | None] = mapped_column(
        ForeignKey("events.id", ondelete="CASCADE"), nullable=True
    )
    track_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # correct | incorrect | missed | wrong_route | wrong_class | tracking_error
    verdict: Mapped[str] = mapped_column(String(30))
    expected: Mapped[str | None] = mapped_column(String(200), nullable=True)
    note: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(UtcDateTime, default=utcnow)


class GroundTruthCount(Base):
    """A manual count entered by a researcher for a scene object over a run."""

    __tablename__ = "ground_truth_counts"

    id: Mapped[int] = mapped_column(primary_key=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("runs.id", ondelete="CASCADE"))
    object_id: Mapped[str] = mapped_column(String(100))
    label: Mapped[str] = mapped_column(String(200), default="")
    count: Mapped[int] = mapped_column(Integer)
    note: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(UtcDateTime, default=utcnow)


class InstalledModel(Base):
    __tablename__ = "installed_models"

    id: Mapped[int] = mapped_column(primary_key=True)
    model_id: Mapped[str] = mapped_column(String(100), unique=True)
    provider: Mapped[str] = mapped_column(String(50))
    path: Mapped[str] = mapped_column(String(1000))
    size_bytes: Mapped[int] = mapped_column(Integer, default=0)
    source_url: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    installed_at: Mapped[datetime] = mapped_column(UtcDateTime, default=utcnow)


class Benchmark(Base):
    __tablename__ = "benchmarks"

    id: Mapped[int] = mapped_column(primary_key=True)
    model_id: Mapped[str] = mapped_column(String(100))
    provider: Mapped[str] = mapped_column(String(50))
    device: Mapped[str] = mapped_column(String(50))
    results: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(UtcDateTime, default=utcnow)


class Setting(Base):
    __tablename__ = "settings"

    key: Mapped[str] = mapped_column(String(100), primary_key=True)
    value: Mapped[Any] = mapped_column(JSON, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(UtcDateTime, default=utcnow, onupdate=utcnow)


# Tables with their own modules, registered here so migrations and the
# metadata see them: Anomaly Assistant events (pathscope/anomaly/models.py) and
# the licensed recognition modules (pathscope/recognition/registry/models.py).
from pathscope.anomaly import models as _anomaly_models  # noqa: E402,F401
from pathscope.location import models as _location_models  # noqa: E402,F401
from pathscope.recognition.registry import models as _recognition_models  # noqa: E402,F401
from pathscope.relationships import models as _relationship_models  # noqa: E402,F401
