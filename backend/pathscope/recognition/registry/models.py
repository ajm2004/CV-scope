"""ORM models of the recognition modules.

Kept in their own tables, apart from the ordinary research data:

* ``recognition_people`` / ``recognition_face_templates`` /
  ``recognition_enrollment_images``: enrolled identities; the biometric
  templates are sealed (encrypted) with a key kept outside the database and
  the enrollment images are encrypted files on disk;
* ``recognition_vehicles``: the vehicle registry;
* ``recognition_events``: every recognition decision with its confidence,
  quality, model version, camera, track and frame;
* ``recognition_audit``: sensitive operations;
* ``recognition_access_tokens``: role-based access to the recognition API.

No attribute such as ethnicity, emotion, health, religion, age or gender is
stored or inferred anywhere.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any
from uuid import uuid4

from sqlalchemy import (
    JSON,
    Boolean,
    Date,
    Float,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from pathscope.db.base import Base, UtcDateTime, utcnow


def new_uuid() -> str:
    return uuid4().hex


class RecognitionPerson(Base):
    __tablename__ = "recognition_people"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_uuid)
    display_name: Mapped[str] = mapped_column(String(200))
    reference_id: Mapped[str | None] = mapped_column(String(200), nullable=True)
    notes: Mapped[str] = mapped_column(Text, default="")
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    valid_from: Mapped[date | None] = mapped_column(Date, nullable=True)
    valid_until: Mapped[date | None] = mapped_column(Date, nullable=True)
    # draft | enrolled | insufficient
    enrollment_status: Mapped[str] = mapped_column(String(20), default="draft")
    enrollment_quality: Mapped[float | None] = mapped_column(Float, nullable=True)
    enrollment_summary: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    model_version: Mapped[str] = mapped_column(String(100), default="")
    enrolled_at: Mapped[datetime | None] = mapped_column(UtcDateTime, nullable=True)
    created_by: Mapped[str] = mapped_column(String(200), default="")
    created_at: Mapped[datetime] = mapped_column(UtcDateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(UtcDateTime, default=utcnow, onupdate=utcnow)

    templates: Mapped[list[RecognitionFaceTemplate]] = relationship(back_populates="person", cascade="all, delete-orphan")
    images: Mapped[list[RecognitionEnrollmentImage]] = relationship(back_populates="person", cascade="all, delete-orphan")


class RecognitionEnrollmentImage(Base):
    __tablename__ = "recognition_enrollment_images"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_uuid)
    person_id: Mapped[str] = mapped_column(ForeignKey("recognition_people.id", ondelete="CASCADE"))
    view: Mapped[str] = mapped_column(String(20))
    # Appearance the picture was taken in ("" = the first enrollment, else a
    # label such as "Glasses" or "Hard hat"). Each look holds its own views.
    variant: Mapped[str] = mapped_column(String(40), default="", server_default="")
    # False for the rear / appearance reference: no face, no biometric input
    biometric: Mapped[bool] = mapped_column(Boolean, default=True)
    path: Mapped[str] = mapped_column(String(1000))
    width: Mapped[int] = mapped_column(Integer, default=0)
    height: Mapped[int] = mapped_column(Integer, default=0)
    quality: Mapped[float | None] = mapped_column(Float, nullable=True)
    quality_detail: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(UtcDateTime, default=utcnow)

    person: Mapped[RecognitionPerson] = relationship(back_populates="images")


class RecognitionFaceTemplate(Base):
    """One sealed embedding. Never returned by the API."""

    __tablename__ = "recognition_face_templates"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_uuid)
    person_id: Mapped[str] = mapped_column(ForeignKey("recognition_people.id", ondelete="CASCADE"))
    image_id: Mapped[str | None] = mapped_column(ForeignKey("recognition_enrollment_images.id", ondelete="SET NULL"), nullable=True)
    view: Mapped[str] = mapped_column(String(20))
    variant: Mapped[str] = mapped_column(String(40), default="", server_default="")
    quality: Mapped[float] = mapped_column(Float, default=0.0)
    dim: Mapped[int] = mapped_column(Integer)
    model_version: Mapped[str] = mapped_column(String(100), default="")
    sealed: Mapped[bytes] = mapped_column(LargeBinary)
    created_at: Mapped[datetime] = mapped_column(UtcDateTime, default=utcnow)

    person: Mapped[RecognitionPerson] = relationship(back_populates="templates")


class RecognitionVehicle(Base):
    __tablename__ = "recognition_vehicles"
    __table_args__ = (Index("ix_recognition_vehicles_plate", "plate"),)

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_uuid)
    plate: Mapped[str] = mapped_column(String(20))  # normalized
    country: Mapped[str] = mapped_column(String(10), default="")
    region: Mapped[str] = mapped_column(String(50), default="")
    vehicle_type: Mapped[str] = mapped_column(String(30), default="")
    description: Mapped[str] = mapped_column(Text, default="")
    owner_ref: Mapped[str] = mapped_column(String(200), default="")
    groups: Mapped[list[str]] = mapped_column(JSON, default=list)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    notes: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(UtcDateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(UtcDateTime, default=utcnow, onupdate=utcnow)


class RecognitionEvent(Base):
    __tablename__ = "recognition_events"
    __table_args__ = (
        Index("ix_recognition_events_run", "run_id", "media_time_s"),
        Index("ix_recognition_events_person", "person_id"),
        Index("ix_recognition_events_vehicle", "vehicle_id"),
        Index("ix_recognition_events_plate", "plate_normalized"),
        Index("ix_recognition_events_time", "wall_time"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    run_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    experiment_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    camera_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    track_id: Mapped[int] = mapped_column(Integer)
    object_class: Mapped[str] = mapped_column(String(50), default="")
    module: Mapped[str] = mapped_column(String(10))  # face | plate
    # face: recognized | possible_match | identity_changed | identity_cleared
    # plate: plate_read | registered_vehicle | plate_changed
    kind: Mapped[str] = mapped_column(String(30))
    status: Mapped[str] = mapped_column(String(30), default="")
    person_id: Mapped[str | None] = mapped_column(ForeignKey("recognition_people.id", ondelete="SET NULL"), nullable=True)
    vehicle_id: Mapped[str | None] = mapped_column(ForeignKey("recognition_vehicles.id", ondelete="SET NULL"), nullable=True)
    plate_raw: Mapped[str | None] = mapped_column(String(20), nullable=True)
    plate_normalized: Mapped[str | None] = mapped_column(String(20), nullable=True)
    plate_format: Mapped[str | None] = mapped_column(String(50), nullable=True)
    plate_region: Mapped[str | None] = mapped_column(String(50), nullable=True)
    plate_fields: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    similarity: Mapped[float | None] = mapped_column(Float, nullable=True)
    second_similarity: Mapped[float | None] = mapped_column(Float, nullable=True)
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    quality: Mapped[float | None] = mapped_column(Float, nullable=True)
    n_observations: Mapped[int] = mapped_column(Integer, default=0)
    usable_observations: Mapped[int] = mapped_column(Integer, default=0)
    best_frame_index: Mapped[int | None] = mapped_column(Integer, nullable=True)
    model_version: Mapped[str] = mapped_column(String(200), default="")
    frame_index: Mapped[int] = mapped_column(Integer, default=0)
    media_time_s: Mapped[float] = mapped_column(Float, default=0.0)
    wall_time: Mapped[datetime] = mapped_column(UtcDateTime, default=utcnow)
    context: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    crop_path: Mapped[str | None] = mapped_column(String(1000), nullable=True)


class RecognitionAudit(Base):
    __tablename__ = "recognition_audit"
    __table_args__ = (Index("ix_recognition_audit_at", "at"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    at: Mapped[datetime] = mapped_column(UtcDateTime, default=utcnow)
    actor: Mapped[str] = mapped_column(String(200), default="")
    actor_role: Mapped[str] = mapped_column(String(20), default="")
    action: Mapped[str] = mapped_column(String(60))
    target_type: Mapped[str | None] = mapped_column(String(30), nullable=True)
    target_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    detail: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    client: Mapped[str | None] = mapped_column(String(100), nullable=True)


class RecognitionAccessToken(Base):
    __tablename__ = "recognition_access_tokens"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_uuid)
    name: Mapped[str] = mapped_column(String(200))
    role: Mapped[str] = mapped_column(String(20))  # viewer | operator | admin
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_by: Mapped[str] = mapped_column(String(200), default="")
    created_at: Mapped[datetime] = mapped_column(UtcDateTime, default=utcnow)
    last_used_at: Mapped[datetime | None] = mapped_column(UtcDateTime, nullable=True)
    expires_at: Mapped[datetime | None] = mapped_column(UtcDateTime, nullable=True)
