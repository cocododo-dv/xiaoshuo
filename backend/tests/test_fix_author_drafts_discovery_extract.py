"""legacy-author-drafts 修复回归。

(1) 发现稿（object_type=project）「提取结构」：提示词必须向模型索要
    candidate_brief.snowflake_steps，归一化要接受模型把步骤键直接放在 candidate_brief
    里的写法，且拿不到任何步骤时 fail-closed 并说明收到了什么。
(2) promote-canonical 之后立刻 derive-from-generation：草稿是 HTML、权威正文是
    canonicalize 后的纯文本，两边按同一规则归一化后相等即为空操作——不得新增修订、
    不得把草稿标成 canonical_dirty。
"""

from __future__ import annotations

import json

import pytest

from novel_system.db.models import (
    AuthorDraftEvent,
    AuthorDraftRevision,
    AuthorStructureCandidate,
    FinalScene,
    SnowflakeStepRun,
)
from novel_system.services.llm_client import LLMResponse
from tests.test_author_drafts import _create_chapter, _create_scene, _finalize_scene

SNOWFLAKE_DISCOVERY_STEP_KEYS = {
    "book_brief",
    "one_sentence_summary",
    "one_paragraph_summary",
    "scene_list",
    "scene_details",
}


@pytest.fixture(autouse=True)
def _llm_enabled(monkeypatch):
    monkeypatch.setenv("NOVEL_SYSTEM_LLM_ENABLED", "true")


def _install_structure_extract_fake(monkeypatch, payload_factory):
    """按 test_author_drafts 的在线记账替身写法，只服务 author_structure_extract。"""

    captured: dict = {}

    def fake_generate(self, request, *, accounting_hook=None):  # noqa: ANN001
        assert request.node_id == "author_structure_extract", request.node_id
        captured["request"] = request
        payload = payload_factory()
        usage = {"input_tokens": 12, "output_tokens": 24, "total_tokens": 36}
        response = LLMResponse(
            request_id="resp_author_structure_extract",
            provider="test-online-provider",
            model=request.model,
            text=json.dumps(payload, ensure_ascii=False),
            structured_output=payload,
            response_format="json_object",
            raw_response={"id": "resp_author_structure_extract", "usage": usage},
            usage=usage,
            finish_reason="stop",
        )
        if accounting_hook is not None:
            handle = accounting_hook.before_dispatch(request=request, dispatch_kind="initial")
            accounting_hook.after_response(handle, request=request, response=response, latency_ms=1)
        return response

    monkeypatch.setattr("novel_system.services.llm_client.LLMClient.generate", fake_generate)
    return captured


def _discovery_draft_with_content(client, key: str) -> dict:
    project_response = client.post(
        "/api/v2/projects",
        json={
            "title": f"发现稿 {key}",
            "genre": "悬疑",
            "target_chapter_count": 2,
            "target_word_count": 60000,
            "outline_text": "一封旧信把她带回雨城。",
        },
        headers={"X-Idempotency-Key": f"fix-discovery-project-{key}"},
    )
    assert project_response.status_code == 200, project_response.text
    project_id = project_response.json()["data"]["project"]["project_id"]
    ensured = client.post(f"/api/v1/projects/{project_id}/discovery-draft/ensure")
    assert ensured.status_code == 200, ensured.text
    draft = ensured.json()["data"]["draft"]
    saved = client.patch(
        f"/api/v1/author-drafts/{draft['draft_id']}",
        json={
            "content": (
                "读者：想要情感代价的悬疑读者。\n"
                "一句话：制图师揭开铁路旧案，并赌上自己的家人。\n"
                "场景：1. 她在车站墙里发现封存的地图。2. 她用地图换证人的安全。"
            ),
            "base_revision_no": draft["revision_no"],
        },
    )
    assert saved.status_code == 200, saved.text
    return saved.json()["data"]["draft"]


def _user_prompt_text(request) -> str:
    return "\n".join(
        str(message.get("content", ""))
        for message in (request.messages or [])
        if message.get("role") == "user"
    )


def _chapter_style_brief() -> dict:
    # 模型按旧提示词的字面理解会给出章节词表——这是线上真实失败的形状。
    return {
        "candidate_brief": {
            "core_promise": "真相与保护不能同时兑现。",
            "plot_movement": "旧信把主角带回事发地。",
            "chapter_question": "谁在暗处盯着？",
        },
        "uncertainty_notes": [],
        "rationale": "从发现稿反向提取。",
    }


def test_project_structure_extract_prompt_requests_snowflake_steps(client, monkeypatch) -> None:
    captured = _install_structure_extract_fake(monkeypatch, _chapter_style_brief)
    draft = _discovery_draft_with_content(client, "prompt")

    client.post(f"/api/v1/author-drafts/{draft['draft_id']}/structure-extract")

    assert "request" in captured, "extraction never reached the LLM"
    prompt_text = _user_prompt_text(captured["request"])
    assert "snowflake_steps" in prompt_text
    # 契约段由代码侧 _append_project_step_contract 追加，而不只靠仓库 yaml 里的
    # task_prompt 文案：库里若有活动 prompts 快照，yaml 根本不会被读。断言标题与
    # 各步骤键都出现在追加段之内，才真正覆盖「快照遮蔽仓库文件」这条路径。
    marker = "## Project Discovery Target Contract"
    assert marker in prompt_text, "code-side project contract section missing from the user prompt"
    contract_section = prompt_text.split(marker, 1)[1]
    assert "snowflake_steps" in contract_section
    for step_key in SNOWFLAKE_DISCOVERY_STEP_KEYS:
        assert step_key in contract_section, step_key


