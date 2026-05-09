from __future__ import annotations

from types import SimpleNamespace

from fastapi.testclient import TestClient
from sqlalchemy import select

from novel_system.db.models import OperationLog, ReviewItem
from novel_system.services.style_profile import STYLE_FEATURE_CONTRACT_VERSION, StyleProfileService


def test_style_profile_service_extracts_structured_yaml_and_sample_lines() -> None:
    profile = StyleProfileService.build_profile(
        sample_texts=[
            """
style_profile:
  features:
    syntax:
      guidance:
        - Fold one long sentence after two short beats.
    imagery:
      guidance:
        - Keep paper and door imagery tactile.
  calibration_lines:
    - The gate clicked shut like a verdict.
  banned_moves:
    - Do not copy signature author phrasing.
""",
            "Dialogue stays sparse; silence carries the pressure before the reveal.",
        ],
    )

    assert profile is not None
    assert profile["contract_version"] == STYLE_FEATURE_CONTRACT_VERSION
    assert profile["features"]["syntax"]["guidance"] == ["Fold one long sentence after two short beats."]
    assert profile["features"]["imagery"]["guidance"] == ["Keep paper and door imagery tactile."]
    assert profile["features"]["dialogue_ratio"]["guidance"] == [
        "Dialogue stays sparse; silence carries the pressure before the reveal."
    ]
    assert profile["features"]["rhythm"]["guidance"] == [
        "Dialogue stays sparse; silence carries the pressure before the reveal."
    ]
    assert profile["calibration_lines"] == ["The gate clicked shut like a verdict."]
    assert profile["banned_moves"] == ["Do not copy signature author phrasing."]


def test_style_profile_contract_api_returns_readable_yaml_example(client: TestClient) -> None:
    response = client.get("/api/v1/style-profile/contract")

    assert response.status_code == 200
    payload = response.json()["data"]
    assert payload["contract_version"] == STYLE_FEATURE_CONTRACT_VERSION
    assert "rhythm" in payload["feature_names"]
    assert "dialogue_ratio" in payload["feature_names"]
    assert "style_profile:" in payload["example_yaml"]
    assert "banned_moves:" in payload["example_yaml"]


def test_style_profile_extract_api_returns_structured_profile_yaml(client: TestClient) -> None:
    response = client.post(
        "/api/v1/style-profile/extract",
        json={
            "sample_texts": [
                "Short pressure beats carry the rhythm; tactile paper imagery keeps dialogue sparse.",
            ],
            "calibration_lines": ["The gate clicked shut like a verdict."],
            "banned_moves": ["Do not copy named-author phrasing."],
        },
    )

    assert response.status_code == 200
    payload = response.json()["data"]
    profile = payload["profile"]
    assert profile["contract_version"] == STYLE_FEATURE_CONTRACT_VERSION
    assert profile["features"]["rhythm"]["guidance"] == [
        "Short pressure beats carry the rhythm; tactile paper imagery keeps dialogue sparse."
    ]
    assert profile["features"]["imagery"]["guidance"] == [
        "Short pressure beats carry the rhythm; tactile paper imagery keeps dialogue sparse."
    ]
    assert profile["features"]["dialogue_ratio"]["guidance"] == [
        "Short pressure beats carry the rhythm; tactile paper imagery keeps dialogue sparse."
    ]
    assert profile["calibration_lines"] == ["The gate clicked shut like a verdict."]
    assert profile["banned_moves"] == ["Do not copy named-author phrasing."]
    assert payload["profile_yaml"].startswith("style_profile:")
    assert "dialogue_ratio:" in payload["profile_yaml"]


