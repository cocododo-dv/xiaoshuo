"""Wave 3（结果闭环治理 §5.5/§6.3）：Best-of-N 作者终选门。

完成门可复算证明：
- 关键场景候选生成后暂停编排（awaiting_candidate_selection），未选择前
  管线不归档、adopt-current 也拒绝（双入口封死）；
- 盲化视图：默认按 blinded_order 输出全文、剥离机器分数；主动展开不重排；
- 终选一次写入：同选幂等、异选 409，显式重开后方可改选（审计留痕）；
- 选择后 resume-after-selection 从批判修订/QC 继续，安全归档，终稿=选中稿。
"""

from __future__ import annotations

import json

from sqlalchemy import select

from novel_system.db.models import (
    ChapterGoal,
    ChapterState,
    FinalScene,
    HumanReviewEvent,
    RelationProfile,
    SceneCard,
    SceneDraft,
    SceneRunState,
    VoiceProfile,
)
from novel_system.services.llm_client import LLMRequest, LLMResponse
from novel_system.services.orchestrator import Orchestrator
from novel_system.services.qc_engine import HardQcEngine, SoftQcEngine
from novel_system.services.scene_generation import SceneGenerationService

SCENE_ID = "CH300_SC01"
CHAPTER_ID = "CH300"


def _response(payload: dict, *, request_id: str) -> LLMResponse:
    return LLMResponse(
        request_id=request_id,
        provider="fake-provider",
        model="fake-model",
        text=json.dumps(payload, ensure_ascii=False),
        structured_output=payload,
        response_format="json_object",
        raw_response={"id": request_id, "model": "fake-model", "usage": {"input_tokens": 60, "output_tokens": 18, "total_tokens": 78}, "finish_reason": "stop"},
        usage={"input_tokens": 60, "output_tokens": 18, "total_tokens": 78},
        finish_reason="stop",
    )


class FakeSceneClient:
    def __init__(self) -> None:
        self.requests: list[LLMRequest] = []

    def generate(self, request: LLMRequest) -> LLMResponse:
        self.requests.append(request)
        index = len(self.requests)
        payload = {"scene_text": f"Provider-generated draft #{index} for terminal selection.", "continuity_notes": []}
        return _response(payload, request_id=f"resp_scene_{index:03d}")


class FakePassQcClient:
    def __init__(self, payload: dict) -> None:
        self.payload = payload

    def generate(self, request: LLMRequest) -> LLMResponse:
        return _response(self.payload, request_id="resp_qc_001")


def _hard_pass() -> dict:
    return {"resolution_code": "hard_pass", "pass_flag": True, "next_action": "pass", "issues": [], "rewrite_brief": []}


def _soft_pass() -> dict:
    return {
        "resolution_code": "soft_pass",
        "pass_flag": True,
        "next_action": "pass",
        "issues": [],
        "rewrite_brief": [],
        "carry_forward_note": False,
        "note_scope": None,
        "carry_note_text": None,
    }


def _seed_scene(session, *, constraint_intensity: float | None = 0.9) -> None:
    session.add(ChapterGoal(chapter_id=CHAPTER_ID, planned_scene_count=1, chapter_goal="A reunion turns dangerous."))
    session.add(ChapterState(chapter_id=CHAPTER_ID, current_phase="drafting"))
    session.add(
        SceneCard(
            scene_id=SCENE_ID,
            chapter_id=CHAPTER_ID,
            scene_seq=1,
            pov_character_id="CHAR_A",
            onstage_chars_json=["CHAR_A", "CHAR_B"],
            location="Clocktower Roof",
            scene_goal="Force both characters to reveal what they know.",
            beats_json=["arrival", "reveal", "standoff"],
            must_include_text="",
            target_length_band="short",
            scene_type="reunion",
            is_chapter_last=0,
            constraint_intensity=constraint_intensity,
        )
    )
    session.add(SceneRunState(scene_id=SCENE_ID, scene_status="ready"))
    session.add(
        VoiceProfile(
            row_id="voice_profile_VOICE_CHAR_A_v1",
            voice_profile_id="VOICE_CHAR_A",
            version=1,
            character_id="CHAR_A",
            content="tight internal narration",
            active_flag=1,
        )
    )
    session.add(
        RelationProfile(
            row_id="relation_profile_REL_CHAR_A_CHAR_B_v1",
            relation_profile_id="REL_CHAR_A_CHAR_B",
            left_character_id="CHAR_A",
            right_character_id="CHAR_B",
            version=1,
            content="they mistrust each other but still care",
            active_flag=1,
        )
    )
    session.commit()


def _make_orchestrator(session) -> Orchestrator:
    return Orchestrator(
        session,
        scene_generation_service=SceneGenerationService(session, llm_client=FakeSceneClient()),
        hard_qc_engine=HardQcEngine(session, llm_client=FakePassQcClient(_hard_pass())),
        soft_qc_engine=SoftQcEngine(session, llm_client=FakePassQcClient(_soft_pass())),
    )


