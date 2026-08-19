from __future__ import annotations

from types import SimpleNamespace

import pytest
from sqlalchemy import select

from novel_system.db.models import (
    ChapterMemory,
    ChapterGoal,
    ChapterRunJob,
    FinalScene,
    LlmCall,
    OperationLog,
    ProjectBacktrackItem,
    SceneCard,
    SceneRunState,
    StoryProject,
    StyleReferenceBook,
    StyleReferenceInjectionBinding,
    StyleReferenceProfile,
    StyleReferenceRun,
)
from novel_system.services.errors import DomainError
from novel_system.services.canon_continuity import CanonContinuityService
from novel_system.services.projects import ProjectChapterFlowService


def _create_project(client, *, title: str = "雨城残响", target_chapter_count: int = 2, key: str = "default") -> dict:
    response = client.post(
        "/api/v1/projects",
        json={
            "title": title,
            "genre": "都市悬疑",
            "target_chapter_count": target_chapter_count,
            "target_word_count": 120000,
            "outline_text": "女主收到一封来自十年前的信。\n她回到雨城，发现旧案和家族秘密有关。\n结尾她决定公开真相。",
        },
        headers={"X-Idempotency-Key": f"create-project-{key}-{target_chapter_count}"},
    )
    assert response.status_code == 200
    return response.json()["data"]["project"]


def _generate_plan(client, project_id: str) -> dict:
    response = client.post(
        f"/api/v1/projects/{project_id}/outline-plan",
        json={},
        headers={"X-Idempotency-Key": f"plan-{project_id}"},
    )
    assert response.status_code == 200
    return response.json()["data"]["plan"]


def _approve_plan(client, project_id: str, plan_id: str) -> dict:
    response = client.post(
        f"/api/v1/projects/{project_id}/outline-plan/{plan_id}/approve",
        json={},
        headers={"X-Idempotency-Key": f"approve-plan-{plan_id}"},
    )
    assert response.status_code == 200
    return response.json()["data"]


def test_project_create_list_and_dashboard_keep_free_text_outline(client) -> None:
    project = _create_project(client, title="雨城残响", key="list-dashboard")

    assert project["project_id"].startswith("PRJ_")
    assert project["title"] == "雨城残响"
    assert project["status"] == "outline_draft"
    assert "来自十年前的信" in project["outline_text"]

    list_response = client.get("/api/v1/projects")
    assert list_response.status_code == 200
    items = list_response.json()["data"]["items"]
    assert [item["project_id"] for item in items] == [project["project_id"]]

    dashboard_response = client.get(f"/api/v1/projects/{project['project_id']}/dashboard")
    assert dashboard_response.status_code == 200
    dashboard = dashboard_response.json()["data"]
    assert dashboard["project"]["project_id"] == project["project_id"]
    assert dashboard["project"]["outline_text"] == project["outline_text"]
    assert dashboard["next_action"] == "generate_outline_plan"
    assert dashboard["chapters"] == []


def test_outline_plan_generation_returns_reviewable_chapters_and_scenes(client) -> None:
    project = _create_project(client, target_chapter_count=2)

    plan = _generate_plan(client, project["project_id"])

    assert plan["status"] == "pending_review"
    chapters = plan["plan_json"]["chapters"]
    assert len(chapters) == 2
    assert chapters[0]["chapter_id"].endswith("_CH01")
    assert chapters[0]["chapter_goal"]
    assert chapters[0]["scenes"]
    assert chapters[0]["scenes"][0]["scene_id"].endswith("_SC01")
    assert chapters[0]["scenes"][0]["scene_goal"]
    assert chapters[0]["scenes"][0]["beats_json"]
    assert "禁复刻" in " ".join(plan["plan_json"]["reference_safety"])


def test_outline_plan_generation_uses_project_outline_llm_when_live(client, session, monkeypatch) -> None:
    class FakeOutlineRunner:
        def __init__(self, db_session) -> None:
            self.session = db_session

        def run(self, **kwargs):
            assert kwargs["node_id"] == "project_outline_plan"
            context = kwargs["context"]
            assert context.scope_type == "project"
            assert context.scope_id == kwargs["chapter_id"]
            assert context.project_id == kwargs["chapter_id"]
            assert context.chapter_id is None
            assert context.scene_id is None
            self.session.add(
                LlmCall(
                    llm_call_id="llm_call_project_outline_test",
                    scope_type="project",
                    scope_id=kwargs["chapter_id"],
                    provider="fake",
                    model="fake-model",
                    node_id="project_outline_plan",
                    step="project_outline_plan",
                    request_payload_summary={"template_name": "project_outline_plan"},
                    response_payload_summary={"source": "llm"},
                    prompt_tokens=1,
                    completion_tokens=1,
                    total_tokens=2,
                    latency_ms=1,
                )
            )
            self.session.flush()
            return SimpleNamespace(
                llm_call_id="llm_call_project_outline_test",
                response=SimpleNamespace(
                    structured_output={
                        "reference_safety": ["abstract craft only"],
                        "chapters": [
                            {
                                "title": "LLM Chapter One",
                                "chapter_goal": "Force the protagonist into a visible choice.",
                                "main_plot_push": "The old letter becomes actionable.",
                                "emotional_target": "Trust costs something visible.",
                                "ending_effect": "A new clue changes the next action.",
                                "must_not": "Do not copy source-book expression.",
                                "scenes": [
                                    {
                                        "scene_goal": "Open with the letter and a forced choice.",
                                        "beats_json": ["letter arrives", "choice is made"],
                                        "must_include_text": "letter",
                                        "forbidden_text": "source-book names",
                                        "exit_change": "The protagonist commits.",
                                        "hook": "A witness calls back.",
                                        "target_length_band": "medium",
                                        "scene_type": "plot_scene",
                                    }
                                ],
                            }
                        ],
                    }
                ),
            )

    monkeypatch.setenv("NOVEL_SYSTEM_LLM_ENABLED", "true")
    monkeypatch.setattr("novel_system.services.projects.LLMNodeRunner", FakeOutlineRunner, raising=False)
    project = _create_project(client, target_chapter_count=1, key="llm-plan")

    plan = _generate_plan(client, project["project_id"])

    assert plan["plan_json"]["source"] == "llm"
    assert plan["plan_json"]["llm_call_id"] == "llm_call_project_outline_test"
    assert plan["plan_json"]["chapters"][0]["title"] == "LLM Chapter One"
    assert session.get(LlmCall, "llm_call_project_outline_test") is not None


