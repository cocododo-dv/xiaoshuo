"""Database bootstrap settings with no dependency on services or ORM modules."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


BACKEND_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DATABASE_PATH = BACKEND_ROOT / "novel_system.db"


@dataclass(frozen=True, slots=True)
class DatabaseRuntime:
    database_url: str
    sqlite_foreign_keys_enabled: bool


def load_database_runtime() -> DatabaseRuntime:
    return DatabaseRuntime(
        database_url=os.environ.get(
            "NOVEL_SYSTEM_DATABASE_URL",
            f"sqlite:///{DEFAULT_DATABASE_PATH.as_posix()}",
        ),
        sqlite_foreign_keys_enabled=_strict_bool_env(
            "NOVEL_SYSTEM_SQLITE_FOREIGN_KEYS_ENABLED",
            True,
        ),
    )


def _strict_bool_env(name: str, default: bool) -> bool:
    raw_value = os.environ.get(name)
    if raw_value is None:
        return default
    normalized = raw_value.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise ValueError(f"{name} must be a boolean (1/0, true/false, yes/no, on/off)")
