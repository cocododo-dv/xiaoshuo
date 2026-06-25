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


def test_run_jobs_exposes_structured_missing_fields_on_contract_block(client, session) -> None:
    """Fix A：异步 run-jobs 在执行契约拦截时，serialize 必须透出结构化 missing_fields，
    且与同步 run/full 的 error.details.missing_fields 同源——修复前异步路径丢失该信息。"""
    from novel_system.services.scene_run_jobs import _run_scene_job_worker

    scene_id = _seed_fe_scene(session)

    # 同步 run/full 的 missing_fields 作为同源基准（已知非空）
    full = client.post(f"/api/v1/scenes/{scene_id}/run/full", headers={"X-Idempotency-Key": "fa-full"})
    assert full.status_code == 409, full.text
    expected = set(full.json()["error"]["details"]["missing_fields"])
    assert expected, "基准 missing_fields 不应为空"

    # 异步：建任务(无预检阻断→queued) → 同步驱动 worker(不起线程，确定性) → 因契约拦截以 failed 终态
    created = client.post(f"/api/v1/scenes/{scene_id}/run/jobs?start=false", headers={"X-Idempotency-Key": "fa-job"})
    assert created.status_code == 200, created.text
    job_id = created.json()["data"]["job_id"]
    _run_scene_job_worker(job_id)

    polled = client.get(f"/api/v1/run-jobs/{job_id}").json()["data"]
    assert polled["error_code"] == "SCENE_EXECUTION_CONTRACT_BLOCKED"
    # 关键断言：异步路径透出结构化 missing_fields（修复前此处为空 → 红）
    assert polled["missing_fields"], "异步 run-jobs 必须透出结构化 missing_fields"
    assert set(polled["missing_fields"]) == expected, "异步 missing_fields 必须与同步 run/full 同源"


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


def test_normalize_patch_output_tops_up_single_llm_option_to_two() -> None:
    """Fix B：真 LLM 仅回 1 个候选时，补足到 ≥2，且补足项可区分、不污染前端 offline 正则。"""
    import re as _re
    from novel_system.services.writer_deep_review import _normalize_patch_output

    out = _normalize_patch_output(
        {"patches": [{"replacement_text": "她把证据袋按进掌心，没有解释。", "tone": "sharper", "label": "更狠"}], "rationale": "压缩解释余量"},
        source_excerpt="她把证据袋放回原处，转身解释了三句。",
        issue_dimension="把这段改得更凝练",
        target_text_ref="ref-1",
    )
    opts = out["replacement_options"]
    assert len(opts) >= 2, "真 LLM 只回 1 个时必须补足到 ≥2"
    llm = [o for o in opts if str(o["option_id"]).startswith("option_llm_")]
    topup = [o for o in opts if o.get("is_fallback_topup")]
    assert len(llm) == 1 and len(topup) >= 1, "应恰有 1 个真 LLM 候选 + ≥1 个可区分的补足项"
    assert all(str(o["replacement_text"]).strip() for o in opts)
    assert topup[0]["replacement_text"].strip() != llm[0]["replacement_text"].strip(), "补足项不得与真候选重复"
    # 诚实但不冒充：rationale 整串不得匹配前端 /offline deterministic/i（否则真改写被整体丢弃）
    assert not _re.search(r"offline deterministic", out["rationale"], _re.I)


def test_normalize_patch_output_keeps_multi_llm_options_without_topup() -> None:
    """Fix B 边界：模型已给 ≥2 个候选时，不补足、不加标记。"""
    from novel_system.services.writer_deep_review import _normalize_patch_output

    out = _normalize_patch_output(
        {"patches": [{"replacement_text": "甲版改写。"}, {"replacement_text": "乙版改写。"}], "rationale": "两版"},
        source_excerpt="原句。",
        issue_dimension="dim",
        target_text_ref="r",
    )
    opts = out["replacement_options"]
    assert len(opts) == 2
    assert not any(o.get("is_fallback_topup") for o in opts), "已有 ≥2 个真候选不应补足"


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