def test_approve_outline_plan_materializes_chapter_goals_and_scene_cards(client, session) -> None:
    project = _create_project(client, target_chapter_count=2)
    plan = _generate_plan(client, project["project_id"])

    result = _approve_plan(client, project["project_id"], plan["plan_id"])

    assert result["project"]["status"] == "chapter_ready"
    assert result["project"]["current_chapter_id"].endswith("_CH01")
    assert result["created_chapter_count"] == 2
    assert result["created_scene_count"] >= 2

    chapter = session.get(ChapterGoal, result["project"]["current_chapter_id"])
    assert chapter is not None
    assert chapter.project_id == project["project_id"]
    assert chapter.outline_plan_id == plan["plan_id"]
    assert chapter.writer_brief_json["source"] == "project_outline_plan"

    scenes = (
        session.query(SceneCard)
        .filter(SceneCard.chapter_id == result["project"]["current_chapter_id"])
        .order_by(SceneCard.scene_seq)
        .all()
    )
    assert scenes
    assert all(scene.project_id == project["project_id"] for scene in scenes)
    assert all(scene.outline_plan_id == plan["plan_id"] for scene in scenes)
    assert scenes[-1].is_chapter_last == 1


def test_ready_reference_profile_can_bind_to_project_but_draft_profile_cannot(client, session) -> None:
    project = _create_project(client)
    session.add(
        StyleReferenceBook(
            book_id="BOOK_STYLE",
            title="参考书",
            author_label="某作者",
            source_kind="path",
            source_path="ref.txt",
            cloud_policy="local_only",
            text_checksum="checksum",
            total_chars=120,
            status="ready",
            stats_json={},
        )
    )
    # SQLite FK enforcement is enabled in runtime.  Keep the fixture's write
    # order identical to the product contract instead of relying on ORM table
    # ordering for objects that do not declare relationships.
    session.flush()
    session.add(
        StyleReferenceRun(
            run_id="RUN_STYLE",
            book_id="BOOK_STYLE",
            status="done",
            phase="done",
            coverage_json={},
        )
    )
    session.flush()
    session.add(
        StyleReferenceProfile(
            profile_id="PROFILE_READY",
            book_id="BOOK_STYLE",
            run_id="RUN_STYLE",
            title="抽象风格画像",
            status="active",
            profile_json={"rhythm": ["短句推进"], "forbidden_copy_rules": ["不复制原文表达"]},
        )
    )
    session.add(
        StyleReferenceProfile(
            profile_id="PROFILE_DRAFT",
            book_id="BOOK_STYLE",
            run_id="RUN_STYLE",
            title="未完成画像",
            status="draft",
            profile_json={},
        )
    )
    session.commit()

    ready_response = client.post(
        f"/api/v1/projects/{project['project_id']}/reference-profiles",
        json={"profile_id": "PROFILE_READY"},
        headers={"X-Idempotency-Key": "bind-ready-profile"},
    )
    assert ready_response.status_code == 200
    payload = ready_response.json()["data"]
    assert payload["project"]["reference_profile_ids"] == ["PROFILE_READY"]
    assert payload["reference_profile"]["profile_id"] == "PROFILE_READY"
    assert payload["binding_id"].startswith("sr_bind_")
    assert payload["review_ids"] == []

    refreshed_project = session.get(StoryProject, project["project_id"])
    assert refreshed_project is not None

    bindings = session.execute(
        select(StyleReferenceInjectionBinding).where(
            StyleReferenceInjectionBinding.scope == "project",
            StyleReferenceInjectionBinding.scope_ref_id == project["project_id"],
            StyleReferenceInjectionBinding.task_type == "scene_generation",
        )
    ).scalars().all()
    assert [binding.profile_id for binding in bindings] == ["PROFILE_READY"]

    draft_response = client.post(
        f"/api/v1/projects/{project['project_id']}/reference-profiles",
        json={"profile_id": "PROFILE_DRAFT"},
        headers={"X-Idempotency-Key": "bind-draft-profile"},
    )
    assert draft_response.status_code == 409
    assert draft_response.json()["error"]["code"] == "REFERENCE_PROFILE_NOT_READY"

    dashboard_response = client.get(f"/api/v1/projects/{project['project_id']}/dashboard")
    assert dashboard_response.status_code == 200
    profiles = dashboard_response.json()["data"]["reference_profiles"]
    assert profiles == [
        {
            "profile_id": "PROFILE_READY",
            "title": "抽象风格画像",
            "status": "active",
            "profile_json": {"rhythm": ["短句推进"], "forbidden_copy_rules": ["不复制原文表达"]},
            "safe_summary": {
                "abstract_tags": [
                    {"label": "节奏", "summary": "短句推进"},
                    {"label": "安全提示", "summary": "不复制原文表达"},
                ],
                "safety_note": "仅使用抽象节奏、结构和安全规则；不展示或复制参考书原文。",
            },
            "binding_id": bindings[0].binding_id,
            "scope": "project",
            "scope_ref_id": project["project_id"],
            "task_type": "scene_generation",
            "strategy": "A",
        }
    ]


