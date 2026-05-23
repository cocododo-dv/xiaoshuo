"""create style_reference v1.1 schema (PR-1)

Revision ID: 20260523_0037
Revises: 20260523_0036
Create Date: 2026-05-23

PR-1 落地《风格参考模块重构执行手册 v1.1》§4.2 的 11 张新表。
表名前缀 `style_reference_*`,与旧 reference_* 表物理隔离。

幂等模式(沿用 20260419_0011_reference_learning.py 的 `if X not in tables:` 防御):
仓库的 0001_init_schema 会 `Base.metadata.create_all`,所以新 ORM 注册到 metadata
后,新启动的 db 在 0001 跑完时就已经有 11 张 style_reference_* 表了。本 migration
只在它们尚不存在时显式补建,保证从早期数据库一路 upgrade 过来的环境也能拿到表。
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260523_0037"
down_revision = "20260523_0036"
branch_labels = None
depends_on = None


_NEW_TABLES_DROP_ORDER = [
    "style_reference_banned_terms",
    "style_reference_validation_reports",
    "style_reference_injection_bindings",
    "style_reference_profiles",
    "style_reference_evidences",
    "style_reference_findings",
    "style_reference_quotes",
    "style_reference_extractions",
    "style_reference_runs",
    "style_reference_paragraphs",
    "style_reference_books",
]


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())

    if "style_reference_books" not in tables:
        op.create_table(
            "style_reference_books",
            sa.Column("book_id", sa.String(), nullable=False),
            sa.Column("title", sa.String(), nullable=False),
            sa.Column("author_label", sa.String(), nullable=True),
            sa.Column("source_kind", sa.String(), nullable=False),
            sa.Column("source_path", sa.Text(), nullable=True),
            sa.Column("cloud_policy", sa.String(), nullable=False),
            sa.Column("text_checksum", sa.String(), nullable=False),
            sa.Column("total_chars", sa.Integer(), nullable=False),
            sa.Column("status", sa.String(), nullable=False),
            sa.Column("stats_json", sa.JSON(), nullable=False),
            sa.Column("created_at", sa.String(), nullable=False),
            sa.Column("updated_at", sa.String(), nullable=False),
            sa.PrimaryKeyConstraint("book_id"),
            sa.UniqueConstraint("text_checksum", name="uq_style_reference_books_text_checksum"),
        )
        op.create_index(
            "ix_style_reference_books_status_updated_at",
            "style_reference_books",
            ["status", "updated_at"],
        )

    if "style_reference_paragraphs" not in tables:
        op.create_table(
            "style_reference_paragraphs",
            sa.Column("paragraph_id", sa.String(), nullable=False),
            sa.Column("book_id", sa.String(), nullable=False),
            sa.Column("paragraph_index", sa.Integer(), nullable=False),
            sa.Column("paragraph_type", sa.String(), nullable=False),
            sa.Column("start_offset", sa.Integer(), nullable=False),
            sa.Column("end_offset", sa.Integer(), nullable=False),
            sa.Column("text", sa.Text(), nullable=False),
            sa.Column("char_count", sa.Integer(), nullable=False),
            sa.Column("classifier_confidence", sa.Float(), nullable=False),
            sa.Column("created_at", sa.String(), nullable=False),
            sa.ForeignKeyConstraint(["book_id"], ["style_reference_books.book_id"]),
            sa.PrimaryKeyConstraint("paragraph_id"),
        )
        op.create_index(
            "ix_style_reference_paragraphs_book_type",
            "style_reference_paragraphs",
            ["book_id", "paragraph_type"],
        )
        op.create_index(
            "ix_style_reference_paragraphs_book_index",
            "style_reference_paragraphs",
            ["book_id", "paragraph_index"],
        )

    if "style_reference_runs" not in tables:
        op.create_table(
            "style_reference_runs",
            sa.Column("run_id", sa.String(), nullable=False),
            sa.Column("book_id", sa.String(), nullable=False),
            sa.Column("status", sa.String(), nullable=False),
            sa.Column("phase", sa.String(), nullable=False),
            sa.Column("coverage_json", sa.JSON(), nullable=False),
            sa.Column("started_at", sa.String(), nullable=True),
            sa.Column("finished_at", sa.String(), nullable=True),
            sa.Column("created_at", sa.String(), nullable=False),
            sa.Column("updated_at", sa.String(), nullable=False),
            sa.ForeignKeyConstraint(["book_id"], ["style_reference_books.book_id"]),
            sa.PrimaryKeyConstraint("run_id"),
        )
        op.create_index(
            "ix_style_reference_runs_book_status",
            "style_reference_runs",
            ["book_id", "status"],
        )

    if "style_reference_extractions" not in tables:
        op.create_table(
            "style_reference_extractions",
            sa.Column("extraction_id", sa.String(), nullable=False),
            sa.Column("book_id", sa.String(), nullable=False),
            sa.Column("run_id", sa.String(), nullable=False),
            sa.Column("layer", sa.String(), nullable=False),
            sa.Column("sub_dimension", sa.String(), nullable=False),
            sa.Column("llm_call_id", sa.String(), nullable=True),
            sa.Column("raw_payload_json", sa.JSON(), nullable=False),
            sa.Column("status", sa.String(), nullable=False),
            sa.Column("validation_errors_json", sa.JSON(), nullable=False),
            sa.Column("purpose", sa.String(), nullable=False),
            sa.Column("created_at", sa.String(), nullable=False),
            sa.Column("updated_at", sa.String(), nullable=False),
            sa.ForeignKeyConstraint(["book_id"], ["style_reference_books.book_id"]),
            sa.ForeignKeyConstraint(["run_id"], ["style_reference_runs.run_id"]),
            sa.PrimaryKeyConstraint("extraction_id"),
        )
        op.create_index(
            "ix_style_reference_extractions_book_layer_sub",
            "style_reference_extractions",
            ["book_id", "layer", "sub_dimension"],
        )
        op.create_index(
            "ix_style_reference_extractions_run_status",
            "style_reference_extractions",
            ["run_id", "status"],
        )

    if "style_reference_quotes" not in tables:
        op.create_table(
            "style_reference_quotes",
            sa.Column("quote_id", sa.String(), nullable=False),
            sa.Column("book_id", sa.String(), nullable=False),
            # paragraph_id 可空:支持 anchor_kind=counter_example 的合成 quote
            sa.Column("paragraph_id", sa.String(), nullable=True),
            sa.Column("span_start", sa.Integer(), nullable=False),
            sa.Column("span_end", sa.Integer(), nullable=False),
            sa.Column("quote_text", sa.Text(), nullable=False),
            sa.Column("illustrates_dims", sa.JSON(), nullable=False),
            sa.Column("extracted_features", sa.JSON(), nullable=False),
            sa.Column("created_at", sa.String(), nullable=False),
            sa.ForeignKeyConstraint(["book_id"], ["style_reference_books.book_id"]),
            sa.ForeignKeyConstraint(
                ["paragraph_id"], ["style_reference_paragraphs.paragraph_id"]
            ),
            sa.PrimaryKeyConstraint("quote_id"),
        )
        op.create_index(
            "ix_style_reference_quotes_book",
            "style_reference_quotes",
            ["book_id"],
        )

    if "style_reference_findings" not in tables:
        op.create_table(
            "style_reference_findings",
            sa.Column("finding_id", sa.String(), nullable=False),
            sa.Column("book_id", sa.String(), nullable=False),
            sa.Column("run_id", sa.String(), nullable=False),
            sa.Column("extraction_id", sa.String(), nullable=False),
            sa.Column("sub_dimension", sa.String(), nullable=False),
            sa.Column("finding_kind", sa.String(), nullable=False),
            sa.Column("statement", sa.Text(), nullable=False),
            sa.Column("confidence", sa.String(), nullable=False),
            sa.Column("status", sa.String(), nullable=False),
            sa.Column("review_id", sa.String(), nullable=True),
            sa.Column("created_at", sa.String(), nullable=False),
            sa.Column("updated_at", sa.String(), nullable=False),
            sa.ForeignKeyConstraint(["book_id"], ["style_reference_books.book_id"]),
            sa.ForeignKeyConstraint(["run_id"], ["style_reference_runs.run_id"]),
            sa.ForeignKeyConstraint(
                ["extraction_id"], ["style_reference_extractions.extraction_id"]
            ),
            sa.PrimaryKeyConstraint("finding_id"),
            sa.UniqueConstraint("review_id", name="uq_style_reference_findings_review_id"),
            sa.UniqueConstraint(
                "extraction_id",
                "sub_dimension",
                "finding_kind",
                name="uq_style_reference_findings_extract_sub_kind",
            ),
        )
        op.create_index(
            "ix_style_reference_findings_book_sub_kind",
            "style_reference_findings",
            ["book_id", "sub_dimension", "finding_kind"],
        )

    if "style_reference_evidences" not in tables:
        op.create_table(
            "style_reference_evidences",
            sa.Column("evidence_id", sa.String(), nullable=False),
            sa.Column("finding_id", sa.String(), nullable=False),
            sa.Column("quote_id", sa.String(), nullable=False),
            sa.Column("anchor_kind", sa.String(), nullable=False),
            sa.Column("is_synthetic", sa.Integer(), nullable=False),
            sa.Column("created_at", sa.String(), nullable=False),
            sa.ForeignKeyConstraint(
                ["finding_id"], ["style_reference_findings.finding_id"]
            ),
            sa.ForeignKeyConstraint(["quote_id"], ["style_reference_quotes.quote_id"]),
            sa.PrimaryKeyConstraint("evidence_id"),
            sa.UniqueConstraint(
                "finding_id", "quote_id", name="uq_style_reference_evidences_finding_quote"
            ),
        )

    if "style_reference_profiles" not in tables:
        op.create_table(
            "style_reference_profiles",
            sa.Column("profile_id", sa.String(), nullable=False),
            sa.Column("book_id", sa.String(), nullable=False),
            sa.Column("run_id", sa.String(), nullable=False),
            sa.Column("title", sa.String(), nullable=False),
            sa.Column("status", sa.String(), nullable=False),
            sa.Column("profile_json", sa.JSON(), nullable=False),
            sa.Column("coverage_json", sa.JSON(), nullable=False),
            sa.Column("source_finding_ids_json", sa.JSON(), nullable=False),
            sa.Column("version_tag", sa.String(), nullable=True),
            sa.Column("created_at", sa.String(), nullable=False),
            sa.Column("updated_at", sa.String(), nullable=False),
            sa.ForeignKeyConstraint(["book_id"], ["style_reference_books.book_id"]),
            sa.ForeignKeyConstraint(["run_id"], ["style_reference_runs.run_id"]),
            sa.PrimaryKeyConstraint("profile_id"),
        )
        op.create_index(
            "ix_style_reference_profiles_book_status",
            "style_reference_profiles",
            ["book_id", "status"],
        )
        op.create_index(
            "ix_style_reference_profiles_version_tag",
            "style_reference_profiles",
            ["version_tag"],
        )

    if "style_reference_injection_bindings" not in tables:
        op.create_table(
            "style_reference_injection_bindings",
            sa.Column("binding_id", sa.String(), nullable=False),
            sa.Column("profile_id", sa.String(), nullable=False),
            sa.Column("scope", sa.String(), nullable=False),
            sa.Column("scope_ref_id", sa.String(), nullable=True),
            sa.Column("task_type", sa.String(), nullable=False),
            sa.Column("strategy", sa.String(), nullable=False),
            sa.Column("config_json", sa.JSON(), nullable=False),
            sa.Column("status", sa.String(), nullable=False),
            sa.Column("created_at", sa.String(), nullable=False),
            sa.Column("updated_at", sa.String(), nullable=False),
            sa.ForeignKeyConstraint(
                ["profile_id"], ["style_reference_profiles.profile_id"]
            ),
            sa.PrimaryKeyConstraint("binding_id"),
        )
        op.create_index(
            "ix_style_reference_injection_bindings_profile_scope_ref",
            "style_reference_injection_bindings",
            ["profile_id", "scope", "scope_ref_id"],
        )
        op.create_index(
            "ix_style_reference_injection_bindings_task_type",
            "style_reference_injection_bindings",
            ["task_type"],
        )

    if "style_reference_validation_reports" not in tables:
        op.create_table(
            "style_reference_validation_reports",
            sa.Column("report_id", sa.String(), nullable=False),
            sa.Column("profile_id", sa.String(), nullable=False),
            sa.Column("target_kind", sa.String(), nullable=False),
            sa.Column("target_ref_id", sa.String(), nullable=True),
            sa.Column("verdict", sa.String(), nullable=False),
            sa.Column("quantitative_json", sa.JSON(), nullable=False),
            sa.Column("semantic_json", sa.JSON(), nullable=False),
            sa.Column("plagiarism_json", sa.JSON(), nullable=False),
            sa.Column("forbidden_hits_json", sa.JSON(), nullable=False),
            sa.Column("mode_executed", sa.String(), nullable=False),
            sa.Column("created_at", sa.String(), nullable=False),
            sa.ForeignKeyConstraint(
                ["profile_id"], ["style_reference_profiles.profile_id"]
            ),
            sa.PrimaryKeyConstraint("report_id"),
        )
        op.create_index(
            "ix_style_reference_validation_reports_profile_target",
            "style_reference_validation_reports",
            ["profile_id", "target_ref_id"],
        )
        op.create_index(
            "ix_style_reference_validation_reports_verdict",
            "style_reference_validation_reports",
            ["verdict"],
        )

    if "style_reference_banned_terms" not in tables:
        op.create_table(
            "style_reference_banned_terms",
            sa.Column("term_id", sa.String(), nullable=False),
            sa.Column("profile_id", sa.String(), nullable=False),
            sa.Column("term", sa.String(), nullable=False),
            sa.Column("replacement_hint", sa.String(), nullable=True),
            sa.Column("source", sa.String(), nullable=False),
            sa.Column("scope", sa.String(), nullable=False),
            sa.Column("created_at", sa.String(), nullable=False),
            sa.Column("updated_at", sa.String(), nullable=False),
            sa.ForeignKeyConstraint(
                ["profile_id"], ["style_reference_profiles.profile_id"]
            ),
            sa.PrimaryKeyConstraint("term_id"),
            sa.UniqueConstraint(
                "profile_id",
                "term",
                "scope",
                name="uq_style_reference_banned_terms_profile_term_scope",
            ),
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing = set(inspector.get_table_names())
    for table_name in _NEW_TABLES_DROP_ORDER:
        if table_name in existing:
            op.drop_table(table_name)
