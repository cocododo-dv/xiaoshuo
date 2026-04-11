from __future__ import annotations

from novel_system.db.models import HumanReviewEvent, ReviewItem


def test_review_items_filter_by_status_scene_and_chapter(client, session) -> None:
    session.add_all(
        [
            ReviewItem(
                review_id="review_status_pending",
                scene_id="CH001_SC01",
                chapter_id="CH001",
                item_type="style_observation",
                status="pending",
                candidate_text="status match",
            ),
            ReviewItem(
                review_id="review_status_approved",
                scene_id="CH001_SC01",
                chapter_id="CH001",
                item_type="style_observation",
                status="approved",
                candidate_text="status mismatch",
            ),
        ]
    )
    session.commit()

    response = client.get("/api/v1/review-items", params={"status": "pending"})
    assert response.status_code == 200
    assert [item["review_id"] for item in response.json()["data"]["items"]] == ["review_status_pending"]

    session.add_all(
        [
            ReviewItem(
                review_id="review_scene_match",
                scene_id="CH009_SC01",
                chapter_id="CH009",
                item_type="style_observation",
                status="approved",
                candidate_text="scene match",
            ),
            ReviewItem(
                review_id="review_scene_mismatch",
                scene_id="CH009_SC02",
                chapter_id="CH009",
                item_type="style_observation",
                status="approved",
                candidate_text="scene mismatch",
            ),
        ]
    )
    session.commit()

    response = client.get("/api/v1/review-items", params={"scene_id": "CH009_SC01"})
    assert response.status_code == 200
    assert [item["review_id"] for item in response.json()["data"]["items"]] == ["review_scene_match"]

    session.add_all(
        [
            ReviewItem(
                review_id="review_chapter_match",
                scene_id="CH010_SC01",
                chapter_id="CH010",
                item_type="style_observation",
                status="approved",
                candidate_text="chapter match",
            ),
            ReviewItem(
                review_id="review_chapter_mismatch",
                scene_id="CH010_SC01",
                chapter_id="CH011",
                item_type="style_observation",
                status="approved",
                candidate_text="chapter mismatch",
            ),
        ]
    )
    session.commit()

    response = client.get("/api/v1/review-items", params={"chapter_id": "CH010"})
    assert response.status_code == 200
    assert [item["review_id"] for item in response.json()["data"]["items"]] == ["review_chapter_match"]


def test_review_items_filter_by_item_type(client, session) -> None:
    session.add_all(
        [
            ReviewItem(
                review_id="review_item_type_scene_memory",
                scene_id="CH020_SC01",
                chapter_id="CH020",
                item_type="scene_memory",
                status="pending",
                candidate_text="item type match",
            ),
            ReviewItem(
                review_id="review_item_type_scene_summary",
                scene_id="CH020_SC01",
                chapter_id="CH020",
                item_type="scene_summary",
                status="pending",
                candidate_text="same collection but different item type",
            ),
        ]
    )
    session.commit()

    response = client.get("/api/v1/review-items", params={"item_type": "scene_memory"})
    assert response.status_code == 200
    assert [item["review_id"] for item in response.json()["data"]["items"]] == ["review_item_type_scene_memory"]


def test_review_items_filter_by_target_collection(client, session) -> None:
    session.add_all(
        [
            ReviewItem(
                review_id="review_collection_scene_memory",
                scene_id="CH030_SC01",
                chapter_id="CH030",
                item_type="scene_memory",
                status="pending",
                candidate_text="collection match one",
            ),
            ReviewItem(
                review_id="review_collection_scene_summary",
                scene_id="CH030_SC01",
                chapter_id="CH030",
                item_type="scene_summary",
                status="pending",
                candidate_text="collection match two",
            ),
            ReviewItem(
                review_id="review_collection_chapter_summary",
                scene_id="CH030_SC01",
                chapter_id="CH030",
                item_type="chapter_summary",
                status="pending",
                candidate_text="collection mismatch",
            ),
        ]
    )
    session.commit()

    response = client.get("/api/v1/review-items", params={"target_collection": "scene_memories"})
    assert response.status_code == 200
    assert sorted(item["review_id"] for item in response.json()["data"]["items"]) == [
        "review_collection_scene_memory",
        "review_collection_scene_summary",
    ]


