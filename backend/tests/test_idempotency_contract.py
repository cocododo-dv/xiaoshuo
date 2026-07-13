from __future__ import annotations

from datetime import UTC, datetime, timedelta
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier, Lock

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session as SqlAlchemySession

from novel_system.db.models import IdempotencyKey
from novel_system.db.session import SessionLocal
from novel_system.services.errors import DomainError
from novel_system.services.idempotency import (
    IdempotencyLeaseService,
    canonical_request_hash,
    execute_with_idempotency,
)


def chapter_payload(goal: str) -> dict:
    return {
        "chapter_id": "CH001",
        "planned_scene_count": 3,
        "chapter_goal": goal,
        "main_plot_push": "推进重逢线索",
        "emotional_target": "紧张试探",
        "ending_effect": "以余波收束",
    }


def test_post_requires_idempotency_header(client) -> None:
    response = client.post("/api/v1/chapters", json=chapter_payload("目标一"))

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "IDEMPOTENCY_KEY_REQUIRED"


def test_same_key_same_payload_is_replayed(client) -> None:
    payload = chapter_payload("目标一")
    first = client.post(
        "/api/v1/chapters",
        json=payload,
        headers={"X-Idempotency-Key": "chapter-create-1"},
    )
    second = client.post(
        "/api/v1/chapters",
        json=payload,
        headers={"X-Idempotency-Key": "chapter-create-1"},
    )

    assert first.status_code == 200
    assert second.status_code == 200
    assert second.headers["X-Idempotency-Status"] == "replayed"


def test_same_key_different_payload_is_rejected(client) -> None:
    first = client.post(
        "/api/v1/chapters",
        json=chapter_payload("目标一"),
        headers={"X-Idempotency-Key": "chapter-create-2"},
    )
    second = client.post(
        "/api/v1/chapters",
        json=chapter_payload("目标二"),
        headers={"X-Idempotency-Key": "chapter-create-2"},
    )

    assert first.status_code == 200
    assert second.status_code == 409
    assert second.json()["error"]["code"] == "IDEMPOTENCY_KEY_REUSED_WITH_DIFFERENT_PAYLOAD"


def test_concurrent_same_key_insert_is_reported_as_in_progress(session, monkeypatch) -> None:
    def raise_duplicate_key() -> None:
        raise IntegrityError("INSERT INTO idempotency_keys", {}, Exception("duplicate key"))

    monkeypatch.setattr(session, "flush", raise_duplicate_key)

    with pytest.raises(DomainError) as exc_info:
        execute_with_idempotency(
            session,
            idempotency_key="chapter-create-race",
            method="POST",
            path_template="/api/v1/chapters",
            payload=chapter_payload("race"),
            action=lambda: {"created": True},
        )

    assert exc_info.value.code == "IDEMPOTENCY_REQUEST_IN_PROGRESS"
    assert exc_info.value.status_code == 409
    assert exc_info.value.details["retryable"] is True


def test_failed_idempotent_action_reenters_with_same_execution_and_new_attempt(session) -> None:
    seen: list[tuple[str, int]] = []

    def fail(lease) -> dict:  # noqa: ANN001
        seen.append((lease.execution_id, lease.attempt_no))
        raise DomainError("SIMULATED_FAILURE", "fail after a durable checkpoint")

    with pytest.raises(DomainError, match="fail after a durable checkpoint"):
        execute_with_idempotency(
            session,
            idempotency_key="retry-same-execution",
            method="POST",
            path_template="/api/v1/scenes/{scene_id}/run/full",
            payload={"scene_id": "SC01"},
            action=fail,
            worker_id="worker-a",
        )

    result, replay = execute_with_idempotency(
        session,
        idempotency_key="retry-same-execution",
        method="POST",
        path_template="/api/v1/scenes/{scene_id}/run/full",
        payload={"scene_id": "SC01"},
        action=lambda lease: seen.append((lease.execution_id, lease.attempt_no)) or {"ok": True},
        worker_id="worker-b",
    )

    assert result["ok"] is True
    assert replay is None
    assert seen == [
        ("idempotency:retry-same-execution", 1),
        ("idempotency:retry-same-execution", 2),
    ]


def test_active_idempotency_lease_is_not_reclaimed_by_another_worker(session) -> None:
    request_hash = canonical_request_hash("POST", "/run", {"scene_id": "SC01"})
    first = IdempotencyLeaseService(session).claim(
        idempotency_key="active-lease",
        request_hash=request_hash,
        worker_id="worker-a",
        lease_seconds=30,
    )
    session.commit()

    other = SessionLocal()
    try:
        with pytest.raises(DomainError) as exc_info:
            IdempotencyLeaseService(other).claim(
                idempotency_key="active-lease",
                request_hash=request_hash,
                worker_id="worker-b",
                lease_seconds=30,
            )
        assert exc_info.value.code == "IDEMPOTENCY_REQUEST_IN_PROGRESS"
    finally:
        other.close()

    assert first.worker_id == "worker-a"
    assert first.attempt_no == 1


