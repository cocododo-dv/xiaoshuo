from __future__ import annotations

from novel_system.services.versioning import (
    PromotionService,
    ReviewMaterializationService,
    RuntimeRecoveryService,
    VectorLifecycleService,
)
from novel_system.services.versioning.base import VersioningServiceBase


def test_lifecycle_entrypoints_live_on_concrete_services() -> None:
    assert "materialize_review" in ReviewMaterializationService.__dict__
    assert "run_reindex" in VectorLifecycleService.__dict__
    assert "run_verify" in VectorLifecycleService.__dict__
    assert "release_review" in PromotionService.__dict__
    assert "run_due_promotions" in PromotionService.__dict__
    assert "recover_stuck_jobs" in RuntimeRecoveryService.__dict__

    assert "materialize_review" not in VersioningServiceBase.__dict__
    assert "run_verify" not in VersioningServiceBase.__dict__
    assert "release_review" not in VersioningServiceBase.__dict__
    assert "run_due_promotions" not in VersioningServiceBase.__dict__
    assert "recover_stuck_jobs" not in VersioningServiceBase.__dict__