def test_project_chapter_run_stops_at_final_review_and_approve_final_advances(client, session, monkeypatch) -> None:
    class FakeChapterRunnerService:
        def __init__(self, db_session) -> None:
            self.session = db_session

        def run_full(self, chapter_id: str) -> dict:
                scenes = (
                    self.session.query(SceneCard)
                    .filter(SceneCard.chapter_id == chapter_id)
                    .order_by(SceneCard.scene_seq)
                    .all()
                )
                for scene in scenes:
                    final_row_id = f"fake_final_{scene.scene_id}"
                    self.session.add(
                        FinalScene(
                            row_id=final_row_id,
                            scene_id=scene.scene_id,
                            chapter_id=chapter_id,
                            source_bundle_id=f"fake_bundle_{scene.scene_id}",
                            source_bundle_hash=f"fake_hash_{scene.scene_id}",
                            content=f"Final body for {scene.scene_id}.",
                        )
                    )
                    state = self.session.get(SceneRunState, scene.scene_id)
                    if state is not None:
                        state.current_final_scene_row_id = final_row_id
                        state.narrative_sync_status = "synced"
                        state.narrative_sync_final_scene_row_id = final_row_id
                self.session.flush()
                canon = CanonContinuityService(self.session)
                for scene in scenes:
                    canon.verify_scene_complete(
                        scene.project_id,
                        scene.scene_id,
                        actor_ref="test-runner",
                        note="测试运行器模拟作者完成正史核验。",
                    )
                result = {
                    "chapter_id": chapter_id,
                    "status": "completed",
                    "current_scene_id": scenes[-1].scene_id if scenes else None,
                    "completed_scene_ids": [scene.scene_id for scene in scenes],
                    "blocked_scene_id": None,
                    "latest_error": None,
                }
                self.session.add(
                    ChapterRunJob(
                        job_id=f"fake_job_{chapter_id}",
                        chapter_id=chapter_id,
                        status="completed",
                        job_type="chapter_full",
                        payload_json=result,
                        result_summary_json={"near_final_ready": True},
                    )
                )
                self.session.flush()
                return result

    monkeypatch.setattr("novel_system.services.projects.ChapterRunnerService", FakeChapterRunnerService)
    project = _create_project(client, target_chapter_count=2)
    plan = _generate_plan(client, project["project_id"])
    approved = _approve_plan(client, project["project_id"], plan["plan_id"])
    first_chapter_id = approved["project"]["current_chapter_id"]

    run_response = client.post(
        f"/api/v1/projects/{project['project_id']}/chapters/{first_chapter_id}/run",
        json={},
        headers={"X-Idempotency-Key": "run-project-chapter-1"},
    )
    assert run_response.status_code == 200
    run_payload = run_response.json()["data"]
    assert run_payload["project"]["status"] == "chapter_final_review"
    assert run_payload["review_packet"]["chapter_id"] == first_chapter_id
    assert run_payload["review_packet"]["issues_summary"] == []

    dashboard_response = client.get(f"/api/v1/projects/{project['project_id']}/dashboard")
    assert dashboard_response.status_code == 200
    dashboard_payload = dashboard_response.json()["data"]
    assert dashboard_payload["next_action"] == "approve_chapter_final"
    body_hash = dashboard_payload["review_packet"]["body_hash"]

    read_response = client.post(
        f"/api/v1/projects/{project['project_id']}/chapters/{first_chapter_id}/read-confirm",
        json={"note": "Read in full before approving."},
    )
    assert read_response.status_code == 200
    assert read_response.json()["data"]["body_hash"] == body_hash

    approve_response = client.post(
        f"/api/v1/projects/{project['project_id']}/chapters/{first_chapter_id}/approve-final",
        json={"revision_notes": "Keep the second scene tense on the next pass."},
        headers={"X-Idempotency-Key": "approve-project-chapter-1"},
    )
    assert approve_response.status_code == 200
    approve_payload = approve_response.json()["data"]
    next_project = approve_payload["project"]
    assert next_project["status"] == "chapter_ready"
    assert next_project["current_chapter_id"].endswith("_CH02")
    assert next_project["approved_chapter_ids"] == [first_chapter_id]
    assert approve_payload["approval_note"]["revision_notes"] == "Keep the second scene tense on the next pass."

    approval_log = session.execute(
        select(OperationLog).where(
            OperationLog.event_type == "chapter_final_approval",
            OperationLog.object_type == "chapter",
            OperationLog.object_ref == first_chapter_id,
        )
    ).scalar_one()
    assert approval_log.payload_json["revision_notes"] == "Keep the second scene tense on the next pass."
    assert approval_log.payload_json["project_id"] == project["project_id"]
    session.expire_all()
    assert session.get(ChapterGoal, first_chapter_id).state == "approved"


