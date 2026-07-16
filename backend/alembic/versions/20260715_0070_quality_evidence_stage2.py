"""Add fail-closed stage-2 quality evidence and strategy policy storage.

Hidden benchmark answers/rubrics are deliberately not stored.  The database
keeps only frozen manifest/rubric hashes, sanitized generation-result hashes,
explicit human value observations, and evidence-bound strategy policies.

Revision ID: 20260715_0070
Revises: 20260715_0069
Create Date: 2026-07-15
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "20260715_0070"
down_revision = "20260715_0069"
branch_labels = None
depends_on = None


def _inspector():
    return sa.inspect(op.get_bind())


def _has_table(table_name: str) -> bool:
    return _inspector().has_table(table_name)


def _columns(table_name: str) -> set[str]:
    if not _has_table(table_name):
        return set()
    return {str(column["name"]) for column in _inspector().get_columns(table_name)}


def upgrade() -> None:
    if not _has_table("quality_benchmark_manifests"):
        op.create_table(
            "quality_benchmark_manifests",
            sa.Column("manifest_id", sa.String(), nullable=False),
            sa.Column("schema_version", sa.Integer(), nullable=False, server_default="1"),
            sa.Column("manifest_version", sa.String(), nullable=False),
            sa.Column("split_kind", sa.String(), nullable=False, server_default="hidden"),
            sa.Column("manifest_hash", sa.String(), nullable=False),
            sa.Column("public_cases_hash", sa.String(), nullable=False),
            sa.Column("rubric_hash", sa.String(), nullable=False),
            sa.Column("case_count", sa.Integer(), nullable=False),
            sa.Column("isolation_mode", sa.String(), nullable=False),
            sa.Column("storage_ref", sa.Text(), nullable=False),
            sa.Column("status", sa.String(), nullable=False, server_default="frozen"),
            sa.Column("created_at", sa.String(), nullable=False),
            sa.CheckConstraint(
                "case_count > 0",
                name="ck_quality_benchmark_manifests_case_count_positive",
            ),
            sa.CheckConstraint(
                "split_kind = 'hidden'",
                name="ck_quality_benchmark_manifests_hidden_split",
            ),
            sa.CheckConstraint(
                "status IN ('frozen','retired')",
                name="ck_quality_benchmark_manifests_status",
            ),
            sa.PrimaryKeyConstraint("manifest_id"),
        )
        op.create_index(
            "ix_quality_benchmark_manifests_hash",
            "quality_benchmark_manifests",
            ["manifest_hash"],
            unique=True,
        )

    experiment_columns = _columns("evaluation_experiments")
    for column in (
        sa.Column("benchmark_manifest_id", sa.String(), nullable=True),
        sa.Column("benchmark_manifest_hash", sa.String(), nullable=True),
        sa.Column("hidden_rubric_hash", sa.String(), nullable=True),
    ):
        if experiment_columns and column.name not in experiment_columns:
            op.add_column("evaluation_experiments", column)

    pair_columns = _columns("evaluation_pairs")
    for column in (
        sa.Column("scene_function", sa.String(), nullable=True),
        sa.Column("treatment_benchmark_result_id", sa.String(), nullable=True),
        sa.Column("control_benchmark_result_id", sa.String(), nullable=True),
        sa.Column("benchmark_case_id_hash", sa.String(), nullable=True),
    ):
        if pair_columns and column.name not in pair_columns:
            op.add_column("evaluation_pairs", column)

    if not _has_table("quality_strategy_policies"):
        op.create_table(
            "quality_strategy_policies",
            sa.Column("policy_id", sa.String(), nullable=False),
            sa.Column("policy_version", sa.Integer(), nullable=False, server_default="1"),
            sa.Column("genre", sa.String(), nullable=False, server_default="*"),
            sa.Column("scene_function", sa.String(), nullable=False, server_default="*"),
            sa.Column("weights_json", sa.JSON(), nullable=False),
            sa.Column("thresholds_json", sa.JSON(), nullable=False),
            sa.Column("best_of_n_requested", sa.Boolean(), nullable=False, server_default="0"),
            sa.Column("best_of_n_n", sa.Integer(), nullable=False, server_default="1"),
            sa.Column("evidence_experiment_id", sa.String(), nullable=True),
            sa.Column("benchmark_manifest_id", sa.String(), nullable=True),
            sa.Column("status", sa.String(), nullable=False, server_default="active"),
            sa.Column("created_by", sa.String(), nullable=False, server_default="operator"),
            sa.Column("created_at", sa.String(), nullable=False),
            sa.Column("updated_at", sa.String(), nullable=False),
            sa.CheckConstraint(
                "best_of_n_n >= 1 AND best_of_n_n <= 5",
                name="ck_quality_strategy_policies_best_of_n_positive",
            ),
            sa.CheckConstraint(
                "policy_version >= 1",
                name="ck_quality_strategy_policies_version_positive",
            ),
            sa.CheckConstraint(
                "best_of_n_requested IN (0,1)",
                name="ck_quality_strategy_policies_best_of_n_boolean",
            ),
            sa.CheckConstraint(
                "status IN ('active','retired')",
                name="ck_quality_strategy_policies_status",
            ),
            sa.ForeignKeyConstraint(
                ["benchmark_manifest_id"],
                ["quality_benchmark_manifests.manifest_id"],
            ),
            sa.ForeignKeyConstraint(
                ["evidence_experiment_id"],
                ["evaluation_experiments.experiment_id"],
            ),
            sa.PrimaryKeyConstraint("policy_id"),
            sa.UniqueConstraint(
                "genre",
                "scene_function",
                "policy_version",
                name="uq_quality_strategy_policy_scope_version",
            ),
        )
        op.create_index(
            "ix_quality_strategy_policies_scope_status",
            "quality_strategy_policies",
            ["genre", "scene_function", "status"],
            unique=False,
        )

    if not _has_table("quality_benchmark_runs"):
        op.create_table(
            "quality_benchmark_runs",
            sa.Column("run_id", sa.String(), nullable=False),
            sa.Column("manifest_id", sa.String(), nullable=False),
            sa.Column("manifest_hash", sa.String(), nullable=False),
            sa.Column("rubric_hash", sa.String(), nullable=False),
            sa.Column("policy_id", sa.String(), nullable=True),
            sa.Column("generator_ref", sa.String(), nullable=False),
            sa.Column("generation_policy_hash", sa.String(), nullable=False),
            sa.Column("generation_arm", sa.String(), nullable=False, server_default="unassigned"),
            sa.Column("status", sa.String(), nullable=False, server_default="collecting"),
            sa.Column("case_count_expected", sa.Integer(), nullable=False),
            sa.Column("case_count_recorded", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("created_at", sa.String(), nullable=False),
            sa.Column("completed_at", sa.String(), nullable=True),
            sa.CheckConstraint(
                "case_count_expected > 0",
                name="ck_quality_benchmark_runs_expected_positive",
            ),
            sa.CheckConstraint(
                "case_count_recorded >= 0",
                name="ck_quality_benchmark_runs_recorded_nonnegative",
            ),
            sa.CheckConstraint(
                "status IN ('collecting','completed','invalid')",
                name="ck_quality_benchmark_runs_status",
            ),
            sa.CheckConstraint(
                "generation_arm IN ('treatment','control','unassigned')",
                name="ck_quality_benchmark_runs_generation_arm",
            ),
            sa.ForeignKeyConstraint(["manifest_id"], ["quality_benchmark_manifests.manifest_id"]),
            sa.ForeignKeyConstraint(["policy_id"], ["quality_strategy_policies.policy_id"]),
            sa.PrimaryKeyConstraint("run_id"),
        )
        op.create_index(
            "ix_quality_benchmark_runs_manifest_status",
            "quality_benchmark_runs",
            ["manifest_id", "status"],
            unique=False,
        )

    if not _has_table("quality_benchmark_results"):
        op.create_table(
            "quality_benchmark_results",
            sa.Column("result_id", sa.String(), nullable=False),
            sa.Column("run_id", sa.String(), nullable=False),
            sa.Column("case_id_hash", sa.String(), nullable=False),
            sa.Column("genre", sa.String(), nullable=False),
            sa.Column("scene_function", sa.String(), nullable=False),
            sa.Column("artifact_ref", sa.String(), nullable=False),
            sa.Column("generation_input_hash", sa.String(), nullable=False),
            sa.Column("generation_prompt_hash", sa.String(), nullable=False),
            sa.Column("output_hash", sa.String(), nullable=False),
            sa.Column("prompt_leakage_check", sa.String(), nullable=False, server_default="passed"),
            sa.Column("automated_metrics_json", sa.JSON(), nullable=False),
            sa.Column("cost_tokens", sa.Integer(), nullable=True),
            sa.Column("cost_micros", sa.Integer(), nullable=True),
            sa.Column("cost_currency", sa.String(), nullable=True),
            sa.Column("cost_basis", sa.String(), nullable=True),
            sa.Column("latency_ms", sa.Integer(), nullable=True),
            sa.Column("created_at", sa.String(), nullable=False),
            sa.CheckConstraint(
                "cost_tokens IS NULL OR cost_tokens >= 0",
                name="ck_quality_benchmark_results_cost_nonnegative",
            ),
            sa.CheckConstraint(
                "latency_ms IS NULL OR latency_ms >= 0",
                name="ck_quality_benchmark_results_latency_nonnegative",
            ),
            sa.CheckConstraint(
                "cost_micros IS NULL OR cost_micros >= 0",
                name="ck_quality_benchmark_results_cost_micros_nonnegative",
            ),
            sa.CheckConstraint(
                "((cost_micros IS NULL AND cost_currency IS NULL AND cost_basis IS NULL) OR "
                "(cost_micros IS NOT NULL AND cost_currency IS NOT NULL AND cost_basis IS NOT NULL))",
                name="ck_quality_benchmark_results_cost_tuple_complete",
            ),
            sa.CheckConstraint(
                "cost_basis IS NULL OR cost_basis IN ('estimated','actual','billed')",
                name="ck_quality_benchmark_results_cost_basis",
            ),
            sa.CheckConstraint(
                "prompt_leakage_check = 'passed'",
                name="ck_quality_benchmark_results_prompt_leakage_passed",
            ),
            sa.ForeignKeyConstraint(["run_id"], ["quality_benchmark_runs.run_id"]),
            sa.PrimaryKeyConstraint("result_id"),
            sa.UniqueConstraint(
                "run_id",
                "case_id_hash",
                name="uq_quality_benchmark_result_run_case",
            ),
        )
        op.create_index(
            "ix_quality_benchmark_results_strategy_cell",
            "quality_benchmark_results",
            ["genre", "scene_function", "run_id"],
            unique=False,
        )

    if not _has_table("quality_value_observations"):
        op.create_table(
            "quality_value_observations",
            sa.Column("observation_id", sa.String(), nullable=False),
            sa.Column("result_id", sa.String(), nullable=False),
            sa.Column("reviewer_ref", sa.String(), nullable=False),
            sa.Column("provenance", sa.String(), nullable=False),
            sa.Column("source_text_hash", sa.String(), nullable=True),
            sa.Column("edited_text_hash", sa.String(), nullable=True),
            sa.Column("human_edit_distance", sa.Integer(), nullable=True),
            sa.Column("human_edit_distance_ratio", sa.Float(), nullable=True),
            sa.Column("first_usable", sa.Boolean(), nullable=True),
            sa.Column("follow_read_intent", sa.Integer(), nullable=True),
            sa.Column("created_at", sa.String(), nullable=False),
            sa.CheckConstraint(
                "provenance = 'human'",
                name="ck_quality_value_observations_human_only",
            ),
            sa.CheckConstraint(
                "human_edit_distance IS NULL OR human_edit_distance >= 0",
                name="ck_quality_value_observations_edit_distance_nonnegative",
            ),
            sa.CheckConstraint(
                "human_edit_distance_ratio IS NULL OR "
                "(human_edit_distance_ratio >= 0 AND human_edit_distance_ratio <= 1)",
                name="ck_quality_value_observations_edit_ratio_range",
            ),
            sa.CheckConstraint(
                "follow_read_intent IS NULL OR "
                "(follow_read_intent >= 1 AND follow_read_intent <= 5)",
                name="ck_quality_value_observations_follow_read_range",
            ),
            sa.ForeignKeyConstraint(["result_id"], ["quality_benchmark_results.result_id"]),
            sa.PrimaryKeyConstraint("observation_id"),
            sa.UniqueConstraint(
                "result_id",
                "reviewer_ref",
                name="uq_quality_value_observation_result_reviewer",
            ),
        )
        op.create_index(
            "ix_quality_value_observations_result",
            "quality_value_observations",
            ["result_id"],
            unique=False,
        )


def downgrade() -> None:
    pair_columns = _columns("evaluation_pairs")
    for column_name in (
        "benchmark_case_id_hash",
        "control_benchmark_result_id",
        "treatment_benchmark_result_id",
        "scene_function",
    ):
        if column_name in pair_columns:
            with op.batch_alter_table("evaluation_pairs") as batch:
                batch.drop_column(column_name)

    experiment_columns = _columns("evaluation_experiments")
    for column_name in (
        "hidden_rubric_hash",
        "benchmark_manifest_hash",
        "benchmark_manifest_id",
    ):
        if column_name in experiment_columns:
            with op.batch_alter_table("evaluation_experiments") as batch:
                batch.drop_column(column_name)

    for table_name in (
        "quality_value_observations",
        "quality_benchmark_results",
        "quality_benchmark_runs",
        "quality_strategy_policies",
        "quality_benchmark_manifests",
    ):
        if _has_table(table_name):
            op.drop_table(table_name)
