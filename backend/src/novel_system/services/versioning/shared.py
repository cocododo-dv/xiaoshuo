from __future__ import annotations

import re
from datetime import UTC, datetime

from novel_system.db.models import utcnow


def now_iso() -> str:
    return utcnow()


def parse_iso_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    normalized = value.replace("Z", "+00:00")
    parsed = datetime.fromisoformat(normalized)
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def safe_identifier_fragment(value: str) -> str:
    normalized = re.sub(r"[^A-Za-z0-9_.-]+", "_", value).strip("_")
    return normalized or "item"


def collection_family_for_scope(object_type: str, scope: str, scope_ref_id: str | None) -> str:
    return f"{object_type}_{scope}_{scope_ref_id or 'global'}"


def collection_alias_for_row(collection_family: str, row_id: str) -> str:
    return f"{collection_family}__candidate__{row_id}"


def snapshot_version_for_row(row_id: str) -> str:
    return f"snapshot__{row_id}"


def embedding_version_for_row(row_id: str) -> str:
    return f"embed__{row_id}"
