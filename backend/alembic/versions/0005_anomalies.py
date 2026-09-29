"""Anomaly Assistant: experiments.anomaly and the anomaly_events table

Revision ID: 0005_anomalies
Revises: 0004_enrollment_variants
Create Date: 2026-09-23
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "0005_anomalies"
down_revision = "0004_enrollment_variants"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("experiments", sa.Column("anomaly", sa.JSON(), nullable=True))
    op.create_table(
        "anomaly_events",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("uid", sa.String(32), nullable=False, unique=True),
        sa.Column("run_id", sa.Integer(), sa.ForeignKey("runs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("experiment_id", sa.Integer(), sa.ForeignKey("experiments.id", ondelete="CASCADE"), nullable=True),
        sa.Column("camera_id", sa.Integer(), sa.ForeignKey("cameras.id", ondelete="SET NULL"), nullable=True),
        sa.Column("zone_id", sa.String(100), nullable=False),
        sa.Column("zone_name", sa.String(200), nullable=False),
        sa.Column("expected_state", sa.Text(), nullable=False),
        sa.Column("kind", sa.String(20), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("area_pct", sa.Float(), nullable=False),
        sa.Column("bbox", sa.JSON(), nullable=False),
        sa.Column("started_media_s", sa.Float(), nullable=False),
        sa.Column("confirmed_media_s", sa.Float(), nullable=False),
        sa.Column("ended_media_s", sa.Float(), nullable=True),
        sa.Column("duration_s", sa.Float(), nullable=True),
        sa.Column("started_at", sa.DateTime(), nullable=False),
        sa.Column("confirmed_at", sa.DateTime(), nullable=False),
        sa.Column("ended_at", sa.DateTime(), nullable=True),
        sa.Column("end_reason", sa.String(30), nullable=True),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("objects", sa.JSON(), nullable=False),
        sa.Column("subjects", sa.JSON(), nullable=False),
        sa.Column("metrics", sa.JSON(), nullable=False),
        sa.Column("evidence", sa.JSON(), nullable=False),
        sa.Column("zone_settings", sa.JSON(), nullable=False),
        sa.Column("published", sa.Boolean(), nullable=False),
        sa.Column("llm_status", sa.String(20), nullable=False),
        sa.Column("llm_verdict", sa.String(20), nullable=True),
        sa.Column("llm_category", sa.String(30), nullable=True),
        sa.Column("llm_description", sa.Text(), nullable=True),
        sa.Column("llm_confidence", sa.Float(), nullable=True),
        sa.Column("llm_evidence", sa.Text(), nullable=True),
        sa.Column("llm_provider", sa.String(30), nullable=True),
        sa.Column("llm_model", sa.String(120), nullable=True),
        sa.Column("llm_latency_ms", sa.Float(), nullable=True),
        sa.Column("llm_error", sa.Text(), nullable=True),
        sa.Column("llm_at", sa.DateTime(), nullable=True),
        sa.Column("feedback", sa.String(20), nullable=True),
        sa.Column("note", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_anomaly_run", "anomaly_events", ["run_id", "started_media_s"])
    op.create_index("ix_anomaly_camera_time", "anomaly_events", ["camera_id", "confirmed_at"])


def downgrade() -> None:
    op.drop_index("ix_anomaly_camera_time", table_name="anomaly_events")
    op.drop_index("ix_anomaly_run", table_name="anomaly_events")
    op.drop_table("anomaly_events")
    with op.batch_alter_table("experiments") as batch:
        batch.drop_column("anomaly")
