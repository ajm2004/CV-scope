"""Relationship & Event Correlation Engine: entities, observations, relationships,
correlated events, support links, versioned rules, analyses, audit; experiments.relations

Revision ID: 0006_relationships
Revises: 0005_anomalies
Create Date: 2026-09-23
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "0006_relationships"
down_revision = "0005_anomalies"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("experiments", sa.Column("relations", sa.JSON(), nullable=True))
    op.create_table(
        "relation_analyses",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("run_id", sa.Integer(), sa.ForeignKey("runs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("experiment_id", sa.Integer(), nullable=True),
        sa.Column("camera_id", sa.Integer(), nullable=True),
        sa.Column("source", sa.String(20), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("current", sa.Boolean(), nullable=False),
        sa.Column("rules", sa.JSON(), nullable=False),
        sa.Column("settings", sa.JSON(), nullable=False),
        sa.Column("calibration", sa.JSON(), nullable=False),
        sa.Column("stats", sa.JSON(), nullable=False),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("created_by", sa.String(200), nullable=False),
        sa.Column("started_at", sa.DateTime(), nullable=False),
        sa.Column("finished_at", sa.DateTime(), nullable=True),
    )
    op.create_index("ix_relation_analyses_run", "relation_analyses", ["run_id", "current"])
    op.create_table(
        "relation_entities",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("key", sa.String(200), nullable=False, unique=True),
        sa.Column("entity_type", sa.String(40), nullable=False),
        sa.Column("ref", sa.String(160), nullable=False),
        sa.Column("source", sa.String(40), nullable=False),
        sa.Column("label", sa.String(300), nullable=False),
        sa.Column("secret_label", sa.String(100), nullable=True),
        sa.Column("run_id", sa.Integer(), nullable=True),
        sa.Column("camera_id", sa.Integer(), nullable=True),
        sa.Column("experiment_id", sa.Integer(), nullable=True),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.Column("first_seen", sa.DateTime(), nullable=True),
        sa.Column("last_seen", sa.DateTime(), nullable=True),
        sa.Column("first_media_s", sa.Float(), nullable=True),
        sa.Column("last_media_s", sa.Float(), nullable=True),
        sa.Column("metadata", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_relation_entities_run", "relation_entities", ["run_id"])
    op.create_index("ix_relation_entities_seen", "relation_entities", ["last_seen"])
    op.create_index("ix_relation_entities_type", "relation_entities", ["entity_type"])
    op.create_table(
        "relation_observations",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("uid", sa.String(32), nullable=False, unique=True),
        sa.Column("analysis_id", sa.Integer(), sa.ForeignKey("relation_analyses.id", ondelete="CASCADE"), nullable=True),
        sa.Column("run_id", sa.Integer(), nullable=True),
        sa.Column("camera_id", sa.Integer(), nullable=True),
        sa.Column("entity_id", sa.Integer(), sa.ForeignKey("relation_entities.id", ondelete="CASCADE"), nullable=False),
        sa.Column("object_entity_id", sa.Integer(), sa.ForeignKey("relation_entities.id", ondelete="CASCADE"), nullable=True),
        sa.Column("observation_type", sa.String(40), nullable=False),
        sa.Column("media_time_s", sa.Float(), nullable=True),
        sa.Column("at", sa.DateTime(), nullable=False),
        sa.Column("source", sa.String(40), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.Column("value", sa.JSON(), nullable=False),
    )
    op.create_index("ix_relation_obs_analysis", "relation_observations", ["analysis_id", "media_time_s"])
    op.create_index("ix_relation_obs_entity", "relation_observations", ["entity_id", "at"])
    op.create_index("ix_relation_obs_run", "relation_observations", ["run_id", "media_time_s"])
    op.create_table(
        "relation_relationships",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("uid", sa.String(32), nullable=False, unique=True),
        sa.Column("analysis_id", sa.Integer(), sa.ForeignKey("relation_analyses.id", ondelete="CASCADE"), nullable=True),
        sa.Column("run_id", sa.Integer(), nullable=True),
        sa.Column("experiment_id", sa.Integer(), nullable=True),
        sa.Column("camera_id", sa.Integer(), nullable=True),
        sa.Column("subject_id", sa.Integer(), sa.ForeignKey("relation_entities.id", ondelete="CASCADE"), nullable=False),
        sa.Column("relation_type", sa.String(60), nullable=False),
        sa.Column("object_id", sa.Integer(), sa.ForeignKey("relation_entities.id", ondelete="CASCADE"), nullable=False),
        sa.Column("start_media_s", sa.Float(), nullable=True),
        sa.Column("end_media_s", sa.Float(), nullable=True),
        sa.Column("start_at", sa.DateTime(), nullable=False),
        sa.Column("end_at", sa.DateTime(), nullable=True),
        sa.Column("status", sa.String(10), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("state", sa.String(20), nullable=False),
        sa.Column("components", sa.JSON(), nullable=False),
        sa.Column("rule_key", sa.String(60), nullable=False),
        sa.Column("rule_version", sa.Integer(), nullable=False),
        sa.Column("rule_name", sa.String(200), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("zone_id", sa.String(100), nullable=True),
        sa.Column("sources", sa.JSON(), nullable=False),
        sa.Column("calibration", sa.JSON(), nullable=False),
        sa.Column("metrics", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_relation_rel_analysis", "relation_relationships", ["analysis_id"])
    op.create_index("ix_relation_rel_object", "relation_relationships", ["object_id", "relation_type"])
    op.create_index("ix_relation_rel_run", "relation_relationships", ["run_id", "start_media_s"])
    op.create_index("ix_relation_rel_start", "relation_relationships", ["start_at"])
    op.create_index("ix_relation_rel_subject", "relation_relationships", ["subject_id", "relation_type"])
    op.create_index("ix_relation_rel_type", "relation_relationships", ["relation_type", "start_at"])
    op.create_table(
        "relation_correlated",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("uid", sa.String(32), nullable=False, unique=True),
        sa.Column("analysis_id", sa.Integer(), sa.ForeignKey("relation_analyses.id", ondelete="CASCADE"), nullable=True),
        sa.Column("run_id", sa.Integer(), nullable=True),
        sa.Column("experiment_id", sa.Integer(), nullable=True),
        sa.Column("camera_id", sa.Integer(), nullable=True),
        sa.Column("kind", sa.String(20), nullable=False),
        sa.Column("event_type", sa.String(200), nullable=False),
        sa.Column("label", sa.String(300), nullable=False),
        sa.Column("start_media_s", sa.Float(), nullable=True),
        sa.Column("end_media_s", sa.Float(), nullable=True),
        sa.Column("start_at", sa.DateTime(), nullable=False),
        sa.Column("end_at", sa.DateTime(), nullable=True),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("state", sa.String(20), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("rule_key", sa.String(60), nullable=False),
        sa.Column("rule_version", sa.Integer(), nullable=False),
        sa.Column("rule_name", sa.String(200), nullable=False),
        sa.Column("roles", sa.JSON(), nullable=False),
        sa.Column("temporal", sa.JSON(), nullable=False),
        sa.Column("metrics", sa.JSON(), nullable=False),
        sa.Column("published", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_relation_cor_analysis", "relation_correlated", ["analysis_id"])
    op.create_index("ix_relation_cor_run", "relation_correlated", ["run_id", "start_media_s"])
    op.create_index("ix_relation_cor_start", "relation_correlated", ["start_at"])
    op.create_table(
        "relation_support",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("relationship_id", sa.Integer(), sa.ForeignKey("relation_relationships.id", ondelete="CASCADE"), nullable=True),
        sa.Column("correlated_id", sa.Integer(), sa.ForeignKey("relation_correlated.id", ondelete="CASCADE"), nullable=True),
        sa.Column("observation_id", sa.Integer(), sa.ForeignKey("relation_observations.id", ondelete="CASCADE"), nullable=True),
        sa.Column("supporting_relationship_id", sa.Integer(), sa.ForeignKey("relation_relationships.id", ondelete="CASCADE"), nullable=True),
        sa.Column("role", sa.String(40), nullable=False),
    )
    op.create_index("ix_relation_support_cor", "relation_support", ["correlated_id"])
    op.create_index("ix_relation_support_obs", "relation_support", ["observation_id"])
    op.create_index("ix_relation_support_rel", "relation_support", ["relationship_id"])
    op.create_table(
        "relation_rules",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("key", sa.String(60), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("kind", sa.String(20), nullable=False),
        sa.Column("definition", sa.JSON(), nullable=False),
        sa.Column("note", sa.Text(), nullable=False),
        sa.Column("created_by", sa.String(200), nullable=False),
        sa.Column("archived", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("key", "version", name="uq_relation_rule_version"),
    )
    op.create_table(
        "relation_audit",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("at", sa.DateTime(), nullable=False),
        sa.Column("actor", sa.String(200), nullable=False),
        sa.Column("actor_role", sa.String(20), nullable=False),
        sa.Column("action", sa.String(60), nullable=False),
        sa.Column("target_type", sa.String(40), nullable=True),
        sa.Column("target_id", sa.String(100), nullable=True),
        sa.Column("detail", sa.JSON(), nullable=False),
        sa.Column("client", sa.String(100), nullable=True),
    )
    op.create_index("ix_relation_audit_at", "relation_audit", ["at"])


def downgrade() -> None:
    op.drop_index("ix_relation_audit_at", table_name="relation_audit")
    op.drop_table("relation_audit")
    op.drop_table("relation_rules")
    op.drop_index("ix_relation_support_cor", table_name="relation_support")
    op.drop_index("ix_relation_support_obs", table_name="relation_support")
    op.drop_index("ix_relation_support_rel", table_name="relation_support")
    op.drop_table("relation_support")
    op.drop_index("ix_relation_cor_analysis", table_name="relation_correlated")
    op.drop_index("ix_relation_cor_run", table_name="relation_correlated")
    op.drop_index("ix_relation_cor_start", table_name="relation_correlated")
    op.drop_table("relation_correlated")
    op.drop_index("ix_relation_rel_analysis", table_name="relation_relationships")
    op.drop_index("ix_relation_rel_object", table_name="relation_relationships")
    op.drop_index("ix_relation_rel_run", table_name="relation_relationships")
    op.drop_index("ix_relation_rel_start", table_name="relation_relationships")
    op.drop_index("ix_relation_rel_subject", table_name="relation_relationships")
    op.drop_index("ix_relation_rel_type", table_name="relation_relationships")
    op.drop_table("relation_relationships")
    op.drop_index("ix_relation_obs_analysis", table_name="relation_observations")
    op.drop_index("ix_relation_obs_entity", table_name="relation_observations")
    op.drop_index("ix_relation_obs_run", table_name="relation_observations")
    op.drop_table("relation_observations")
    op.drop_index("ix_relation_entities_run", table_name="relation_entities")
    op.drop_index("ix_relation_entities_seen", table_name="relation_entities")
    op.drop_index("ix_relation_entities_type", table_name="relation_entities")
    op.drop_table("relation_entities")
    op.drop_index("ix_relation_analyses_run", table_name="relation_analyses")
    op.drop_table("relation_analyses")
    with op.batch_alter_table("experiments") as batch:
        batch.drop_column("relations")