def _selection_gate(session) -> HumanReviewEvent:
    events = session.execute(
        select(HumanReviewEvent).order_by(HumanReviewEvent.created_at.desc())
    ).scalars().all()
    for event in events:
        if (event.details_json or {}).get("gate_type") == "style_candidate_selection":
            return event
    raise AssertionError("no style_candidate_selection gate event found")


# ---------- 暂停：关键场景未选择前不可归档 ----------

def test_critical_scene_pauses_before_selection(session) -> None:
    _seed_scene(session)
    orchestrator = _make_orchestrator(session)

    result = orchestrator.run_scene(SCENE_ID)
    session.commit()

    state = session.get(SceneRunState, SCENE_ID)
    assert result["scene_status"] == "awaiting_candidate_selection"
    assert result["author_state"] == "awaiting_author_choice"
    assert result["can_archive"] is False
    assert result["latest_valid_draft_row_id"]
    assert state.current_final_scene_row_id is None
    assert session.execute(select(FinalScene)).scalars().all() == []

    gate = _selection_gate(session)
    details = gate.details_json
    assert details["decision_status"] == "awaiting"
    assert details["candidate_row_ids"]
    assert sorted(details["blinded_order"]) == sorted(details["candidate_row_ids"])
    assert "tokens_used" in details


def test_standard_scene_does_not_pause(session) -> None:
    _seed_scene(session, constraint_intensity=0.5)  # standard：机器下限自动选择
    orchestrator = _make_orchestrator(session)

    result = orchestrator.run_scene(SCENE_ID)
    session.commit()

    assert result["scene_status"] == "archived"


def test_adopt_refuses_before_selection(client, session) -> None:
    _seed_scene(session)
    _make_orchestrator(session).run_scene(SCENE_ID)
    session.commit()

    response = client.post(
        f"/api/v1/scenes/{SCENE_ID}/adopt-current",
        json={},
        headers={"X-Idempotency-Key": "w3-adopt-await"},
    )
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "SELECTION_REQUIRED"


# ---------- 盲化视图 ----------

def _seed_manual_gate(session, row_ids: list[str], blinded: list[str]) -> HumanReviewEvent:
    for i, row_id in enumerate(row_ids):
        session.add(
            SceneDraft(
                row_id=row_id,
                scene_id=SCENE_ID,
                chapter_id=CHAPTER_ID,
                stage="style_draft",
                content=f"候选正文 {i}：潮水退去，闸门上的名字露出来。",
                source_bundle_id="bundle_w3",
                source_bundle_hash="hash_w3",
            )
        )
    event = HumanReviewEvent(
        event_id="hre_sel_manual_1",
        scene_id=SCENE_ID,
        chapter_id=CHAPTER_ID,
        object_ref=f"candidate_selection:{SCENE_ID}",
        event_source="candidate_selection",
        priority="high",
        status="awaiting_review",
        allowed_actions_json=["select"],
        details_json={
            "gate_type": "style_candidate_selection",
            "candidate_row_ids": row_ids,
            "blinded_order": blinded,
            "decision_status": "awaiting",
            "selected_row_id": None,
            "tokens_used": 0,
        },
    )
    session.add(event)
    state = session.get(SceneRunState, SCENE_ID)
    state.scene_status = "awaiting_candidate_selection"
    state.current_human_review_event_id = event.event_id
    session.commit()
    return event


def test_blinded_candidates_view_strips_scores_and_uses_blinded_order(client, session) -> None:
    _seed_scene(session)
    row_ids = ["w3_cand_a", "w3_cand_b", "w3_cand_c"]
    blinded = ["w3_cand_b", "w3_cand_c", "w3_cand_a"]
    _seed_manual_gate(session, row_ids, blinded)

    data = client.get(f"/api/v1/scenes/{SCENE_ID}/style-candidates").json()["data"]

    assert data["blinded"] is True
    assert [c["row_id"] for c in data["candidates"]] == blinded
    for candidate in data["candidates"]:
        assert "adversarial_score" not in candidate  # 默认剥离机器分数（§5.5）
        assert "selected" not in candidate  # 盲化视图不泄漏机器预选
        assert candidate["content"]  # 展示完整正文，不只预览

    # 作者主动展开：附分数但不得重排（分数只做标注，不做默认排序）
    scored = client.get(f"/api/v1/scenes/{SCENE_ID}/style-candidates?include_scores=true").json()["data"]
    assert [c["row_id"] for c in scored["candidates"]] == blinded
    assert all("adversarial_score" in c for c in scored["candidates"])


# ---------- 终选锁定与重开 ----------