def test_project_chapter_final_requires_current_read_confirmation(client, session) -> None:
    project = _create_project(client, target_chapter_count=1, key="read-confirm")
    plan = _generate_plan(client, project["project_id"])
    approved = _approve_plan(client, project["project_id"], plan["plan_id"])
    chapter_id = approved["project"]["current_chapter_id"]
    scenes = session.query(SceneCard).filter(SceneCard.chapter_id == chapter_id).all()
    assert scenes
    final_rows = []
    for index, scene in enumerate(scenes, start=1):
        final_row = FinalScene(
            row_id=f"final_{scene.scene_id}",
            scene_id=scene.scene_id,
            chapter_id=chapter_id,
            source_bundle_id=f"bundle_read_confirm_{index}",
            source_bundle_hash=f"hash_read_confirm_{index}",
            content=f"第一版正文，需要通读后才能批准。场景 {index}。",
        )
        final_rows.append(final_row)
        session.add(final_row)
        state = session.get(SceneRunState, scene.scene_id)
        assert state is not None
        state.current_final_scene_row_id = final_row.row_id
        state.narrative_sync_status = "synced"
        state.narrative_sync_final_scene_row_id = final_row.row_id
    session.flush()
    canon = CanonContinuityService(session)
    for scene in scenes:
        canon.verify_scene_complete(
            project["project_id"],
            scene.scene_id,
            actor_ref="test-author",
            note="测试已通读本场正史。",
        )
    session.add(
        ChapterRunJob(
            job_id=f"read_confirm_job_{chapter_id}",
            chapter_id=chapter_id,
            status="completed",
            job_type="chapter_run_full",
            payload_json={},
            result_summary_json={"latest_error": None},
        )
    )
    db_project = session.get(StoryProject, project["project_id"])
    assert db_project is not None
    db_project.status = "chapter_final_review"
    session.commit()

    dashboard_response = client.get(f"/api/v1/projects/{project['project_id']}/dashboard")
    assert dashboard_response.status_code == 200
    packet = dashboard_response.json()["data"]["review_packet"]
    assert packet["body"].startswith("第一版正文")
    assert packet["body_hash"]
    assert packet["read_confirmation"] is None

    approve_response = client.post(
        f"/api/v1/projects/{project['project_id']}/chapters/{chapter_id}/approve-final",
        json={},
        headers={"X-Idempotency-Key": "approve-without-read-confirm"},
    )
    assert approve_response.status_code == 409
    assert approve_response.json()["error"]["code"] == "CHAPTER_FINAL_READ_CONFIRM_REQUIRED"

    confirm_response = client.post(
        f"/api/v1/projects/{project['project_id']}/chapters/{chapter_id}/read-confirm",
        json={"note": "Read full chapter."},
        headers={"X-Operator-Ref": "author-c"},
    )
    assert confirm_response.status_code == 200, confirm_response.text
    confirmed = confirm_response.json()["data"]
    assert confirmed["chapter_id"] == chapter_id
    assert confirmed["body_hash"] == packet["body_hash"]
    assert confirmed["confirmed_by"] == "author-c"

    dashboard_after_confirm = client.get(f"/api/v1/projects/{project['project_id']}/dashboard").json()["data"]
    assert dashboard_after_confirm["review_packet"]["read_confirmation"]["body_hash"] == packet["body_hash"]

    previous_final = final_rows[0]
    replacement = FinalScene(
        row_id=f"{previous_final.row_id}_v2",
        scene_id=previous_final.scene_id,
        chapter_id=previous_final.chapter_id,
        source_bundle_id=previous_final.source_bundle_id,
        source_bundle_hash=previous_final.source_bundle_hash,
        parent_final_scene_row_id=previous_final.row_id,
        content="第二版正文已经变化，旧阅读确认不能批准。",
        status="archived",
    )
    previous_final.status = "superseded"
    previous_final.superseded_by_final_scene_row_id = replacement.row_id
    session.add(replacement)
    state = session.get(SceneRunState, previous_final.scene_id)
    state.current_final_scene_row_id = replacement.row_id
    state.narrative_sync_status = "pending_review"
    state.narrative_sync_final_scene_row_id = replacement.row_id
    session.flush()
    CanonContinuityService(session).verify_scene_complete(
        project["project_id"],
        scenes[0].scene_id,
        actor_ref="author-c",
        note="第二版正文形成新终稿后重新核对本场正史。",
    )
    session.commit()
    changed_packet = client.get(f"/api/v1/projects/{project['project_id']}/dashboard").json()["data"]["review_packet"]
    assert changed_packet["body_hash"] != packet["body_hash"]
    assert changed_packet["read_confirmation"] is None

    changed_approve = client.post(
        f"/api/v1/projects/{project['project_id']}/chapters/{chapter_id}/approve-final",
        json={},
        headers={"X-Idempotency-Key": "approve-stale-read-confirm"},
    )
    assert changed_approve.status_code == 409
    assert changed_approve.json()["error"]["code"] == "CHAPTER_FINAL_READ_CONFIRM_REQUIRED"

    confirm_changed = client.post(
        f"/api/v1/projects/{project['project_id']}/chapters/{chapter_id}/read-confirm",
        json={"note": "Read changed body."},
        headers={"X-Operator-Ref": "author-c"},
    )
    assert confirm_changed.status_code == 200

    approve_after_confirm = client.post(
        f"/api/v1/projects/{project['project_id']}/chapters/{chapter_id}/approve-final",
        json={"revision_notes": "Ready after reading."},
        headers={"X-Idempotency-Key": "approve-after-read-confirm"},
    )
    assert approve_after_confirm.status_code == 200, approve_after_confirm.text
    assert approve_after_confirm.json()["data"]["project"]["status"] == "completed"

    read_log = (
        session.query(OperationLog)
        .filter_by(event_type="chapter_final_read_confirmed", object_type="chapter", object_ref=chapter_id)
        .order_by(OperationLog.operation_id.desc())
        .first()
    )
    assert read_log.payload_json["confirmed_by"] == "author-c"


