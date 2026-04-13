from __future__ import annotations

import os
import sqlite3
import subprocess
import sys
from pathlib import Path


def test_alembic_upgrade_respects_database_url_env(tmp_path: Path) -> None:
    repo_root = Path(__file__).resolve().parents[1]
    backend_dir = repo_root
    db_path = tmp_path / "alembic-runtime.sqlite"
    env = os.environ.copy()
    env["PYTHONPATH"] = str(backend_dir / "src")
    env["NOVEL_SYSTEM_DATABASE_URL"] = f"sqlite:///{db_path.as_posix()}"

    subprocess.run(
        [sys.executable, "-m", "alembic", "-c", str(backend_dir / "alembic.ini"), "upgrade", "head"],
        cwd=backend_dir,
        env=env,
        check=True,
    )

    connection = sqlite3.connect(db_path)
    try:
        columns = [row[1] for row in connection.execute("PRAGMA table_info(chapter_states)").fetchall()]
        chapter_goal_columns = [row[1] for row in connection.execute("PRAGMA table_info(chapter_goals)").fetchall()]
        scene_card_columns = [row[1] for row in connection.execute("PRAGMA table_info(scene_cards)").fetchall()]
        staged_backfill_exists = connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='staged_backfill'"
        ).fetchone()
    finally:
        connection.close()

    assert "manual_hold_reason" in columns
    assert "trashed_flag" in chapter_goal_columns
    assert "trashed_at" in chapter_goal_columns
    assert "trashed_by" in chapter_goal_columns
    assert "trashed_flag" in scene_card_columns
    assert "trashed_at" in scene_card_columns
    assert "trashed_by" in scene_card_columns
    assert staged_backfill_exists == ("staged_backfill",)
