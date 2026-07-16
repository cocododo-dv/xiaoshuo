from __future__ import annotations

from types import SimpleNamespace

from sqlalchemy import select

from novel_system.db.models import (
    AuthorDraft,
    AutoRewriteRun,
    ChapterGoal,
    FinalScene,
    LlmCall,
    QcReport,
    SceneCard,
    SceneDraft,
    SceneQualityContract,
    SceneRunState,
)
from novel_system.services.llm_client import parse_model_routing_config


CHAPTER_ID = "QAUTO_CH01"
SCENE_ID = "QAUTO_CH01_SC01"
FINAL_ROW_ID = "final_scene_QAUTO_CH01_SC01_v1"


def _headers(key: str) -> dict[str, str]:
    return {"X-Idempotency-Key": key}


def _all_clear_literary_analysis(_content: str):
    from novel_system.services.literary_quality import QUALITY_DIMENSIONS

    return (
        {
            dimension: {"risk": False, "score": 1.0, "evidence": ""}
            for dimension in QUALITY_DIMENSIONS
        },
        [],
    )


def _install_llm_candidate(monkeypatch, content: str, *, llm_call_id: str) -> None:
    class FakeAutoRewriteRunner:
        def __init__(self, db_session, **kwargs) -> None:
            self.session = db_session

        def run(self, **kwargs):
            assert kwargs["node_id"] == "scene_auto_rewrite"
            return SimpleNamespace(
                llm_call_id=llm_call_id,
                response=SimpleNamespace(
                    structured_output={"scene_text": content, "rewrite_notes": ["test candidate"]}
                ),
            )

    monkeypatch.setenv("NOVEL_SYSTEM_LLM_ENABLED", "true")
    monkeypatch.setattr(
        "novel_system.services.scene_quality.LLMNodeRunner",
        FakeAutoRewriteRunner,
        raising=False,
    )


def _seed_scene(session, *, content: str, forbidden_text: str = "不能改名林岑，也不能删除盐钟残片。") -> None:
    session.add(
        ChapterGoal(
            chapter_id=CHAPTER_ID,
            planned_scene_count=1,
            chapter_goal="林岑必须在公开真相和保护幸存者之间做选择。",
            main_plot_push="让盐钟残片指向失踪案真相。",
            emotional_target="林岑从旁观修复师变成承担代价的人。",
            ending_effect="读者意识到她的选择已经无法撤回。",
            writer_brief_json={
                "chapter_promise": "真相和保护不能同时满足。",
                "ending_question": "林岑会把证据交给谁？",
            },
        )
    )
    session.add(
        SceneCard(
            scene_id=SCENE_ID,
            chapter_id=CHAPTER_ID,
            scene_seq=1,
            pov_character_id="林岑",
            onstage_chars_json=["林岑", "许望"],
            location="无灯船坞",
            scene_goal="林岑发现证据，但必须决定是否立刻公开。",
            beats_json=["找到录音带", "听见幸存者编号", "把证据分成两份"],
            must_include_text="盐钟残片；幸存者阿砚；许望",
            forbidden_text=forbidden_text,
            exit_change="林岑藏起一半证据，准备先转移幸存者。",
            hook="第二枚盐钟的影子出现在雾墙上。",
            writer_brief_json={
                "character_desire": "确认证据是否真实。",
                "obstacle": "公开会让幸存者暴露。",
                "choice_under_pressure": "公开真相或先保护幸存者。",
                "power_shift": "林岑成为证据持有人。",
                "reader_aftertaste": "她越冷静，越像在越界。",
            },
        )
    )
    session.add(
        SceneRunState(
            scene_id=SCENE_ID,
            scene_status="archived",
            current_final_scene_row_id=FINAL_ROW_ID,
            current_bundle_id="bundle_qauto_v1",
            current_bundle_hash="hash_qauto_v1",
        )
    )
    session.add(
        FinalScene(
            row_id=FINAL_ROW_ID,
            scene_id=SCENE_ID,
            chapter_id=CHAPTER_ID,
            content=content,
            status="approved",
            source_bundle_id="bundle_qauto_v1",
            source_bundle_hash="hash_qauto_v1",
        )
    )
    session.commit()