def test_project_review_packet_uses_aggregate_or_assembled_manuscript_body(client, session) -> None:
    project = _create_project(client, target_chapter_count=1, key="review-packet-body")
    plan = _generate_plan(client, project["project_id"])
    approved = _approve_plan(client, project["project_id"], plan["plan_id"])
    chapter_id = approved["project"]["current_chapter_id"]
    scenes = (
        session.query(SceneCard)
        .filter(SceneCard.chapter_id == chapter_id)
        .order_by(SceneCard.scene_seq)
        .all()
    )
    assert scenes

    for index, scene in enumerate(scenes, start=1):
        final_row_id = f"final_{scene.scene_id}"
        session.add(
            FinalScene(
                row_id=final_row_id,
                scene_id=scene.scene_id,
                chapter_id=chapter_id,
                content=f"assembled scene {index}",
                source_bundle_id=f"bundle_{index}",
                source_bundle_hash=f"hash_{index}",
            )
        )
        state = session.get(SceneRunState, scene.scene_id)
        assert state is not None
        state.current_final_scene_row_id = final_row_id
        state.scene_status = "archived"

    session.add(
        ChapterMemory(
            row_id="chapter_memory_final",
            chapter_id=chapter_id,
            aggregate_stage="final",
            content="aggregate chapter body",
            active_flag=1,
            runtime_eligible=1,
            runtime_eligibility_basis="final_aggregate",
        )
    )
    session.add(
        ChapterRunJob(
            job_id=f"completed_job_{chapter_id}",
            chapter_id=chapter_id,
            status="completed",
            job_type="chapter_run_full",
            payload_json={},
            result_summary_json={"latest_error": None},
        )
    )
    db_project = session.get(StoryProject, project["project_id"])
    assert db_project is not None
    db_project.status = "chapter_final_review"
    session.commit()

    response = client.get(f"/api/v1/projects/{project['project_id']}/dashboard")

    assert response.status_code == 200
    packet = response.json()["data"]["review_packet"]
    assert packet["chapter_id"] == chapter_id
    assert packet["body"] == "aggregate chapter body"
    assert packet["body_source"] == "aggregate"
    assert packet["char_count"] == len("aggregate chapter body")
    assert packet["body_empty_reason"] is None
    assert packet["completion_status"] == "complete"
    assert packet["comparison_status"] == "aggregate_differs_current"
    assert packet["missing_scene_ids"] == []
    assert packet["scene_coverage"]["completed_count"] == len(scenes)
    assert packet["scene_coverage"]["total_count"] == len(scenes)
    assert packet["scene_coverage"]["percent"] == 100
    assert packet["missing_scene_labels"] == []
    assert packet["target_word_count_band"]["target"] == 120000
    assert packet["target_word_count_band"]["min"] == 102000
    assert packet["target_word_count_band"]["max"] == 138000
    assert packet["aggregate_row_id"] == "chapter_memory_final"
    assert "source_safety_scan" in packet


