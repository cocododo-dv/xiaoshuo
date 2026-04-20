"""add reference book learning tables

Revision ID: 20260419_0011
Revises: 20260418_0010
Create Date: 2026-04-19
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260419_0011"
down_revision = "20260418_0010"
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
    "ELSE 'review_items' END"
)


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    tables = set(inspector.get_table_names())

    if "review_items" in tables and "target_collection" in {column["name"] for column in inspector.get_columns("review_items")}:
        with op.batch_alter_table("review_items", recreate="always") as batch_op:
            batch_op.drop_column("target_collection")
            batch_op.add_column(sa.Column("target_collection", sa.String(), sa.Computed(TARGET_COLLECTION_SQL, persisted=True)))

    if "narrative_patterns" not in tables:
        op.create_table(
            "narrative_patterns",
            sa.Column("row_id", sa.String(), nullable=False),
            sa.Column("narrative_pattern_id", sa.String(), nullable=False),
            sa.Column("version", sa.Integer(), nullable=False),
            sa.Column("scope", sa.String(), nullable=False),
            sa.Column("scope_ref_id", sa.String(), nullable=True),
            sa.Column("content", sa.Text(), nullable=False),
            sa.Column("source_review_id", sa.String(), nullable=True),
            sa.Column("active_flag", sa.Integer(), nullable=False),
            sa.Column("runtime_eligible", sa.Integer(), nullable=False),
            sa.Column("runtime_eligibility_basis", sa.String(), nullable=False),
            sa.Column("effective_at", sa.String(), nullable=True),
            sa.Column("created_at", sa.String(), nullable=False),
            sa.Column("updated_at", sa.String(), nullable=False),
            sa.CheckConstraint("NOT (active_flag = 0 AND runtime_eligible = 1)", name="ck_narrative_patterns_runtime"),
            sa.PrimaryKeyConstraint("row_id"),
        )

    if "reference_books" not in tables:
        op.create_table(
            "reference_books",
            sa.Column("book_id", sa.String(), nullable=False),
            sa.Column("title", sa.String(), nullable=False),
            sa.Column("author_label", sa.String(), nullable=True),
            sa.Column("source_kind", sa.String(), nullable=False),
            sa.Column("source_path", sa.Text(), nullable=True),
            sa.Column("file_name", sa.String(), nullable=True),
            sa.Column("cloud_policy", sa.String(), nullable=False),
            sa.Column("analysis_focus", sa.String(), nullable=False),
            sa.Column("text_checksum", sa.String(), nullable=False),
            sa.Column("status", sa.String(), nullable=False),
            sa.Column("total_chars", sa.Integer(), nullable=False),
            sa.Column("total_segments", sa.Integer(), nullable=False),
            sa.Column("stats_json", sa.JSON(), nullable=False),
            sa.Column("created_at", sa.String(), nullable=False),
            sa.Column("updated_at", sa.String(), nullable=False),
            sa.PrimaryKeyConstraint("book_id"),
        )

    if "reference_book_segments" not in tables:
        op.create_table(
            "reference_book_segments",
            sa.Column("segment_id", sa.String(), nullable=False),
            sa.Column("book_id", sa.String(), nullable=False),
            sa.Column("segment_index", sa.Integer(), nullable=False),
            sa.Column("chapter_hint", sa.String(), nullable=True),
            sa.Column("segment_kind", sa.String(), nullable=False),
            sa.Column("start_offset", sa.Integer(), nullable=False),
            sa.Column("end_offset", sa.Integer(), nullable=False),
            sa.Column("text", sa.Text(), nullable=False),
            sa.Column("selected_count", sa.Integer(), nullable=False),
            sa.Column("created_at", sa.String(), nullable=False),
            sa.ForeignKeyConstraint(["book_id"], ["reference_books.book_id"]),
            sa.PrimaryKeyConstraint("segment_id"),
        )

    if "reference_learning_runs" not in tables:
        op.create_table(
            "reference_learning_runs",
            sa.Column("run_id", sa.String(), nullable=False),
            sa.Column("book_id", sa.String(), nullable=False),
            sa.Column("status", sa.String(), nullable=False),
            sa.Column("batch_size", sa.Integer(), nullable=False),
            sa.Column("coverage_json", sa.JSON(), nullable=False),
            sa.Column("round_count", sa.Integer(), nullable=False),
            sa.Column("profile_id", sa.String(), nullable=True),
            sa.Column("created_at", sa.String(), nullable=False),
            sa.Column("updated_at", sa.String(), nullable=False),
            sa.ForeignKeyConstraint(["book_id"], ["reference_books.book_id"]),
            sa.PrimaryKeyConstraint("run_id"),
        )

    if "reference_learning_rounds" not in tables:
        op.create_table(
            "reference_learning_rounds",
            sa.Column("round_id", sa.String(), nullable=False),
            sa.Column("book_id", sa.String(), nullable=False),
            sa.Column("run_id", sa.String(), nullable=False),
            sa.Column("round_index", sa.Integer(), nullable=False),
            sa.Column("status", sa.String(), nullable=False),
            sa.Column("segment_ids_json", sa.JSON(), nullable=False),
            sa.Column("finding_ids_json", sa.JSON(), nullable=False),
            sa.Column("created_at", sa.String(), nullable=False),
            sa.Column("updated_at", sa.String(), nullable=False),
            sa.ForeignKeyConstraint(["book_id"], ["reference_books.book_id"]),
            sa.ForeignKeyConstraint(["run_id"], ["reference_learning_runs.run_id"]),
            sa.PrimaryKeyConstraint("round_id"),
        )

    if "reference_findings" not in tables:
        op.create_table(
            "reference_findings",
            sa.Column("finding_id", sa.String(), nullable=False),
            sa.Column("book_id", sa.String(), nullable=False),
            sa.Column("run_id", sa.String(), nullable=False),
            sa.Column("round_id", sa.String(), nullable=False),
            sa.Column("segment_id", sa.String(), nullable=False),
            sa.Column("review_id", sa.String(), nullable=False),
            sa.Column("finding_type", sa.String(), nullable=False),
            sa.Column("dimension", sa.String(), nullable=False),
            sa.Column("summary", sa.Text(), nullable=False),
            sa.Column("evidence_preview", sa.Text(), nullable=False),
            sa.Column("candidate_payload_json", sa.JSON(), nullable=False),
            sa.Column("status", sa.String(), nullable=False),
            sa.Column("created_at", sa.String(), nullable=False),
            sa.Column("updated_at", sa.String(), nullable=False),
            sa.ForeignKeyConstraint(["book_id"], ["reference_books.book_id"]),
            sa.ForeignKeyConstraint(["run_id"], ["reference_learning_runs.run_id"]),
            sa.ForeignKeyConstraint(["round_id"], ["reference_learning_rounds.round_id"]),
            sa.ForeignKeyConstraint(["segment_id"], ["reference_book_segments.segment_id"]),
            sa.PrimaryKeyConstraint("finding_id"),
        )

    if "reference_profiles" not in tables:
        op.create_table(
            "reference_profiles",
            sa.Column("profile_id", sa.String(), nullable=False),
            sa.Column("book_id", sa.String(), nullable=False),
            sa.Column("run_id", sa.String(), nullable=False),
            sa.Column("title", sa.String(), nullable=False),
            sa.Column("status", sa.String(), nullable=False),
            sa.Column("profile_json", sa.JSON(), nullable=False),
            sa.Column("coverage_json", sa.JSON(), nullable=False),
            sa.Column("source_finding_ids_json", sa.JSON(), nullable=False),
            sa.Column("created_at", sa.String(), nullable=False),
            sa.Column("updated_at", sa.String(), nullable=False),
            sa.ForeignKeyConstraint(["book_id"], ["reference_books.book_id"]),
            sa.ForeignKeyConstraint(["run_id"], ["reference_learning_runs.run_id"]),
            sa.PrimaryKeyConstraint("profile_id"),
        )


def downgrade() -> None:
    pass