def test_quality_contract_generates_fixed_fields_preserves_chinese_and_hashes_stably(client, session) -> None:
    _seed_scene(
        session,
        content="林岑看见盐钟残片。她突然意识到一切都变得不同了。",
    )

    first = client.post(f"/api/v1/scenes/{SCENE_ID}/quality-contract", headers=_headers("contract-1"))
    second = client.post(f"/api/v1/scenes/{SCENE_ID}/quality-contract", headers=_headers("contract-2"))

    assert first.status_code == 200
    assert second.status_code == 200
    first_contract = first.json()["data"]["contract"]
    second_contract = second.json()["data"]["contract"]

    assert first_contract["contract_version"] == "scene_quality_contract_v1"
    assert first_contract["contract_hash"] == second_contract["contract_hash"]
    assert set(first_contract["payload"]) == {
        "scene_function",
        "pov_or_actor",
        "visible_desire",
        "obstacle",
        "forced_choice",
        "price_paid",
        "relationship_turn",
        "information_release",
        "image_necessity",
        "irreversible_change",
        "ending_action",
        "next_scene_pull",
        "author_protected_intent",
        "forbidden_changes",
    }
    assert "林岑" in first_contract["payload"]["pov_or_actor"]
    assert "公开真相或先保护幸存者" in first_contract["payload"]["forced_choice"]
    assert "盐钟残片" in first_contract["payload"]["image_necessity"]
    assert "不能改名林岑" in first_contract["payload"]["forbidden_changes"]

    rows = session.execute(select(SceneQualityContract).where(SceneQualityContract.scene_id == SCENE_ID)).scalars().all()
    assert len(rows) == 1
    assert rows[0].contract_hash == first_contract["contract_hash"]


def test_auto_rewrite_full_scene_can_promote_and_rollback_without_overwriting_author_draft(
    client, session, monkeypatch
) -> None:
    monkeypatch.setattr(
        "novel_system.services.final_text_gate.analyze_literary_quality",
        _all_clear_literary_analysis,
    )
    _seed_scene(
        session,
        content="林岑看着盐钟残片。她忽然意识到真相很重要。最后，一切都变得不同了。",
    )
    draft = AuthorDraft(
        draft_id="author_draft_scene_QAUTO_CH01_SC01_current",
        object_type="scene",
        object_id=SCENE_ID,
        source_text_ref=f"final_scene:{FINAL_ROW_ID}",
        content="作者稿保留自己的句子，不应被自动重写覆盖。",
        revision_no=1,
        status="current",
    )
    session.add(draft)
    session.commit()

    rewrite = client.post(f"/api/v1/scenes/{SCENE_ID}/auto-rewrite", headers=_headers("rewrite-full"))

    assert rewrite.status_code == 200
    run = rewrite.json()["data"]["run"]
    assert run["branch"] == "full_scene"
    assert run["status"] == "candidate_ready"
    assert run["gate_results"]["promotable"] is True
    assert run["candidate_draft_row_id"]
    assert run["llm_call_id"] is None
    assert session.query(LlmCall).count() == 0
    assert session.get(SceneDraft, run["candidate_draft_row_id"]).generation_llm_call_id is None

    promote = client.post(f"/api/v1/auto-rewrite-runs/{run['run_id']}/promote", headers=_headers("promote-full"))

    assert promote.status_code == 200
    promoted = promote.json()["data"]["run"]
    assert promoted["status"] == "promoted"
    assert promoted["promoted_final_scene_row_id"] != FINAL_ROW_ID
    session.expire_all()
    assert session.get(SceneRunState, SCENE_ID).current_final_scene_row_id == promoted["promoted_final_scene_row_id"]
    assert session.get(FinalScene, FINAL_ROW_ID).content.startswith("林岑看着盐钟残片")
    assert session.get(AuthorDraft, draft.draft_id).content == "作者稿保留自己的句子，不应被自动重写覆盖。"

    rollback = client.post(f"/api/v1/auto-rewrite-runs/{run['run_id']}/rollback", headers=_headers("rollback-full"))

    assert rollback.status_code == 200
    session.expire_all()
    rolled_back = rollback.json()["data"]["run"]
    assert rolled_back["status"] == "rolled_back"
    assert session.get(SceneRunState, SCENE_ID).current_final_scene_row_id == FINAL_ROW_ID
    assert session.get(AutoRewriteRun, run["run_id"]).promoted_final_scene_row_id == promoted["promoted_final_scene_row_id"]


