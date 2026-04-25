"""add author draft tables

Revision ID: 20260425_0015
Revises: 20260425_0014
Create Date: 2026-04-25
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260425_0015"
down_revision = "20260425_0014"
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
    "ELSE 'review_items' END"
)


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    tables = set(inspector.get_table_names())

    if "author_drafts" not in tables:
        op.create_table(
            "author_drafts",
            sa.Column("draft_id", sa.String(), nullable=False),
            sa.Column("object_type", sa.String(), nullable=False),
            sa.Column("object_id", sa.String(), nullable=False),
            sa.Column("source_text_ref", sa.String(), nullable=False),
            sa.Column("content", sa.Text(), nullable=False),
            sa.Column("revision_no", sa.Integer(), nullable=False),
            sa.Column("status", sa.String(), nullable=False),
            sa.Column("created_by", sa.String(), nullable=False),
            sa.Column("updated_by", sa.String(), nullable=False),
            sa.Column("created_at", sa.String(), nullable=False),
            sa.Column("updated_at", sa.String(), nullable=False),
            sa.CheckConstraint("object_type IN ('scene','chapter')", name="ck_author_drafts_object_type"),
            sa.CheckConstraint("status IN ('current','superseded','archived')", name="ck_author_drafts_status"),
            sa.PrimaryKeyConstraint("draft_id"),
        )

    if "author_draft_events" not in tables:
        op.create_table(
            "author_draft_events",
            sa.Column("event_id", sa.String(), nullable=False),
            sa.Column("draft_id", sa.String(), nullable=False),
            sa.Column("object_type", sa.String(), nullable=False),
            sa.Column("object_id", sa.String(), nullable=False),
            sa.Column("event_type", sa.String(), nullable=False),
            sa.Column("patch_id", sa.String(), nullable=True),
            sa.Column("revision_id", sa.String(), nullable=True),
            sa.Column("option_id", sa.String(), nullable=True),
            sa.Column("note", sa.Text(), nullable=True),
            sa.Column("payload_json", sa.JSON(), nullable=False),
            sa.Column("created_by", sa.String(), nullable=False),
            sa.Column("created_at", sa.String(), nullable=False),
            sa.CheckConstraint(
                "event_type IN ('created','edited','candidate_inserted','candidate_saved','candidate_rejected')",
                name="ck_author_draft_events_type",
            ),
            sa.PrimaryKeyConstraint("event_id"),
        )

    if "passage_patch_candidates" in tables:
        columns = {column["name"] for column in inspector.get_columns("passage_patch_candidates")}
        with op.batch_alter_table("passage_patch_candidates") as batch_op:
            if "source_draft_id" not in columns:
                batch_op.add_column(sa.Column("source_draft_id", sa.String(), nullable=True))
            if "generation_llm_call_id" not in columns:
                batch_op.add_column(sa.Column("generation_llm_call_id", sa.String(), nullable=True))
            if "rationale" not in columns:
                batch_op.add_column(sa.Column("rationale", sa.Text(), nullable=True))

    if "review_items" in tables:
        columns = {column["name"] for column in inspector.get_columns("review_items")}
        if "target_collection" in columns:
            with op.batch_alter_table("review_items", recreate="always") as batch_op:
                batch_op.drop_column("target_collection")
                batch_op.add_column(sa.Column("target_collection", sa.String(), sa.Computed(TARGET_COLLECTION_SQL, persisted=True)))


def downgrade() -> None:
    pass
