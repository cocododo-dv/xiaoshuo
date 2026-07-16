"""Wave 6（§8 第 5 项）：编排信号面板显示成本、预算和裁判独立性。

完成门口径：任意场景可解释总成本、各阶段占比、是否超预算、评审是否独立——都从
GET /api/v1/scenes/{id}/orchestration-signals 一读拿到。
"""
from __future__ import annotations

from novel_system.db.models import ChapterGoal, LlmCall, SceneCard, SceneRunState, StoryProject


def _seed(session):
    session.add(StoryProject(project_id="OP", title="Orchestration signals", outline_text=""))
    session.add(ChapterGoal(chapter_id="OCH1", project_id="OP", chapter_goal="g", planned_scene_count=1))
    session.add(SceneCard(scene_id="OS1", chapter_id="OCH1", project_id="OP", scene_seq=1, scene_goal="g"))
    session.add(SceneRunState(scene_id="OS1", scene_token_budget=1000, scene_tokens_used=300,
                              criticality_level="critical"))
    session.add(
        LlmCall(
            llm_call_id="oc1", provider="openai_compatible", model="gpt-5",
            scope_type="scene", scope_id="OS1",
            node_id="style_draft", step="style_draft", scene_id="OS1", chapter_id="OCH1",
            project_id="OP", prompt_tokens=200, completion_tokens=100, total_tokens=300,
        )
    )
    session.commit()


def test_signals_include_cost_and_judge_independence(client, session):
    _seed(session)
    r = client.get("/api/v1/scenes/OS1/orchestration-signals")
    assert r.status_code == 200, r.text
    data = r.json()["data"]
    assert data["available"] is True
    # 成本节：总成本 + 各阶段占比 + 是否超预算
    assert "cost" in data and data["cost"] is not None
    assert data["cost"]["total_cost"] > 0
    assert "phase_breakdown" in data["cost"]
    assert data["cost"]["over_budget"] is False
    # 裁判独立性节
    assert "judge_independence" in data and data["judge_independence"] is not None
    assert "correlated_judge" in data["judge_independence"]


def test_signals_missing_scene_available_false(client):
    r = client.get("/api/v1/scenes/NOPE/orchestration-signals")
    assert r.status_code == 200, r.text
    assert r.json()["data"]["available"] is False
