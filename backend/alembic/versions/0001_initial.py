"""initial schema

Revision ID: 0001_initial
Revises:
Create Date: 2026-09-21
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "0001_initial"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "projects",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("tags", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    op.create_table(
        "sites",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("project_id", sa.Integer(), sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_table(
        "videos",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("filename", sa.String(400), nullable=False),
        sa.Column("path", sa.String(1000), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column("duration_s", sa.Float(), nullable=True),
        sa.Column("fps", sa.Float(), nullable=True),
        sa.Column("width", sa.Integer(), nullable=True),
        sa.Column("height", sa.Integer(), nullable=True),
        sa.Column("frame_count", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_table(
        "cameras",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("project_id", sa.Integer(), sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False),
        sa.Column("site_id", sa.Integer(), sa.ForeignKey("sites.id", ondelete="SET NULL"), nullable=True),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("location", sa.String(400), nullable=False),
        sa.Column("source_type", sa.String(20), nullable=False),
        sa.Column("source_uri", sa.String(1000), nullable=False),
        sa.Column("video_id", sa.Integer(), sa.ForeignKey("videos.id", ondelete="SET NULL"), nullable=True),
        sa.Column("width", sa.Integer(), nullable=True),
        sa.Column("height", sa.Integer(), nullable=True),
        sa.Column("requested_fps", sa.Float(), nullable=True),
        sa.Column("processing_fps", sa.Float(), nullable=True),
        sa.Column("rotation", sa.Integer(), nullable=False),
        sa.Column("crop", sa.JSON(), nullable=True),
        sa.Column("inference_size", sa.Integer(), nullable=True),
        sa.Column("reconnect", sa.JSON(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("notes", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    op.create_table(
        "scene_configs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("camera_id", sa.Integer(), sa.ForeignKey("cameras.id", ondelete="CASCADE"), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("document", sa.JSON(), nullable=False),
        sa.Column("frozen", sa.Boolean(), nullable=False),
        sa.Column("created_from_id", sa.Integer(), sa.ForeignKey("scene_configs.id", ondelete="SET NULL"), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("camera_id", "version", name="uq_scene_camera_version"),
    )
    op.create_table(
        "experiments",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("project_id", sa.Integer(), sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False),
        sa.Column("camera_id", sa.Integer(), sa.ForeignKey("cameras.id", ondelete="SET NULL"), nullable=True),
        sa.Column("scene_config_id", sa.Integer(), sa.ForeignKey("scene_configs.id", ondelete="SET NULL"), nullable=True),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("notes", sa.Text(), nullable=False),
        sa.Column("condition_notes", sa.Text(), nullable=False),
        sa.Column("tags", sa.JSON(), nullable=False),
        sa.Column("object_classes", sa.JSON(), nullable=False),
        sa.Column("model_id", sa.String(100), nullable=False),
        sa.Column("tracker_id", sa.String(50), nullable=False),
        sa.Column("inference", sa.JSON(), nullable=False),
        sa.Column("tracker_settings", sa.JSON(), nullable=False),
        sa.Column("rules", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    op.create_table(
        "runs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("experiment_id", sa.Integer(), sa.ForeignKey("experiments.id", ondelete="CASCADE"), nullable=False),
        sa.Column("camera_id", sa.Integer(), sa.ForeignKey("cameras.id", ondelete="SET NULL"), nullable=True),
        sa.Column("scene_config_id", sa.Integer(), sa.ForeignKey("scene_configs.id", ondelete="SET NULL"), nullable=True),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("started_at", sa.DateTime(), nullable=True),
        sa.Column("ended_at", sa.DateTime(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("snapshot", sa.JSON(), nullable=False),
        sa.Column("stats", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_table(
        "events",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("run_id", sa.Integer(), sa.ForeignKey("runs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("experiment_id", sa.Integer(), sa.ForeignKey("experiments.id", ondelete="CASCADE"), nullable=False),
        sa.Column("camera_id", sa.Integer(), nullable=True),
        sa.Column("track_id", sa.Integer(), nullable=False),
        sa.Column("object_class", sa.String(50), nullable=False),
        sa.Column("event_type", sa.String(40), nullable=False),
        sa.Column("rule_id", sa.String(100), nullable=True),
        sa.Column("rule_name", sa.String(200), nullable=True),
        sa.Column("route", sa.String(200), nullable=True),
        sa.Column("object_id", sa.String(100), nullable=True),
        sa.Column("object_name", sa.String(200), nullable=True),
        sa.Column("direction", sa.String(20), nullable=True),
        sa.Column("frame_index", sa.Integer(), nullable=False),
        sa.Column("media_time_s", sa.Float(), nullable=False),
        sa.Column("wall_time", sa.DateTime(), nullable=False),
        sa.Column("entered_at_s", sa.Float(), nullable=True),
        sa.Column("completed_at_s", sa.Float(), nullable=True),
        sa.Column("duration_s", sa.Float(), nullable=True),
        sa.Column("avg_speed", sa.Float(), nullable=True),
        sa.Column("speed_unit", sa.String(20), nullable=True),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.Column("context", sa.JSON(), nullable=False),
    )
    op.create_index("ix_events_run_time", "events", ["run_id", "media_time_s"])
    op.create_index("ix_events_experiment", "events", ["experiment_id"])
    op.create_index("ix_events_type_route", "events", ["event_type", "route"])
    op.create_table(
        "track_summaries",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("run_id", sa.Integer(), sa.ForeignKey("runs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("track_id", sa.Integer(), nullable=False),
        sa.Column("object_class", sa.String(50), nullable=False),
        sa.Column("first_seen_s", sa.Float(), nullable=False),
        sa.Column("last_seen_s", sa.Float(), nullable=False),
        sa.Column("first_seen_at", sa.DateTime(), nullable=True),
        sa.Column("last_seen_at", sa.DateTime(), nullable=True),
        sa.Column("n_frames", sa.Integer(), nullable=False),
        sa.Column("path_length", sa.Float(), nullable=True),
        sa.Column("path_unit", sa.String(20), nullable=False),
        sa.Column("avg_speed", sa.Float(), nullable=True),
        sa.Column("speed_unit", sa.String(20), nullable=True),
        sa.Column("mean_confidence", sa.Float(), nullable=True),
        sa.Column("final_state", sa.String(20), nullable=False),
        sa.Column("route_result", sa.String(200), nullable=True),
        sa.Column("lost_count", sa.Integer(), nullable=False),
    )
    op.create_index("ix_tracks_run", "track_summaries", ["run_id", "track_id"])
    op.create_table(
        "trajectories",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("run_id", sa.Integer(), sa.ForeignKey("runs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("track_id", sa.Integer(), nullable=False),
        sa.Column("object_class", sa.String(50), nullable=False),
        sa.Column("points", sa.JSON(), nullable=False),
        sa.Column("n_points", sa.Integer(), nullable=False),
    )
    op.create_index("ix_traj_run", "trajectories", ["run_id", "track_id"])
    op.create_table(
        "evaluations",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("run_id", sa.Integer(), sa.ForeignKey("runs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("event_id", sa.Integer(), sa.ForeignKey("events.id", ondelete="CASCADE"), nullable=True),
        sa.Column("track_id", sa.Integer(), nullable=True),
        sa.Column("verdict", sa.String(30), nullable=False),
        sa.Column("expected", sa.String(200), nullable=True),
        sa.Column("note", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_table(
        "ground_truth_counts",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("run_id", sa.Integer(), sa.ForeignKey("runs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("object_id", sa.String(100), nullable=False),
        sa.Column("label", sa.String(200), nullable=False),
        sa.Column("count", sa.Integer(), nullable=False),
        sa.Column("note", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_table(
        "installed_models",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("model_id", sa.String(100), nullable=False, unique=True),
        sa.Column("provider", sa.String(50), nullable=False),
        sa.Column("path", sa.String(1000), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column("source_url", sa.String(1000), nullable=True),
        sa.Column("installed_at", sa.DateTime(), nullable=False),
    )
    op.create_table(
        "benchmarks",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("model_id", sa.String(100), nullable=False),
        sa.Column("provider", sa.String(50), nullable=False),
        sa.Column("device", sa.String(50), nullable=False),
        sa.Column("results", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_table(
        "settings",
        sa.Column("key", sa.String(100), primary_key=True),
        sa.Column("value", sa.JSON(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )


def downgrade() -> None:
    for name in (
        "settings", "benchmarks", "installed_models", "ground_truth_counts", "evaluations", "trajectories",
        "track_summaries", "events", "runs", "experiments", "scene_configs", "cameras", "videos", "sites", "projects",
    ):
        op.drop_table(name)
