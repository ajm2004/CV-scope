"""enrollment looks: a label on every enrollment image and template

Revision ID: 0004_enrollment_variants
Revises: 0003_recordings
Create Date: 2026-09-22
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "0004_enrollment_variants"
down_revision = "0003_recordings"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # "" is the first enrollment; later sessions carry a label such as "Glasses".
    op.add_column("recognition_enrollment_images", sa.Column("variant", sa.String(40), nullable=False, server_default=""))
    op.add_column("recognition_face_templates", sa.Column("variant", sa.String(40), nullable=False, server_default=""))


def downgrade() -> None:
    op.drop_column("recognition_face_templates", "variant")
    op.drop_column("recognition_enrollment_images", "variant")
