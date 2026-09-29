"""Location Engine and cross-camera correlation: location nodes (sites, buildings,
floors, areas, roads, cameras, sensors), links, scene-zone mapping, cross-camera transitions

Revision ID: 0007_locations
Revises: 0006_relationships
Create Date: 2026-09-23
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "0007_locations"
down_revision = "0006_relationships"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "location_nodes",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("parent_id", sa.Integer(), sa.ForeignKey("location_nodes.id", ondelete="CASCADE"), nullable=True),
        sa.Column("project_id", sa.Integer(), sa.ForeignKey("projects.id", ondelete="SET NULL"), nullable=True),
        sa.Column("kind", sa.String(30), nullable=False),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("camera_id", sa.Integer(), sa.ForeignKey("cameras.id", ondelete="CASCADE"), nullable=True),
        sa.Column("sensor_id", sa.String(100), nullable=True),
        sa.Column("x", sa.Float(), nullable=True),
        sa.Column("y", sa.Float(), nullable=True),
        sa.Column("w", sa.Float(), nullable=True),
        sa.Column("h", sa.Float(), nullable=True),
        sa.Column("shape", sa.JSON(), nullable=False),
        sa.Column("lat", sa.Float(), nullable=True),
        sa.Column("lon", sa.Float(), nullable=True),
        sa.Column("level", sa.Integer(), nullable=True),
        sa.Column("orientation_deg", sa.Float(), nullable=True),
        sa.Column("fov_deg", sa.Float(), nullable=True),
        sa.Column("view_range", sa.Float(), nullable=True),
        sa.Column("layout", sa.JSON(), nullable=True),
        sa.Column("is_entry", sa.Boolean(), nullable=False),
        sa.Column("restricted", sa.Boolean(), nullable=False),
        sa.Column("meta", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("camera_id", name="uq_location_camera"),
    )
    op.create_index("ix_location_nodes_parent", "location_nodes", ["parent_id"])
    op.create_table(
        "location_links",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("source_id", sa.Integer(), sa.ForeignKey("location_nodes.id", ondelete="CASCADE"), nullable=False),
        sa.Column("target_id", sa.Integer(), sa.ForeignKey("location_nodes.id", ondelete="CASCADE"), nullable=False),
        sa.Column("kind", sa.String(20), nullable=False),
        sa.Column("one_way", sa.Boolean(), nullable=False),
        sa.Column("travel_min_s", sa.Float(), nullable=True),
        sa.Column("travel_max_s", sa.Float(), nullable=True),
        sa.Column("via_id", sa.Integer(), sa.ForeignKey("location_nodes.id", ondelete="SET NULL"), nullable=True),
        sa.Column("shared_id", sa.Integer(), sa.ForeignKey("location_nodes.id", ondelete="SET NULL"), nullable=True),
        sa.Column("overlap", sa.Boolean(), nullable=False),
        sa.Column("distance", sa.Float(), nullable=True),
        sa.Column("notes", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_location_links_source", "location_links", ["source_id"])
    op.create_index("ix_location_links_target", "location_links", ["target_id"])
    op.create_table(
        "location_zone_links",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("camera_id", sa.Integer(), sa.ForeignKey("cameras.id", ondelete="CASCADE"), nullable=False),
        sa.Column("object_id", sa.String(100), nullable=False),
        sa.Column("object_kind", sa.String(20), nullable=False),
        sa.Column("node_id", sa.Integer(), sa.ForeignKey("location_nodes.id", ondelete="CASCADE"), nullable=False),
        sa.UniqueConstraint("camera_id", "object_id", name="uq_location_zone"),
    )
    op.create_table(
        "crosscam_transitions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("uid", sa.String(32), nullable=False, unique=True),
        sa.Column("subject_id", sa.Integer(), sa.ForeignKey("relation_entities.id", ondelete="CASCADE"), nullable=False),
        sa.Column("basis", sa.String(20), nullable=False),
        sa.Column("from_track_id", sa.Integer(), sa.ForeignKey("relation_entities.id", ondelete="SET NULL"), nullable=True),
        sa.Column("to_track_id", sa.Integer(), sa.ForeignKey("relation_entities.id", ondelete="SET NULL"), nullable=True),
        sa.Column("from_camera_id", sa.Integer(), nullable=True),
        sa.Column("to_camera_id", sa.Integer(), nullable=True),
        sa.Column("from_run_id", sa.Integer(), nullable=True),
        sa.Column("to_run_id", sa.Integer(), nullable=True),
        sa.Column("from_node_id", sa.Integer(), sa.ForeignKey("location_nodes.id", ondelete="SET NULL"), nullable=True),
        sa.Column("to_node_id", sa.Integer(), sa.ForeignKey("location_nodes.id", ondelete="SET NULL"), nullable=True),
        sa.Column("from_place", sa.String(200), nullable=True),
        sa.Column("to_place", sa.String(200), nullable=True),
        sa.Column("left_at", sa.DateTime(), nullable=False),
        sa.Column("arrived_at", sa.DateTime(), nullable=False),
        sa.Column("left_media_s", sa.Float(), nullable=True),
        sa.Column("arrived_media_s", sa.Float(), nullable=True),
        sa.Column("gap_s", sa.Float(), nullable=False),
        sa.Column("expected_min_s", sa.Float(), nullable=True),
        sa.Column("expected_max_s", sa.Float(), nullable=True),
        sa.Column("expected_source", sa.String(20), nullable=False),
        sa.Column("topology", sa.String(20), nullable=False),
        sa.Column("path", sa.JSON(), nullable=False),
        sa.Column("hops", sa.Integer(), nullable=True),
        sa.Column("identity_confidence", sa.Float(), nullable=True),
        sa.Column("components", sa.JSON(), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("state", sa.String(20), nullable=False),
        sa.Column("sensor_evidence", sa.JSON(), nullable=False),
        sa.Column("flags", sa.JSON(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_crosscam_arrived", "crosscam_transitions", ["arrived_at"])
    op.create_index("ix_crosscam_from_run", "crosscam_transitions", ["from_run_id"])
    op.create_index("ix_crosscam_subject", "crosscam_transitions", ["subject_id", "arrived_at"])
    op.create_index("ix_crosscam_to_run", "crosscam_transitions", ["to_run_id"])


def downgrade() -> None:
    op.drop_index("ix_crosscam_arrived", table_name="crosscam_transitions")
    op.drop_index("ix_crosscam_from_run", table_name="crosscam_transitions")
    op.drop_index("ix_crosscam_subject", table_name="crosscam_transitions")
    op.drop_index("ix_crosscam_to_run", table_name="crosscam_transitions")
    op.drop_table("crosscam_transitions")
    op.drop_table("location_zone_links")
    op.drop_index("ix_location_links_source", table_name="location_links")
    op.drop_index("ix_location_links_target", table_name="location_links")
    op.drop_table("location_links")
    op.drop_index("ix_location_nodes_parent", table_name="location_nodes")
    op.drop_table("location_nodes")
