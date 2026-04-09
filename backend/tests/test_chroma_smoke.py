from __future__ import annotations

from pathlib import Path

import pytest

from novel_system.tools.chroma_smoke import run_chroma_smoke

pytestmark = pytest.mark.chroma_integration


def test_chroma_smoke_round_trip(tmp_path: Path) -> None:
    result = run_chroma_smoke(tmp_path / "chroma-smoke")

    assert result["backend"] == "chroma"
    assert result["collection_exists"] is True
    assert result["query_ids"] == ["doc-1"]
