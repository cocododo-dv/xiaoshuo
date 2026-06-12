"""FE 目录建的场景（无 SceneRunState 行）走 run 管线的守卫（FE-ALIGN F6）。

起草台把 scnRun 接到 scenes run 管线后，FE 目录直接建的最小场景卡必须：
- workbench 可读（自动补建运行态行，而不是 AttributeError 500）；
- run/full 给结构化 409（执行契约缺字段），而不是 500；
- run/jobs 能建任务（blocked/queued 均可，不 500）。
"""

from __future__ import annotations

from novel_system.db.models import ChapterGoal, SceneCard, SceneRunState, StoryProject


def _seed_fe_scene(session) -> str:
    session.add(StoryProject(project_id="PRJ_FE_RUN", title="守卫之书", outline_text="o", planning_mode="snowflake"))
    session.add(
        ChapterGoal(
            chapter_id="CH_FE_RUN_01",
            project_id="PRJ_FE_RUN",
            planned_scene_count=1,
            chapter_goal="第一章",
            writer_brief_json={"title": "第一章"},
        )
    )
    session.add(
        SceneCard(
            scene_id="CH_FE_RUN_01_SC01",
            chapter_id="CH_FE_RUN_01",
            project_id="PRJ_FE_RUN",
            scene_seq=1,
            scene_goal="开场",
            scene_type="proactive",
            is_chapter_last=1,
            writer_brief_json={"source": "catalog_import", "title": "开场", "goal": "目标", "conflict": "阻碍", "setback": "挫折"},
        )
    )
    session.commit()
    return "CH_FE_RUN_01_SC01"


def test_workbench_tolerates_missing_run_state(client, session) -> None:
    scene_id = _seed_fe_scene(session)
    assert session.get(SceneRunState, scene_id) is None
    response = client.get(f"/api/v1/scenes/{scene_id}/workbench")
    assert response.status_code == 200, response.text
    data = response.json()["data"]
    assert data["scene_run_state"]["scene_status"] == "ready"
    assert session.get(SceneRunState, scene_id) is not None  # 已按约定补建


def test_run_full_returns_structured_409_not_500(client, session) -> None:
    scene_id = _seed_fe_scene(session)
    response = client.post(
        f"/api/v1/scenes/{scene_id}/run/full",
        headers={"X-Idempotency-Key": "fe-run-guard-full"},
    )
    # FE 最小场景卡缺执行契约必填字段 → 结构化引导（前端把它翻成「去补全场景卡」）
    assert response.status_code == 409, response.text
    body = response.json()["error"]
    assert body["code"] == "SCENE_EXECUTION_CONTRACT_BLOCKED"
    assert body["details"]["missing_fields"]


def test_run_jobs_creates_job_without_500(client, session) -> None:
    scene_id = _seed_fe_scene(session)
    response = client.post(
        f"/api/v1/scenes/{scene_id}/run/jobs?start=false",
        headers={"X-Idempotency-Key": "fe-run-guard-job"},
    )
    assert response.status_code == 200, response.text
    job = response.json()["data"]
    assert job["status"] in {"queued", "blocked"}
    assert job["job_id"]
    poll = client.get(f"/api/v1/run-jobs/{job['job_id']}")
    assert poll.status_code == 200


def test_author_note_instruction_formatting() -> None:
    from novel_system.services.scene_generation import author_note_instruction

    assert author_note_instruction(None) == ""
    assert author_note_instruction("   ") == ""
    block = author_note_instruction("结尾改成开放式，少给一句解释。")
    assert "Author Rewrite Instruction" in block
    assert "结尾改成开放式" in block
    # 超长截断（500 字上限）
    long_note = "改" * 800
    assert author_note_instruction(long_note).count("改") == 500


def test_run_jobs_carries_author_note(client, session) -> None:
    scene_id = _seed_fe_scene(session)
    response = client.post(
        f"/api/v1/scenes/{scene_id}/run/jobs?start=false",
        json={"author_note": "把对话压短，多留白。"},
        headers={"X-Idempotency-Key": "fe-run-note-job"},
    )
    assert response.status_code == 200, response.text
    job = response.json()["data"]
    assert job["author_note"] == "把对话压短，多留白。"
    poll = client.get(f"/api/v1/run-jobs/{job['job_id']}").json()["data"]
    assert poll["author_note"] == "把对话压短，多留白。"


def test_run_full_forwards_author_note_to_orchestrator(client, session, monkeypatch) -> None:
    from novel_system.api.routes import scenes as scenes_routes

    captured = {}

    class _StubOrchestrator:
        def __init__(self, _session):
            pass

        def run_scene(self, scene_id, author_note=None):
            captured["scene_id"] = scene_id
            captured["author_note"] = author_note
            return {"scene_status": "stubbed"}

    monkeypatch.setattr(scenes_routes, "Orchestrator", _StubOrchestrator)
    scene_id = _seed_fe_scene(session)
    response = client.post(
        f"/api/v1/scenes/{scene_id}/run/full",
        json={"author_note": "雨景贯穿全场。"},
        headers={"X-Idempotency-Key": "fe-run-note-full"},
    )
    assert response.status_code == 200, response.text
    assert captured == {"scene_id": scene_id, "author_note": "雨景贯穿全场。"}



def test_passage_patch_candidate_for_fe_scene_offline(client, session) -> None:
    """FE-ALIGN G4：内联改写端点对 FE 目录场景可用；LLM 关闭走离线确定性客户端。"""
    scene_id = _seed_fe_scene(session)
    response = client.post(
        "/api/v1/passages/patch-candidates",
        json={
            "object_type": "scene",
            "object_id": scene_id,
            "scene_id": scene_id,
            "source_excerpt": "她把证据袋放回原处，转身解释了三句。",
            "issue_dimension": "把这段改得更凝练，让动作自己说话",
        },
        headers={"X-Idempotency-Key": "fe-patch-g4"},
    )
    assert response.status_code == 200, response.text
    cand = response.json()["data"]["candidate"]
    assert cand["patch_id"]
    options = cand["replacement_options"]
    assert len(options) >= 2
    assert all(o.get("replacement_text") for o in options)
    # 离线兜底有明确标记——前端据此按「模型不可用」处理，不冒充真实改写
    assert "offline deterministic" in (cand.get("rationale") or "")

    accept = client.post(
        f"/api/v1/passage-patch-candidates/{cand['patch_id']}/accept",
        json={"selected_option_id": options[0]["option_id"]},
        headers={"X-Idempotency-Key": "fe-patch-g4-accept"},
    )
    assert accept.status_code == 200
    assert accept.json()["data"]["candidate"]["author_decision"] == "accepted"
