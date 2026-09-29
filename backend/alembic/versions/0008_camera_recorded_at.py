"""Video file cameras: when the recording started, so a file run dates its
results by the recording time (for cross-camera correlation of recorded videos)

Revision ID: 0008_camera_recorded_at
Revises: 0007_locations
Create Date: 2026-09-23
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "0008_camera_recorded_at"
down_revision = "0007_locations"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("cameras") as batch:
        batch.add_column(sa.Column("recorded_at", sa.DateTime(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("cameras") as batch:
        batch.drop_column("recorded_at")
