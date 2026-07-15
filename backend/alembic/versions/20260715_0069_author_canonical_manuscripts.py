"""Author-draft canonical promotion provenance and narrative-sync pointers.

Revision ID: 20260715_0069
Revises: 20260715_0068
Create Date: 2026-07-15
"""

from __future__ import annotations

import hashlib

import sqlalchemy as sa
from alembic import op


revision = "20260715_0069"
down_revision = "20260715_0068"
branch_labels = None
depends_on = None


def _columns(table_name: str) -> set[str]:
    inspector = sa.inspect(op.get_bind())
    if not inspector.has_table(table_name):
        return set()
    return {str(column["name"]) for column in inspector.get_columns(table_name)}


def upgrade() -> None:
    bind = op.get_bind()

    author_columns = _columns("author_drafts")
    if author_columns:
        if "last_promoted_revision_no" not in author_columns:
            op.add_column("author_drafts", sa.Column("last_promoted_revision_no", sa.Integer(), nullable=True))
        if "last_promoted_final_scene_row_id" not in author_columns:
            op.add_column(
                "author_drafts",
                sa.Column("last_promoted_final_scene_row_id", sa.String(), nullable=True),
            )

    final_columns = _columns("final_scenes")
    if final_columns:
        additions = (
            ("content_hash", sa.Column("content_hash", sa.String(), nullable=True)),
            (
                "source_kind",
                sa.Column("source_kind", sa.String(), nullable=False, server_default="generation"),
            ),
            ("source_author_draft_id", sa.Column("source_author_draft_id", sa.String(), nullable=True)),
            (
                "source_author_draft_revision_no",
                sa.Column("source_author_draft_revision_no", sa.Integer(), nullable=True),
            ),
            ("parent_final_scene_row_id", sa.Column("parent_final_scene_row_id", sa.String(), nullable=True)),
            (
                "superseded_by_final_scene_row_id",
                sa.Column("superseded_by_final_scene_row_id", sa.String(), nullable=True),
            ),
            (
                "created_by",
                sa.Column("created_by", sa.String(), nullable=False, server_default="system"),
            ),
        )
        for name, column in additions:
            if name not in final_columns:
                op.add_column("final_scenes", column)

        # SQLite has no built-in sha256 function. Backfill through the migration
        # connection so every legacy FinalScene has stable content identity.
        rows = bind.execute(sa.text("SELECT row_id, content FROM final_scenes WHERE content_hash IS NULL")).all()
        for row_id, content in rows:
            digest = hashlib.sha256(str(content or "").encode("utf-8")).hexdigest()
            bind.execute(
                sa.text("UPDATE final_scenes SET content_hash = :digest WHERE row_id = :row_id"),
                {"digest": digest, "row_id": row_id},
            )

    state_columns = _columns("scene_run_states")
    if state_columns:
        if "narrative_sync_status" not in state_columns:
            op.add_column(
                "scene_run_states",
                sa.Column("narrative_sync_status", sa.String(), nullable=False, server_default="synced"),
            )
        if "narrative_sync_final_scene_row_id" not in state_columns:
            op.add_column(
                "scene_run_states",
                sa.Column("narrative_sync_final_scene_row_id", sa.String(), nullable=True),
            )
        bind.execute(
            sa.text(
                "UPDATE scene_run_states "
                "SET narrative_sync_status = 'synced', "
                "narrative_sync_final_scene_row_id = current_final_scene_row_id "
                "WHERE current_final_scene_row_id IS NOT NULL "
                "AND narrative_sync_final_scene_row_id IS NULL"
            )
        )


def downgrade() -> None:
    state_columns = _columns("scene_run_states")
    if state_columns:
        with op.batch_alter_table("scene_run_states") as batch:
            if "narrative_sync_final_scene_row_id" in state_columns:
                batch.drop_column("narrative_sync_final_scene_row_id")
            if "narrative_sync_status" in state_columns:
                batch.drop_column("narrative_sync_status")

    final_columns = _columns("final_scenes")
    if final_columns:
        with op.batch_alter_table("final_scenes") as batch:
            for name in (
                "created_by",
                "superseded_by_final_scene_row_id",
                "parent_final_scene_row_id",
                "source_author_draft_revision_no",
                "source_author_draft_id",
                "source_kind",
                "content_hash",
            ):
                if name in final_columns:
                    batch.drop_column(name)

    author_columns = _columns("author_drafts")
    if author_columns:
        with op.batch_alter_table("author_drafts") as batch:
            if "last_promoted_final_scene_row_id" in author_columns:
                batch.drop_column("last_promoted_final_scene_row_id")
            if "last_promoted_revision_no" in author_columns:
                batch.drop_column("last_promoted_revision_no")