def test_human_review_events_apply_all_supported_filters(client, session) -> None:
    session.add_all(
        [
            HumanReviewEvent(
                event_id="human_review_filtered_match",
                scene_id="CH001_SC01",
                chapter_id="CH001",
                object_ref="review_scene_pending",
                event_source="idempotency_recovery",
                priority="high",
                owner="ops.duwei",
                status="needs_followup",
                allowed_actions_json=["inspect"],
                result_status_map_json={"inspect": "needs_followup"},
                details_json={},
                default_action="inspect",
            ),
            HumanReviewEvent(
                event_id="human_review_filtered_wrong_status",
                scene_id="CH001_SC01",
                chapter_id="CH001",
                object_ref="review_scene_pending",
                event_source="idempotency_recovery",
                priority="high",
                owner="ops.duwei",
                status="resolved",
                allowed_actions_json=["inspect"],
                result_status_map_json={"inspect": "needs_followup"},
                details_json={},
                default_action="inspect",
            ),
            HumanReviewEvent(
                event_id="human_review_filtered_wrong_source",
                scene_id="CH001_SC01",
                chapter_id="CH001",
                object_ref="review_scene_pending",
                event_source="manual_review",
                priority="high",
                owner="ops.duwei",
                status="needs_followup",
                allowed_actions_json=["inspect"],
                result_status_map_json={"inspect": "needs_followup"},
                details_json={},
                default_action="inspect",
            ),
            HumanReviewEvent(
                event_id="human_review_filtered_wrong_priority",
                scene_id="CH001_SC01",
                chapter_id="CH001",
                object_ref="review_scene_pending",
                event_source="idempotency_recovery",
                priority="normal",
                owner="ops.duwei",
                status="needs_followup",
                allowed_actions_json=["inspect"],
                result_status_map_json={"inspect": "needs_followup"},
                details_json={},
                default_action="inspect",
            ),
            HumanReviewEvent(
                event_id="human_review_filtered_wrong_owner",
                scene_id="CH001_SC01",
                chapter_id="CH001",
                object_ref="review_scene_pending",
                event_source="idempotency_recovery",
                priority="high",
                owner="ops.other",
                status="needs_followup",
                allowed_actions_json=["inspect"],
                result_status_map_json={"inspect": "needs_followup"},
                details_json={},
                default_action="inspect",
            ),
            HumanReviewEvent(
                event_id="human_review_filtered_wrong_scene",
                scene_id="CH001_SC02",
                chapter_id="CH001",
                object_ref="review_scene_pending",
                event_source="idempotency_recovery",
                priority="high",
                owner="ops.duwei",
                status="needs_followup",
                allowed_actions_json=["inspect"],
                result_status_map_json={"inspect": "needs_followup"},
                details_json={},
                default_action="inspect",
            ),
            HumanReviewEvent(
                event_id="human_review_filtered_wrong_chapter",
                scene_id="CH001_SC01",
                chapter_id="CH002",
                object_ref="review_scene_pending",
                event_source="idempotency_recovery",
                priority="high",
                owner="ops.duwei",
                status="needs_followup",
                allowed_actions_json=["inspect"],
                result_status_map_json={"inspect": "needs_followup"},
                details_json={},
                default_action="inspect",
            ),
        ]
    )
    session.commit()

    response = client.get(
        "/api/v1/human-review-events",
        params={
            "status": "needs_followup",
            "event_source": "idempotency_recovery",
            "priority": "high",
            "owner": "ops.duwei",
            "scene_id": "CH001_SC01",
            "chapter_id": "CH001",
        },
    )

    assert response.status_code == 200
    assert [item["event_id"] for item in response.json()["data"]["items"]] == ["human_review_filtered_match"]
