from __future__ import annotations

from novel_system.db.models import HumanReviewEvent, ReviewItem


def test_review_items_apply_all_supported_filters(client, session) -> None:
    session.add_all(
        [
            ReviewItem(
                review_id="review_scene_pending",
                scene_id="CH001_SC01",
                chapter_id="CH001",
                item_type="style_observation",
                status="pending",
                candidate_text="keep the clipped line",
            ),
            ReviewItem(
                review_id="review_scene_wrong_status",
                scene_id="CH001_SC01",
                chapter_id="CH001",
                item_type="style_observation",
                status="approved",
                candidate_text="wrong status",
            ),
            ReviewItem(
                review_id="review_other_scene",
                scene_id="CH001_SC02",
                chapter_id="CH001",
                item_type="style_observation",
                status="pending",
                candidate_text="wrong scene",
            ),
        ]
    )
    session.commit()

    response = client.get(
        "/api/v1/review-items",
        params={
            "status": "pending",
            "item_type": "style_observation",
            "target_collection": "style_observations",
            "scene_id": "CH001_SC01",
            "chapter_id": "CH001",
        },
    )

    assert response.status_code == 200
    assert [item["review_id"] for item in response.json()["data"]["items"]] == ["review_scene_pending"]


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
