"""Stored anomaly events (their evidence pictures live in files under <data>/anomalies)."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import JSON, Boolean, Float, ForeignKey, Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from pathscope.db.base import Base, UtcDateTime, utcnow


class AnomalyEvent(Base):
    """One confirmed anomaly of a run: what the detector saw, the evidence and the model's reading.

    ``status``: ``raised`` (alert published), ``awaiting_model`` (a
    model-confirmed zone waits for the verdict), ``dismissed`` (the model
    judged it irrelevant; kept for review, never alerted), ``held`` (the model
    could not be asked and the policy holds such events)."""

    __tablename__ = "anomaly_events"
    __table_args__ = (
        Index("ix_anomaly_run", "run_id", "started_media_s"),
        Index("ix_anomaly_camera_time", "camera_id", "confirmed_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    uid: Mapped[str] = mapped_column(String(32), unique=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("runs.id", ondelete="CASCADE"))
    experiment_id: Mapped[int | None] = mapped_column(ForeignKey("experiments.id", ondelete="CASCADE"), nullable=True)
    camera_id: Mapped[int | None] = mapped_column(ForeignKey("cameras.id", ondelete="SET NULL"), nullable=True)
    zone_id: Mapped[str] = mapped_column(String(100))
    zone_name: Mapped[str] = mapped_column(String(200), default="")
    expected_state: Mapped[str] = mapped_column(Text, default="")
    kind: Mapped[str] = mapped_column(String(20))
    status: Mapped[str] = mapped_column(String(20), default="raised")
    confidence: Mapped[float] = mapped_column(Float, default=0.0)
    area_pct: Mapped[float] = mapped_column(Float, default=0.0)
    bbox: Mapped[list[float]] = mapped_column(JSON, default=list)
    started_media_s: Mapped[float] = mapped_column(Float, default=0.0)
    confirmed_media_s: Mapped[float] = mapped_column(Float, default=0.0)
    ended_media_s: Mapped[float | None] = mapped_column(Float, nullable=True)
    duration_s: Mapped[float | None] = mapped_column(Float, nullable=True)
    started_at: Mapped[datetime] = mapped_column(UtcDateTime, default=utcnow)
    confirmed_at: Mapped[datetime] = mapped_column(UtcDateTime, default=utcnow)
    ended_at: Mapped[datetime | None] = mapped_column(UtcDateTime, nullable=True)
    end_reason: Mapped[str | None] = mapped_column(String(30), nullable=True)
    summary: Mapped[str] = mapped_column(Text, default="")
    # [{track_id, object_class, confidence}] and aliased subjects (ids and status only, never names)
    objects: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    subjects: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    metrics: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    # evidence name -> path relative to <data>/anomalies/run-<run_id>
    evidence: Mapped[dict[str, str]] = mapped_column(JSON, default=dict)
    # Zone settings when it happened: validation, interpret_at, webhooks, record_clip
    zone_settings: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    published: Mapped[bool] = mapped_column(Boolean, default=False)
    # Vision language model
    llm_status: Mapped[str] = mapped_column(String(20), default="off")  # off | queued | running | done | failed | skipped
    llm_verdict: Mapped[str | None] = mapped_column(String(20), nullable=True)
    llm_category: Mapped[str | None] = mapped_column(String(30), nullable=True)
    llm_description: Mapped[str | None] = mapped_column(Text, nullable=True)
    llm_confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    llm_evidence: Mapped[str | None] = mapped_column(Text, nullable=True)
    llm_provider: Mapped[str | None] = mapped_column(String(30), nullable=True)
    llm_model: Mapped[str | None] = mapped_column(String(120), nullable=True)
    llm_latency_ms: Mapped[float | None] = mapped_column(Float, nullable=True)
    llm_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    llm_at: Mapped[datetime | None] = mapped_column(UtcDateTime, nullable=True)
    # Operator review
    feedback: Mapped[str | None] = mapped_column(String(20), nullable=True)  # true_positive | false_alarm
    note: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(UtcDateTime, default=utcnow)
