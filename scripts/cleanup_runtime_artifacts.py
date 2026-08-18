"""Conservatively prune reproducible files from ``.codex-run``.

Database files, backups, migration rehearsals, QA evidence directories and the
workspace encryption secret are intentionally outside the candidate set.
"""

from __future__ import annotations

import argparse
import json
import shutil
import time
from pathlib import Path


REPRODUCIBLE_DIRECTORIES = frozenset(
    {
        "pip-lock-verify",
        "uv-lock-verify",
        "e2e",
        "e2e-linux",
    }
)
REPRODUCIBLE_FILE_SUFFIXES = frozenset({".log", ".pid"})


def _newest_mtime(path: Path) -> float:
    newest = path.stat().st_mtime
    if path.is_dir():
        for child in path.rglob("*"):
            try:
                newest = max(newest, child.stat().st_mtime)
            except FileNotFoundError:
                continue
    return newest


def cleanup_runtime_artifacts(
    run_dir: Path,
    *,
    retention_days: int,
    apply: bool,
    now: float | None = None,
) -> dict[str, object]:
    root = run_dir.resolve()
    if retention_days < 1:
        raise ValueError("retention_days must be at least 1")
    cutoff = (time.time() if now is None else now) - retention_days * 86400
    removed: list[str] = []
    reclaimable_bytes = 0
    if not root.exists():
        return {"run_dir": str(root), "apply": apply, "removed": removed, "reclaimable_bytes": 0}

    candidates = [
        child
        for child in root.iterdir()
        if (child.is_dir() and child.name in REPRODUCIBLE_DIRECTORIES)
        or (child.is_file() and child.suffix.lower() in REPRODUCIBLE_FILE_SUFFIXES)
    ]
    for candidate in sorted(candidates, key=lambda path: path.name):
        resolved = candidate.resolve()
        if resolved.parent != root or _newest_mtime(resolved) > cutoff:
            continue
        size = (
            sum(item.stat().st_size for item in resolved.rglob("*") if item.is_file())
            if resolved.is_dir()
            else resolved.stat().st_size
        )
        reclaimable_bytes += size
        removed.append(resolved.name)
        if not apply:
            continue
        if resolved.is_dir():
            shutil.rmtree(resolved)
        else:
            resolved.unlink()
    return {
        "run_dir": str(root),
        "apply": apply,
        "retention_days": retention_days,
        "removed": removed,
        "reclaimable_bytes": reclaimable_bytes,
    }


def main() -> int:
    repository_root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-dir", type=Path, default=repository_root / ".codex-run")
    parser.add_argument("--retention-days", type=int, default=14)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    result = cleanup_runtime_artifacts(
        args.run_dir,
        retention_days=args.retention_days,
        apply=args.apply,
    )
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
