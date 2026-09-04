"""Writer review: a failing *revision* leg must degrade, never surface as a bare 500.

The diagnosis leg already persisted a blocked evaluation on ``LLMNodeExecutionError``;
the revision leg (``writer_scene_revision`` / ``writer_chapter_revision``) did not
handle ``LLMNodeContinuityError`` (prompt over the continuity input budget) and the
whole ``POST .../writer-review/run`` exploded with ``500 INTERNAL_ERROR`` after the
diagnosis rows were already committed.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from novel_system.db.models import (
    ChapterGoal,
    FinalScene,
    RevisionCandidate,
    SceneCard,
    SceneRunState,
    StoryProject,
    WriterEvaluation,
)
from novel_system.services.llm_client import LLMResponse, OnlineAccountedExecution
from novel_system.services.llm_task_runner import (
    CONTINUITY_BUDGET_ERROR_CODE,
    CONTINUITY_BUDGET_MESSAGE,
    SCENE_SPLIT_RECOMMENDATION,
    LLMNodeContinuityError,
    LLMNodeExecutionError,
    LLMNodeRunner,
)
from novel_system.services.writer_review import (
    REVISION_BLOCKER_DIMENSION,
    WRITER_REVIEW_LENSES,
    WriterReviewService,
)
from tests.real_llm_fakes import install_online_writer_pipeline

PROJECT_ID = "PROJECT_WR_BUDGET"
CHAPTER_ID = "CH_WR_BUDGET_01"
SCENE_ID = "CH_WR_BUDGET_01_SC01"
FINAL_ROW_ID = "final_wr_budget_01"

CONTINUITY_WARNING = {
    "code": "continuity_budget_exceeded",
    "message": "Prompt still exceeds the safe input budget after deterministic continuity compaction.",
    "recommended_action": "split_scene",
    "requires_scene_split": True,
    "compressed_sections": ["chapter_summary"],
    "omitted_sections": [],
    "estimated_input_tokens": 91000,
    "target_input_tokens": 24000,
}


@pytest.fixture(autouse=True)
def _online_writer_pipeline(monkeypatch):
    install_online_writer_pipeline(monkeypatch)


def _seed_scene_with_final(session) -> None:
    session.add(StoryProject(project_id=PROJECT_ID, title="Writer review budget", outline_text=""))
    session.add(
        ChapterGoal(
            chapter_id=CHAPTER_ID,
            project_id=PROJECT_ID,
            planned_scene_count=1,
            chapter_goal="主角第一次意识到盟友隐瞒了关键事实。",
            main_plot_push="把线索从传闻推进到可验证证据。",
            emotional_target="信任被轻轻撕开。",
            ending_effect="留下一个温柔但危险的疑问。",
            writer_brief_json={
                "core_promise": "一次看似平静的同行，露出背叛的缝隙。",
                "plot_movement": "主线获得证据入口。",
                "character_shift": "主角从依赖转向试探。",
                "chapter_question": "盟友究竟在保护谁？",
                "ending_aftertaste": "亲近关系开始发冷。",
            },
        )
    )
    session.add(
        SceneCard(
            scene_id=SCENE_ID,
            chapter_id=CHAPTER_ID,
            scene_seq=1,
            scene_goal="主角试探盟友，却发现对方避开了最关键的名字。",
            exit_change="主角决定暗中核查盟友的行踪。",
            hook="那个名字一出口，盟友杯中的茶晃了一下。",
            writer_brief_json={
                "character_desire": "主角想确认盟友是否可信。",
                "obstacle": "盟友用玩笑遮住事实。",
                "stakes": "判断错就会把证据交给错误的人。",
                "subtext": "两人都在隐瞒。",
                "irreversible_change": "主角第一次把盟友列为调查对象。",
                "reader_question": "盟友为什么不能说出那个名字？",
            },
        )
    )
    session.add(
        SceneRunState(
            scene_id=SCENE_ID,
            scene_status="finalized",
            current_final_scene_row_id=FINAL_ROW_ID,
            current_bundle_id="bundle_wr_budget_01",
            current_bundle_hash="hash_wr_budget_01",
        )
    )
    session.add(
        FinalScene(
            row_id=FINAL_ROW_ID,
            scene_id=SCENE_ID,
            chapter_id=CHAPTER_ID,
            content="茶盏在桌面上轻轻一响。她问出那个名字时，他先笑，随后说窗外雨声太大。",
            status="approved",
            source_bundle_id="bundle_wr_budget_01",
            source_bundle_hash="hash_wr_budget_01",
        )
    )
    session.commit()


def _install_failing_revision_node(monkeypatch, *, failing_node_id: str, error: Exception) -> list[str]:
    """Let the diagnosis lenses run through the online fake, fail only the revision node."""

    seen: list[str] = []
    original_run = LLMNodeRunner.run

    def patched_run(self, *, node_id, **kwargs):
        seen.append(node_id)
        if node_id == failing_node_id:
            raise error
        return original_run(self, node_id=node_id, **kwargs)

    monkeypatch.setattr(LLMNodeRunner, "run", patched_run)
    return seen


def _continuity_error(node_id: str) -> LLMNodeContinuityError:
    return LLMNodeContinuityError(
        llm_call_id=f"llm_call_{node_id}_budget",
        request_summary={"node_id": node_id},
        response_summary={
            "message": CONTINUITY_BUDGET_MESSAGE,
            "continuity_warning": CONTINUITY_WARNING,
            "recommended_action": SCENE_SPLIT_RECOMMENDATION,
        },
        continuity_warning=CONTINUITY_WARNING,
    )


def _aggregate_evaluation(session, *, object_type: str, object_id: str) -> WriterEvaluation:
    session.expire_all()
    rows = (
        session.query(WriterEvaluation)
        .filter_by(object_type=object_type, object_id=object_id, parent_evaluation_id=None)
        .all()
    )
    assert len(rows) == 1
    return rows[0]


def _blocker_finding(evaluation: WriterEvaluation) -> dict:
    matches = [item for item in (evaluation.findings_json or []) if item.get("dimension") == REVISION_BLOCKER_DIMENSION]
    assert len(matches) == 1
    return matches[0]


def test_scene_writer_review_continuity_budget_on_revision_returns_200_with_persisted_blocker(
    client: TestClient, session, monkeypatch
) -> None:
    _seed_scene_with_final(session)
    seen = _install_failing_revision_node(
        monkeypatch,
        failing_node_id="writer_scene_revision",
        error=_continuity_error("writer_scene_revision"),
    )

    response = client.post(f"/api/v1/scenes/{SCENE_ID}/writer-review/run")

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["ok"] is True
    data = body["data"]
    # 四个诊断镜头先跑完，修订节点才被预算拒绝：诊断结果不能被修订失败吞掉。
    assert seen == [*[lens.scene_node_id for lens in WRITER_REVIEW_LENSES], "writer_scene_revision"]
    assert data["evaluation"]["overall_score"] is not None
    assert data["evaluation"]["scores"]["desire"] > 0
    assert data["evaluation"]["requires_human_review"] is True
    assert data["candidates"] == []

    blocker = data["revision_blocker"]
    assert blocker["status"] == "unavailable"
    assert blocker["code"] == CONTINUITY_BUDGET_ERROR_CODE
    assert blocker["node_id"] == "writer_scene_revision"
    assert blocker["llm_call_id"] == "llm_call_writer_scene_revision_budget"
    assert blocker["retryable"] is False
    assert blocker["continuity_warning"] == CONTINUITY_WARNING
    assert blocker["recommended_action"] == SCENE_SPLIT_RECOMMENDATION
    assert blocker["author_action"]["target_ref"] == f"scene_card:{SCENE_ID}"
    assert blocker["author_action"]["target_view"]
    assert blocker["author_action"]["primary_button_label"]
    assert f"错误：{CONTINUITY_BUDGET_ERROR_CODE}" in blocker["author_action"]["evidence_summary"]

    # 阻塞原因作为 blocker finding 挂在聚合评审上，旧 UI 的问题列表就能直接看到。
    finding = next(item for item in data["evaluation"]["findings"] if item["dimension"] == REVISION_BLOCKER_DIMENSION)
    assert finding["severity"] == "blocker"
    assert finding["revision_blocker"]["code"] == CONTINUITY_BUDGET_ERROR_CODE

    # 持久化状态：4 个镜头 + 1 个聚合评审已落库，没有伪造候选。
    session.expire_all()
    assert session.query(WriterEvaluation).filter_by(scene_id=SCENE_ID).count() == len(WRITER_REVIEW_LENSES) + 1
    aggregate = _aggregate_evaluation(session, object_type="scene", object_id=SCENE_ID)
    assert aggregate.overall_score is not None
    assert aggregate.requires_human_review == 1
    persisted = _blocker_finding(aggregate)
    assert persisted["revision_blocker"]["code"] == CONTINUITY_BUDGET_ERROR_CODE
    assert persisted["revision_blocker"]["continuity_warning"]["estimated_input_tokens"] == 91000
    assert session.query(RevisionCandidate).filter_by(scene_id=SCENE_ID).count() == 0

    # 后续 GET 同样带回阻塞信息，作家刷新页面后不会丢失原因。
    review = client.get(f"/api/v1/scenes/{SCENE_ID}/writer-review")
    assert review.status_code == 200
    review_data = review.json()["data"]
    assert review_data["status"] == "reviewed"
    assert review_data["candidates"] == []
    assert review_data["revision_blocker"]["code"] == CONTINUITY_BUDGET_ERROR_CODE
    assert review_data["latest_evaluation"]["evaluation_id"] == aggregate.evaluation_id


def test_chapter_writer_review_continuity_budget_on_revision_returns_200_and_replays_idempotently(
    client: TestClient, session, monkeypatch
) -> None:
    _seed_scene_with_final(session)
    seen = _install_failing_revision_node(
        monkeypatch,
        failing_node_id="writer_chapter_revision",
        error=_continuity_error("writer_chapter_revision"),
    )
    headers = {"X-Idempotency-Key": "writer-review-budget-chapter-1"}

    response = client.post(f"/api/v1/chapters/{CHAPTER_ID}/writer-review/run", headers=headers)

    assert response.status_code == 200, response.text
    data = response.json()["data"]
    assert seen == [*[lens.chapter_node_id for lens in WRITER_REVIEW_LENSES], "writer_chapter_revision"]
    assert data["evaluation"]["object_type"] == "chapter"
    assert data["evaluation"]["overall_score"] is not None
    assert data["candidates"] == []
    blocker = data["revision_blocker"]
    assert blocker["code"] == CONTINUITY_BUDGET_ERROR_CODE
    assert blocker["node_id"] == "writer_chapter_revision"
    assert blocker["continuity_warning"]["requires_scene_split"] is True
    assert blocker["author_action"]["target_ref"] == f"chapter:{CHAPTER_ID}"

    aggregate = _aggregate_evaluation(session, object_type="chapter", object_id=CHAPTER_ID)
    assert aggregate.requires_human_review == 1
    assert _blocker_finding(aggregate)["revision_blocker"]["code"] == CONTINUITY_BUDGET_ERROR_CODE
    assert session.query(RevisionCandidate).filter_by(chapter_id=CHAPTER_ID).count() == 0

    # 带幂等键的成功降级会被记录并可重放；线上就是带键请求炸成了 500。
    replay = client.post(f"/api/v1/chapters/{CHAPTER_ID}/writer-review/run", headers=headers)
    assert replay.status_code == 200
    assert replay.headers.get("X-Idempotency-Status") == "replayed"
    assert replay.json()["data"]["revision_blocker"]["code"] == CONTINUITY_BUDGET_ERROR_CODE
    assert len(seen) == len(WRITER_REVIEW_LENSES) + 1

    # 章节手稿摘要复用同一份评审摘要，阻塞信息也要一起带出。
    manuscript = client.get(f"/api/v1/chapter-manuscripts/{CHAPTER_ID}")
    assert manuscript.status_code == 200
    summary = manuscript.json()["data"]["writer_review_summary"]
    assert summary["revision_blocker"]["code"] == CONTINUITY_BUDGET_ERROR_CODE
    assert summary["candidate_count"] == 0


def test_scene_writer_review_revision_provider_failure_degrades_without_500(
    client: TestClient, session, monkeypatch
) -> None:
    _seed_scene_with_final(session)
    _install_failing_revision_node(
        monkeypatch,
        failing_node_id="writer_scene_revision",
        error=LLMNodeExecutionError(
            llm_call_id="llm_call_writer_scene_revision_502",
            error_code="LLM_PROVIDER_HTTP_ERROR",
            message="provider returned 502",
            request_summary={"node_id": "writer_scene_revision"},
            response_summary={"message": "provider returned 502", "retryable": True},
            retryable=True,
        ),
    )

    response = client.post(f"/api/v1/scenes/{SCENE_ID}/writer-review/run")

    assert response.status_code == 200, response.text
    data = response.json()["data"]
    assert data["candidates"] == []
    blocker = data["revision_blocker"]
    assert blocker["code"] == "LLM_PROVIDER_HTTP_ERROR"
    assert blocker["retryable"] is True
    assert blocker["continuity_warning"] is None
    assert blocker["llm_call_id"] == "llm_call_writer_scene_revision_502"
    aggregate = _aggregate_evaluation(session, object_type="scene", object_id=SCENE_ID)
    assert _blocker_finding(aggregate)["revision_blocker"]["code"] == "LLM_PROVIDER_HTTP_ERROR"


class _MalformedRevisionClient(OnlineAccountedExecution):
    """Valid diagnosis for every lens, then a schema-breaking revision payload."""

    def __init__(self) -> None:
        self.requests = []

    def generate(self, request):
        self.requests.append(request)
        node_id = request.node_id
        if node_id.endswith("_diagnosis"):
            from novel_system.services.writer_review import ALL_WRITER_REVIEW_DIMENSIONS

            payload = {
                "overall_score": 0.6,
                "scores": {dim: 0.6 for dim in ALL_WRITER_REVIEW_DIMENSIONS},
                "findings": [],
                "revision_brief": [],
                "requires_human_review": False,
            }
        else:
            payload = {"revised_text": 42, "diff_summary": None}
        return LLMResponse(
            request_id=f"req_{node_id}_{len(self.requests)}",
            provider="test_provider",
            model=request.model,
            text="{}",
            structured_output=payload,
            response_format=request.response_format,
            raw_response={"id": f"req_{node_id}", "model": request.model},
            usage={"input_tokens": 10, "output_tokens": 20, "total_tokens": 30},
            finish_reason="stop",
        )

    def generate_accounted(self, request, *, accounting_hook):
        handle = accounting_hook.before_dispatch(request=request, dispatch_kind="initial")
        response = self.generate(request)
        accounting_hook.after_response(handle, request=request, response=response, latency_ms=1)
        return response


def test_scene_writer_review_malformed_revision_payload_degrades_without_fabricating_candidate(session) -> None:
    _seed_scene_with_final(session)
    fake_client = _MalformedRevisionClient()

    payload = WriterReviewService(session, llm_client=fake_client).run_scene_review(SCENE_ID, actor_ref="writer.tdd")

    assert [request.node_id for request in fake_client.requests][-1] == "writer_scene_revision"
    assert payload["candidates"] == []
    blocker = payload["revision_blocker"]
    assert blocker["code"] == "WRITER_REVISION_PAYLOAD_INVALID"
    assert blocker["llm_call_id"]
    assert blocker["llm_call_id"].startswith("llm_call_")
    assert "revised_text" in blocker["message"]
    assert payload["evaluation"]["overall_score"] == 0.6
    assert session.query(RevisionCandidate).filter_by(scene_id=SCENE_ID).count() == 0
