from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
CLEANUP_SCRIPT = REPOSITORY_ROOT / "scripts" / "cleanup_runtime_artifacts.py"


def test_cleanup_removes_only_expired_reproducible_artifacts(tmp_path: Path) -> None:
    run_dir = tmp_path / ".codex-run"
    old_cache = run_dir / "pip-lock-verify"
    old_cache.mkdir(parents=True)
    (old_cache / "package.whl").write_bytes(b"cache")
    old_log = run_dir / "old-test.log"
    old_log.write_text("log", encoding="utf-8")
    backup = run_dir / "backups" / "novel-system.db"
    backup.parent.mkdir()
    backup.write_bytes(b"database")
    secret = run_dir / "config.secret"
    secret.write_text("secret", encoding="utf-8")
    old_time = time.time() - 30 * 86400
    for path in (old_cache / "package.whl", old_cache, old_log, backup, backup.parent, secret):
        os.utime(path, (old_time, old_time))

    completed = subprocess.run(
        [
            sys.executable,
            str(CLEANUP_SCRIPT),
            "--run-dir",
            str(run_dir),
            "--retention-days",
            "14",
            "--apply",
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    result = json.loads(completed.stdout)
    assert result["removed"] == ["old-test.log", "pip-lock-verify"]
    assert not old_cache.exists()
    assert not old_log.exists()
    assert backup.read_bytes() == b"database"
    assert secret.read_text(encoding="utf-8") == "secret"
