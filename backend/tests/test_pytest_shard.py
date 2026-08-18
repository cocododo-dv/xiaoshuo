from __future__ import annotations

from pathlib import Path

import pytest

from scripts import pytest_shard


def _make_test_files(root: Path, count: int) -> list[Path]:
    files = []
    for index in reversed(range(count)):
        path = root / f"test_{index:02d}.py"
        path.write_text("", encoding="utf-8")
        files.append(path)
    (root / "helper.py").write_text("", encoding="utf-8")
    return sorted(files, key=lambda path: path.name)


def test_shards_cover_every_test_file_once(monkeypatch, tmp_path: Path) -> None:
    expected = _make_test_files(tmp_path, 11)
    monkeypatch.setattr(pytest_shard, "TESTS_ROOT", tmp_path)

    shards = [
        pytest_shard.select_shard(shard_index=index, shard_count=4)
        for index in range(4)
    ]

    assert sorted(path for shard in shards for path in shard) == expected
    assert sum(len(set(shard)) for shard in shards) == len(expected)
    assert all(set(left).isdisjoint(right) for i, left in enumerate(shards) for right in shards[i + 1 :])


@pytest.mark.parametrize(
    ("index", "count"),
    [(0, 0), (-1, 4), (4, 4)],
)
def test_invalid_shard_parameters_fail(index: int, count: int) -> None:
    with pytest.raises(ValueError):
        pytest_shard.select_shard(shard_index=index, shard_count=count)