def test_style_profile_extract_api_uses_llm_when_live(client: TestClient, monkeypatch) -> None:
    class FakeStyleProfileRunner:
        def __init__(self, db_session) -> None:
            self.session = db_session

        def run(self, **kwargs):
            assert kwargs["node_id"] == "style_profile_extract"
            return SimpleNamespace(
                llm_call_id="llm_call_style_profile_extract_test",
                response=SimpleNamespace(
                    structured_output={
                        "contract_version": STYLE_FEATURE_CONTRACT_VERSION,
                        "features": {
                            "rhythm": {"guidance": ["LLM rhythm guidance"]},
                            "syntax": {"guidance": []},
                            "imagery": {"guidance": ["LLM image guidance"]},
                            "narrative_distance": {"guidance": []},
                            "emotion_curve": {"guidance": []},
                            "paragraph_density": {"guidance": []},
                            "dialogue_ratio": {"guidance": ["LLM dialogue guidance"]},
                        },
                        "calibration_lines": ["LLM calibration"],
                        "banned_moves": ["No protected imitation"],
                    }
                ),
            )

    monkeypatch.setenv("NOVEL_SYSTEM_LLM_ENABLED", "true")
    monkeypatch.setattr("novel_system.services.style_profile.LLMNodeRunner", FakeStyleProfileRunner, raising=False)

    response = client.post(
        "/api/v1/style-profile/extract",
        json={"sample_texts": ["short rhythm and tactile image pressure"]},
    )

    assert response.status_code == 200
    payload = response.json()["data"]
    assert payload["source"] == "llm"
    assert payload["llm_call_id"] == "llm_call_style_profile_extract_test"
    assert payload["profile"]["features"]["rhythm"]["guidance"] == ["LLM rhythm guidance"]


def test_style_profile_review_candidate_api_creates_pending_style_rule_review(
    client: TestClient,
    session,
) -> None:
    profile = {
        "contract_version": STYLE_FEATURE_CONTRACT_VERSION,
        "features": {
            "rhythm": {"guidance": ["Use clipped beats before longer release lines."]},
            "syntax": {"guidance": []},
            "imagery": {"guidance": ["Keep tactile objects in frame."]},
            "narrative_distance": {"guidance": []},
            "emotion_curve": {"guidance": []},
            "paragraph_density": {"guidance": []},
            "dialogue_ratio": {"guidance": ["Keep dialogue sparse."]},
        },
        "calibration_lines": [],
        "banned_moves": ["Do not copy named-author phrasing."],
    }

    response = client.post(
        "/api/v1/style-profile/review-candidate",
        json={
            "profile": profile,
            "scope": "global",
            "scope_ref_id": "global",
        },
        headers={
            "X-Idempotency-Key": "style-profile-review-candidate",
            "X-Operator-Ref": "style.lab",
        },
    )

    assert response.status_code == 200
    payload = response.json()["data"]
    review = payload["review"]
    assert review["review_id"].startswith("review_style_profile_global_global_")
    assert review["item_type"] == "style_rule_set"
    assert review["target_collection"] == "style_rules"
    assert review["status"] == "pending"
    assert review["candidate_payload_json"]["lineage_key"] == "style_profile_global_global"
    assert review["candidate_payload_json"]["scope"] == "global"
    assert review["candidate_payload_json"]["scope_ref_id"] == "global"
    assert review["candidate_payload_json"]["source"] == "style_profile_extract"
    assert review["candidate_payload_json"]["contract_version"] == STYLE_FEATURE_CONTRACT_VERSION
    assert review["candidate_payload_json"]["content"] == review["candidate_text"]
    assert "style_profile:" in review["candidate_text"]
    assert payload["target"]["target_ref"] == f"review_item:{review['review_id']}"

    session.expire_all()
    stored = session.get(ReviewItem, review["review_id"])
    assert stored is not None
    assert stored.item_type == "style_rule_set"
    assert stored.active_on_approve == 0

    knowledge_response = client.get("/api/v1/knowledge/style_rule/style_profile_global_global")
    assert knowledge_response.status_code == 200
    candidate_version = knowledge_response.json()["data"]["candidate_version"]
    assert candidate_version["source"] == "style_profile_extract"
    assert candidate_version["style_profile"]["contract_version"] == STYLE_FEATURE_CONTRACT_VERSION
    assert candidate_version["style_profile"]["features"]["imagery"]["guidance"] == [
        "Keep tactile objects in frame."
    ]


