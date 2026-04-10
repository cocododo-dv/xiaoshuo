"""knowledge family registry and direct-read tables

Revision ID: 20260410_0003
Revises: 20260409_0002
Create Date: 2026-04-10
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

from novel_system.db import models  # noqa: F401
from novel_system.db.base import Base

revision = "20260410_0003"
down_revision = "20260409_0002"
branch_labels = None
depends_on = None

TARGET_COLLECTION_SQL = (
    "CASE "
    "WHEN item_type = 'style_observation' THEN 'style_observations' "
    "WHEN item_type = 'style_rule_set' THEN 'style_rules' "
    "WHEN item_type = 'banned_rule_cluster' THEN 'banned_rule_clusters' "
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
    "ELSE 'review_items' END"
)


def upgrade() -> None:
    bind = op.get_bind()

    with op.batch_alter_table("review_items", recreate="always") as batch_op:
        batch_op.drop_column("target_collection")
        batch_op.add_column(sa.Column("target_collection", sa.String(), sa.Computed(TARGET_COLLECTION_SQL, persisted=True)))

    with op.batch_alter_table("voice_profiles") as batch_op:
        batch_op.add_column(sa.Column("runtime_eligible", sa.Integer(), nullable=False, server_default="0"))
        batch_op.add_column(
            sa.Column("runtime_eligibility_basis", sa.String(), nullable=False, server_default="stage_blocked")
        )
        batch_op.add_column(sa.Column("effective_at", sa.String(), nullable=True))
        batch_op.add_column(sa.Column("source_review_id", sa.String(), nullable=True))

    with op.batch_alter_table("relation_profiles") as batch_op:
        batch_op.add_column(sa.Column("runtime_eligible", sa.Integer(), nullable=False, server_default="0"))
        batch_op.add_column(
            sa.Column("runtime_eligibility_basis", sa.String(), nullable=False, server_default="stage_blocked")
        )
        batch_op.add_column(sa.Column("effective_at", sa.String(), nullable=True))
        batch_op.add_column(sa.Column("source_review_id", sa.String(), nullable=True))

    with op.batch_alter_table("scene_memories") as batch_op:
        batch_op.add_column(sa.Column("source_review_id", sa.String(), nullable=True))
        batch_op.add_column(sa.Column("effective_at", sa.String(), nullable=True))

    with op.batch_alter_table("chapter_memories") as batch_op:
        batch_op.add_column(sa.Column("source_review_id", sa.String(), nullable=True))
        batch_op.add_column(
            sa.Column("runtime_eligibility_basis", sa.String(), nullable=False, server_default="stage_blocked")
        )
        batch_op.add_column(sa.Column("effective_at", sa.String(), nullable=True))

    Base.metadata.create_all(
        bind=bind,
        tables=[
            Base.metadata.tables["style_rules"],
            Base.metadata.tables["banned_rule_clusters"],
            Base.metadata.tables["world_rules"],
            Base.metadata.tables["calibration_lines"],
            Base.metadata.tables["foreshadow_tracker"],
        ],
    )


def downgrade() -> None:
    bind = op.get_bind()

    Base.metadata.tables["foreshadow_tracker"].drop(bind=bind, checkfirst=True)
    Base.metadata.tables["calibration_lines"].drop(bind=bind, checkfirst=True)
    Base.metadata.tables["world_rules"].drop(bind=bind, checkfirst=True)
    Base.metadata.tables["banned_rule_clusters"].drop(bind=bind, checkfirst=True)
    Base.metadata.tables["style_rules"].drop(bind=bind, checkfirst=True)

    with op.batch_alter_table("chapter_memories") as batch_op:
        batch_op.drop_column("effective_at")
        batch_op.drop_column("runtime_eligibility_basis")
        batch_op.drop_column("source_review_id")

    with op.batch_alter_table("scene_memories") as batch_op:
        batch_op.drop_column("effective_at")
        batch_op.drop_column("source_review_id")

    with op.batch_alter_table("relation_profiles") as batch_op:
        batch_op.drop_column("source_review_id")
        batch_op.drop_column("effective_at")
        batch_op.drop_column("runtime_eligibility_basis")
        batch_op.drop_column("runtime_eligible")

    with op.batch_alter_table("voice_profiles") as batch_op:
        batch_op.drop_column("source_review_id")
        batch_op.drop_column("effective_at")
        batch_op.drop_column("runtime_eligibility_basis")
        batch_op.drop_column("runtime_eligible")

    with op.batch_alter_table("review_items", recreate="always") as batch_op:
        batch_op.drop_column("target_collection")
        batch_op.add_column(
            sa.Column(
                "target_collection",
                sa.String(),
                sa.Computed(
                    "CASE "
                    "WHEN item_type = 'style_observation' THEN 'style_observations' "
                    "WHEN item_type = 'scene_memory' THEN 'scene_memories' "
                    "ELSE 'review_items' END",
                    persisted=True,
                ),
            )
        )
