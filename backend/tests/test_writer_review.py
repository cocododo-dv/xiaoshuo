from __future__ import annotations

from fastapi.testclient import TestClient

from novel_system.db.models import (
    ChapterGoal,
    ChapterMemory,
    ChapterState,
    FinalScene,
    LlmCall,
    RevisionCandidate,
    SceneCard,
    SceneRunState,
    WriterEvaluation,
)
from novel_system.services.bundle_builder import BundleBuilder
from novel_system.services.llm_client import LLMResponse
from novel_system.services.writer_review import WriterReviewService


CHAPTER_ID = "CH_WRITER_01"
SCENE_ID = "CH_WRITER_01_SC01"
FINAL_ROW_ID = "final_writer_01"


def _seed_scene_with_final(session) -> None:
    session.add(
        ChapterGoal(
            chapter_id=CHAPTER_ID,
            planned_scene_count=1,
            chapter_goal="主角第一次意识到盟友隐瞒了关键事实。",
            main_plot_push="把线索从传闻推进到可验证证据。",
            emotional_target="信任被轻轻撕开，但还不能摊牌。",
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
            beats_json=["共享线索", "提到关键名字", "盟友转移话题"],
            exit_change="主角决定暗中核查盟友的行踪。",
            hook="那个名字一出口，盟友杯中的茶晃了一下。",
            writer_brief_json={
                "character_desire": "主角想确认盟友是否可信。",
                "obstacle": "盟友用玩笑和旧情分遮住事实。",
                "stakes": "如果判断错，主角会把证据交给错误的人。",
                "secret_or_misunderstanding": "盟友知道关键名字，却装作第一次听见。",
                "subtext": "两人都在关心对方，也都在隐瞒。",
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
            current_bundle_id="bundle_writer_01",
            current_bundle_hash="hash_writer_01",
        )
    )
    session.add(
        FinalScene(
            row_id=FINAL_ROW_ID,
            scene_id=SCENE_ID,
            chapter_id=CHAPTER_ID,
            content="茶盏在桌面上轻轻一响。她问出那个名字时，他先笑，随后说窗外雨声太大。",
            status="approved",
            source_bundle_id="bundle_writer_01",
            source_bundle_hash="hash_writer_01",
        )
    )
    session.commit()


class ScriptedWriterReviewClient:
    def __init__(self, *, malformed_diagnosis: bool = False) -> None:
        self.malformed_diagnosis = malformed_diagnosis
        self.requests = []

    def generate(self, request):
        self.requests.append(request)
        node_id = request.node_id
        if node_id in {"writer_scene_diagnosis", "writer_chapter_diagnosis"}:
            payload = self._diagnosis_payload(node_id)
        elif node_id == "writer_scene_revision":
            payload = {
                "revised_text": "茶盏轻响。她问出那个名字，他的笑意停在唇边，杯中茶面先晃了一下。",
                "diff_summary": "把试探从说明推进到动作，让紧张落在茶盏、停顿和回避上。",
                "changed_dimensions": ["subtext", "turn", "reader_hook"],
                "rewrite_strategy": "full_scene_rewrite",
            }
        elif node_id == "writer_chapter_revision":
            payload = {
                "revision_plan": [
                    "保留现有证据线，但把每场结尾改成一次新的选择，而不是单纯发现线索。",
                    "压缩解释句，把旧友关系的裂痕放进动作和对白停顿。",
                ],
                "selected_rewrite_passages": [
                    {
                        "source_excerpt": "她问出那个名字时，他先笑，随后说窗外雨声太大。",
                        "revised_text": "她问出那个名字时，他先笑。窗外雨声尚未变大，他却先侧过脸去听。",
                        "reason": "让回避先于借口出现，增强潜台词。",
                    }
                ],
                "diff_summary": "章节候选以修订计划和局部重写为主，不整章覆盖。",
                "changed_dimensions": ["subtext", "scene_necessity", "ending_hook"],
                "rewrite_strategy": "revision_plan",
            }
        else:
            payload = {"ok": True}
        return LLMResponse(
            request_id=f"req_{node_id}",
            provider="test_provider",
            model=request.model,
            text="{}",
            structured_output=payload,
            response_format=request.response_format,
            raw_response={"id": f"req_{node_id}", "model": request.model},
            usage={"input_tokens": 10, "output_tokens": 20, "total_tokens": 30},
            finish_reason="stop",
        )

    def _diagnosis_payload(self, node_id):
        if self.malformed_diagnosis:
            return {"overall_score": "not-a-number"}
        return {
            "overall_score": 0.64,
            "scores": {
                "desire": 0.68,
                "obstacle": 0.62,
                "stakes": 0.6,
                "turn": 0.66,
                "subtext": 0.58,
                "irreversible_change": 0.61,
                "scene_necessity": 0.7,
                "reader_hook": 0.63,
                "continuity": 0.74,
                "character_agency": 0.57,
                "dialogue_edge": 0.52,
                "information_rhythm": 0.59,
                "imagery_freshness": 0.55,
                "expression_repetition": 0.49,
                "power_shift": 0.6,
                "ending_drive": 0.64,
            },
            "findings": [
                {
                    "dimension": "dialogue_edge",
                    "severity": "major",
                    "issue": "人物的回避动作成立，但对白还没有形成足够锋利的互相试探。",
                    "recommendation": "让一方说出半句真话，另一方用动作截断它。",
                    "evidence_excerpt": "他先笑，随后说窗外雨声太大。",
                    "evidence_location": "source paragraph 1",
                    "why_it_matters": "这里是关系裂缝的核心瞬间，若只靠说明会削弱读者的怀疑。",
                }
            ],
            "revision_brief": [
                {
                    "dimension": "dialogue_edge",
                    "action": "把回避改成可见动作，并让对白承担关系压力。",
                    "priority": "high",
                }
            ],
            "requires_human_review": False,
        }


def test_chapter_and_scene_writer_brief_round_trip_and_invalid_type_is_rejected(client: TestClient) -> None:
    chapter_payload = {
        "chapter_id": "CH_WRITER_FORM",
        "chapter_goal": "写出一次关系试探。",
        "writer_brief_json": {
            "core_promise": "旧友重逢的温度下藏着危险。",
            "plot_movement": "得到下一处地点。",
            "character_shift": "从信任转向怀疑。",
            "chapter_question": "旧友为什么改口？",
            "ending_aftertaste": "温情里有刺。",
        },
    }
    chapter_response = client.post(
        "/api/v1/chapters",
        json=chapter_payload,
        headers={"X-Idempotency-Key": "writer-form-chapter"},
    )
    assert chapter_response.status_code == 200

    scene_payload = {
        "scene_id": "CH_WRITER_FORM_SC01",
        "chapter_id": "CH_WRITER_FORM",
        "scene_goal": "主角听见旧友改口。",
        "writer_brief_json": {
            "character_desire": "逼旧友说真话。",
            "obstacle": "旧友回避。",
            "stakes": "错误信任会暴露线索。",
            "secret_or_misunderstanding": "旧友隐瞒了见面对象。",
            "subtext": "两人都在试探彼此底线。",
            "irreversible_change": "主角决定独自行动。",
            "reader_question": "旧友保护的是谁？",
        },
    }
    scene_response = client.post(
        "/api/v1/scenes",
        json=scene_payload,
        headers={"X-Idempotency-Key": "writer-form-scene"},
    )
    assert scene_response.status_code == 200

    workspace = client.get("/api/v1/chapters/CH_WRITER_FORM/author-workspace").json()["data"]
    assert workspace["chapter"]["writer_brief_json"]["core_promise"] == "旧友重逢的温度下藏着危险。"
    assert workspace["scenes"][0]["writer_brief_json"]["character_desire"] == "逼旧友说真话。"

    invalid_response = client.post(
        "/api/v1/scenes",
        json={
            "scene_id": "CH_WRITER_FORM_SC_BAD",
            "chapter_id": "CH_WRITER_FORM",
            "scene_goal": "非法戏剧卡类型。",
            "writer_brief_json": ["not", "an", "object"],
        },
        headers={"X-Idempotency-Key": "writer-form-scene-bad"},
    )
    assert invalid_response.status_code == 400
    assert invalid_response.json()["error"]["code"] == "WRITER_BRIEF_INVALID"


def test_scene_writer_review_creates_evaluation_and_candidate_without_overwriting_final(client: TestClient, session) -> None:
    _seed_scene_with_final(session)

    run_response = client.post(f"/api/v1/scenes/{SCENE_ID}/writer-review/run")
    assert run_response.status_code == 200
    payload = run_response.json()["data"]

    assert payload["evaluation"]["rubric_id"] == "drama_effectiveness_v1"
    assert payload["evaluation"]["object_type"] == "scene"
    assert payload["evaluation"]["scores"]["desire"] > 0
    assert payload["evaluation"]["revision_brief"]
    assert payload["candidates"][0]["status"] == "candidate"
    assert payload["candidates"][0]["revision_type"] == "scene_revision"
    assert "作家修订候选" in payload["candidates"][0]["proposed_text"]

    candidate_id = payload["candidates"][0]["revision_id"]
    original_final = session.get(FinalScene, FINAL_ROW_ID).content

    accept_response = client.post(f"/api/v1/revision-candidates/{candidate_id}/accept", json={"note": "采用方向，稍后人工合并。"})
    assert accept_response.status_code == 200
    assert accept_response.json()["data"]["revision"]["status"] == "accepted"

    session.expire_all()
    assert session.get(FinalScene, FINAL_ROW_ID).content == original_final
    assert session.get(RevisionCandidate, candidate_id).status == "accepted"
    assert session.query(WriterEvaluation).filter_by(scene_id=SCENE_ID).count() == 1

    review_response = client.get(f"/api/v1/scenes/{SCENE_ID}/writer-review")
    assert review_response.status_code == 200
    review = review_response.json()["data"]
    assert review["latest_evaluation"]["overall_score"] == payload["evaluation"]["overall_score"]
    assert review["candidates"][0]["status"] == "accepted"


def test_scene_writer_review_uses_llm_diagnosis_evidence_and_real_rewrite_candidate(session) -> None:
    _seed_scene_with_final(session)
    fake_client = ScriptedWriterReviewClient()

    payload = WriterReviewService(session, llm_client=fake_client).run_scene_review(SCENE_ID, actor_ref="writer.tdd")

    evaluation = payload["evaluation"]
    finding = evaluation["findings"][0]
    candidate = payload["candidates"][0]

    assert [request.node_id for request in fake_client.requests] == ["writer_scene_diagnosis", "writer_scene_revision"]
    assert evaluation["evaluator_llm_call_id"]
    persisted_call = session.get(LlmCall, evaluation["evaluator_llm_call_id"])
    assert persisted_call is not None
    assert persisted_call.node_id == "writer_scene_diagnosis"
    assert evaluation["scores"]["dialogue_edge"] == 0.52
    assert finding["evidence_excerpt"] == "他先笑，随后说窗外雨声太大。"
    assert finding["evidence_location"] == "source paragraph 1"
    assert finding["why_it_matters"].startswith("这里是关系裂缝")
    assert candidate["proposed_text"].startswith("茶盏轻响。")
    assert candidate["diff_summary"]["candidate_kind"] == "full_scene_rewrite"
    assert candidate["diff_summary"]["rewrite_strategy"] == "full_scene_rewrite"
    assert candidate["diff_summary"]["changed_dimensions"] == ["subtext", "turn", "reader_hook"]


def test_chapter_writer_review_prefers_final_aggregate_and_creates_revision_plan_candidate(session) -> None:
    _seed_scene_with_final(session)
    session.add(
        ChapterState(
            chapter_id=CHAPTER_ID,
            current_phase="finalized",
            chapter_passed_scene_count=1,
            last_final_memory_row_id="chapter_memory_writer_final",
        )
    )
    session.add(
        ChapterMemory(
            row_id="chapter_memory_writer_final",
            chapter_id=CHAPTER_ID,
            content="最终聚合：她发现旧友回避关键名字，决定暗中核查。",
            aggregate_stage="final",
            active_flag=1,
        )
    )
    session.commit()
    fake_client = ScriptedWriterReviewClient()

    payload = WriterReviewService(session, llm_client=fake_client).run_chapter_review(CHAPTER_ID, actor_ref="writer.tdd")

    evaluation = payload["evaluation"]
    candidate = payload["candidates"][0]

    assert [request.node_id for request in fake_client.requests] == ["writer_chapter_diagnosis", "writer_chapter_revision"]
    assert evaluation["source_text_ref"] == "chapter_memory:chapter_memory_writer_final"
    assert evaluation["evaluator_llm_call_id"]
    assert session.get(LlmCall, evaluation["evaluator_llm_call_id"]).node_id == "writer_chapter_diagnosis"
    assert candidate["revision_type"] == "chapter_revision"
    assert "【章节修订计划】" in candidate["proposed_text"]
    assert "【局部改写】" in candidate["proposed_text"]
    assert candidate["diff_summary"]["candidate_kind"] == "revision_plan"
    assert candidate["diff_summary"]["rewrite_strategy"] == "revision_plan"


def test_writer_review_malformed_llm_payload_blocks_without_fabricating_scores(session) -> None:
    _seed_scene_with_final(session)
    fake_client = ScriptedWriterReviewClient(malformed_diagnosis=True)

    payload = WriterReviewService(session, llm_client=fake_client).run_scene_review(SCENE_ID, actor_ref="writer.tdd")

    evaluation = payload["evaluation"]

    assert [request.node_id for request in fake_client.requests] == ["writer_scene_diagnosis"]
    assert evaluation["requires_human_review"] is True
    assert evaluation["overall_score"] is None
    assert evaluation["scores"] == {}
    assert evaluation["findings"][0]["dimension"] == "writer_diagnosis_payload"
    assert evaluation["findings"][0]["evidence_excerpt"] == ""
    assert payload["candidates"] == []
    assert session.query(RevisionCandidate).filter_by(scene_id=SCENE_ID).count() == 0


def test_chapter_writer_review_uses_assembled_text_and_returns_candidate(client: TestClient, session) -> None:
    _seed_scene_with_final(session)

    run_response = client.post(f"/api/v1/chapters/{CHAPTER_ID}/writer-review/run")
    assert run_response.status_code == 200
    payload = run_response.json()["data"]

    assert payload["evaluation"]["object_type"] == "chapter"
    assert payload["evaluation"]["rubric_id"] == "drama_effectiveness_v1"
    assert payload["evaluation"]["scores"]["reader_hook"] > 0
    assert payload["candidates"][0]["revision_type"] == "chapter_revision"

    manuscript_response = client.get(f"/api/v1/chapter-manuscripts/{CHAPTER_ID}")
    assert manuscript_response.status_code == 200
    summary = manuscript_response.json()["data"]["writer_review_summary"]
    assert summary["latest_evaluation"]["evaluation_id"] == payload["evaluation"]["evaluation_id"]
    assert summary["candidate_count"] == 1


def test_bundle_builder_injects_writer_briefs_without_replacing_existing_cards(session) -> None:
    _seed_scene_with_final(session)

    bundle = BundleBuilder(session).build(SCENE_ID)
    snapshot = bundle["snapshot"]

    assert snapshot["inline_digests"]["chapter_goal"] == "主角第一次意识到盟友隐瞒了关键事实。"
    assert "scene_card" in snapshot["inline_digests"]
    assert "chapter_writer_brief" in snapshot["inline_digests"]
    assert "scene_writer_brief" in snapshot["inline_digests"]
    assert "character_desire" in snapshot["inline_digests"]["scene_writer_brief"]
    assert any(item["slot"] == "scene_writer_brief" for item in snapshot["ordered_injections"])
