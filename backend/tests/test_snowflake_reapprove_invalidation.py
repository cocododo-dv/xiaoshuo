"""QA3 回归：对「已物化出章节/场景」的项目再次确认（re-approve）上游雪花步，
不得因 chapter_states.chapter_id UNIQUE 约束而 500。

复现的 BUG-1：approve_step → ProjectRuntimeInvalidationService.invalidate_for_snowflake_step
里 263-loop 与 backtracks._apply_block 在 autoflush=False 的会话下各建一遍同一 chapter 的
ChapterState（session.get 看不到 pending 新对象）→ 同一 flush 批次重复 INSERT → IntegrityError。

此前的 re-approve 测试都没先物化章节，故 263-loop early-return，从不触发。本测试先物化再 re-approve。
"""
from __future__ import annotations

from novel_system.db.models import ChapterState

ALL_STEPS = [
    "book_brief",
    "one_sentence_summary",
    "one_paragraph_summary",
    "character_sheets",
    "short_synopsis",
    "character_synopses",
    "long_synopsis",
    "character_bibles",
    "scene_list",
    "scene_details",
]


def _create_project(client, key: str) -> dict:
    response = client.post(
        "/api/v2/projects",
        json={
            "title": f"QA3再批准 {key}",
            "genre": "悬疑",
            "target_chapter_count": 2,
            "target_word_count": 120000,
            "outline_text": "旧潮汐记录正被改写。\n档案修复师追查真相。\n她必须决定真相值不值得。",
        },
        headers={"X-Idempotency-Key": f"qa3-reappr-create-{key}"},
    )
    assert response.status_code == 200, response.text
    return response.json()["data"]["project"]


def _generate(client, pid: str, step_key: str, payload: dict | None = None) -> dict:
    r = client.post(
        f"/api/v2/projects/{pid}/snowflake-workspace/steps/{step_key}/generate",
        json=payload or {},
        headers={"X-Idempotency-Key": f"qa3-reappr-gen-{pid}-{step_key}-{(payload or {}).get('force_new')}"},
    )
    assert r.status_code == 200, r.text
    return r.json()["data"]


def _approve(client, pid: str, step_key: str):
    return client.post(
        f"/api/v2/projects/{pid}/snowflake-workspace/steps/{step_key}/approve",
        json={},
        headers={"X-Idempotency-Key": f"qa3-reappr-approve-{pid}-{step_key}"},
    )


def _drop_chapter_states(session) -> int:
    """复现 BUG-1 触发条件：章节存在但无 ChapterState 行。
    seed_fe_demo_works（tide/salt）与 catalog.py（FE 章节编排冷启动/导入）建章时都不建 ChapterState，
    只有 approve_outline_plan 会建——本测试经后者建章，故显式删去 ChapterState 以还原 demo/目录态。"""
    rows = session.query(ChapterState).all()
    n = len(rows)
    for r in rows:
        session.delete(r)
    session.commit()
    return n