def test_project_structure_extract_accepts_step_keys_directly_in_candidate_brief(client, session, monkeypatch) -> None:
    _install_structure_extract_fake(
        monkeypatch,
        lambda: {
            "candidate_brief": {
                "book_brief": {"category": "悬疑", "target_reader": "想要情感代价的悬疑读者。"},
                "one_sentence_summary": {"summary": "制图师揭开铁路旧案，并赌上自己的家人。"},
                "scene_list": {
                    "scenes": [
                        {"summary": "她在车站墙里发现封存的地图。", "primary_form": "proactive"},
                        {"summary": "她用地图换证人的安全。", "primary_form": "reactive"},
                    ]
                },
            },
            "uncertainty_notes": ["一段话概括在稿子里没有依据，未提取。"],
            "rationale": "只提取稿子明确支持的步骤。",
        },
    )
    draft = _discovery_draft_with_content(client, "direct-keys")

    extract_response = client.post(f"/api/v1/author-drafts/{draft['draft_id']}/structure-extract")

    assert extract_response.status_code == 200, extract_response.text
    candidate = extract_response.json()["data"]["candidate"]
    assert candidate["object_type"] == "project"
    assert set(candidate["candidate_brief"]["snowflake_steps"]) == {"book_brief", "one_sentence_summary", "scene_list"}
    assert candidate["candidate_brief"]["snowflake_steps"]["one_sentence_summary"]["summary"].startswith("制图师")
    assert candidate["uncertainty_notes"] == ["一段话概括在稿子里没有依据，未提取。"]

    apply_response = client.post(f"/api/v1/author-structure-candidates/{candidate['candidate_id']}/apply-to-snowflake")

    assert apply_response.status_code == 200, apply_response.text
    assert sorted(apply_response.json()["data"]["imported_step_keys"]) == ["book_brief", "one_sentence_summary", "scene_list"]
    session.expire_all()
    runs = session.query(SnowflakeStepRun).filter(SnowflakeStepRun.project_id == draft["object_id"]).all()
    assert {run.step_key for run in runs} == {"book_brief", "one_sentence_summary", "scene_list"}
    assert all(run.status == "pending_review" for run in runs)


def test_project_structure_extract_still_accepts_nested_snowflake_steps(client, monkeypatch) -> None:
    step_body = {"summary": "样例步骤。"}
    _install_structure_extract_fake(
        monkeypatch,
        lambda: {
            "candidate_brief": {"snowflake_steps": {key: dict(step_body) for key in SNOWFLAKE_DISCOVERY_STEP_KEYS}},
            "uncertainty_notes": [],
            "rationale": "嵌套写法。",
        },
    )
    draft = _discovery_draft_with_content(client, "nested")

    extract_response = client.post(f"/api/v1/author-drafts/{draft['draft_id']}/structure-extract")

    assert extract_response.status_code == 200, extract_response.text
    candidate = extract_response.json()["data"]["candidate"]
    assert set(candidate["candidate_brief"]["snowflake_steps"]) == SNOWFLAKE_DISCOVERY_STEP_KEYS


def test_project_structure_extract_without_any_step_fails_closed_and_names_received_keys(client, session, monkeypatch) -> None:
    _install_structure_extract_fake(monkeypatch, _chapter_style_brief)
    draft = _discovery_draft_with_content(client, "no-steps")

    extract_response = client.post(f"/api/v1/author-drafts/{draft['draft_id']}/structure-extract")

    assert extract_response.status_code == 502, extract_response.text
    error = extract_response.json()["error"]
    assert error["code"] == "AUTHOR_STRUCTURE_OUTPUT_INVALID"
    assert error["details"]["object_type"] == "project"
    assert error["details"]["received_keys"] == ["chapter_question", "core_promise", "plot_movement"]
    assert error["details"]["expected_step_keys"] == sorted(SNOWFLAKE_DISCOVERY_STEP_KEYS)
    session.expire_all()
    assert session.query(AuthorStructureCandidate).filter_by(object_id=draft["object_id"]).count() == 0