def test_auto_rewrite_uses_llm_candidate_when_live(client, session, monkeypatch) -> None:
    class FakeAutoRewriteRunner:
        def __init__(self, db_session, **kwargs) -> None:
            self.session = db_session

        def run(self, **kwargs):
            assert kwargs["node_id"] == "scene_auto_rewrite"
            self.session.add(
                LlmCall(
                    llm_call_id="llm_call_scene_auto_rewrite_test",
                    scope_type="scene",
                    scope_id=kwargs["scene_id"],
                    provider="fake",
                    model="fake-model",
                    node_id="scene_auto_rewrite",
                    step="scene_auto_rewrite",
                    request_payload_summary={"template_name": "scene_auto_rewrite"},
                    response_payload_summary={"source": "llm"},
                    prompt_tokens=1,
                    completion_tokens=1,
                    total_tokens=2,
                    latency_ms=1,
                )
            )
            self.session.flush()
            return SimpleNamespace(
                llm_call_id="llm_call_scene_auto_rewrite_test",
                response=SimpleNamespace(
                    structured_output={
                        "scene_text": "LLM rewritten scene keeps the required evidence and adds a visible cost.",
                        "rewrite_notes": ["LLM candidate"],
                    }
                ),
            )

    monkeypatch.setenv("NOVEL_SYSTEM_LLM_ENABLED", "true")
    monkeypatch.setattr("novel_system.services.scene_quality.LLMNodeRunner", FakeAutoRewriteRunner, raising=False)
    _seed_scene(
        session,
        content="Lin sees the evidence. She realizes the truth matters. In the end, everything changes.",
    )

    response = client.post(f"/api/v1/scenes/{SCENE_ID}/auto-rewrite", headers=_headers("rewrite-live-llm"))

    assert response.status_code == 200
    run = response.json()["data"]["run"]
    assert run["llm_call_id"] == "llm_call_scene_auto_rewrite_test"
    assert run["candidate_draft_row_id"]
    session.expire_all()
    assert session.get(LlmCall, "llm_call_scene_auto_rewrite_test").provider == "fake"


def test_auto_rewrite_scans_actual_candidate_instead_of_safe_source(client, session, monkeypatch) -> None:
    # Source-specific names are deliberately not process-wide defaults.  Bind
    # the protected term explicitly so this test exercises the active safety
    # policy instead of depending on a hidden, work-specific global blacklist.
    monkeypatch.setenv("NOVEL_SYSTEM_PROTECTED_SOURCE_TERMS_JSON", '["路明非"]')
    _install_llm_candidate(
        monkeypatch,
        "林岑握住盐钟残片，把幸存者阿砚推给许望。路明非站在门口等她选择。",
        llm_call_id="llm_candidate_source_leak",
    )
    _seed_scene(
        session,
        content="林岑握住盐钟残片，让幸存者阿砚先跟许望离开。她必须留下承担代价。",
    )

    response = client.post(
        f"/api/v1/scenes/{SCENE_ID}/auto-rewrite",
        headers=_headers("rewrite-candidate-source-leak"),
    )

    assert response.status_code == 200
    run = response.json()["data"]["run"]
    assert run["status"] == "blocked"
    assert run["candidate_draft_row_id"]
    assert "source_safety" in run["promotion_blockers"]
    assert any(item.startswith("literary:") for item in run["promotion_blockers"])
    assert run["gate_results"]["source_safety"]["safe"] is False
    assert "路明非" in session.get(SceneDraft, run["candidate_draft_row_id"]).content


