from __future__ import annotations

import json
from pathlib import Path

from novel_system.contracts.bundle import BundleSnapshotHashProjection
from novel_system.services.hash_engine import (
    compute_bundle_hash_projection,
    verify_bundle_snapshot_hash,
)


def test_bundle_hash_matches_golden_vector() -> None:
    fixture_path = Path(__file__).parent / "fixtures" / "bundle_hash_projection.json"
    payload = BundleSnapshotHashProjection.model_validate(
        json.loads(fixture_path.read_text(encoding="utf-8"))
    )

    assert compute_bundle_hash_projection(payload) == (
        "311c57097d809b81a6ece39943041c3b412e3ab67ab3efd2d5619498d4ef96a4"
    )


def test_bundle_snapshot_verifier_uses_the_published_projection() -> None:
    fixture_path = Path(__file__).parent / "fixtures" / "bundle_hash_projection.json"
    snapshot = json.loads(fixture_path.read_text(encoding="utf-8"))
    expected_hash = "311c57097d809b81a6ece39943041c3b412e3ab67ab3efd2d5619498d4ef96a4"
    snapshot["scene_id"] = "envelope-only-scene"
    snapshot["chapter_id"] = "envelope-only-chapter"

    valid = verify_bundle_snapshot_hash(snapshot, expected_hash=expected_hash)
    snapshot["inline_digests"] = {
        **snapshot["inline_digests"],
        "author_instruction": "tampered",
    }
    invalid = verify_bundle_snapshot_hash(snapshot, expected_hash=expected_hash)

    assert valid == {
        "valid": True,
        "error_code": None,
        "expected_hash": expected_hash,
        "computed_hash": expected_hash,
    }
    assert invalid["valid"] is False
    assert invalid["error_code"] == "bundle_hash_mismatch"
