from __future__ import annotations


def test_final_aggregate_reports_noop_when_chapter_has_no_scene_memories(client) -> None:
    chapter_response = client.post(
        "/api/v1/chapters",
        json={
            "chapter_id": "CH201",
            "planned_scene_count": 1,
            "chapter_goal": "No memory aggregate",
            "main_plot_push": "No passed scenes yet",
            "emotional_target": "Hold",
            "ending_effect": "No-op",
        },
        headers={"X-Idempotency-Key": "chapter-runtime-create-no-memory"},
    )
    assert chapter_response.status_code == 200

    aggregate_result = client.post(
        "/api/v1/chapters/CH201/runtime/aggregate/final",
        headers={"X-Idempotency-Key": "chapter-final-aggregate-no-memory"},
    )

    assert aggregate_result.status_code == 200
    receipt = aggregate_result.json()["data"]["receipt"]
    assert receipt["status"] == "no_op"
    assert receipt["reason"] == "no_scene_memories"
    assert receipt["chapter_memory_row_id"] is None
