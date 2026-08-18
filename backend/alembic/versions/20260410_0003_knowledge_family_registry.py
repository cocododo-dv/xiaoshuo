"""knowledge family registry and direct-read tables

Revision ID: 20260410_0003
Revises: 20260409_0002
Create Date: 2026-04-10
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

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


def _create_table(table_name: str, *columns: object) -> None:
    if table_name in sa.inspect(op.get_bind()).get_table_names():
        return
    (op.create_table)(table_name, *columns)


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    with op.batch_alter_table("review_items", recreate="always") as batch_op:
        batch_op.drop_column("target_collection")
        batch_op.add_column(sa.Column("target_collection", sa.String(), sa.Computed(TARGET_COLLECTION_SQL, persisted=True)))

    _add_missing_columns(
        inspector,
        "voice_profiles",
        [
            sa.Column("runtime_eligible", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("runtime_eligibility_basis", sa.String(), nullable=False, server_default="stage_blocked"),
            sa.Column("effective_at", sa.String(), nullable=True),
            sa.Column("source_review_id", sa.String(), nullable=True),
        ],
    )

    _add_missing_columns(
        inspector,
        "relation_profiles",
        [
            sa.Column("runtime_eligible", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("runtime_eligibility_basis", sa.String(), nullable=False, server_default="stage_blocked"),
            sa.Column("effective_at", sa.String(), nullable=True),
            sa.Column("source_review_id", sa.String(), nullable=True),
        ],
    )

    _add_missing_columns(
        inspector,
        "scene_memories",
        [
            sa.Column("source_review_id", sa.String(), nullable=True),
            sa.Column("effective_at", sa.String(), nullable=True),
        ],
    )

    _add_missing_columns(
        inspector,
        "chapter_memories",
        [
            sa.Column("source_review_id", sa.String(), nullable=True),
            sa.Column("runtime_eligibility_basis", sa.String(), nullable=False, server_default="stage_blocked"),
            sa.Column("effective_at", sa.String(), nullable=True),
        ],
    )

    _create_runtime_item_table(
        "style_rules",
        "style_rule_set_id",
        "content",
        "ck_style_rules_runtime",
    )
    _create_runtime_item_table(
        "banned_rule_clusters",
        "banned_cluster_id",
        "content",
        "ck_banned_clusters_runtime",
    )
    _create_table(
        "world_rules",
        sa.Column("row_id", sa.String(), nullable=False),
        sa.Column("world_rule_id", sa.String(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("scope", sa.String(), nullable=False),
        sa.Column("scope_ref_id", sa.String(), nullable=True),
        sa.Column("rule_tier", sa.String(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("source_review_id", sa.String(), nullable=True),
        sa.Column("active_flag", sa.Integer(), nullable=False),
        sa.Column("runtime_eligible", sa.Integer(), nullable=False),
        sa.Column("runtime_eligibility_basis", sa.String(), nullable=False),
        sa.Column("effective_at", sa.String(), nullable=True),
        sa.Column("expires_at", sa.String(), nullable=True),
        sa.Column("created_at", sa.String(), nullable=False),
        sa.Column("updated_at", sa.String(), nullable=False),
        sa.CheckConstraint(
            "NOT (active_flag = 0 AND runtime_eligible = 1)",
            name="ck_world_rules_runtime",
        ),
        sa.PrimaryKeyConstraint("row_id"),
    )
    _create_runtime_item_table(
        "calibration_lines",
        "calibration_line_id",
        "text",
        "ck_calibration_lines_runtime",
    )
    _create_table(
        "foreshadow_tracker",
        sa.Column("row_id", sa.String(), nullable=False),
        sa.Column("foreshadow_id", sa.String(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("chapter_id", sa.String(), nullable=False),
        sa.Column("scene_id", sa.String(), nullable=True),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("tracker_status", sa.String(), nullable=False),
        sa.Column("source_review_id", sa.String(), nullable=True),
        sa.Column("active_flag", sa.Integer(), nullable=False),
        sa.Column("runtime_eligible", sa.Integer(), nullable=False),
        sa.Column("runtime_eligibility_basis", sa.String(), nullable=False),
        sa.Column("effective_at", sa.String(), nullable=True),
        sa.Column("created_at", sa.String(), nullable=False),
        sa.Column("updated_at", sa.String(), nullable=False),
        sa.CheckConstraint(
            "NOT (active_flag = 0 AND runtime_eligible = 1)",
            name="ck_foreshadow_runtime",
        ),
        sa.PrimaryKeyConstraint("row_id"),
    )


def _create_runtime_item_table(
    table_name: str,
    lineage_column: str,
    text_column: str,
    check_name: str,
) -> None:
    _create_table(
        table_name,
        sa.Column("row_id", sa.String(), nullable=False),
        sa.Column(lineage_column, sa.String(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("scope", sa.String(), nullable=False),
        sa.Column("scope_ref_id", sa.String(), nullable=True),
        sa.Column(text_column, sa.Text(), nullable=False),
        sa.Column("source_review_id", sa.String(), nullable=True),
        sa.Column("active_flag", sa.Integer(), nullable=False),
        sa.Column("runtime_eligible", sa.Integer(), nullable=False),
        sa.Column("runtime_eligibility_basis", sa.String(), nullable=False),
        sa.Column("effective_at", sa.String(), nullable=True),
        sa.Column("created_at", sa.String(), nullable=False),
        sa.Column("updated_at", sa.String(), nullable=False),
        sa.CheckConstraint(
            "NOT (active_flag = 0 AND runtime_eligible = 1)",
            name=check_name,
        ),
        sa.PrimaryKeyConstraint("row_id"),
    )


def _add_missing_columns(inspector: sa.Inspector, table_name: str, columns: list[sa.Column]) -> None:
    existing_columns = {column["name"] for column in inspector.get_columns(table_name)}
    missing_columns = [column for column in columns if column.name not in existing_columns]
    if not missing_columns:
        return

    with op.batch_alter_table(table_name) as batch_op:
        for column in missing_columns:
            batch_op.add_column(column)


def downgrade() -> None:
    op.drop_table("foreshadow_tracker")
    op.drop_table("calibration_lines")
    op.drop_table("world_rules")
    op.drop_table("banned_rule_clusters")
    op.drop_table("style_rules")

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
