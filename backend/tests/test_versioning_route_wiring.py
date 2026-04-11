from __future__ import annotations

from novel_system.api.routes import indexing as indexing_routes
from novel_system.api.routes import review as review_routes


def test_approve_review_route_uses_review_materialization_service(client, monkeypatch) -> None:
    called: dict[str, object] = {}

    class FakeService:
        def __init__(self, session) -> None:
            called["session"] = session

        def materialize_review(self, review_id: str) -> dict:
            called["review_id"] = review_id
            return {"review_id": review_id, "materialize_status": "succeeded"}

    class LegacyBomb:
        def __init__(self, *_args, **_kwargs) -> None:
            raise AssertionError("legacy VersionManager route dependency used")

    monkeypatch.setattr(review_routes, "ReviewMaterializationService", FakeService, raising=False)
    monkeypatch.setattr(review_routes, "VersionManager", LegacyBomb, raising=False)

    response = client.post(
        "/api/v1/review-items/review_route_materialize/approve",
        headers={"X-Idempotency-Key": "route-materialize-service"},
    )

    assert response.status_code == 200
    assert response.json()["data"] == {
        "actor_ref": "operator",
        "review_id": "review_route_materialize",
        "materialize_status": "succeeded",
    }
    assert called["review_id"] == "review_route_materialize"


def test_release_review_route_uses_promotion_service(client, monkeypatch) -> None:
    called: dict[str, object] = {}

    class FakeService:
        def __init__(self, session) -> None:
            called["session"] = session

        def release_review(self, review_id: str) -> dict:
            called["review_id"] = review_id
            return {"review_id": review_id, "released": True}

    class LegacyBomb:
        def __init__(self, *_args, **_kwargs) -> None:
            raise AssertionError("legacy VersionManager route dependency used")

    monkeypatch.setattr(review_routes, "PromotionService", FakeService, raising=False)
    monkeypatch.setattr(review_routes, "VersionManager", LegacyBomb, raising=False)

    response = client.post(
        "/api/v1/review-items/review_route_release/release",
        headers={"X-Idempotency-Key": "route-release-service"},
    )

    assert response.status_code == 200
    assert response.json()["data"] == {
        "actor_ref": "operator",
        "review_id": "review_route_release",
        "released": True,
    }
    assert called["review_id"] == "review_route_release"


def test_retry_verify_route_uses_vector_lifecycle_service(client, monkeypatch) -> None:
    called: dict[str, object] = {}

    class FakeService:
        def __init__(self, session) -> None:
            called["session"] = session

        def run_verify(self, job_id: str) -> dict:
            called["job_id"] = job_id
            return {"job_id": job_id, "status": "succeeded", "alias_scope": "style_observation:global:global"}

    class LegacyBomb:
        def __init__(self, *_args, **_kwargs) -> None:
            raise AssertionError("legacy VersionManager route dependency used")

    monkeypatch.setattr(indexing_routes, "VectorLifecycleService", FakeService, raising=False)
    monkeypatch.setattr(indexing_routes, "VersionManager", LegacyBomb, raising=False)

    response = client.post(
        "/api/v1/index/verify/verify_route_job/retry",
        headers={"X-Idempotency-Key": "route-verify-service"},
    )

    assert response.status_code == 200
    assert response.json()["data"] == {
        "actor_ref": "operator",
        "job_id": "verify_route_job",
        "status": "succeeded",
        "alias_scope": "style_observation:global:global",
    }
    assert called["job_id"] == "verify_route_job"


def test_recovery_sweep_route_uses_runtime_recovery_service(client, monkeypatch) -> None:
    called: dict[str, object] = {}

    class FakeService:
        def __init__(self, session) -> None:
            called["session"] = session

        def recover_stuck_jobs(self) -> dict:
            called["called"] = True
            return {"reclaimed_jobs": 1, "created_human_review_events": 0}

    class LegacyBomb:
        def __init__(self, *_args, **_kwargs) -> None:
            raise AssertionError("legacy VersionManager route dependency used")

    monkeypatch.setattr(indexing_routes, "RuntimeRecoveryService", FakeService, raising=False)
    monkeypatch.setattr(indexing_routes, "VersionManager", LegacyBomb, raising=False)

    response = client.post(
        "/api/v1/runtime/recovery/sweep",
        headers={"X-Idempotency-Key": "route-recovery-service"},
    )

    assert response.status_code == 200
    assert response.json()["data"] == {
        "actor_ref": "operator",
        "reclaimed_jobs": 1,
        "created_human_review_events": 0,
    }
    assert called["called"] is True


def test_run_due_promotions_route_uses_promotion_service(client, monkeypatch) -> None:
    called: dict[str, object] = {}

    class FakeService:
        def __init__(self, session) -> None:
            called["session"] = session

        def run_due_promotions(self) -> dict:
            called["called"] = True
            return {"promoted": 2, "promoted_review_ids": ["review_a", "review_b"]}

    class LegacyBomb:
        def __init__(self, *_args, **_kwargs) -> None:
            raise AssertionError("legacy VersionManager route dependency used")

    monkeypatch.setattr(indexing_routes, "PromotionService", FakeService, raising=False)
    monkeypatch.setattr(indexing_routes, "VersionManager", LegacyBomb, raising=False)

    response = client.post(
        "/api/v1/runtime/promotions/run-due",
        headers={"X-Idempotency-Key": "route-promotions-service"},
    )

    assert response.status_code == 200
    assert response.json()["data"] == {
        "actor_ref": "operator",
        "promoted": 2,
        "promoted_review_ids": ["review_a", "review_b"],
    }
    assert called["called"] is True