def test_auto_rewrite_safe_candidate_can_repair_unsafe_source(client, session, monkeypatch) -> None:
    monkeypatch.setenv("NOVEL_SYSTEM_PROTECTED_SOURCE_TERMS_JSON", '["路明非"]')
    monkeypatch.setattr(
        "novel_system.services.final_text_gate.analyze_literary_quality",
        _all_clear_literary_analysis,
    )
    _install_llm_candidate(
        monkeypatch,
        (
            "林岑攥住盐钟残片，把幸存者阿砚交给许望。她必须在公开录音和保护阿砚之间选择，"
            "门外脚步逼近，她撕毁通行证作为代价，随后推开雾门。"
        ),
        llm_call_id="llm_candidate_repairs_source",
    )
    _seed_scene(session, content="路明非站在门口，旧稿仍带有受保护来源词。")

    response = client.post(
        f"/api/v1/scenes/{SCENE_ID}/auto-rewrite",
        headers=_headers("rewrite-repairs-unsafe-source"),
    )

    assert response.status_code == 200
    run = response.json()["data"]["run"]
    assert run["status"] == "candidate_ready"
    assert run["gate_results"]["source_safety"]["safe"] is True
    assert run["gate_results"]["promotable"] is True


def test_auto_rewrite_cannot_use_author_waiver_for_machine_promotion(
    client, session, monkeypatch
) -> None:
    monkeypatch.setattr(
        "novel_system.services.final_text_gate.analyze_literary_quality",
        _all_clear_literary_analysis,
    )
    monkeypatch.setattr(
        "novel_system.services.human_review_manager.HumanReviewManager.accepted_soft_risk_waiver",
        lambda *_args, **_kwargs: {
            "event_id": "review_machine_waiver",
            "reason": "author accepted an ordinary-delivery warning",
            "actor_ref": "author",
            "qc_report_id": "qc_machine_waiver",
        },
    )
    _install_llm_candidate(
        monkeypatch,
        "林岑必须在公开证据和保护幸存者之间选择，她撕毁通行证作为代价。",
        llm_call_id="llm_candidate_machine_waiver",
    )
    _seed_scene(
        session,
        content="林岑握住盐钟残片，让幸存者阿砚先跟许望离开。她必须留下承担代价。",
    )

    response = client.post(
        f"/api/v1/scenes/{SCENE_ID}/auto-rewrite",
        headers=_headers("rewrite-machine-waiver"),
    )

    assert response.status_code == 200
    run = response.json()["data"]["run"]
    assert run["status"] == "blocked"
    assert run["gate_results"]["promotable"] is False
    assert "continuity:missing_required_text" in run["promotion_blockers"]
    assert run["gate_results"]["final_text_gate"]["continuity"]["waiver"] is None


def test_auto_rewrite_gate_scores_are_computed_from_candidate(client, session) -> None:
    _seed_scene(
        session,
        content="林岑看着盐钟残片。她忽然意识到真相很重要。最后，一切都变得不同了。",
    )

    response = client.post(
        f"/api/v1/scenes/{SCENE_ID}/auto-rewrite",
        headers=_headers("rewrite-real-scores"),
    )

    assert response.status_code == 200
    gate = response.json()["data"]["run"]["gate_results"]
    nested_scores = gate["final_text_gate"]["literary_quality"]["scores"]
    assert gate["scores"] == nested_scores
    assert gate["scores"] != {
        "character_scene_core": 0.86,
        "ending_drive": 0.82,
        "choice_pressure": 0.83,
    }


