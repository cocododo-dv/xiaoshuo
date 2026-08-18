"""Run one deterministic shard of the backend test-file suite."""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path


BACKEND_ROOT = Path(__file__).resolve().parents[1]
TESTS_ROOT = BACKEND_ROOT / "tests"


def select_shard(*, shard_index: int, shard_count: int) -> list[Path]:
    if shard_count < 1:
        raise ValueError("shard_count must be positive")
    if not 0 <= shard_index < shard_count:
        raise ValueError("shard_index must satisfy 0 <= index < count")
    files = sorted(TESTS_ROOT.glob("test_*.py"), key=lambda path: path.name)
    return [path for index, path in enumerate(files) if index % shard_count == shard_index]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--shard-index", type=int, required=True)
    parser.add_argument("--shard-count", type=int, required=True)
    parser.add_argument("--list-only", action="store_true")
    parser.add_argument("pytest_args", nargs=argparse.REMAINDER)
    args = parser.parse_args(argv)
    try:
        selected = select_shard(shard_index=args.shard_index, shard_count=args.shard_count)
    except ValueError as exc:
        parser.error(str(exc))
    if not selected:
        parser.error("selected shard contains no test files")
    if args.list_only:
        for path in selected:
            print(path.relative_to(BACKEND_ROOT).as_posix())
        return 0
    pytest_args = list(args.pytest_args)
    if pytest_args[:1] == ["--"]:
        pytest_args.pop(0)
    command = [
        sys.executable,
        "-m",
        "pytest",
        *pytest_args,
        *(str(path.relative_to(BACKEND_ROOT)) for path in selected),
    ]
    return subprocess.run(command, cwd=BACKEND_ROOT, check=False).returncode


if __name__ == "__main__":
    raise SystemExit(main())
