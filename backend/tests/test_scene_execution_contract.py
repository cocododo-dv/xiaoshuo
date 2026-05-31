from __future__ import annotations

from novel_system.db.models import (
    ChapterGoal,
    FinalScene,
    ProjectBacktrackItem,
    QcReport,
    SceneCard,
    SceneExecutionContract,
    SceneRunState,
    StoryProject,
    StyleReferenceBook,
    StyleReferenceInjectionBinding,
    StyleReferenceProfile,
    StyleReferenceRun,
)


PROJECT_ID = "PRJ_EXECUTION"
CHAPTER_ID = f"{PROJECT_ID}_CH01"
SCENE_ID = f"{CHAPTER_ID}_SC01"
REACTIVE_SCENE_ID = f"{CHAPTER_ID}_SC02"


def _seed_project(session) -> None:
    session.add(
        StoryProject(
            project_id=PROJECT_ID,
            title="雨城残响",
            genre="都市悬疑",
            target_word_count=120000,
            target_chapter_count=1,
            outline_text="林岚回到雨城追查旧案，并在真相与保护幸存者之间做选择。",
            planning_mode="snowflake",
            status="chapter_ready",
            current_chapter_id=CHAPTER_ID,
            reference_profile_ids_json=[],
        )
    )
    session.add(
        ChapterGoal(
            chapter_id=CHAPTER_ID,
            project_id=PROJECT_ID,
            planned_scene_count=2,
            chapter_goal="林岚必须决定先公开真相还是先保护幸存者。",
            main_plot_push="证据逼近旧案核心。",
            emotional_target="信任变成代价。",
            ending_effect="选择一旦做出就无法撤回。",
            writer_brief_json={
                "core_promise": "真相和保护无法同时满足。",
                "ending_question": "林岚会把证据交给谁？",
            },
        )
    )
    session.add(
        SceneCard(
            scene_id=SCENE_ID,
            chapter_id=CHAPTER_ID,
            project_id=PROJECT_ID,
            scene_seq=1,
            pov_character_id="林岚",
            onstage_chars_json=["林岚", "许望"],
            location="旧码头仓库",
            scene_goal="林岚拿到录音，但必须决定是否立刻公开。",
            beats_json=["找到录音", "许望要求先藏起来", "林岚做出选择"],
            must_include_text="盐钟残片；幸存者阿砚；许望",
            forbidden_text="不得复刻参考书原文表达",
            exit_change="林岚藏起一半证据，准备先转移幸存者。",
            hook="第二枚盐钟的影子出现在雾墙上。",
            scene_type="proactive",
            writer_brief_json={
                "scene_form": "proactive",
                "scene_crucible": "只要证据公开过早，幸存者的位置就会暴露。",
                "goal": "确认录音是否足以公开真相。",
                "conflict": "许望要求她先保护幸存者，不要现在公开录音。",
                "setback": "她只能把证据拆开保存，因此暂时失去完整公开的机会。",
                "character_desire": "拿到足够证据后立刻行动。",
                "obstacle": "行动越快，幸存者越危险。",
                "stakes": "幸存者阿砚会暴露。",
                "secret_or_misunderstanding": "许望已经提前接触过幸存者。",
                "choice_under_pressure": "立刻公开录音，还是先保护幸存者。",
                "power_shift": "录音从许望手里转到林岚手里。",
                "new_information": "录音里出现第二枚盐钟。",
                "emotional_turn": "笃定变成克制。",
                "image_anchor": "盐钟残片上的裂纹。",
                "reader_aftertaste": "她的冷静正在越界。",
            },
        )
    )
    session.add(
        SceneCard(
            scene_id=REACTIVE_SCENE_ID,
            chapter_id=CHAPTER_ID,
            project_id=PROJECT_ID,
            scene_seq=2,
            pov_character_id="林岚",
            onstage_chars_json=["林岚"],
            location="雨城旧居",
            scene_goal="林岚从挫败里恢复，并决定下一步调查方向。",
            beats_json=["崩溃", "权衡", "决定"],
            must_include_text="被拆开的证据袋",
            exit_change="她决定去见阿砚。",
            hook="门口的脚印已经消失。",
            scene_type="reactive",
            writer_brief_json={
                "scene_form": "reactive",
                "scene_crucible": "如果她在这一刻退缩，整个调查就会死掉。",
                "reaction": "林岚意识到自己差一点害死阿砚。",
                "dilemma": "继续追查会扩大危险，停下又会让真相永远沉底。",
                "decision": "她决定在天亮前单独去见阿砚。",
                "character_desire": "保住阿砚并继续追查。",
                "obstacle": "她已经无法确定还能信谁。",
                "stakes": "一旦迟疑，所有证据都会被清洗。",
                "choice_under_pressure": "停下调查，还是独自推进。",
                "power_shift": "她不再接受许望的节奏。",
                "new_information": "旧居门口有人来过。",
                "emotional_turn": "恐惧变成孤注一掷。",
                "image_anchor": "被拆开的证据袋。",
                "reader_aftertaste": "她已经没有退路。",
            },
        )
    )
    session.add(SceneRunState(scene_id=SCENE_ID, scene_status="ready", attempt_budget=4))
    session.add(SceneRunState(scene_id=REACTIVE_SCENE_ID, scene_status="ready", attempt_budget=4))
    session.add(
        StyleReferenceBook(
            book_id="BOOK_EXECUTION",
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
    session.add(
        StyleReferenceRun(
            run_id="RUN_EXECUTION",
            book_id="BOOK_EXECUTION",
            status="done",
            phase="done",
            coverage_json={},
        )
    )
    session.add(
        StyleReferenceProfile(
            profile_id="PROFILE_EXECUTION",
            book_id="BOOK_EXECUTION",
            run_id="RUN_EXECUTION",
            title="抽象画像",
            status="active",
            profile_json={
                "style_rules": ["短句推进", "对白压缩解释"],
                "structure_rules": ["主动场景尽量以 setback 收束", "反应场景必须落到 decision"],
                "safety_rules": ["不得借用原文表达", "不得借用角色设定"],
            },
        )
    )
    session.add(
        StyleReferenceInjectionBinding(
            binding_id="BIND_EXECUTION",
            profile_id="PROFILE_EXECUTION",
            scope="project",
            scope_ref_id=PROJECT_ID,
            task_type="scene_generation",
            strategy="A",
            config_json={},
            status="active",
        )
    )
    session.commit()


def _headers(key: str) -> dict[str, str]:
    return {"X-Idempotency-Key": key}


def test_execution_contract_endpoint_generates_proactive_contract_and_splits_reference_rules(client, session) -> None:
    _seed_project(session)

    response = client.post(f"/api/v1/scenes/{SCENE_ID}/execution-contract", headers=_headers("execution-contract"))

    assert response.status_code == 200
    payload = response.json()["data"]["contract"]
    assert payload["scene_id"] == SCENE_ID
    assert payload["status"] == "active"
    assert payload["payload"]["scene_mode"] == "proactive"
    assert payload["payload"]["scene_crucible"] == "只要证据公开过早，幸存者的位置就会暴露。"
    assert payload["payload"]["goal"]
    assert payload["payload"]["conflict"]
    assert payload["payload"]["setback_or_victory"]
    assert payload["payload"]["image_anchor"] == "盐钟残片上的裂纹。"
    assert payload["payload"]["reference_rules"] == {
        "style_rules": ["短句推进", "对白压缩解释"],
        "structure_rules": ["主动场景尽量以 setback 收束", "反应场景必须落到 decision"],
        "safety_rules": ["不得借用原文表达", "不得借用角色设定"],
    }

    read_back = client.get(f"/api/v1/scenes/{SCENE_ID}/execution-contract")
    assert read_back.status_code == 200
    assert read_back.json()["data"]["contract"]["contract_id"] == payload["contract_id"]
    assert session.get(SceneExecutionContract, payload["contract_id"]).status == "active"


def test_execution_contract_endpoint_generates_reactive_contract(client, session) -> None:
    _seed_project(session)

    response = client.post(f"/api/v1/scenes/{REACTIVE_SCENE_ID}/execution-contract", headers=_headers("execution-reactive"))

    assert response.status_code == 200
    payload = response.json()["data"]["contract"]["payload"]
    assert payload["scene_mode"] == "reactive"
    assert payload["scene_crucible"] == "如果她在这一刻退缩，整个调查就会死掉。"
    assert payload["reaction"] == "林岚意识到自己差一点害死阿砚。"
    assert payload["dilemma"]
    assert payload["decision"]
    assert payload["relationship_turn"] == "她不再接受许望的节奏。"


def test_execution_contract_blocks_scene_run_when_required_fields_cannot_be_derived(client, session) -> None:
    _seed_project(session)
    scene = session.get(SceneCard, SCENE_ID)
    assert scene is not None
    scene.writer_brief_json = {
        "scene_form": "proactive",
        "character_desire": "尽快行动",
    }
    session.commit()

    contract_response = client.post(f"/api/v1/scenes/{SCENE_ID}/execution-contract", headers=_headers("execution-blocked"))

    assert contract_response.status_code == 200
    contract = contract_response.json()["data"]["contract"]
    assert contract["status"] == "blocked"
    assert set(contract["missing_fields"]) >= {"scene_crucible", "conflict", "setback_or_victory"}

    run_response = client.post(f"/api/v1/scenes/{SCENE_ID}/run/full", headers=_headers("run-blocked-contract"))
    assert run_response.status_code == 409
    assert run_response.json()["error"]["code"] == "SCENE_EXECUTION_CONTRACT_BLOCKED"


def test_scene_triage_backtrack_uses_author_language_for_missing_contract_fields(client, session) -> None:
    _seed_project(session)
    scene = session.get(SceneCard, SCENE_ID)
    assert scene is not None
    scene.writer_brief_json = {
        "scene_form": "proactive",
        "character_desire": "尽快行动",
    }
    session.commit()

    contract_response = client.post(f"/api/v1/scenes/{SCENE_ID}/execution-contract", headers=_headers("execution-author-language"))
    assert contract_response.status_code == 200
    contract = contract_response.json()["data"]["contract"]
    assert contract["status"] == "blocked"
    assert "scene_crucible" in contract["missing_fields"]

    triage_response = client.post(f"/api/v1/scenes/{SCENE_ID}/triage", headers=_headers("triage-author-language"))

    assert triage_response.status_code == 200
    triage = triage_response.json()["data"]["triage"]
    assert triage["decision"] == "no"
    backtrack = session.get(ProjectBacktrackItem, triage["backtrack_item_id"])
    assert backtrack is not None
    assert "坩埚/场景压力" in backtrack.problem_summary
    assert "冲突推进" in backtrack.problem_summary
    assert "scene_crucible" not in backtrack.problem_summary
    assert "setback_or_victory" not in backtrack.recommended_fix


def test_scene_triage_returns_yes_maybe_and_no_and_manages_backtrack_items(client, session) -> None:
    _seed_project(session)
    contract = client.post(f"/api/v1/scenes/{SCENE_ID}/execution-contract", headers=_headers("execution-triage")).json()["data"]["contract"]
    state = session.get(SceneRunState, SCENE_ID)
    assert state is not None

    final_scene = FinalScene(
        row_id="final_scene_execution_yes",
        scene_id=SCENE_ID,
        chapter_id=CHAPTER_ID,
        content="林岚把录音拆成两份，先送走阿砚，再回头公开真相。",
        status="approved",
        source_bundle_id="bundle_yes",
        source_bundle_hash="hash_yes",
    )
    qc_report = QcReport(
        qc_report_id="qc_execution_yes",
        scene_id=SCENE_ID,
        chapter_id=CHAPTER_ID,
        qc_type="soft_qc",
        source_draft_row_id="draft_style_yes",
        source_bundle_id="bundle_yes",
        resolution_code="soft_pass",
        pass_flag=1,
        next_action="pass",
        issues_json=[],
        rewrite_brief_json=[],
    )
    session.add_all([final_scene, qc_report])
    state.current_final_scene_row_id = final_scene.row_id
    state.current_qc_report_id = qc_report.qc_report_id
    state.scene_status = "archived"
    session.commit()

    yes_response = client.post(f"/api/v1/scenes/{SCENE_ID}/triage", headers=_headers("triage-yes"))
    assert yes_response.status_code == 200
    yes_decision = yes_response.json()["data"]["triage"]
    assert yes_decision["decision"] == "yes"
    assert yes_decision["next_action"] == "chapter_aggregate"
    assert yes_decision["source_qc_report_id"] == "qc_execution_yes"

    state.current_final_scene_row_id = None
    state.scene_status = "soft_qc_patch_required"
    state.soft_patch_count = 0
    qc_report.resolution_code = "soft_patch_requested"
    qc_report.pass_flag = 0
    qc_report.next_action = "patch"
    qc_report.issues_json = [{"issue_key": "ending_drive", "message": "ending needs more pull"}]
    qc_report.rewrite_brief_json = [{"instruction": "End on a visible choice."}]
    session.commit()

    maybe_response = client.post(f"/api/v1/scenes/{SCENE_ID}/triage", headers=_headers("triage-maybe"))
    assert maybe_response.status_code == 200
    maybe_decision = maybe_response.json()["data"]["triage"]
    assert maybe_decision["decision"] == "maybe"
    assert maybe_decision["next_action"] == "auto_rewrite"
    assert "soft_patch_requested" in maybe_decision["reason_codes"]

    state.soft_patch_count = 1
    state.scene_status = "soft_qc_patch_required"
    session.commit()

    no_response = client.post(f"/api/v1/scenes/{SCENE_ID}/triage", headers=_headers("triage-no"))
    assert no_response.status_code == 200
    no_decision = no_response.json()["data"]["triage"]
    assert no_decision["decision"] == "no"
    assert no_decision["next_action"] == "create_backtrack_item"
    assert "soft_patch_limit_reached" in no_decision["reason_codes"]

    session.expire_all()
    backtrack_rows = session.query(ProjectBacktrackItem).filter_by(project_id=PROJECT_ID).all()
    assert len(backtrack_rows) == 1
    assert backtrack_rows[0].scope == "scene_detail"
    assert backtrack_rows[0].status == "pending"
    assert session.get(SceneRunState, SCENE_ID).scene_status == "needs_replan"

    listing = client.get(f"/api/v1/projects/{PROJECT_ID}/backtrack-items")
    assert listing.status_code == 200
    items = listing.json()["data"]["items"]
    assert len(items) == 1
    assert items[0]["scope"] == "scene_detail"

    resolve = client.post(
        f"/api/v1/projects/{PROJECT_ID}/backtrack-items/{items[0]['item_id']}/resolve",
        json={"resolution_note": "已回到 scene_details 重新规划。"},
        headers=_headers("triage-resolve"),
    )
    assert resolve.status_code == 200
    resolved = resolve.json()["data"]["item"]
    assert resolved["status"] == "resolved"
    assert resolved["resolution_note"] == "已回到 scene_details 重新规划。"