def test_project_final_review_can_request_scene_revision_without_advancing_chapter(client, session) -> None:
    project = _create_project(client, target_chapter_count=1, key="scene-revision-review")
    plan = _generate_plan(client, project["project_id"])
    approved = _approve_plan(client, project["project_id"], plan["plan_id"])
    chapter_id = approved["project"]["current_chapter_id"]
    scenes = (
        session.query(SceneCard)
        .filter(SceneCard.chapter_id == chapter_id)
        .order_by(SceneCard.scene_seq)
        .all()
    )
    assert scenes
    first_scene = scenes[0]
    for index, scene in enumerate(scenes, start=1):
        final_row_id = f"final_review_{scene.scene_id}"
        session.add(
            FinalScene(
                row_id=final_row_id,
                scene_id=scene.scene_id,
                chapter_id=chapter_id,
                content=f"final scene {index} body",
                source_bundle_id=f"bundle_review_{index}",
                source_bundle_hash=f"hash_review_{index}",
            )
        )
        state = session.get(SceneRunState, scene.scene_id)
        assert state is not None
        state.current_final_scene_row_id = final_row_id
        state.scene_status = "archived"
    session.add(
        ChapterRunJob(
            job_id=f"review_job_{chapter_id}",
            chapter_id=chapter_id,
            status="completed",
            job_type="chapter_run_full",
            payload_json={},
            result_summary_json={"latest_error": None},
        )
    )
    db_project = session.get(StoryProject, project["project_id"])
    assert db_project is not None
    db_project.status = "chapter_final_review"
    session.commit()

    dashboard_response = client.get(f"/api/v1/projects/{project['project_id']}/dashboard")
    assert dashboard_response.status_code == 200
    packet = dashboard_response.json()["data"]["review_packet"]
    assert packet["scene_reviews"][0]["scene_id"] == first_scene.scene_id
    assert packet["scene_reviews"][0]["body_excerpt"].startswith("final scene 1")

    response = client.post(
        f"/api/v1/projects/{project['project_id']}/chapters/{chapter_id}/final-review",
        json={
            "decision": "request_scene_revision",
            "revision_notes": "The first scene needs a visible cost before approval.",
            "scene_decisions": [
                {
                    "scene_id": first_scene.scene_id,
                    "decision": "request_revision",
                    "note": "Add a consequence the protagonist cannot undo.",
                }
            ],
        },
        headers={"X-Idempotency-Key": "final-review-scene-revision"},
    )

    assert response.status_code == 200, response.text
    payload = response.json()["data"]
    assert payload["project"]["status"] == "chapter_blocked"
    assert payload["project"]["current_chapter_id"] == chapter_id
    assert payload["review_decision"]["decision"] == "request_scene_revision"
    assert payload["backtrack_items"][0]["scene_id"] == first_scene.scene_id
    session.expire_all()
    db_project = session.get(StoryProject, project["project_id"])
    assert db_project.current_chapter_id == chapter_id
    assert db_project.approved_chapter_ids_json == []
    backtrack = session.query(ProjectBacktrackItem).filter_by(scene_id=first_scene.scene_id, status="pending").one()
    assert backtrack.problem_summary == "Add a consequence the protagonist cannot undo."


def test_project_review_packet_reports_empty_body_reason(client, session) -> None:
    project = _create_project(client, target_chapter_count=1, key="review-packet-empty")
    plan = _generate_plan(client, project["project_id"])
    approved = _approve_plan(client, project["project_id"], plan["plan_id"])
    chapter_id = approved["project"]["current_chapter_id"]
    session.add(
        ChapterRunJob(
            job_id=f"empty_job_{chapter_id}",
            chapter_id=chapter_id,
            status="completed",
            job_type="chapter_run_full",
            payload_json={},
            result_summary_json={"latest_error": None},
        )
    )
    db_project = session.get(StoryProject, project["project_id"])
    assert db_project is not None
    db_project.status = "chapter_final_review"
    session.commit()

    response = client.get(f"/api/v1/projects/{project['project_id']}/dashboard")

    assert response.status_code == 200
    packet = response.json()["data"]["review_packet"]
    assert packet["body"] == ""
    assert packet["body_source"] == "empty"
    assert packet["body_empty_reason"] == "no_generated_scenes"
    assert packet["completion_status"] == "empty"
    assert packet["missing_scene_ids"]
    assert packet["scene_coverage"]["completed_count"] == 0
    assert packet["scene_coverage"]["total_count"] == len(packet["scene_reviews"])
    assert packet["missing_scene_labels"]
    assert packet["missing_scene_labels"][0].startswith("第 1 场：")


def test_project_chapter_run_job_blocks_when_llm_disabled(client, monkeypatch) -> None:
    monkeypatch.setenv("NOVEL_SYSTEM_LLM_ENABLED", "false")
    project = _create_project(client, target_chapter_count=1, key="run-job-offline")
    plan = _generate_plan(client, project["project_id"])
    approved = _approve_plan(client, project["project_id"], plan["plan_id"])
    chapter_id = approved["project"]["current_chapter_id"]

    response = client.post(
        f"/api/v1/projects/{project['project_id']}/chapters/{chapter_id}/run-job",
        headers={"X-Idempotency-Key": "run-job-offline"},
    )

    assert response.status_code == 409
    error = response.json()["error"]
    assert error["code"] == "LLM_DISABLED_FOR_CHAPTER_RUN"
    assert error["details"]["author_action"] == {
        "title": "需要先启用真实模型",
        "message": "当前还没有可用的 LLM 运行配置。配置 provider、密钥/地址并测试通过后，再开始章节起草。",
        "target_view": "config",
        "target_ref": "system_config:llm",
        "primary_button_label": "去系统配置",
        "evidence_summary": ["llm_enabled=false", "generation_mode=offline_disabled"],
    }

    dashboard_response = client.get(f"/api/v1/projects/{project['project_id']}/dashboard")
    assert dashboard_response.status_code == 200
    runtime = dashboard_response.json()["data"]["runtime"]
    assert runtime["llm_enabled"] is False
    assert runtime["provider_ready"] is False
    assert "missing_routes" in runtime
    assert runtime["next_setup_action"]["target_view"] == "config"


