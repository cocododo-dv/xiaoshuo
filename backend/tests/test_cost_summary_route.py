"""Wave 6（§6.3）：GET /api/v2/projects/{id}/cost-summary —— 成本页数据源。

project / chapter / scene 三级下钻；空项目不 500。
"""
from __future__ import annotations

from novel_system.db.models import FinalScene, LlmCall, SceneCard, SceneRunState


def _seed(session):
    session.add(SceneCard(scene_id="RS1", chapter_id="RCH1", project_id="RP", scene_seq=1, scene_goal="g"))
    session.add(SceneRunState(scene_id="RS1", scene_token_budget=1000, scene_tokens_used=300))
    session.add(
        LlmCall(
            llm_call_id="rc1", provider="openai_compatible", model="gpt-5",
            node_id="style_draft", step="style_draft", scene_id="RS1", chapter_id="RCH1",
            project_id="RP", prompt_tokens=200, completion_tokens=100, total_tokens=300,
        )
    )
    session.add(
        FinalScene(row_id="rfs1", scene_id="RS1", chapter_id="RCH1", content="正文",
                   status="archived", source_bundle_id="b", source_bundle_hash="h")
    )
    session.commit()


def test_project_cost_summary(client, session):
    _seed(session)
    r = client.get("/api/v2/projects/RP/cost-summary")
    assert r.status_code == 200, r.text
    data = r.json()["data"]
    assert data["level"] == "project"
    summary = data["summary"]
    assert summary["total_cost"] > 0
    assert summary["archived_scene_count"] == 1
    assert "judge_independence" in summary


def test_scene_drilldown(client, session):
    _seed(session)
    r = client.get("/api/v2/projects/RP/cost-summary", params={"scene_id": "RS1"})
    assert r.status_code == 200, r.text
    data = r.json()["data"]
    assert data["level"] == "scene"
    assert data["summary"]["scene_id"] == "RS1"
    assert data["summary"]["budget"]["budget"] == 1000
    assert "phase_breakdown" in data["summary"]


def test_chapter_drilldown(client, session):
    _seed(session)
    r = client.get("/api/v2/projects/RP/cost-summary", params={"chapter_id": "RCH1"})
    assert r.status_code == 200, r.text
    data = r.json()["data"]
    assert data["level"] == "chapter"
    assert data["summary"]["chapter_id"] == "RCH1"
    assert data["summary"]["archived_scene_count"] == 1


def test_empty_project_does_not_500(client):
    r = client.get("/api/v2/projects/NOPE/cost-summary")
    assert r.status_code == 200, r.text
    data = r.json()["data"]
    assert data["summary"]["total_cost"] == 0
