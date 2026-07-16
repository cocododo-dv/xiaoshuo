from __future__ import annotations


def _headers(key: str) -> dict[str, str]:
    return {"X-Idempotency-Key": key}


def _validation_issues(response) -> list[dict[str, str]]:
    payload = response.json()
    assert payload["ok"] is False
    assert payload["error"]["code"] == "REQUEST_VALIDATION_FAILED"
    return payload["error"]["details"]["issues"]


def test_chapter_upsert_rejects_server_owned_fields(client) -> None:
    response = client.post(
        "/api/v1/chapters",
        json={
            "chapter_id": "BOUNDARY_CH",
            "chapter_goal": "Keep lifecycle fields server-owned.",
            "trashed_flag": 0,
        },
        headers=_headers("boundary-ch-extra"),
    )

    assert response.status_code == 422
    assert any(item["type"] == "extra_forbidden" for item in _validation_issues(response))
    assert "Keep lifecycle fields server-owned." not in response.text


def test_scene_upsert_rejects_rollups_and_timestamps(client) -> None:
    chapter = client.post(
        "/api/v1/chapters",
        json={"chapter_id": "BOUNDARY_SC_CH", "chapter_goal": "A goal."},
        headers=_headers("boundary-sc-ch"),
    )
    assert chapter.status_code == 200

    response = client.post(
        "/api/v1/scenes",
        json={
            "scene_id": "BOUNDARY_SC",
            "chapter_id": "BOUNDARY_SC_CH",
            "scene_goal": "A scene goal.",
            "words_current": 999999,
            "updated_at": "spoofed",
        },
        headers=_headers("boundary-sc-extra"),
    )

    assert response.status_code == 422
    forbidden = {
        item["field"].rsplit(".", 1)[-1]
        for item in _validation_issues(response)
    }
    assert forbidden == {"updated_at", "words_current"}
    assert "999999" not in response.text


def test_existing_scene_cannot_be_reparented(client) -> None:
    for suffix in ("A", "B"):
        response = client.post(
            "/api/v1/chapters",
            json={"chapter_id": f"BOUNDARY_{suffix}", "chapter_goal": suffix},
            headers=_headers(f"boundary-parent-{suffix}"),
        )
        assert response.status_code == 200

    created = client.post(
        "/api/v1/scenes",
        json={
            "scene_id": "BOUNDARY_MOVE_SC",
            "chapter_id": "BOUNDARY_A",
            "scene_goal": "Stay in chapter A.",
        },
        headers=_headers("boundary-sc-create"),
    )
    assert created.status_code == 200

    moved = client.post(
        "/api/v1/scenes",
        json={
            "scene_id": "BOUNDARY_MOVE_SC",
            "chapter_id": "BOUNDARY_B",
            "scene_goal": "Try to move.",
        },
        headers=_headers("boundary-sc-move"),
    )

    assert moved.status_code == 409
    assert moved.json()["error"]["code"] == "SCENE_IDENTITY_IMMUTABLE"
