from __future__ import annotations


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
