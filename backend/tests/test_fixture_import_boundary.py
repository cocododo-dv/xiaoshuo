from __future__ import annotations


def test_fixture_import_is_hidden_and_disabled_without_explicit_opt_in(client, monkeypatch) -> None:
    monkeypatch.setenv("NOVEL_SYSTEM_ENABLE_FIXTURE_IMPORT", "false")

    response = client.post(
        "/api/v1/review-items/import-demo",
        json={
            "review_id": "must-not-be-created",
            "item_type": "style_observation",
            "candidate_text": "fixture",
        },
    )

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "FIXTURE_IMPORT_DISABLED"
    assert "/api/v1/review-items/import-demo" not in client.get("/openapi.json").json()["paths"]