def test_select_locks_and_reopen_allows_change(client, session) -> None:
    _seed_scene(session)
    row_ids = ["w3_cand_a", "w3_cand_b", "w3_cand_c"]
    _seed_manual_gate(session, row_ids, list(reversed(row_ids)))

    first = client.post(
        f"/api/v1/scenes/{SCENE_ID}/style-candidates/w3_cand_a/select",
        json={"no_clear_difference": False},
        headers={"X-Idempotency-Key": "w3-select-1"},
    )
    assert first.status_code == 200

    # 相同选择重复提交（不同幂等键）→ 幂等返回
    same = client.post(
        f"/api/v1/scenes/{SCENE_ID}/style-candidates/w3_cand_a/select",
        json={},
        headers={"X-Idempotency-Key": "w3-select-1b"},
    )
    assert same.status_code == 200

    # 提交不同 row_id → 拒绝（终选一次写入）
    other = client.post(
        f"/api/v1/scenes/{SCENE_ID}/style-candidates/w3_cand_b/select",
        json={},
        headers={"X-Idempotency-Key": "w3-select-2"},
    )
    assert other.status_code == 409
    assert other.json()["error"]["code"] == "SELECTION_LOCKED"

    # 显式重开 → 可改选，且审计留痕
    reopen = client.post(
        f"/api/v1/scenes/{SCENE_ID}/style-candidates/reopen",
        json={"reason": "想再看一遍第二稿"},
        headers={"X-Idempotency-Key": "w3-reopen-1"},
    )
    assert reopen.status_code == 200

    retry = client.post(
        f"/api/v1/scenes/{SCENE_ID}/style-candidates/w3_cand_b/select",
        json={},
        headers={"X-Idempotency-Key": "w3-select-3"},
    )
    assert retry.status_code == 200

    gate = _selection_gate(session)
    session.refresh(gate)
    details = gate.details_json
    assert details["selected_row_id"] == "w3_cand_b"
    history = details.get("decision_history") or []
    assert any(entry.get("action") == "reopen" for entry in history)
    assert any(entry.get("action") == "select" and entry.get("row_id") == "w3_cand_a" for entry in history)


def test_select_outside_gate_candidates_rejected(client, session) -> None:
    _seed_scene(session)
    _seed_manual_gate(session, ["w3_cand_a"], ["w3_cand_a"])
    session.add(
        SceneDraft(
            row_id="w3_outside",
            scene_id=SCENE_ID,
            chapter_id=CHAPTER_ID,
            stage="style_draft",
            content="不在终选清单里的旧稿。",
            source_bundle_id="bundle_w3",
            source_bundle_hash="hash_w3",
        )
    )
    session.commit()

    response = client.post(
        f"/api/v1/scenes/{SCENE_ID}/style-candidates/w3_outside/select",
        json={},
        headers={"X-Idempotency-Key": "w3-select-outside"},
    )
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "CANDIDATE_NOT_IN_GATE"


# ---------- resume：选择后安全续跑 ----------

def test_resume_requires_selection(client, session) -> None:
    _seed_scene(session)
    _make_orchestrator(session).run_scene(SCENE_ID)
    session.commit()

    response = client.post(
        f"/api/v1/scenes/{SCENE_ID}/resume-after-selection",
        json={},
        headers={"X-Idempotency-Key": "w3-resume-early"},
    )
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "SELECTION_REQUIRED"


def test_select_then_resume_archives_the_chosen_candidate(client, session) -> None:
    _seed_scene(session)
    _make_orchestrator(session).run_scene(SCENE_ID)
    session.commit()

    gate = _selection_gate(session)
    chosen_row_id = gate.details_json["candidate_row_ids"][0]
    chosen_content = session.get(SceneDraft, chosen_row_id).content

    selected = client.post(
        f"/api/v1/scenes/{SCENE_ID}/style-candidates/{chosen_row_id}/select",
        json={"no_clear_difference": True},
        headers={"X-Idempotency-Key": "w3-select-resume-1"},
    )
    assert selected.status_code == 200

    resumed = client.post(
        f"/api/v1/scenes/{SCENE_ID}/resume-after-selection",
        json={},
        headers={"X-Idempotency-Key": "w3-resume-1"},
    )
    assert resumed.status_code == 200
    data = resumed.json()["data"]
    assert data["scene_status"] == "archived"
    assert data["author_state"] == "archived"

    state = session.get(SceneRunState, SCENE_ID)
    final = session.get(FinalScene, state.current_final_scene_row_id)
    assert final is not None and final.status == "archived"
    # 终稿=作者选中稿，或其唯一一次批判修订稿（§5.5 允许；血缘必须指向选中稿）
    if final.content != chosen_content:
        from novel_system.db.models import AttemptTracker

        attempts = session.execute(
            select(AttemptTracker).where(AttemptTracker.scene_id == SCENE_ID)
        ).scalars().all()
        assert any(
            (attempt.details_json or {}).get("source_style_draft_row_id") == chosen_row_id
            for attempt in attempts
        ), "修订稿的来源必须是作者选中稿"

    # 重复 resume 不重复归档
    again = client.post(
        f"/api/v1/scenes/{SCENE_ID}/resume-after-selection",
        json={},
        headers={"X-Idempotency-Key": "w3-resume-2"},
    )
    assert again.status_code in (200, 409)
    finals = session.execute(select(FinalScene).where(FinalScene.scene_id == SCENE_ID)).scalars().all()
    assert len(finals) == 1

    session.refresh(gate)
    assert gate.details_json["decision_status"] == "selected"
    assert gate.status != "awaiting_review"  # gate 已闭合
