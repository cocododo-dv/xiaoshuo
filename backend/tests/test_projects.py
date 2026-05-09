from __future__ import annotations

from types import SimpleNamespace

from novel_system.db.models import (
    ChapterGoal,
    ChapterRunJob,
    LlmCall,
    ReferenceBook,
    ReferenceLearningRun,
    ReferenceProfile,
    SceneCard,
)


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
            self.session.add(
                LlmCall(
                    llm_call_id="llm_call_project_outline_test",
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
        ReferenceBook(
            book_id="BOOK_STYLE",
            title="参考书",
            author_label="某作者",
            source_kind="path",
            source_path="ref.txt",
            cloud_policy="local_only",
            analysis_focus="style_structure",
            text_checksum="checksum",
            status="profile_ready",
        )
    )
    session.add(
        ReferenceLearningRun(
            run_id="RUN_STYLE",
            book_id="BOOK_STYLE",
            status="completed",
            batch_size=8,
            profile_id="PROFILE_READY",
        )
    )
    session.add(
        ReferenceProfile(
            profile_id="PROFILE_READY",
            book_id="BOOK_STYLE",
            run_id="RUN_STYLE",
            title="抽象风格画像",
            status="ready",
            profile_json={"rhythm": ["短句推进"], "forbidden_copy_rules": ["不复制原文表达"]},
        )
    )
    session.add(
        ReferenceProfile(
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
    assert ready_response.json()["data"]["project"]["reference_profile_ids"] == ["PROFILE_READY"]

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
            "status": "ready",
            "profile_json": {"rhythm": ["短句推进"], "forbidden_copy_rules": ["不复制原文表达"]},
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
    assert dashboard_response.json()["data"]["next_action"] == "approve_chapter_final"

    approve_response = client.post(
        f"/api/v1/projects/{project['project_id']}/chapters/{first_chapter_id}/approve-final",
        json={},
        headers={"X-Idempotency-Key": "approve-project-chapter-1"},
    )
    assert approve_response.status_code == 200
    next_project = approve_response.json()["data"]["project"]
    assert next_project["status"] == "chapter_ready"
    assert next_project["current_chapter_id"].endswith("_CH02")
    assert next_project["approved_chapter_ids"] == [first_chapter_id]