def test_style_profile_knowledge_detail_exposes_active_and_candidate_profiles_for_diff(
    client: TestClient,
) -> None:
    active_profile = {
        "contract_version": STYLE_FEATURE_CONTRACT_VERSION,
        "features": {
            "rhythm": {"guidance": ["Keep sentences slow and even."]},
            "syntax": {"guidance": []},
            "imagery": {"guidance": ["Keep tactile objects in frame."]},
            "narrative_distance": {"guidance": []},
            "emotion_curve": {"guidance": []},
            "paragraph_density": {"guidance": []},
            "dialogue_ratio": {"guidance": ["Use frequent dialogue turns."]},
        },
        "calibration_lines": [],
        "banned_moves": [],
    }
    candidate_profile = {
        "contract_version": STYLE_FEATURE_CONTRACT_VERSION,
        "features": {
            "rhythm": {"guidance": ["Use clipped beats before longer release lines."]},
            "syntax": {"guidance": []},
            "imagery": {"guidance": ["Keep tactile objects in frame."]},
            "narrative_distance": {"guidance": []},
            "emotion_curve": {"guidance": []},
            "paragraph_density": {"guidance": ["Use compact paragraphs."]},
            "dialogue_ratio": {"guidance": []},
        },
        "calibration_lines": [],
        "banned_moves": [],
    }

    active_response = client.post(
        "/api/v1/style-profile/review-candidate",
        json={
            "profile": active_profile,
            "scope": "global",
            "scope_ref_id": "diff",
            "active_on_approve": 1,
        },
        headers={"X-Idempotency-Key": "style-profile-diff-active"},
    )
    assert active_response.status_code == 200
    active_review_id = active_response.json()["data"]["review"]["review_id"]
    assert client.post(
        f"/api/v1/review-items/{active_review_id}/approve",
        headers={"X-Idempotency-Key": "style-profile-diff-active-approve"},
    ).status_code == 200

    candidate_response = client.post(
        "/api/v1/style-profile/review-candidate",
        json={
            "profile": candidate_profile,
            "scope": "global",
            "scope_ref_id": "diff",
        },
        headers={"X-Idempotency-Key": "style-profile-diff-candidate"},
    )
    assert candidate_response.status_code == 200

    knowledge_response = client.get("/api/v1/knowledge/style_rule/style_profile_global_diff")
    assert knowledge_response.status_code == 200
    data = knowledge_response.json()["data"]
    assert data["active_version"]["source"] == "style_profile_extract"
    assert data["active_version"]["style_profile"]["features"]["rhythm"]["guidance"] == [
        "Keep sentences slow and even."
    ]
    assert data["candidate_version"]["style_profile"]["features"]["rhythm"]["guidance"] == [
        "Use clipped beats before longer release lines."
    ]

    review_items_response = client.get("/api/v1/review-items?status=pending&item_type=style_rule_set")
    assert review_items_response.status_code == 200
    candidate_review = next(
        item
        for item in review_items_response.json()["data"]["items"]
        if item["candidate_payload_json"]["lineage_key"] == "style_profile_global_diff"
    )
    assert candidate_review["style_profile_baseline"]["features"]["rhythm"]["guidance"] == [
        "Keep sentences slow and even."
    ]


