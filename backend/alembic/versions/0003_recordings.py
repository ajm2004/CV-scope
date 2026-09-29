"""video recording of live runs: experiments.recording and the recordings table

Revision ID: 0003_recordings
Revises: 0002_recognition
Create Date: 2026-09-22
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "0003_recordings"
down_revision = "0002_recognition"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("experiments", sa.Column("recording", sa.JSON(), nullable=True))
    op.create_table(
        "recordings",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("run_id", sa.Integer(), sa.ForeignKey("runs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("experiment_id", sa.Integer(), sa.ForeignKey("experiments.id", ondelete="CASCADE"), nullable=True),
        sa.Column("camera_id", sa.Integer(), sa.ForeignKey("cameras.id", ondelete="SET NULL"), nullable=True),
        sa.Column("kind", sa.String(20), nullable=False),
        sa.Column("path", sa.String(1000), nullable=False),
        sa.Column("mime", sa.String(50), nullable=False),
        sa.Column("codec", sa.String(10), nullable=False),
        sa.Column("width", sa.Integer(), nullable=False),
        sa.Column("height", sa.Integer(), nullable=False),
        sa.Column("fps", sa.Float(), nullable=False),
        sa.Column("frames", sa.Integer(), nullable=False),
        sa.Column("media_start_s", sa.Float(), nullable=False),
        sa.Column("media_end_s", sa.Float(), nullable=False),
        sa.Column("started_at", sa.DateTime(), nullable=False),
        sa.Column("ended_at", sa.DateTime(), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column("overlay", sa.Boolean(), nullable=False),
        sa.Column("triggers", sa.JSON(), nullable=False),
        sa.Column("trigger_count", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_recordings_run", "recordings", ["run_id", "media_start_s"])


def downgrade() -> None:
    op.drop_index("ix_recordings_run", table_name="recordings")
    op.drop_table("recordings")
    with op.batch_alter_table("experiments") as batch:
        batch.drop_column("recording")
