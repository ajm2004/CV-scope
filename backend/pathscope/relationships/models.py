"""Tables of the relationship graph (indexed relational storage).

Nodes are ``relation_entities``; edges are ``relation_relationships``; the
evidence is ``relation_observations`` linked through ``relation_support``
(never copied); higher-level results are ``relation_correlated``. Each run
analysis (live, or a later re-analysis with other rule versions) is a
``relation_analyses`` row: its results stay when a newer analysis becomes
the current one, so past interpretations are never silently replaced.
Rules are ``relation_rules`` rows, immutable per (key, version).

The graph API (``graph.py``) reads these tables through a backend interface,
so a graph database can be added later without changing the API.
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
from sqlalchemy.orm import Mapped, mapped_column

from pathscope.db.base import Base, UtcDateTime, utcnow


class RelationAnalysis(Base):
    __tablename__ = "relation_analyses"
    __table_args__ = (Index("ix_relation_analyses_run", "run_id", "current"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("runs.id", ondelete="CASCADE"))
    experiment_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    camera_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    source: Mapped[str] = mapped_column(String(20), default="live")  # live | replay
    status: Mapped[str] = mapped_column(String(20), default="running")  # running | done | failed
    current: Mapped[bool] = mapped_column(Boolean, default=True)
    # [{key, version, name, kind}] as used; engine settings; calibration used
    rules: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    settings: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    calibration: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    stats: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by: Mapped[str] = mapped_column(String(200), default="")
    started_at: Mapped[datetime] = mapped_column(UtcDateTime, default=utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(UtcDateTime, nullable=True)


class RelationEntity(Base):
    __tablename__ = "relation_entities"
    __table_args__ = (
        Index("ix_relation_entities_type", "entity_type"),
        Index("ix_relation_entities_run", "run_id"),
        Index("ix_relation_entities_seen", "last_seen"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    key: Mapped[str] = mapped_column(String(200), unique=True)
    entity_type: Mapped[str] = mapped_column(String(40))
    ref: Mapped[str] = mapped_column(String(160))
    source: Mapped[str] = mapped_column(String(40), default="")
    # A label that is safe for every viewer ("Person track #182", "Gate North").
    label: Mapped[str] = mapped_column(String(300), default="")
    # Sensitive text (a plate) shown only to viewers with recognition access
    secret_label: Mapped[str | None] = mapped_column(String(100), nullable=True)
    run_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    camera_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    experiment_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    first_seen: Mapped[datetime | None] = mapped_column(UtcDateTime, nullable=True)
    last_seen: Mapped[datetime | None] = mapped_column(UtcDateTime, nullable=True)
    first_media_s: Mapped[float | None] = mapped_column(Float, nullable=True)
    last_media_s: Mapped[float | None] = mapped_column(Float, nullable=True)
    meta: Mapped[dict[str, Any]] = mapped_column("metadata", JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(UtcDateTime, default=utcnow)


class RelationObservation(Base):
    __tablename__ = "relation_observations"
    __table_args__ = (
        Index("ix_relation_obs_entity", "entity_id", "at"),
        Index("ix_relation_obs_analysis", "analysis_id", "media_time_s"),
        Index("ix_relation_obs_run", "run_id", "media_time_s"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    uid: Mapped[str] = mapped_column(String(32), unique=True)
    # None for observations published by external sensors outside an analysis
    analysis_id: Mapped[int | None] = mapped_column(ForeignKey("relation_analyses.id", ondelete="CASCADE"), nullable=True)
    run_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    camera_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    entity_id: Mapped[int] = mapped_column(ForeignKey("relation_entities.id", ondelete="CASCADE"))
    object_entity_id: Mapped[int | None] = mapped_column(ForeignKey("relation_entities.id", ondelete="CASCADE"), nullable=True)
    observation_type: Mapped[str] = mapped_column(String(40))
    media_time_s: Mapped[float | None] = mapped_column(Float, nullable=True)
    at: Mapped[datetime] = mapped_column(UtcDateTime, default=utcnow)
    source: Mapped[str] = mapped_column(String(40), default="rgb")
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    value: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)


class RelationRelationship(Base):
    __tablename__ = "relation_relationships"
    __table_args__ = (
        Index("ix_relation_rel_subject", "subject_id", "relation_type"),
        Index("ix_relation_rel_object", "object_id", "relation_type"),
        Index("ix_relation_rel_analysis", "analysis_id"),
        Index("ix_relation_rel_run", "run_id", "start_media_s"),
        Index("ix_relation_rel_start", "start_at"),
        Index("ix_relation_rel_type", "relation_type", "start_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    uid: Mapped[str] = mapped_column(String(32), unique=True)
    analysis_id: Mapped[int | None] = mapped_column(ForeignKey("relation_analyses.id", ondelete="CASCADE"), nullable=True)
    run_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    experiment_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    camera_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    subject_id: Mapped[int] = mapped_column(ForeignKey("relation_entities.id", ondelete="CASCADE"))
    relation_type: Mapped[str] = mapped_column(String(60))
    object_id: Mapped[int] = mapped_column(ForeignKey("relation_entities.id", ondelete="CASCADE"))
    start_media_s: Mapped[float | None] = mapped_column(Float, nullable=True)
    end_media_s: Mapped[float | None] = mapped_column(Float, nullable=True)
    start_at: Mapped[datetime] = mapped_column(UtcDateTime, default=utcnow)
    end_at: Mapped[datetime | None] = mapped_column(UtcDateTime, nullable=True)
    status: Mapped[str] = mapped_column(String(10), default="open")  # open | closed
    confidence: Mapped[float] = mapped_column(Float, default=0.0)
    state: Mapped[str] = mapped_column(String(20), default="possible")
    components: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    rule_key: Mapped[str] = mapped_column(String(60), default="")
    rule_version: Mapped[int] = mapped_column(Integer, default=1)
    rule_name: Mapped[str] = mapped_column(String(200), default="")
    reason: Mapped[str] = mapped_column(Text, default="")
    zone_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    sources: Mapped[list[str]] = mapped_column(JSON, default=list)
    calibration: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    metrics: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(UtcDateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(UtcDateTime, default=utcnow, onupdate=utcnow)


class RelationCorrelated(Base):
    __tablename__ = "relation_correlated"
    __table_args__ = (
        Index("ix_relation_cor_run", "run_id", "start_media_s"),
        Index("ix_relation_cor_start", "start_at"),
        Index("ix_relation_cor_analysis", "analysis_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    uid: Mapped[str] = mapped_column(String(32), unique=True)
    analysis_id: Mapped[int | None] = mapped_column(ForeignKey("relation_analyses.id", ondelete="CASCADE"), nullable=True)
    run_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    experiment_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    camera_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    kind: Mapped[str] = mapped_column(String(20), default="correlated")  # correlated | deviation
    event_type: Mapped[str] = mapped_column(String(200), default="")
    label: Mapped[str] = mapped_column(String(300), default="")
    start_media_s: Mapped[float | None] = mapped_column(Float, nullable=True)
    end_media_s: Mapped[float | None] = mapped_column(Float, nullable=True)
    start_at: Mapped[datetime] = mapped_column(UtcDateTime, default=utcnow)
    end_at: Mapped[datetime | None] = mapped_column(UtcDateTime, nullable=True)
    confidence: Mapped[float] = mapped_column(Float, default=0.0)
    state: Mapped[str] = mapped_column(String(20), default="possible")
    description: Mapped[str] = mapped_column(Text, default="")
    rule_key: Mapped[str] = mapped_column(String(60), default="")
    rule_version: Mapped[int] = mapped_column(Integer, default=1)
    rule_name: Mapped[str] = mapped_column(String(200), default="")
    # role -> entity id
    roles: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    temporal: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    metrics: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    published: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(UtcDateTime, default=utcnow)


class RelationSupport(Base):
    """Links a relationship or a correlated event to the evidence it rests on."""

    __tablename__ = "relation_support"
    __table_args__ = (
        Index("ix_relation_support_rel", "relationship_id"),
        Index("ix_relation_support_cor", "correlated_id"),
        Index("ix_relation_support_obs", "observation_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    relationship_id: Mapped[int | None] = mapped_column(ForeignKey("relation_relationships.id", ondelete="CASCADE"), nullable=True)
    correlated_id: Mapped[int | None] = mapped_column(ForeignKey("relation_correlated.id", ondelete="CASCADE"), nullable=True)
    observation_id: Mapped[int | None] = mapped_column(ForeignKey("relation_observations.id", ondelete="CASCADE"), nullable=True)
    supporting_relationship_id: Mapped[int | None] = mapped_column(ForeignKey("relation_relationships.id", ondelete="CASCADE"), nullable=True)
    role: Mapped[str] = mapped_column(String(40), default="")


class RelationRule(Base):
    """One immutable version of a relationship rule."""

    __tablename__ = "relation_rules"
    __table_args__ = (UniqueConstraint("key", "version", name="uq_relation_rule_version"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    key: Mapped[str] = mapped_column(String(60))
    version: Mapped[int] = mapped_column(Integer, default=1)
    name: Mapped[str] = mapped_column(String(200), default="")
    kind: Mapped[str] = mapped_column(String(20), default="pair")
    definition: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    note: Mapped[str] = mapped_column(Text, default="")
    created_by: Mapped[str] = mapped_column(String(200), default="")
    archived: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(UtcDateTime, default=utcnow)


class RelationAudit(Base):
    __tablename__ = "relation_audit"
    __table_args__ = (Index("ix_relation_audit_at", "at"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    at: Mapped[datetime] = mapped_column(UtcDateTime, default=utcnow)
    actor: Mapped[str] = mapped_column(String(200), default="")
    actor_role: Mapped[str] = mapped_column(String(20), default="")
    action: Mapped[str] = mapped_column(String(60))
    target_type: Mapped[str | None] = mapped_column(String(40), nullable=True)
    target_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    detail: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    client: Mapped[str | None] = mapped_column(String(100), nullable=True)