def test_reapprove_upstream_step_after_materialization_does_not_500(client, session):
    project = _create_project(client, "broad")
    pid = project["project_id"]

    # 1) 一次性批准全部 10 步（首次批准，无 previous → 不触发 invalidate）
    for step_key in ALL_STEPS:
        _generate(client, pid, step_key)
        assert _approve(client, pid, step_key).status_code == 200

    # 2) 物化 + 批准大纲：materialize 仅建 pending OutlinePlan，章节要 outline/approve 才落库
    materialized = client.post(
        f"/api/v2/projects/{pid}/snowflake-workspace/materialize",
        json={},
        headers={"X-Idempotency-Key": f"qa3-reappr-materialize-{pid}"},
    )
    assert materialized.status_code == 200, materialized.text
    outline_approved = client.post(
        f"/api/v2/projects/{pid}/snowflake-workspace/outline/approve",
        json={},
        headers={"X-Idempotency-Key": f"qa3-reappr-outline-approve-{pid}"},
    )
    assert outline_approved.status_code == 200, outline_approved.text

    catalog = client.get(f"/api/v2/projects/{pid}/catalog").json()["data"]
    scene_total = sum(len(c["scenes"]) for c in catalog["chapters"])
    assert len(catalog["chapters"]) >= 1 and scene_total >= 1, "物化未产出章节/场景，前置不成立"

    # 还原 demo/目录态：章节存在但无 ChapterState 行（这是 BUG-1 的真实触发前置）
    assert _drop_chapter_states(session) >= 1, "前置：approve_outline_plan 应已建 ChapterState 供删除"

    # 3) 再次确认上游步 book_brief（broad impact 覆盖全部已物化场景）
    #    BUG-1：263-loop 与 _apply_block 各建一遍同一 chapter 的 ChapterState → flush 撞 UNIQUE → 500。
    #    修复（263-loop 后 flush）后应 200。
    _generate(client, pid, "book_brief", {"force_new": True})
    resp = _approve(client, pid, "book_brief")
    assert resp.status_code == 200, f"re-approve 上游步在已物化项目上崩溃: {resp.status_code} {resp.text}"

    body = resp.json()
    assert body["ok"] is True
    # 该步确实落为 approved（后端真批准，非静默失败）
    step = body["data"]["step"]
    status = step.get("status") or step.get("artifact", {}).get("status")
    assert status == "approved", f"book_brief 未真正批准: {status}"


def test_reapprove_scoped_step_after_materialization_does_not_500(client, session):
    """scene_details 的 scoped 路径（_apply_block 带具体 chapter_id）同样不得 500。"""
    project = _create_project(client, "scoped")
    pid = project["project_id"]
    for step_key in ALL_STEPS:
        _generate(client, pid, step_key)
        assert _approve(client, pid, step_key).status_code == 200
    materialized = client.post(
        f"/api/v2/projects/{pid}/snowflake-workspace/materialize",
        json={},
        headers={"X-Idempotency-Key": f"qa3-reappr-materialize2-{pid}"},
    )
    assert materialized.status_code == 200, materialized.text
    outline_approved = client.post(
        f"/api/v2/projects/{pid}/snowflake-workspace/outline/approve",
        json={},
        headers={"X-Idempotency-Key": f"qa3-reappr-outline-approve2-{pid}"},
    )
    assert outline_approved.status_code == 200, outline_approved.text
    _drop_chapter_states(session)

    _generate(client, pid, "scene_details", {"force_new": True})
    resp = _approve(client, pid, "scene_details")
    assert resp.status_code == 200, f"re-approve scene_details 崩溃: {resp.status_code} {resp.text}"


def test_repatch_identical_approved_draft_does_not_revert(client, session):
    """QA3 回归（BUG-2 后端守卫）：对已批准步用相同 canonical 草稿 re-PATCH（前端无谓 re-push 的
    "内容未变"语义）不得新建 pending_review 版本、把已确认步打回待审。"""
    from sqlalchemy import select
    from novel_system.db.models import SnowflakeStepRun
    from novel_system.services.snowflake_workspace import SnowflakeWorkspaceService

    project = _create_project(client, "noop-guard")
    pid = project["project_id"]
    _generate(client, pid, "book_brief")
    assert _approve(client, pid, "book_brief").status_code == 200

    run = session.execute(
        select(SnowflakeStepRun).where(
            SnowflakeStepRun.project_id == pid,
            SnowflakeStepRun.step_key == "book_brief",
            SnowflakeStepRun.status == "approved",
        )
    ).scalars().first()
    assert run is not None, "前置：book_brief 应已批准"
    approved_version = run.version
    approved_draft = dict(run.draft_json or {})

    SnowflakeWorkspaceService(session).update_step(pid, "book_brief", {"draft": approved_draft})
    session.commit()
    session.expire_all()

    latest = session.execute(
        select(SnowflakeStepRun)
        .where(SnowflakeStepRun.project_id == pid, SnowflakeStepRun.step_key == "book_brief")
        .order_by(SnowflakeStepRun.version.desc())
    ).scalars().first()
    assert latest.status == "approved", f"identical re-PATCH 把已批准步打回了 {latest.status}"
    assert latest.version == approved_version, "identical re-PATCH 不应新建版本"