def test_high_risk_style_profile_approval_requires_confirmation_and_logs_reason(
    client: TestClient,
    session,
) -> None:
    active_profile = {
        "contract_version": STYLE_FEATURE_CONTRACT_VERSION,
        "features": {
            "rhythm": {"guidance": ["Keep sentences slow and even."]},
            "syntax": {"guidance": []},
            "imagery": {"guidance": ["Keep tactile objects in frame."]},
            "narrative_distance": {"guidance": []},
            "emotion_curve": {"guidance": []},
            "paragraph_density": {"guidance": []},
            "dialogue_ratio": {"guidance": ["Use frequent dialogue turns."]},
        },
        "calibration_lines": [],
        "banned_moves": [],
    }
    candidate_profile = {
        "contract_version": STYLE_FEATURE_CONTRACT_VERSION,
        "features": {
            "rhythm": {"guidance": ["Keep sentences slow and even."]},
            "syntax": {"guidance": []},
            "imagery": {"guidance": ["Keep tactile objects in frame."]},
            "narrative_distance": {"guidance": []},
            "emotion_curve": {"guidance": []},
            "paragraph_density": {"guidance": []},
            "dialogue_ratio": {"guidance": []},
        },
        "calibration_lines": [],
        "banned_moves": [],
    }

    active_response = client.post(
        "/api/v1/style-profile/review-candidate",
        json={
            "profile": active_profile,
            "scope": "global",
            "scope_ref_id": "risk_gate",
            "active_on_approve": 1,
        },
        headers={"X-Idempotency-Key": "style-profile-risk-gate-active"},
    )
    assert active_response.status_code == 200
    active_review_id = active_response.json()["data"]["review"]["review_id"]
    assert client.post(
        f"/api/v1/review-items/{active_review_id}/approve",
        headers={"X-Idempotency-Key": "style-profile-risk-gate-active-approve"},
    ).status_code == 200

    candidate_response = client.post(
        "/api/v1/style-profile/review-candidate",
        json={
            "profile": candidate_profile,
            "scope": "global",
            "scope_ref_id": "risk_gate",
        },
        headers={"X-Idempotency-Key": "style-profile-risk-gate-candidate"},
    )
    assert candidate_response.status_code == 200
    candidate_review_id = candidate_response.json()["data"]["review"]["review_id"]

    blocked = client.post(
        f"/api/v1/review-items/{candidate_review_id}/approve",
        headers={"X-Idempotency-Key": "style-profile-risk-gate-candidate-blocked"},
    )
    assert blocked.status_code == 409
    assert blocked.json()["error"]["code"] == "STYLE_PROFILE_RISK_CONFIRMATION_REQUIRED"

    reason = "Editorially approved reset of dialogue-ratio guidance."
    approved = client.post(
        f"/api/v1/review-items/{candidate_review_id}/approve",
        json={"risk_confirmation": {"acknowledged": True, "reason": reason}},
        headers={
            "X-Idempotency-Key": "style-profile-risk-gate-candidate-approved",
            "X-Operator-Ref": "style.reviewer",
        },
    )
    assert approved.status_code == 200
    assert approved.json()["data"]["risk_confirmation"]["reason"] == reason

    session.expire_all()
    operation = session.execute(
        select(OperationLog)
        .where(
            OperationLog.event_type == "operator_action",
            OperationLog.object_type == "review_item",
            OperationLog.object_ref == candidate_review_id,
        )
        .order_by(OperationLog.operation_id.desc())
    ).scalars().first()
    assert operation is not None
    assert operation.payload_json["request_payload"]["risk_confirmation"]["reason"] == reason

    activity_response = client.get(
        "/api/v1/activity-events",
        params={
            "stream": "operator_action",
            "target_ref": f"review_item:{candidate_review_id}",
            "actor_ref": "style.reviewer",
        },
    )
    assert activity_response.status_code == 200
    activity = next(
        item
        for item in activity_response.json()["data"]["items"]
        if item["object_ref"] == candidate_review_id and item["action"] == "approve_review"
    )
    assert activity["risk_confirmation"] == {
        "acknowledged": True,
        "reason": reason,
        "severity": "high",
    }

    group_items_response = client.get(
        f"/api/v1/target-activity-groups/review_item:{candidate_review_id}/items",
        params={"source": "operator_action", "actor_ref": "style.reviewer"},
    )
    assert group_items_response.status_code == 200
    group_activity = next(
        item
        for item in group_items_response.json()["data"]["items"]
        if item["activity_key"] == f"operator_action:{operation.operation_id}"
    )
    assert group_activity["risk_confirmation"]["reason"] == reason