def test_expired_idempotency_lease_has_one_cas_reclaim_winner(session) -> None:
    request_hash = canonical_request_hash("POST", "/run", {"scene_id": "SC01"})
    expired = (datetime.now(UTC) - timedelta(seconds=5)).isoformat()
    session.add(
        IdempotencyKey(
            idempotency_key="expired-lease",
            request_hash=request_hash,
            status="started",
            worker_id="dead-worker",
            attempt_no=1,
            heartbeat_at=expired,
            lease_expires_at=expired,
        )
    )
    session.commit()

    contender_a = SessionLocal()
    contender_b = SessionLocal()
    try:
        winner = IdempotencyLeaseService(contender_a).claim(
            idempotency_key="expired-lease",
            request_hash=request_hash,
            worker_id="worker-a",
            lease_seconds=30,
        )
        contender_a.commit()
        with pytest.raises(DomainError) as loser:
            IdempotencyLeaseService(contender_b).claim(
                idempotency_key="expired-lease",
                request_hash=request_hash,
                worker_id="worker-b",
                lease_seconds=30,
            )
        assert loser.value.code == "IDEMPOTENCY_REQUEST_IN_PROGRESS"
        assert winner.attempt_no == 2
    finally:
        contender_a.close()
        contender_b.close()


def test_expired_idempotency_lease_barrier_has_one_provider_budget_winner(session, monkeypatch) -> None:
    request_hash = canonical_request_hash("POST", "/run", {"scene_id": "SC01"})
    expired = (datetime.now(UTC) - timedelta(seconds=5)).isoformat()
    session.add(
        IdempotencyKey(
            idempotency_key="expired-lease-barrier",
            request_hash=request_hash,
            status="started",
            worker_id="dead-worker",
            attempt_no=1,
            heartbeat_at=expired,
            lease_expires_at=expired,
        )
    )
    session.commit()

    barrier = Barrier(2)
    refresh_lock = Lock()
    synchronized_sessions: set[int] = set()
    original_refresh = SqlAlchemySession.refresh

    def synchronized_refresh(db, instance, *args, **kwargs):  # noqa: ANN001, ANN002, ANN003
        original_refresh(db, instance, *args, **kwargs)
        if not isinstance(instance, IdempotencyKey) or instance.idempotency_key != "expired-lease-barrier":
            return
        with refresh_lock:
            first_refresh = id(db) not in synchronized_sessions
            synchronized_sessions.add(id(db))
        if first_refresh:
            barrier.wait(timeout=10)

    monkeypatch.setattr(SqlAlchemySession, "refresh", synchronized_refresh)
    provider_budget_effects: list[tuple[str, int]] = []
    effects_lock = Lock()

    def contender(worker_id: str) -> tuple[str, str]:
        db = SessionLocal()
        try:
            try:
                lease = IdempotencyLeaseService(db).claim(
                    idempotency_key="expired-lease-barrier",
                    request_hash=request_hash,
                    worker_id=worker_id,
                    lease_seconds=30,
                )
                db.commit()
            except DomainError as exc:
                return "loser", exc.code
            with effects_lock:
                provider_budget_effects.append((worker_id, lease.attempt_no))
            return "winner", worker_id
        finally:
            db.close()

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(contender, ("worker-a", "worker-b")))

    assert [kind for kind, _value in results].count("winner") == 1
    assert ("loser", "IDEMPOTENCY_REQUEST_IN_PROGRESS") in results
    assert len(provider_budget_effects) == 1
    assert provider_budget_effects[0][1] == 2


def test_lease_renewal_is_fenced_by_worker_and_attempt(session) -> None:
    request_hash = canonical_request_hash("POST", "/run", {"scene_id": "SC01"})
    owner = IdempotencyLeaseService(session).claim(
        idempotency_key="renew-lease",
        request_hash=request_hash,
        worker_id="worker-a",
        lease_seconds=1,
    )
    before = owner.lease_expires_at
    renewed = owner.renew(lease_seconds=120)
    assert renewed > before

    owner.attempt_no += 1
    with pytest.raises(DomainError) as lost:
        owner.renew(lease_seconds=120)
    assert lost.value.code == "RUN_OWNER_LEASE_LOST"