def test_project_chapter_run_job_reuses_existing_running_job(client, session, monkeypatch) -> None:
    project = _create_project(client, target_chapter_count=1, key="run-job-reuse")
    plan = _generate_plan(client, project["project_id"])
    approved = _approve_plan(client, project["project_id"], plan["plan_id"])
    monkeypatch.setenv("NOVEL_SYSTEM_LLM_ENABLED", "true")
    chapter_id = approved["project"]["current_chapter_id"]
    session.add(
        ChapterRunJob(
            job_id="chapter_run_existing",
            chapter_id=chapter_id,
            status="running",
            job_type="chapter_run_full",
            payload_json={
                "scene_ids": [scene["scene_id"] for scene in approved["plan"]["plan_json"]["chapters"][0]["scenes"]],
                "completed_scene_ids": [],
                "current_scene_id": None,
                "blocked_scene_id": None,
            },
            result_summary_json={
                "scene_ids": [scene["scene_id"] for scene in approved["plan"]["plan_json"]["chapters"][0]["scenes"]],
                "completed_scene_ids": [],
                "current_scene_id": None,
                "blocked_scene_id": None,
                "latest_error": None,
            },
        )
    )
    session.commit()

    started_jobs = []
    monkeypatch.setattr(
        "novel_system.api.routes.projects.start_project_chapter_run_job_worker",
        lambda *args: started_jobs.append(args),
        raising=False,
    )

    response = client.post(
        f"/api/v1/projects/{project['project_id']}/chapters/{chapter_id}/run-job",
        json={},
        headers={"X-Idempotency-Key": "run-job-reuse"},
    )

    assert response.status_code == 200
    payload = response.json()["data"]
    assert payload["project"]["status"] == "chapter_running"
    assert payload["run"]["job_id"] == "chapter_run_existing"
    assert payload["run"]["status"] == "running"
    assert started_jobs == []


def test_project_chapter_flow_request_contracts_are_strict(client) -> None:
    base = "/api/v1/projects/missing-project/chapters/missing-chapter"
    cases = [
        (f"{base}/run-job", {"offline_demo": "true"}, "body.offline_demo", "bool_type"),
        (f"{base}/run-job", {"allow_demo": True}, "body.allow_demo", "extra_forbidden"),
        (f"{base}/run-job", {"offline_demo": False, "unexpected": 1}, "body.unexpected", "extra_forbidden"),
        (f"{base}/read-confirm", {"note": "x", "unexpected": 1}, "body.unexpected", "extra_forbidden"),
        (f"{base}/approve-final", {"revision_notes": "x", "unexpected": 1}, "body.unexpected", "extra_forbidden"),
    ]

    for path, body, expected_field, expected_type in cases:
        response = client.post(path, json=body, headers={"X-Idempotency-Key": f"strict-{expected_field}-{expected_type}"})
        assert response.status_code == 422, response.text
        error = response.json()["error"]
        assert error["code"] == "REQUEST_VALIDATION_FAILED"
        assert any(
            issue["field"] == expected_field and issue["type"] == expected_type
            for issue in error["details"]["issues"]
        )


def test_project_chapter_run_service_rejects_non_boolean_or_legacy_demo_flags(session) -> None:
    service = ProjectChapterFlowService(session)
    with pytest.raises(DomainError) as non_boolean:
        service.prepare_chapter_run_job("missing-project", "missing-chapter", offline_demo="true")
    assert non_boolean.value.code == "INVALID_CHAPTER_RUN_MODE"

    with pytest.raises(TypeError):
        service.prepare_chapter_run_job("missing-project", "missing-chapter", allow_demo=True)


def test_project_chapter_flow_request_length_boundaries(client) -> None:
    base = "/api/v1/projects/missing-project/chapters/missing-chapter"
    accepted_cases = [
        (f"{base}/read-confirm", None),
        (f"{base}/read-confirm", {"note": "x" * 1000}),
        (f"{base}/approve-final", None),
        (f"{base}/approve-final", {"revision_notes": "x" * 2000}),
    ]
    for index, (path, body) in enumerate(accepted_cases):
        kwargs = {"headers": {"X-Idempotency-Key": f"accepted-boundary-{index}"}}
        if body is not None:
            kwargs["json"] = body
        response = client.post(path, **kwargs)
        assert response.status_code == 404, response.text
        assert response.json()["error"]["code"] == "PROJECT_NOT_FOUND"

    rejected_cases = [
        (f"{base}/read-confirm", {"note": "x" * 1001}, "body.note"),
        (f"{base}/approve-final", {"revision_notes": "x" * 2001}, "body.revision_notes"),
    ]
    for index, (path, body, expected_field) in enumerate(rejected_cases):
        response = client.post(path, json=body, headers={"X-Idempotency-Key": f"rejected-boundary-{index}"})
        assert response.status_code == 422, response.text
        issues = response.json()["error"]["details"]["issues"]
        assert any(issue["field"] == expected_field and issue["type"] == "string_too_long" for issue in issues)


