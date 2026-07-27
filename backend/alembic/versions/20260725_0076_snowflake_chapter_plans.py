"""Give the snowflake pipeline a real chapter table (Phase 2 of the chaptering redesign).

Revision ID: 20260725_0076
Revises: 20260725_0075
Create Date: 2026-07-25

Before this, "章" had no owner anywhere in the pipeline: steps 9/10 carry no chapter
field, the scene-list prompt tells the model to leave ``chapter_id`` empty because
"the server assigns identities", and the server's starting value was literally
``{project_id}_CH01`` with author input discarded — so a 24-scene book materialized
into one chapter. The only place chapters were actually authored (step 7, 长篇大纲)
was stored as four free-text paragraphs and never read at materialization.

``snowflake_chapter_plans`` makes the chapter a first-class planning row with a stable
``row_uid`` anchor (the same P1-1 lesson scene plans already learned), and
``snowflake_scene_plans.chapter_plan_id`` becomes the author-owned membership link.

``snowflake_scene_plans.spine`` closes a second hole: the author marks 灾一/灾二/灾三
on scenes in step 9, but ``canonFromFE("scenes")`` never sent it and ``feFromCanon``
hard-coded it back to ``""`` — so those marks were wiped on every hydrate. The
spine-anchor chaptering strategy needs them, so they now round-trip.

No data backfill here on purpose: deriving chapter rows from an existing
``long_synopsis`` draft (or from already-materialized ``ChapterGoal`` rows) is real
logic with real edge cases, so it lives in
``SnowflakeChapteringService.ensure_chapter_plans`` where it is testable and
re-runnable, not frozen into a migration.

Reversible: ``downgrade`` drops the table and the two columns. Author-assigned
chapter membership is lost on downgrade (it lives only in these columns), but no
already-materialized ``ChapterGoal`` / ``SceneCard`` row is touched either way.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260725_0076"
down_revision = "20260725_0075"
branch_labels = None
depends_on = None

_TABLE = "snowflake_chapter_plans"
_ROW_UID_INDEX = "ix_snowflake_chapter_plans_row_uid"
_SEQ_INDEX = "ix_snowflake_chapter_plans_seq"
_SCENE_COLUMNS = (
    ("chapter_plan_id", sa.String()),
    ("spine", sa.String()),
)


def upgrade() -> None:
    # 0001 init_schema 通过 Base.metadata.create_all 建当前全部模型表 — inspector 守卫；
    # 新库跑迁移链时表/列/索引已由 create_all 以完整定义建好，历史库才需要补。
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())

    if _TABLE not in tables:
        op.create_table(
            _TABLE,
            sa.Column("chapter_plan_id", sa.String(), primary_key=True),
            sa.Column("project_id", sa.String(), sa.ForeignKey("story_projects.project_id"), nullable=False),
            sa.Column("row_uid", sa.String(), nullable=False),
            sa.Column("chapter_seq", sa.Integer(), nullable=False, server_default="1"),
            sa.Column("act", sa.Integer(), nullable=False, server_default="1"),
            sa.Column("title", sa.String(), nullable=True),
            sa.Column("summary", sa.Text(), nullable=True),
            sa.Column("spine", sa.String(), nullable=True),
            sa.Column("chapter_goal", sa.Text(), nullable=True),
            sa.Column("status", sa.String(), nullable=False, server_default="draft"),
            sa.Column("source_step_run_id", sa.String(), nullable=True),
            sa.Column("removed_at", sa.String(), nullable=True),
            sa.Column("removed_by", sa.String(), nullable=True),
            sa.Column("created_at", sa.String(), nullable=False),
            sa.Column("updated_at", sa.String(), nullable=False),
        )

    existing_indexes = {idx["name"] for idx in sa.inspect(bind).get_indexes(_TABLE)}
    if _ROW_UID_INDEX not in existing_indexes:
        op.create_index(_ROW_UID_INDEX, _TABLE, ["project_id", "row_uid"], unique=True)
    if _SEQ_INDEX not in existing_indexes:
        op.create_index(_SEQ_INDEX, _TABLE, ["project_id", "chapter_seq"])

    if "snowflake_scene_plans" in tables:
        scene_columns = {col["name"] for col in inspector.get_columns("snowflake_scene_plans")}
        for name, column_type in _SCENE_COLUMNS:
            if name not in scene_columns:
                op.add_column("snowflake_scene_plans", sa.Column(name, column_type, nullable=True))


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())

    if "snowflake_scene_plans" in tables:
        scene_columns = {col["name"] for col in inspector.get_columns("snowflake_scene_plans")}
        with op.batch_alter_table("snowflake_scene_plans") as batch:
            for name, _type in reversed(_SCENE_COLUMNS):
                if name in scene_columns:
                    batch.drop_column(name)

    if _TABLE in tables:
        existing_indexes = {idx["name"] for idx in inspector.get_indexes(_TABLE)}
        if _SEQ_INDEX in existing_indexes:
            op.drop_index(_SEQ_INDEX, table_name=_TABLE)
        if _ROW_UID_INDEX in existing_indexes:
            op.drop_index(_ROW_UID_INDEX, table_name=_TABLE)
        op.drop_table(_TABLE)