def test_auto_rewrite_promote_rescans_mutated_candidate(client, session, monkeypatch) -> None:
    monkeypatch.setattr(
        "novel_system.services.final_text_gate.analyze_literary_quality",
        _all_clear_literary_analysis,
    )
    _install_llm_candidate(
        monkeypatch,
        (
            "林岑攥住盐钟残片，把幸存者阿砚交给许望。她必须在公开录音和保护阿砚之间选择，"
            "门外脚步逼近，她撕毁通行证作为代价，随后推开雾门。"
        ),
        llm_call_id="llm_candidate_toctou",
    )
    _seed_scene(session, content="林岑握住盐钟残片，决定先保护幸存者阿砚，并让许望守住门。")
    rewrite = client.post(
        f"/api/v1/scenes/{SCENE_ID}/auto-rewrite",
        headers=_headers("rewrite-toctou"),
    )
    run = rewrite.json()["data"]["run"]
    assert run["status"] == "candidate_ready"

    draft = session.get(SceneDraft, run["candidate_draft_row_id"])
    draft.content = "路明非替换了候选正文。"
    session.commit()

    response = client.post(
        f"/api/v1/auto-rewrite-runs/{run['run_id']}/promote",
        headers=_headers("promote-toctou"),
    )

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "AUTO_REWRITE_NOT_PROMOTABLE"
    session.expire_all()
    assert session.get(SceneRunState, SCENE_ID).current_final_scene_row_id == FINAL_ROW_ID
    assert session.query(FinalScene).filter(FinalScene.scene_id == SCENE_ID).count() == 1


def test_auto_rewrite_promote_rejects_safe_candidate_hash_change(client, session, monkeypatch) -> None:
    monkeypatch.setattr(
        "novel_system.services.final_text_gate.analyze_literary_quality",
        _all_clear_literary_analysis,
    )
    _install_llm_candidate(
        monkeypatch,
        (
            "林岑攥住盐钟残片，把幸存者阿砚交给许望。她必须在公开录音和保护阿砚之间选择，"
            "门外脚步逼近，她撕毁通行证作为代价，随后推开雾门。"
        ),
        llm_call_id="llm_candidate_safe_toctou",
    )
    _seed_scene(session, content="林岑握住盐钟残片，让幸存者阿砚先跟许望离开。她必须留下承担代价。")
    rewrite = client.post(
        f"/api/v1/scenes/{SCENE_ID}/auto-rewrite",
        headers=_headers("rewrite-safe-toctou"),
    )
    run = rewrite.json()["data"]["run"]
    assert run["status"] == "candidate_ready"
    recorded_hash = run["gate_results"]["content_hash"]

    draft = session.get(SceneDraft, run["candidate_draft_row_id"])
    draft.content = (
        "林岑捏着盐钟残片，让幸存者阿砚跟许望走。她必须在公开录音和保护阿砚之间选择，"
        "于是烧掉通行证承担代价，转身走进雾门。"
    )
    session.commit()

    response = client.post(
        f"/api/v1/auto-rewrite-runs/{run['run_id']}/promote",
        headers=_headers("promote-safe-toctou"),
    )

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "AUTO_REWRITE_NOT_PROMOTABLE"
    details = response.json()["error"]["details"]
    assert details["recorded_content_hash"] == recorded_hash
    assert details["actual_content_hash"] != recorded_hash
    session.expire_all()
    assert session.get(SceneRunState, SCENE_ID).current_final_scene_row_id == FINAL_ROW_ID
    assert session.query(FinalScene).filter(FinalScene.scene_id == SCENE_ID).count() == 1


