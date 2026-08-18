"""Retire demo projects and offline-generation configuration.

Revision ID: 20260717_0074
Revises: 20260716_0073
Create Date: 2026-07-17

The migration is intentionally fail-closed: a database that still contains a
retired project marker must be cleaned before the marker column can be removed.
It never relabels fixture-owned rows as real author projects.
"""

from __future__ import annotations

import json
import hashlib
from typing import Any

import sqlalchemy as sa
from alembic import op


revision = "20260717_0074"
down_revision = "20260716_0073"
branch_labels = None
depends_on = None


_RETIRED_CONFIG_KEYS = frozenset(
    {
        "allow_offline_demo",
        "demo_disposable",
        "demo_mode",
        "demo_seed_confirm",
        "llm_offline_demo_enabled",
        "novel_system_allow_offline_demo",
        "novel_system_demo_seed_confirm",
        "offline_demo",
    }
)
_RETIRED_CONFIG_VALUE_MARKERS = ("demo_disposable", "offline_demo")
_REMOVED = object()
_RETIRED_PROJECT_ID_DIGESTS = frozenset(
    {
        "8a28929ac7f9a17e97a421ac2cd63ac73568ebe87bc0cee641a193d91c761577",
        "63479ad69a090b258277ec8fba6f99419a2ffb248981510657c944ccd1148e97",
        "a56cf003085fa58d656f8f6eda253b61ca9ef4d03e3644c4f059fd463b6181fa",
        "1a906b5a3c0053d5b9e643fd8ffbe5cb8deb4d58258939e774be17d5377b4f04",
    }
)


def _json_value(value: Any) -> Any:
    if isinstance(value, str):
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return value
    return value


def _scrub_retired_config(value: Any) -> Any:
    value = _json_value(value)
    if isinstance(value, dict):
        scrubbed: dict[Any, Any] = {}
        for key, item in value.items():
            if str(key).strip().lower() in _RETIRED_CONFIG_KEYS:
                continue
            clean_item = _scrub_retired_config(item)
            if clean_item is not _REMOVED:
                scrubbed[key] = clean_item
        return scrubbed
    if isinstance(value, list):
        scrubbed_items = [_scrub_retired_config(item) for item in value]
        return [item for item in scrubbed_items if item is not _REMOVED]
    if isinstance(value, str):
        normalized = value.strip().lower()
        if any(marker in normalized for marker in _RETIRED_CONFIG_VALUE_MARKERS):
            return _REMOVED
    return value


def _scrub_root(value: Any) -> Any:
    scrubbed = _scrub_retired_config(value)
    return {} if scrubbed is _REMOVED else scrubbed


def _scrub_config_snapshots(bind: sa.Connection) -> None:
    inspector = sa.inspect(bind)
    if "system_config_snapshots" not in inspector.get_table_names():
        return
    rows = bind.execute(
        sa.text(
            "SELECT snapshot_id, parsed_json, validation_json "
            "FROM system_config_snapshots"
        )
    ).mappings()
    for row in rows:
        parsed = _scrub_root(row["parsed_json"])
        validation = _scrub_root(row["validation_json"])
        bind.execute(
            sa.text(
                "UPDATE system_config_snapshots "
                "SET parsed_json = :parsed_json, validation_json = :validation_json, "
                "yaml_raw = :yaml_raw WHERE snapshot_id = :snapshot_id"
            ),
            {
                "snapshot_id": row["snapshot_id"],
                "parsed_json": json.dumps(parsed, ensure_ascii=False),
                "validation_json": json.dumps(validation, ensure_ascii=False),
                # JSON is valid YAML and avoids depending on the live serializer.
                "yaml_raw": json.dumps(parsed, ensure_ascii=False, indent=2),
            },
        )


def upgrade() -> None:
    bind = op.get_bind()
    _scrub_config_snapshots(bind)

    inspector = sa.inspect(bind)
    if "story_projects" not in inspector.get_table_names():
        return
    columns = {column["name"] for column in inspector.get_columns("story_projects")}
    if "is_demo" not in columns:
        return
    project_rows = bind.execute(
        sa.text("SELECT project_id, is_demo FROM story_projects")
    ).mappings()
    retired_rows = sum(
        1
        for row in project_rows
        if int(row["is_demo"] or 0) != 0
        or hashlib.sha256(str(row["project_id"]).encode("utf-8")).hexdigest()
        in _RETIRED_PROJECT_ID_DIGESTS
    )
    if retired_rows:
        raise RuntimeError(
            "retired demo project rows remain; purge them before upgrading to 20260717_0074"
        )
    with op.batch_alter_table("story_projects") as batch_op:
        batch_op.drop_column("is_demo")


def downgrade() -> None:
    raise RuntimeError(
        "20260717_0074 is intentionally irreversible: the retired demo identity "
        "column and generation switches must not be reintroduced"
    )

