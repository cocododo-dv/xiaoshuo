"""hot-path indexes for per-scene/per-chapter runtime tables (audit P-9)

编排/QC/归档热路径按 scene_id / chapter_id 反查 scene_drafts、final_scenes、
qc_reports、llm_calls、attempt_tracker、scene_bundles、human_review_events、
scene_memories、chapter_memories、review_items——这些列此前既无 FK 也无索引
（SQLite 不给 FK 自建索引），行数随长篇线性增长后全表扫描。

索引名与 ORM ``__table_args__`` 中的声明一一对应（schema 漂移守卫
test_metadata_isolation 会 diff 两侧的命名索引）。

Revision ID: 20260702_0060
Revises: 20260618_0059
Create Date: 2026-07-02
"""
from alembic import op
import sqlalchemy as sa

revision = "20260702_0060"
down_revision = "20260618_0059"
branch_labels = None
depends_on = None


_INDEXES: list[tuple[str, str, list[str]]] = [
    ("ix_scene_drafts_scene", "scene_drafts", ["scene_id"]),
    ("ix_final_scenes_scene", "final_scenes", ["scene_id"]),
    ("ix_final_scenes_chapter", "final_scenes", ["chapter_id"]),
    ("ix_qc_reports_scene", "qc_reports", ["scene_id"]),
    ("ix_llm_calls_scene_created", "llm_calls", ["scene_id", "created_at"]),
    ("ix_attempt_tracker_scene", "attempt_tracker", ["scene_id"]),
    ("ix_scene_bundles_scene", "scene_bundles", ["scene_id"]),
    ("ix_human_review_events_scene", "human_review_events", ["scene_id"]),
    ("ix_human_review_events_status", "human_review_events", ["status"]),
    ("ix_review_items_project_state", "review_items", ["project_id", "state"]),
    ("ix_review_items_scene", "review_items", ["scene_id"]),
    ("ix_scene_memories_scene", "scene_memories", ["scene_id"]),
    ("ix_scene_memories_chapter", "scene_memories", ["chapter_id"]),
    ("ix_chapter_memories_chapter", "chapter_memories", ["chapter_id"]),
]


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    for index_name, table_name, columns in _INDEXES:
        if not inspector.has_table(table_name):
            continue
        existing = {index["name"] for index in inspector.get_indexes(table_name)}
        if index_name not in existing:
            op.create_index(index_name, table_name, columns)


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    for index_name, table_name, _columns in reversed(_INDEXES):
        if not inspector.has_table(table_name):
            continue
        existing = {index["name"] for index in inspector.get_indexes(table_name)}
        if index_name in existing:
            op.drop_index(index_name, table_name=table_name)
