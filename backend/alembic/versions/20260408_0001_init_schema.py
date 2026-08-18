"""Frozen initial schema.

Revision ID: 20260408_0001
Revises:
Create Date: 2026-04-08

This migration deliberately contains the schema that existed at revision 0001.
Importing the application's live ORM metadata here would make migration history
change whenever a model changes and would let later missing migrations go unnoticed.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260408_0001"
down_revision = None
branch_labels = None
depends_on = None


def _create_table(table_name: str, *columns: object) -> None:
    """Create one frozen table while tolerating pre-Alembic partial schemas."""
    if table_name in sa.inspect(op.get_bind()).get_table_names():
        return
    (op.create_table)(table_name, *columns)


def upgrade() -> None:
    _create_table(
        "attempt_tracker",
        sa.Column("attempt_id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("scene_id", sa.String(), nullable=True),
        sa.Column("chapter_id", sa.String(), nullable=True),
        sa.Column("step", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("source_bundle_id", sa.String(), nullable=True),
        sa.Column("details_json", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.String(), nullable=False),
        sa.PrimaryKeyConstraint("attempt_id"),
    )
    _create_table(
        "chapter_goals",
        sa.Column("chapter_id", sa.String(), nullable=False),
        sa.Column("planned_scene_count", sa.Integer(), nullable=True),
        sa.Column("mid_aggregate_enabled", sa.Integer(), nullable=False),
        sa.Column("chapter_goal", sa.Text(), nullable=False),
        sa.Column("main_plot_push", sa.Text(), nullable=True),
        sa.Column("emotional_target", sa.Text(), nullable=True),
        sa.Column("ending_effect", sa.Text(), nullable=True),
        sa.Column("must_not", sa.Text(), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.String(), nullable=False),
        sa.Column("updated_at", sa.String(), nullable=False),
        sa.PrimaryKeyConstraint("chapter_id"),
    )
    _create_table(
        "chapter_memories",
        sa.Column("row_id", sa.String(), nullable=False),
        sa.Column("chapter_id", sa.String(), nullable=False),
        sa.Column("aggregate_stage", sa.String(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("active_flag", sa.Integer(), nullable=False),
        sa.Column("runtime_eligible", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.String(), nullable=False),
        sa.PrimaryKeyConstraint("row_id"),
    )
    _create_table(
        "chapter_rolling_notes",
        sa.Column("row_id", sa.String(), nullable=False),
        sa.Column("scene_id", sa.String(), nullable=False),
        sa.Column("chapter_id", sa.String(), nullable=False),
        sa.Column("source_scene_memory_row_id", sa.String(), nullable=False),
        sa.Column("note_text", sa.Text(), nullable=False),
        sa.Column("revision_no", sa.Integer(), nullable=False),
        sa.Column("updated_at", sa.String(), nullable=False),
        sa.PrimaryKeyConstraint("row_id"),
        sa.UniqueConstraint("scene_id"),
    )
    _create_table(
        "final_scenes",
        sa.Column("row_id", sa.String(), nullable=False),
        sa.Column("scene_id", sa.String(), nullable=False),
        sa.Column("chapter_id", sa.String(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("source_bundle_id", sa.String(), nullable=False),
        sa.Column("source_bundle_hash", sa.String(), nullable=False),
        sa.Column("created_at", sa.String(), nullable=False),
        sa.PrimaryKeyConstraint("row_id"),
    )
    _create_table(
        "human_review_events",
        sa.Column("event_id", sa.String(), nullable=False),
        sa.Column("scene_id", sa.String(), nullable=True),
        sa.Column("chapter_id", sa.String(), nullable=True),
        sa.Column("event_source", sa.String(), nullable=False),
        sa.Column("priority", sa.String(), nullable=False),
        sa.Column("owner", sa.String(), nullable=True),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("allowed_actions_json", sa.JSON(), nullable=False),
        sa.Column("result_status_map_json", sa.JSON(), nullable=False),
        sa.Column("default_action", sa.String(), nullable=True),
        sa.Column("created_at", sa.String(), nullable=False),
        sa.Column("updated_at", sa.String(), nullable=False),
        sa.PrimaryKeyConstraint("event_id"),
    )
    _create_table(
        "idempotency_keys",
        sa.Column("idempotency_key", sa.String(), nullable=False),
        sa.Column("request_hash", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("response_json", sa.JSON(), nullable=True),
        sa.Column("worker_id", sa.String(), nullable=True),
        sa.Column("attempt_no", sa.Integer(), nullable=False),
        sa.Column("heartbeat_at", sa.String(), nullable=True),
        sa.Column("lease_expires_at", sa.String(), nullable=True),
        sa.Column("created_at", sa.String(), nullable=False),
        sa.Column("updated_at", sa.String(), nullable=False),
        sa.PrimaryKeyConstraint("idempotency_key"),
    )
    _create_table(
        "operation_logs",
        sa.Column("operation_id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("event_type", sa.String(), nullable=False),
        sa.Column("object_type", sa.String(), nullable=False),
        sa.Column("object_ref", sa.String(), nullable=False),
        sa.Column("payload_json", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.String(), nullable=False),
        sa.PrimaryKeyConstraint("operation_id"),
    )
    _create_table(
        "reconcile_faults",
        sa.Column("fault_id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("fault_scope", sa.String(), nullable=False),
        sa.Column("severity", sa.String(), nullable=False),
        sa.Column("object_ref", sa.String(), nullable=False),
        sa.Column("details_json", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.String(), nullable=False),
        sa.PrimaryKeyConstraint("fault_id"),
    )
    _create_table(
        "reindex_jobs",
        sa.Column("job_id", sa.String(), nullable=False),
        sa.Column("review_id", sa.String(), nullable=True),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("object_type", sa.String(), nullable=False),
        sa.Column("alias_scope", sa.String(), nullable=False),
        sa.Column("target_snapshot_version", sa.String(), nullable=False),
        sa.Column("target_embedding_version", sa.String(), nullable=False),
        sa.Column("worker_id", sa.String(), nullable=True),
        sa.Column("attempt_no", sa.Integer(), nullable=False),
        sa.Column("heartbeat_at", sa.String(), nullable=True),
        sa.Column("lease_expires_at", sa.String(), nullable=True),
        sa.Column("started_at", sa.String(), nullable=True),
        sa.Column("finished_at", sa.String(), nullable=True),
        sa.Column("error_text", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("job_id"),
    )
    _create_table(
        "review_items",
        sa.Column("review_id", sa.String(), nullable=False),
        sa.Column("scene_id", sa.String(), nullable=True),
        sa.Column("chapter_id", sa.String(), nullable=True),
        sa.Column("item_type", sa.String(), nullable=False),
        sa.Column(
            "target_collection",
            sa.String(),
            sa.Computed(
                "CASE WHEN item_type = 'style_observation' THEN 'style_observations' "
                "WHEN item_type = 'calibration_line' THEN 'calibration_lines' "
                "WHEN item_type = 'scene_memory' THEN 'scene_memories' "
                "ELSE 'review_items' END",
                persisted=True,
            ),
            nullable=False,
        ),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("candidate_text", sa.Text(), nullable=False),
        sa.Column("candidate_payload_json", sa.JSON(), nullable=False),
        sa.Column("active_on_approve", sa.Integer(), nullable=False),
        sa.Column("materialize_status", sa.String(), nullable=False),
        sa.Column("retry_count", sa.Integer(), nullable=False),
        sa.Column("max_retry", sa.Integer(), nullable=False),
        sa.Column("approved_item_row_id", sa.String(), nullable=True),
        sa.Column("approved_item_id", sa.String(), nullable=True),
        sa.Column("created_at", sa.String(), nullable=False),
        sa.Column("updated_at", sa.String(), nullable=False),
        sa.CheckConstraint(
            "status IN ('pending','approved','rejected')",
            name="ck_review_items_status",
        ),
        sa.PrimaryKeyConstraint("review_id"),
    )
    _create_table(
        "scene_drafts",
        sa.Column("row_id", sa.String(), nullable=False),
        sa.Column("scene_id", sa.String(), nullable=False),
        sa.Column("chapter_id", sa.String(), nullable=False),
        sa.Column("stage", sa.String(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("source_bundle_id", sa.String(), nullable=False),
        sa.Column("source_bundle_hash", sa.String(), nullable=False),
        sa.Column("created_at", sa.String(), nullable=False),
        sa.PrimaryKeyConstraint("row_id"),
    )
    _create_table(
        "scene_memories",
        sa.Column("row_id", sa.String(), nullable=False),
        sa.Column("scene_id", sa.String(), nullable=False),
        sa.Column("chapter_id", sa.String(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("carry_notes_json", sa.JSON(), nullable=False),
        sa.Column("source_bundle_id", sa.String(), nullable=False),
        sa.Column("final_scene_row_id", sa.String(), nullable=False),
        sa.Column("active_flag", sa.Integer(), nullable=False),
        sa.Column("runtime_eligible", sa.Integer(), nullable=False),
        sa.Column("runtime_eligibility_basis", sa.String(), nullable=False),
        sa.Column("created_at", sa.String(), nullable=False),
        sa.PrimaryKeyConstraint("row_id"),
    )
    _create_table(
        "style_observations",
        sa.Column("row_id", sa.String(), nullable=False),
        sa.Column("style_observation_id", sa.String(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("scope", sa.String(), nullable=False),
        sa.Column("scope_ref_id", sa.String(), nullable=True),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("source_review_id", sa.String(), nullable=True),
        sa.Column("active_flag", sa.Integer(), nullable=False),
        sa.Column("runtime_eligible", sa.Integer(), nullable=False),
        sa.Column("runtime_eligibility_basis", sa.String(), nullable=False),
        sa.Column("effective_at", sa.String(), nullable=True),
        sa.Column("created_at", sa.String(), nullable=False),
        sa.Column("updated_at", sa.String(), nullable=False),
        sa.CheckConstraint(
            "NOT (active_flag = 0 AND runtime_eligible = 1)",
            name="ck_style_obs_runtime",
        ),
        sa.PrimaryKeyConstraint("row_id"),
    )
    _create_table(
        "vector_alias_registry",
        sa.Column("alias_scope", sa.String(), nullable=False),
        sa.Column("object_type", sa.String(), nullable=False),
        sa.Column("scope", sa.String(), nullable=False),
        sa.Column("scope_ref_id", sa.String(), nullable=True),
        sa.Column("collection_family", sa.String(), nullable=False),
        sa.Column("active_alias", sa.String(), nullable=True),
        sa.Column("candidate_alias", sa.String(), nullable=True),
        sa.Column("active_snapshot_version", sa.String(), nullable=True),
        sa.Column("candidate_snapshot_version", sa.String(), nullable=True),
        sa.Column("active_embedding_version", sa.String(), nullable=True),
        sa.Column("candidate_embedding_version", sa.String(), nullable=True),
        sa.Column("verify_status", sa.String(), nullable=False),
        sa.Column("sample_query_success", sa.Integer(), nullable=False),
        sa.Column("updated_at", sa.String(), nullable=False),
        sa.CheckConstraint(
            "(active_alias IS NOT NULL) OR (candidate_alias IS NOT NULL)",
            name="ck_vector_alias_presence",
        ),
        sa.PrimaryKeyConstraint("alias_scope"),
    )
    _create_table(
        "verify_jobs",
        sa.Column("job_id", sa.String(), nullable=False),
        sa.Column("review_id", sa.String(), nullable=True),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("object_type", sa.String(), nullable=False),
        sa.Column("alias_scope", sa.String(), nullable=False),
        sa.Column("target_snapshot_version", sa.String(), nullable=False),
        sa.Column("target_embedding_version", sa.String(), nullable=False),
        sa.Column("worker_id", sa.String(), nullable=True),
        sa.Column("attempt_no", sa.Integer(), nullable=False),
        sa.Column("heartbeat_at", sa.String(), nullable=True),
        sa.Column("lease_expires_at", sa.String(), nullable=True),
        sa.Column("started_at", sa.String(), nullable=True),
        sa.Column("finished_at", sa.String(), nullable=True),
        sa.Column("error_text", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("job_id"),
    )
    _create_table(
        "version_registry",
        sa.Column("registry_id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("object_type", sa.String(), nullable=False),
        sa.Column("lineage_key", sa.String(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("physical_row_id", sa.String(), nullable=False),
        sa.Column("alias_scope", sa.String(), nullable=True),
        sa.Column("materialize_status", sa.String(), nullable=False),
        sa.Column("reindex_status", sa.String(), nullable=False),
        sa.Column("verify_status", sa.String(), nullable=False),
        sa.Column("sample_query_success", sa.Integer(), nullable=False),
        sa.Column("approved_at", sa.String(), nullable=True),
        sa.Column("materialized_at", sa.String(), nullable=True),
        sa.Column("activated_at", sa.String(), nullable=True),
        sa.Column("reindexed_at", sa.String(), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("registry_id"),
    )
    _create_table(
        "chapter_states",
        sa.Column("chapter_id", sa.String(), nullable=False),
        sa.Column("current_phase", sa.String(), nullable=False),
        sa.Column("chapter_passed_scene_count", sa.Integer(), nullable=False),
        sa.Column("chapter_backfill_pending_count", sa.Integer(), nullable=False),
        sa.Column("mid_aggregate_enabled_effective", sa.Integer(), nullable=False),
        sa.Column("aggregate_block_reason", sa.String(), nullable=False),
        sa.Column("last_interim_memory_row_id", sa.String(), nullable=True),
        sa.Column("last_final_memory_row_id", sa.String(), nullable=True),
        sa.Column("updated_at", sa.String(), nullable=False),
        sa.ForeignKeyConstraint(["chapter_id"], ["chapter_goals.chapter_id"]),
        sa.PrimaryKeyConstraint("chapter_id"),
    )
    _create_table(
        "scene_cards",
        sa.Column("scene_id", sa.String(), nullable=False),
        sa.Column("chapter_id", sa.String(), nullable=False),
        sa.Column("scene_seq", sa.Integer(), nullable=False),
        sa.Column("pov_character_id", sa.String(), nullable=True),
        sa.Column("onstage_chars_json", sa.JSON(), nullable=False),
        sa.Column("resolved_relation_id", sa.String(), nullable=True),
        sa.Column("location", sa.String(), nullable=True),
        sa.Column("scene_goal", sa.Text(), nullable=False),
        sa.Column("beats_json", sa.JSON(), nullable=False),
        sa.Column("must_include_text", sa.Text(), nullable=True),
        sa.Column("forbidden_text", sa.Text(), nullable=True),
        sa.Column("exit_change", sa.Text(), nullable=True),
        sa.Column("hook", sa.Text(), nullable=True),
        sa.Column("target_length_band", sa.String(), nullable=True),
        sa.Column("scene_type", sa.String(), nullable=True),
        sa.Column("is_chapter_last", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.String(), nullable=False),
        sa.Column("updated_at", sa.String(), nullable=False),
        sa.ForeignKeyConstraint(["chapter_id"], ["chapter_goals.chapter_id"]),
        sa.PrimaryKeyConstraint("scene_id"),
    )
    _create_table(
        "scene_bundles",
        sa.Column("bundle_id", sa.String(), nullable=False),
        sa.Column("scene_id", sa.String(), nullable=False),
        sa.Column("chapter_id", sa.String(), nullable=False),
        sa.Column("execution_mode", sa.String(), nullable=False),
        sa.Column("bundle_snapshot_hash", sa.String(), nullable=False),
        sa.Column("frozen_snapshot_json", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.String(), nullable=False),
        sa.ForeignKeyConstraint(["scene_id"], ["scene_cards.scene_id"]),
        sa.PrimaryKeyConstraint("bundle_id"),
    )
    _create_table(
        "scene_run_states",
        sa.Column("scene_id", sa.String(), nullable=False),
        sa.Column("scene_status", sa.String(), nullable=False),
        sa.Column("current_bundle_id", sa.String(), nullable=True),
        sa.Column("current_bundle_hash", sa.String(), nullable=True),
        sa.Column("current_neutral_draft_row_id", sa.String(), nullable=True),
        sa.Column("current_style_draft_row_id", sa.String(), nullable=True),
        sa.Column("current_final_scene_row_id", sa.String(), nullable=True),
        sa.Column("current_human_review_event_id", sa.String(), nullable=True),
        sa.Column("current_qc_report_id", sa.String(), nullable=True),
        sa.Column("bundle_build_count", sa.Integer(), nullable=False),
        sa.Column("hard_partial_rewrite_count", sa.Integer(), nullable=False),
        sa.Column("hard_full_rewrite_count", sa.Integer(), nullable=False),
        sa.Column("soft_patch_count", sa.Integer(), nullable=False),
        sa.Column("total_attempt_count", sa.Integer(), nullable=False),
        sa.Column("attempt_budget", sa.Integer(), nullable=False),
        sa.Column("repeat_issue_key", sa.String(), nullable=True),
        sa.Column("repeat_issue_count", sa.Integer(), nullable=False),
        sa.Column("updated_at", sa.String(), nullable=False),
        sa.ForeignKeyConstraint(["scene_id"], ["scene_cards.scene_id"]),
        sa.PrimaryKeyConstraint("scene_id"),
    )


def downgrade() -> None:
    for table_name in (
        "scene_run_states",
        "scene_bundles",
        "scene_cards",
        "chapter_states",
        "version_registry",
        "verify_jobs",
        "vector_alias_registry",
        "style_observations",
        "scene_memories",
        "scene_drafts",
        "review_items",
        "reindex_jobs",
        "reconcile_faults",
        "operation_logs",
        "idempotency_keys",
        "human_review_events",
        "final_scenes",
        "chapter_rolling_notes",
        "chapter_memories",
        "chapter_goals",
        "attempt_tracker",
    ):
        op.drop_table(table_name)