def test_derive_from_generation_right_after_promote_canonical_is_a_noop(client, session) -> None:
    _create_chapter(client, "ADFIX_PROMOTE", planned_scene_count=1)
    _create_scene(client, "ADFIX_PROMOTE_SC01", chapter_id="ADFIX_PROMOTE", scene_seq=1, is_chapter_last=1)
    draft = client.post("/api/v1/author-drafts/scene/ADFIX_PROMOTE_SC01/ensure-blank").json()["data"]["draft"]
    html = "<p>林岑把录音带塞进袖口。</p><p>许望问她是否公开，她只关上船坞的门。</p>"
    saved = client.patch(
        f"/api/v1/author-drafts/{draft['draft_id']}",
        json={"content": html, "base_revision_no": draft["revision_no"]},
    )
    assert saved.status_code == 200, saved.text
    draft = saved.json()["data"]["draft"]

    promoted = client.post(
        f"/api/v1/author-drafts/{draft['draft_id']}/promote-canonical",
        json={
            "base_revision_no": draft["revision_no"],
            "expected_current_final_scene_row_id": None,
            "accepted_warning_codes": [],
        },
        headers={"X-Idempotency-Key": "adfix-promote-canonical"},
    )
    assert promoted.status_code == 200, promoted.text
    final_id = promoted.json()["data"]["final_scene_row_id"]
    session.expire_all()
    # 权威正文是 canonicalize 后的纯文本，而草稿仍是 HTML——两者是同一份文字。
    assert session.get(FinalScene, final_id).content == "林岑把录音带塞进袖口。\n许望问她是否公开，她只关上船坞的门。"
    revisions_before = session.query(AuthorDraftRevision).filter_by(draft_id=draft["draft_id"]).count()
    events_before = session.query(AuthorDraftEvent).filter_by(draft_id=draft["draft_id"]).count()
    clean = client.get("/api/v1/author-drafts/scene/ADFIX_PROMOTE_SC01/current").json()["data"]
    assert clean["runtime_final_ref"] == f"final_scene:{final_id}"
    assert clean["draft"]["canonical_dirty"] is False

    derived = client.post(f"/api/v1/author-drafts/{draft['draft_id']}/derive-from-generation")

    assert derived.status_code == 200, derived.text
    data = derived.json()["data"]
    assert data["changed"] is False
    assert data["draft"]["revision_no"] == draft["revision_no"]
    assert data["draft"]["content"] == html
    assert data["draft"]["canonical_dirty"] is False
    assert data["draft"]["source_text_ref"] == draft["source_text_ref"]
    session.expire_all()
    assert session.query(AuthorDraftRevision).filter_by(draft_id=draft["draft_id"]).count() == revisions_before
    assert session.query(AuthorDraftEvent).filter_by(draft_id=draft["draft_id"]).count() == events_before
    current = client.get("/api/v1/author-drafts/scene/ADFIX_PROMOTE_SC01/current").json()["data"]
    assert current["draft"]["canonical_dirty"] is False
    assert current["draft"]["revision_no"] == draft["revision_no"]


def test_derive_from_generation_treats_html_draft_equal_to_plain_final_as_noop(client, session) -> None:
    _create_chapter(client, "ADFIX_PLAIN", planned_scene_count=1)
    _create_scene(client, "ADFIX_PLAIN_SC01", chapter_id="ADFIX_PLAIN", scene_seq=1, is_chapter_last=1)
    _finalize_scene(session, "ADFIX_PLAIN_SC01", "ADFIX_PLAIN", "第一段正文。\n第二段正文。")
    draft = client.post("/api/v1/author-drafts/scene/ADFIX_PLAIN_SC01/ensure-blank").json()["data"]["draft"]
    saved = client.patch(
        f"/api/v1/author-drafts/{draft['draft_id']}",
        json={"content": "<p>第一段正文。</p><p>第二段正文。</p>", "base_revision_no": draft["revision_no"]},
    )
    assert saved.status_code == 200, saved.text
    draft = saved.json()["data"]["draft"]

    derived = client.post(f"/api/v1/author-drafts/{draft['draft_id']}/derive-from-generation")

    assert derived.status_code == 200, derived.text
    data = derived.json()["data"]
    assert data["changed"] is False
    assert data["draft"]["revision_no"] == draft["revision_no"]
    assert data["draft"]["content"] == "<p>第一段正文。</p><p>第二段正文。</p>"


def test_derive_from_generation_still_copies_genuinely_different_runtime_text(client, session) -> None:
    _create_chapter(client, "ADFIX_DIFF", planned_scene_count=1)
    _create_scene(client, "ADFIX_DIFF_SC01", chapter_id="ADFIX_DIFF", scene_seq=1, is_chapter_last=1)
    final_id = _finalize_scene(session, "ADFIX_DIFF_SC01", "ADFIX_DIFF", "运行终稿改写了第二段。")
    draft = client.post("/api/v1/author-drafts/scene/ADFIX_DIFF_SC01/ensure-blank").json()["data"]["draft"]
    saved = client.patch(
        f"/api/v1/author-drafts/{draft['draft_id']}",
        json={"content": "<p>作者原稿。</p>", "base_revision_no": draft["revision_no"]},
    )
    draft = saved.json()["data"]["draft"]

    derived = client.post(f"/api/v1/author-drafts/{draft['draft_id']}/derive-from-generation")

    assert derived.status_code == 200, derived.text
    data = derived.json()["data"]
    assert data["changed"] is True
    assert data["draft"]["revision_no"] == draft["revision_no"] + 1
    assert data["draft"]["content"] == "运行终稿改写了第二段。"
    assert data["draft"]["source_text_ref"] == f"final_scene:{final_id}"
