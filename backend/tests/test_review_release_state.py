from __future__ import annotations


def import_style_review(
    client,
    *,
    review_id: str,
    lineage_key: str,
    candidate_text: str,
    active_on_approve: int = 0,
) -> str:
    response = client.post(
        "/api/v1/review-items/import-demo",
        json={
            "review_id": review_id,
            "scene_id": "CH001_SC01",
            "chapter_id": "CH001",
            "item_type": "style_observation",
            "candidate_text": candidate_text,
            "candidate_payload_json": {
                "scope": "global",
                "scope_ref_id": "global",
                "lineage_key": lineage_key,
                "text": candidate_text,
            },
            "active_on_approve": active_on_approve,
        },
        headers={"X-Idempotency-Key": f"import-{review_id}"},
    )
    assert response.status_code == 200
    return review_id


def approve_review(client, review_id: str) -> str:
    response = client.post(
        f"/api/v1/review-items/{review_id}/approve",
        headers={"X-Idempotency-Key": f"approve-{review_id}"},
    )
    assert response.status_code == 200
    return response.json()["data"]["approved_item_row_id"]


def test_release_state_blocks_vector_candidate_until_verify_succeeds(client) -> None:
    review_id = import_style_review(
        client,
        review_id="review_release_state_unverified",
        lineage_key="STY_RELEASE_STATE_UNVERIFIED",
        candidate_text="hold the image until the final line snaps shut",
    )
    approve_review(client, review_id)

    detail = client.get(f"/api/v1/review-items/{review_id}")
    assert detail.status_code == 200
    release_state = detail.json()["data"]["release_state"]

    assert release_state["state"] == "blocked"
    assert release_state["blocked_reason"] == "not_verified"
    assert release_state["recommended_action"] == "retry_verify"
    assert release_state["verify_job_id"] == f"verify_{review_id}"
    assert "校验" in release_state["message"]

    release = client.post(
        f"/api/v1/review-items/{review_id}/release",
        headers={"X-Idempotency-Key": f"release-{review_id}"},
    )
    assert release.status_code == 409
    assert release.json()["error"]["message"] == "candidate is not verified"


def test_release_state_becomes_ready_after_verify_and_active_after_release(client) -> None:
    review_id = import_style_review(
        client,
        review_id="review_release_state_ready",
        lineage_key="STY_RELEASE_STATE_READY",
        candidate_text="let the room go quiet before the clue lands",
    )
    approve_review(client, review_id)

    verify = client.post(
        f"/api/v1/index/verify/verify_{review_id}/retry",
        headers={"X-Idempotency-Key": f"verify-{review_id}"},
    )
    assert verify.status_code == 200

    ready_detail = client.get(f"/api/v1/review-items/{review_id}")
    assert ready_detail.status_code == 200
    assert ready_detail.json()["data"]["release_state"] == {
        "state": "ready",
        "blocked_reason": "",
        "message": "候选已批准、已物化且校验通过，可以发布到运行时。",
        "recommended_action": "none",
        "verify_job_id": f"verify_{review_id}",
    }

    released = client.post(
        f"/api/v1/review-items/{review_id}/release",
        headers={"X-Idempotency-Key": f"release-{review_id}"},
    )
    assert released.status_code == 200

    released_detail = client.get(f"/api/v1/review-items/{review_id}")
    assert released_detail.status_code == 200
    assert released_detail.json()["data"]["release_state"] == {
        "state": "active",
        "blocked_reason": "",
        "message": "候选已是当前运行时生效版本，无需再次发布。",
        "recommended_action": "none",
        "verify_job_id": f"verify_{review_id}",
    }
