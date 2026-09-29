"""recognition modules: people, templates, enrollment images, vehicles, events, audit, access tokens

Revision ID: 0002_recognition
Revises: 0001_initial
Create Date: 2026-09-22
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "0002_recognition"
down_revision = "0001_initial"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "recognition_people",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("display_name", sa.String(200), nullable=False),
        sa.Column("reference_id", sa.String(200), nullable=True),
        sa.Column("notes", sa.Text(), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False),
        sa.Column("valid_from", sa.Date(), nullable=True),
        sa.Column("valid_until", sa.Date(), nullable=True),
        sa.Column("enrollment_status", sa.String(20), nullable=False),
        sa.Column("enrollment_quality", sa.Float(), nullable=True),
        sa.Column("enrollment_summary", sa.JSON(), nullable=False),
        sa.Column("model_version", sa.String(100), nullable=False),
        sa.Column("enrolled_at", sa.DateTime(), nullable=True),
        sa.Column("created_by", sa.String(200), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    op.create_table(
        "recognition_enrollment_images",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("person_id", sa.String(32), sa.ForeignKey("recognition_people.id", ondelete="CASCADE"), nullable=False),
        sa.Column("view", sa.String(20), nullable=False),
        sa.Column("biometric", sa.Boolean(), nullable=False),
        sa.Column("path", sa.String(1000), nullable=False),
        sa.Column("width", sa.Integer(), nullable=False),
        sa.Column("height", sa.Integer(), nullable=False),
        sa.Column("quality", sa.Float(), nullable=True),
        sa.Column("quality_detail", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_table(
        "recognition_face_templates",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("person_id", sa.String(32), sa.ForeignKey("recognition_people.id", ondelete="CASCADE"), nullable=False),
        sa.Column("image_id", sa.String(32), sa.ForeignKey("recognition_enrollment_images.id", ondelete="SET NULL"), nullable=True),
        sa.Column("view", sa.String(20), nullable=False),
        sa.Column("quality", sa.Float(), nullable=False),
        sa.Column("dim", sa.Integer(), nullable=False),
        sa.Column("model_version", sa.String(100), nullable=False),
        sa.Column("sealed", sa.LargeBinary(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_table(
        "recognition_vehicles",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("plate", sa.String(20), nullable=False),
        sa.Column("country", sa.String(10), nullable=False),
        sa.Column("region", sa.String(50), nullable=False),
        sa.Column("vehicle_type", sa.String(30), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("owner_ref", sa.String(200), nullable=False),
        sa.Column("groups", sa.JSON(), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False),
        sa.Column("notes", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_recognition_vehicles_plate", "recognition_vehicles", ["plate"])
    op.create_table(
        "recognition_events",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("run_id", sa.Integer(), nullable=True),
        sa.Column("experiment_id", sa.Integer(), nullable=True),
        sa.Column("camera_id", sa.Integer(), nullable=True),
        sa.Column("track_id", sa.Integer(), nullable=False),
        sa.Column("object_class", sa.String(50), nullable=False),
        sa.Column("module", sa.String(10), nullable=False),
        sa.Column("kind", sa.String(30), nullable=False),
        sa.Column("status", sa.String(30), nullable=False),
        sa.Column("person_id", sa.String(32), sa.ForeignKey("recognition_people.id", ondelete="SET NULL"), nullable=True),
        sa.Column("vehicle_id", sa.String(32), sa.ForeignKey("recognition_vehicles.id", ondelete="SET NULL"), nullable=True),
        sa.Column("plate_raw", sa.String(20), nullable=True),
        sa.Column("plate_normalized", sa.String(20), nullable=True),
        sa.Column("plate_format", sa.String(50), nullable=True),
        sa.Column("plate_region", sa.String(50), nullable=True),
        sa.Column("plate_fields", sa.JSON(), nullable=False),
        sa.Column("similarity", sa.Float(), nullable=True),
        sa.Column("second_similarity", sa.Float(), nullable=True),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.Column("quality", sa.Float(), nullable=True),
        sa.Column("n_observations", sa.Integer(), nullable=False),
        sa.Column("usable_observations", sa.Integer(), nullable=False),
        sa.Column("best_frame_index", sa.Integer(), nullable=True),
        sa.Column("model_version", sa.String(200), nullable=False),
        sa.Column("frame_index", sa.Integer(), nullable=False),
        sa.Column("media_time_s", sa.Float(), nullable=False),
        sa.Column("wall_time", sa.DateTime(), nullable=False),
        sa.Column("context", sa.JSON(), nullable=False),
        sa.Column("crop_path", sa.String(1000), nullable=True),
    )
    op.create_index("ix_recognition_events_run", "recognition_events", ["run_id", "media_time_s"])
    op.create_index("ix_recognition_events_person", "recognition_events", ["person_id"])
    op.create_index("ix_recognition_events_vehicle", "recognition_events", ["vehicle_id"])
    op.create_index("ix_recognition_events_plate", "recognition_events", ["plate_normalized"])
    op.create_index("ix_recognition_events_time", "recognition_events", ["wall_time"])
    op.create_table(
        "recognition_audit",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("at", sa.DateTime(), nullable=False),
        sa.Column("actor", sa.String(200), nullable=False),
        sa.Column("actor_role", sa.String(20), nullable=False),
        sa.Column("action", sa.String(60), nullable=False),
        sa.Column("target_type", sa.String(30), nullable=True),
        sa.Column("target_id", sa.String(64), nullable=True),
        sa.Column("detail", sa.JSON(), nullable=False),
        sa.Column("client", sa.String(100), nullable=True),
    )
    op.create_index("ix_recognition_audit_at", "recognition_audit", ["at"])
    op.create_table(
        "recognition_access_tokens",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("role", sa.String(20), nullable=False),
        sa.Column("token_hash", sa.String(64), nullable=False, unique=True),
        sa.Column("active", sa.Boolean(), nullable=False),
        sa.Column("created_by", sa.String(200), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("last_used_at", sa.DateTime(), nullable=True),
        sa.Column("expires_at", sa.DateTime(), nullable=True),
    )


def downgrade() -> None:
    for name in ("recognition_access_tokens", "recognition_audit", "recognition_events", "recognition_vehicles", "recognition_face_templates", "recognition_enrollment_images", "recognition_people"):
        op.drop_table(name)
