from __future__ import annotations

import pytest
from sqlalchemy.exc import IntegrityError

from novel_system.services.errors import DomainError
from novel_system.services.idempotency import execute_with_idempotency


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
