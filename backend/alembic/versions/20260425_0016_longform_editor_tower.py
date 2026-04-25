"""add longform editor tower tables

Revision ID: 20260425_0016
Revises: 20260425_0015
Create Date: 2026-04-25
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260425_0016"
down_revision = "20260425_0015"
branch_labels = None
depends_on = None

TARGET_COLLECTION_SQL = (
    "CASE "
    "WHEN item_type = 'style_observation' THEN 'style_observations' "
    "WHEN item_type = 'style_rule_set' THEN 'style_rules' "
    "WHEN item_type = 'banned_rule_cluster' THEN 'banned_rule_clusters' "
    "WHEN item_type = 'narrative_pattern' THEN 'narrative_patterns' "
    "WHEN item_type = 'voice_card_candidate' THEN 'voice_cards' "
    "WHEN item_type = 'relation_card_candidate' THEN 'relation_cards' "
    "WHEN item_type = 'world_rule' THEN 'world_rules' "
    "WHEN item_type = 'calibration_candidate' THEN 'calibration_lines' "
    "WHEN item_type = 'foreshadow_open' THEN 'foreshadow_tracker' "
    "WHEN item_type = 'foreshadow_touch' THEN 'foreshadow_tracker' "
    "WHEN item_type = 'foreshadow_resolve' THEN 'foreshadow_tracker' "
    "WHEN item_type = 'scene_memory' THEN 'scene_memories' "
    "WHEN item_type = 'scene_summary' THEN 'scene_memories' "
    "WHEN item_type = 'chapter_summary' THEN 'chapter_memories' "
    "WHEN item_type = 'author_preference_profile' THEN 'author_preference_profiles' "
    "WHEN item_type = 'longform_structure_guidance' THEN 'longform_structure_guidance' "
    "ELSE 'review_items' END"
)


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    tables = set(inspector.get_table_names())

    if "longform_diagnostic_cards" not in tables:
        op.create_table(
            "longform_diagnostic_cards",
            sa.Column("card_id", sa.String(), nullable=False),
            sa.Column("card_type", sa.String(), nullable=False),
            sa.Column("severity", sa.String(), nullable=False),
            sa.Column("status", sa.String(), nullable=False),
            sa.Column("object_type", sa.String(), nullable=False),
            sa.Column("object_id", sa.String(), nullable=False),
            sa.Column("chapter_id", sa.String(), nullable=True),
            sa.Column("scene_id", sa.String(), nullable=True),
            sa.Column("character_id", sa.String(), nullable=True),
            sa.Column("source_refs_json", sa.JSON(), nullable=False),
            sa.Column("evidence_json", sa.JSON(), nullable=False),
            sa.Column("recommendation_json", sa.JSON(), nullable=False),
            sa.Column("source_snapshot_hash", sa.String(), nullable=False),
            sa.Column("review_id", sa.String(), nullable=True),
            sa.Column("guidance_id", sa.String(), nullable=True),
            sa.Column("created_by", sa.String(), nullable=False),
            sa.Column("updated_by", sa.String(), nullable=False),
            sa.Column("created_at", sa.String(), nullable=False),
            sa.Column("updated_at", sa.String(), nullable=False),
            sa.CheckConstraint(
                "card_type IN ('character_arc_gap','foreshadow_debt','promise_without_payoff','information_congestion','theme_pressure_light','relationship_turn_stall','ending_drive_drop','reference_leakage_risk')",
                name="ck_longform_diagnostic_cards_type",
            ),
            sa.CheckConstraint("severity IN ('info','minor','major','critical')", name="ck_longform_diagnostic_cards_severity"),
            sa.CheckConstraint(
                "status IN ('open','resolved','dismissed','published_guidance')",
                name="ck_longform_diagnostic_cards_status",
            ),
            sa.CheckConstraint(
                "object_type IN ('book','chapter','scene','character','relation','foreshadow','reference')",
                name="ck_longform_diagnostic_cards_object_type",
            ),
            sa.PrimaryKeyConstraint("card_id"),
        )

    if "longform_structure_guidance" not in tables:
        op.create_table(
            "longform_structure_guidance",
            sa.Column("guidance_id", sa.String(), nullable=False),
            sa.Column("card_id", sa.String(), nullable=True),
            sa.Column("scope_type", sa.String(), nullable=False),
            sa.Column("scope_ref_id", sa.String(), nullable=False),
            sa.Column("content", sa.Text(), nullable=False),
            sa.Column("status", sa.String(), nullable=False),
            sa.Column("runtime_eligible", sa.Integer(), nullable=False),
            sa.Column("source_review_id", sa.String(), nullable=True),
            sa.Column("evidence_json", sa.JSON(), nullable=False),
            sa.Column("recommendation_json", sa.JSON(), nullable=False),
            sa.Column("created_by", sa.String(), nullable=False),
            sa.Column("created_at", sa.String(), nullable=False),
            sa.Column("updated_at", sa.String(), nullable=False),
            sa.CheckConstraint(
                "scope_type IN ('global','chapter','scene','character')",
                name="ck_longform_structure_guidance_scope_type",
            ),
            sa.CheckConstraint(
                "status IN ('draft','approved','rejected','superseded')",
                name="ck_longform_structure_guidance_status",
            ),
            sa.PrimaryKeyConstraint("guidance_id"),
        )

    if "review_items" in tables:
        columns = {column["name"] for column in inspector.get_columns("review_items")}
        if "target_collection" in columns:
            with op.batch_alter_table("review_items", recreate="always") as batch_op:
                batch_op.drop_column("target_collection")
                batch_op.add_column(sa.Column("target_collection", sa.String(), sa.Computed(TARGET_COLLECTION_SQL, persisted=True)))


def downgrade() -> None:
    pass