def test_auto_rewrite_routes_language_only_failure_to_local_patch(client, session, monkeypatch) -> None:
    monkeypatch.setattr(
        "novel_system.services.final_text_gate.analyze_literary_quality",
        _all_clear_literary_analysis,
    )
    _seed_scene(
        session,
        content=(
            "林岑把盐钟残片交给许望，先让幸存者阿砚离开船坞。"
            "林岑必须选择公开证据还是先保护幸存者。她选择先保护幸存者，代价是暂时背负隐瞒真相的嫌疑。"
            "她低头看着录音，沉默了片刻。许望低头看着录音，沉默了片刻。"
            "林岑低头看着录音，沉默了片刻。"
        ),
    )

    response = client.post(f"/api/v1/scenes/{SCENE_ID}/auto-rewrite", headers=_headers("rewrite-patch"))

    assert response.status_code == 200
    run = response.json()["data"]["run"]
    assert run["branch"] == "local_patch"
    assert run["status"] == "candidate_ready"
    assert run["gate_results"]["promotable"] is True
    assert "template_action_reuse" in run["failure_class"]


def test_auto_rewrite_blocks_fact_or_reference_risk_before_candidate_generation(client, session) -> None:
    _seed_scene(
        session,
        content="林岑必须选择公开证据还是先保护幸存者。她把录音带递给许望。",
    )
    session.add(
        QcReport(
            qc_report_id="qc_report_qauto_blocking",
            scene_id=SCENE_ID,
            chapter_id=CHAPTER_ID,
            qc_type="hard_qc",
            source_draft_row_id="draft_style_qauto",
            source_bundle_id="bundle_qauto_v1",
            resolution_code="hard_block_human",
            pass_flag=0,
            next_action="human_review_required",
            issues_json=[{"issue_key": "missing_required_text", "message": "salt clock fragment missing"}],
            rewrite_brief_json=[],
        )
    )
    session.commit()

    response = client.post(f"/api/v1/scenes/{SCENE_ID}/auto-rewrite", headers=_headers("rewrite-block"))

    assert response.status_code == 200
    run = response.json()["data"]["run"]
    assert run["branch"] == "human_review"
    assert run["status"] == "human_review_required"
    assert run["candidate_draft_row_id"] is None
    assert run["gate_results"]["promotable"] is False
    assert "hard_qc_blocker" in run["promotion_blockers"]


def test_quality_state_reports_latest_contract_rewrite_run_and_promotion_blockers(client, session) -> None:
    _seed_scene(
        session,
        content="林岑看着盐钟残片。她忽然意识到真相很重要。最后，一切都变得不同了。",
    )
    client.post(f"/api/v1/scenes/{SCENE_ID}/quality-contract", headers=_headers("contract-state"))
    client.post(
        f"/api/v1/scenes/{SCENE_ID}/auto-rewrite",
        json={"mode": "diagnose_only"},
        headers=_headers("rewrite-diagnose"),
    )

    response = client.get(f"/api/v1/scenes/{SCENE_ID}/quality-state")

    assert response.status_code == 200
    payload = response.json()["data"]
    assert payload["contract"]["contract_version"] == "scene_quality_contract_v1"
    assert payload["latest_run"]["status"] == "diagnosed"
    assert payload["promotion"]["eligible"] is False
    assert "diagnose_only" in payload["promotion"]["blockers"]


def test_model_routing_accepts_dual_track_model_profiles() -> None:
    routing = parse_model_routing_config(
        {
            "model_profiles": {
                "local_fast": {"label": "快跑", "role": "draft"},
                "quality_strong": {"label": "精修", "role": "quality_gate"},
                "dual_track": {"label": "双轨", "role": "hybrid"},
            },
            "task_routing": {
                "scene_quality_contract": {
                    "provider": "openai_compatible",
                    "model": "gpt-5",
                    "temperature": 0.2,
                    "max_output_tokens": 1800,
                    "response_format": "json_object",
                    "model_profile": "quality_strong",
                },
                "scene_auto_rewrite": {
                    "provider": "openai_compatible",
                    "model": "gpt-5",
                    "temperature": 0.55,
                    "max_output_tokens": 5000,
                    "response_format": "json_object",
                    "model_profile": "quality_strong",
                },
            },
            "retry_budget": {},
            "job_runtime": {},
        }
    )

    assert routing.model_profiles["quality_strong"]["role"] == "quality_gate"
    assert routing.task_routing["scene_auto_rewrite"].model_profile == "quality_strong"
