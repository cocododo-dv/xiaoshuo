from __future__ import annotations

import json
from pathlib import Path

from novel_system.contracts.bundle import BundleSnapshotHashProjection
from novel_system.services.hash_engine import compute_bundle_hash_projection


def test_bundle_hash_matches_golden_vector() -> None:
    fixture_path = Path(__file__).parent / "fixtures" / "bundle_hash_projection.json"
    payload = BundleSnapshotHashProjection.model_validate(
        json.loads(fixture_path.read_text(encoding="utf-8"))
    )

    assert compute_bundle_hash_projection(payload) == (
        "311c57097d809b81a6ece39943041c3b412e3ab67ab3efd2d5619498d4ef96a4"
    )