def test_reopen_final_cascades_approval_state_and_is_idempotent(client, session) -> None:
    project = _create_project(client, target_chapter_count=3, key="reopen-final")
    plan = _generate_plan(client, project["project_id"])
    _approve_plan(client, project["project_id"], plan["plan_id"])
    chapter_ids = [
        row[0]
        for row in session.execute(
            select(ChapterGoal.chapter_id)
            .where(ChapterGoal.project_id == project["project_id"])
            .order_by(ChapterGoal.display_order.asc(), ChapterGoal.chapter_id.asc())
        ).all()
    ]
    assert len(chapter_ids) == 3
    db_project = session.get(StoryProject, project["project_id"])
    db_project.approved_chapter_ids_json = list(chapter_ids)
    db_project.current_chapter_id = None
    db_project.status = "completed"
    for chapter_id in chapter_ids:
        session.get(ChapterGoal, chapter_id).state = "approved"
    for chapter_id in chapter_ids[1:]:
        session.add(
            OperationLog(
                event_type="chapter_final_read_confirmed",
                object_type="chapter",
                object_ref=chapter_id,
                payload_json={
                    "project_id": project["project_id"],
                    "chapter_id": chapter_id,
                    "body_hash": f"body-hash-{chapter_id}",
                    "confirmed_by": "author-reopener",
                },
            )
        )
    session.commit()

    target_id = chapter_ids[1]
    path = f"/api/v1/projects/{project['project_id']}/chapters/{target_id}/reopen-final"
    headers = {"X-Idempotency-Key": "reopen-final-cascade", "X-Operator-Ref": "author-reopener"}
    response = client.post(path, json={"reason": "Revise the causal bridge."}, headers=headers)

    assert response.status_code == 200, response.text
    payload = response.json()["data"]
    assert payload["invalidated_chapter_ids"] == chapter_ids[1:]
    assert payload["project"]["approved_chapter_ids"] == chapter_ids[:1]
    assert payload["project"]["current_chapter_id"] == target_id
    assert payload["project"]["status"] == "chapter_ready"
    session.expire_all()
    assert session.get(ChapterGoal, chapter_ids[0]).state == "approved"
    assert session.get(ChapterGoal, target_id).state == "draft"
    assert session.get(ChapterGoal, chapter_ids[2]).state == "planned"
    flow = ProjectChapterFlowService(session)
    for chapter_id in chapter_ids[1:]:
        assert flow._latest_read_confirmation(
            project["project_id"],
            chapter_id,
            f"body-hash-{chapter_id}",
        ) is None

    audit = session.execute(
        select(OperationLog).where(
            OperationLog.event_type == "chapter_final_reopened",
            OperationLog.object_ref == target_id,
        )
    ).scalar_one()
    assert audit.payload_json["reason"] == "Revise the causal bridge."
    assert audit.payload_json["invalidated_chapter_ids"] == chapter_ids[1:]
    assert audit.payload_json["actor_ref"] == "author-reopener"

    replay = client.post(path, json={"reason": "Revise the causal bridge."}, headers=headers)
    assert replay.status_code == 200, replay.text
    assert replay.headers["X-Idempotency-Status"] == "replayed"
    assert replay.json()["data"]["invalidated_chapter_ids"] == chapter_ids[1:]
    reopen_log_count = session.execute(
        select(OperationLog).where(OperationLog.event_type == "chapter_final_reopened")
    ).scalars().all()
    assert len(reopen_log_count) == 1

    no_longer_approved = client.post(
        path,
        json={"reason": "Try again."},
        headers={"X-Idempotency-Key": "reopen-final-not-approved"},
    )
    assert no_longer_approved.status_code == 409
    assert no_longer_approved.json()["error"]["code"] == "CHAPTER_FINAL_NOT_APPROVED"


def test_reopen_final_request_contract_is_strict(client) -> None:
    path = "/api/v1/projects/missing-project/chapters/missing-chapter/reopen-final"
    cases = [
        ({}, "body.reason", "missing"),
        ({"reason": "   "}, "body.reason", "value_error"),
        ({"reason": "x" * 1001}, "body.reason", "string_too_long"),
        ({"reason": "valid", "unexpected": True}, "body.unexpected", "extra_forbidden"),
    ]
    for index, (body, expected_field, expected_type) in enumerate(cases):
        response = client.post(
            path,
            json=body,
            headers={"X-Idempotency-Key": f"reopen-strict-{index}"},
        )
        assert response.status_code == 422, response.text
        issues = response.json()["error"]["details"]["issues"]
        assert any(issue["field"] == expected_field and issue["type"] == expected_type for issue in issues)