def _seed_scene_with_pov(session) -> tuple[str, str]:
    from novel_system.db.models import StoryCharacter

    session.add(StoryProject(project_id="PRJ_VC", title="声卡之书", outline_text="o", planning_mode="snowflake"))
    session.add(StoryCharacter(character_id="CHAR_A", project_id="PRJ_VC", display_name="角色甲"))
    session.add(
        ChapterGoal(chapter_id="CH_VC_01", project_id="PRJ_VC", planned_scene_count=1, chapter_goal="第一章", writer_brief_json={"title": "第一章"})
    )
    session.add(
        SceneCard(
            scene_id="CH_VC_01_SC01",
            chapter_id="CH_VC_01",
            project_id="PRJ_VC",
            scene_seq=1,
            scene_goal="开场",
            scene_type="proactive",
            is_chapter_last=1,
            pov_character_id="CHAR_A",
            writer_brief_json={"source": "test", "title": "开场", "goal": "目标", "conflict": "阻碍", "setback": "挫折", "scene_crucible": "两难"},
        )
    )
    session.commit()
    return "CH_VC_01_SC01", "CHAR_A"


def test_preflight_create_cards_unblocks_voice_profile_missing(client, session) -> None:
    """Fix C：create_minimal_voice_card 动作可真正执行——建出 active 声线卡解阻预检。
    修复前该动作只有无物化落点的 review.item_type='voice_profile'（死胡同）。"""
    from sqlalchemy import select
    from novel_system.db.models import VoiceProfile

    scene_id, char_id = _seed_scene_with_pov(session)

    wb = client.get(f"/api/v1/scenes/{scene_id}/workbench").json()["data"]
    pf = wb["run_preflight"]
    assert pf["can_run"] is False
    assert any(b["code"] == "VOICE_PROFILE_MISSING" for b in pf["blocking_items"])
    voice_action = next(a for a in pf["create_actions"] if a["action"] == "create_minimal_voice_card")
    assert voice_action["executable"] is True
    assert voice_action["endpoint"] == f"/api/v1/scenes/{scene_id}/preflight/create-cards"

    resp = client.post(f"/api/v1/scenes/{scene_id}/preflight/create-cards", headers={"X-Idempotency-Key": "fc-cards"})
    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]
    assert any(c["dependency_type"] == "voice_card" for c in data["created"])
    # 端点回执里 preflight 不再被 voice 拦
    assert not any(b["code"] == "VOICE_PROFILE_MISSING" for b in data["run_preflight"]["blocking_items"])

    # DB 真有 active 声线卡 VOICE_CHAR_A，且 resolver 命中
    session.expire_all()
    vp = session.execute(
        select(VoiceProfile).where(VoiceProfile.voice_profile_id == f"VOICE_{char_id}", VoiceProfile.active_flag == 1)
    ).scalars().first()
    assert vp is not None and vp.character_id == char_id

    # 全新请求 GET workbench 复验已解阻
    wb2 = client.get(f"/api/v1/scenes/{scene_id}/workbench").json()["data"]
    assert not any(b["code"] == "VOICE_PROFILE_MISSING" for b in wb2["run_preflight"]["blocking_items"])


def test_preflight_create_cards_is_idempotent(client, session) -> None:
    """Fix C 幂等：已有 active 声线卡时再调不重复建。"""
    from sqlalchemy import select
    from novel_system.db.models import VoiceProfile

    scene_id, char_id = _seed_scene_with_pov(session)
    client.post(f"/api/v1/scenes/{scene_id}/preflight/create-cards", headers={"X-Idempotency-Key": "fc-i1"})
    client.post(f"/api/v1/scenes/{scene_id}/preflight/create-cards", headers={"X-Idempotency-Key": "fc-i2"})
    session.expire_all()
    rows = session.execute(
        select(VoiceProfile).where(VoiceProfile.voice_profile_id == f"VOICE_{char_id}", VoiceProfile.active_flag == 1)
    ).scalars().all()
    assert len(rows) == 1


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
