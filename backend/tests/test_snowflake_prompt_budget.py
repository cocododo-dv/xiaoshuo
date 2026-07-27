"""雪花提示词输入预算：分级降载的契约。

回归的遗留缺陷：这条渲染路径从不读 `input_token_budget`，载荷（上游十步 + 全表
底稿）随作品体量无界增长。实测 120 场 / 8 角色的书单批 61,777 tok、一次点击 6 批
合计 372k tok，而模板声明 3600——声明值从来没人执行。

降载的红线：**永不为了省预算去销毁故事事实**。本步契约、作者显式意图、焦点成员
一律不动；判不出「无关」时整级跳过（宁可多花预算，不可靠猜削掉主角的档案）；
削了什么必须留痕，跑完阶梯仍超预算必须让作者看见。
"""
from __future__ import annotations

import json

from novel_system.services.context_budget import estimate_tokens
from novel_system.services.snowflake_prompt_budget import (
    PROTECTED_KEYS,
    apply_snowflake_prompt_budget,
    estimate_payload_tokens,
)

P = "她在交班前比对墨迹年份，被缺页阻拦，确认补写却不敢声张，只能把疑点压回心里。"


def _character(i: int, *, deep: bool = True) -> dict:
    member = {"character_id": f"c{i}", "display_name": f"角色{i}",
              "role": "主角" if i == 1 else "配角", "one_sentence_summary": P[:20]}
    if deep:
        member.update({"goal": P, "ambition": P, "values": P, "conflict": P, "epiphany": P,
                       "physical_profile": {f"f{j}": P for j in range(4)},
                       "psychological_profile": {f"f{j}": P for j in range(4)}})
    return member


def _scene(i: int, *, pov: str = "c1", deep: bool = True) -> dict:
    scene = {"row_uid": f"u{i}", "scene_id": f"SC{i:03d}", "chapter_id": "CH01", "scene_seq": i,
             "title": f"第{i}场", "summary": P, "primary_form": "proactive",
             "scene_type": "proactive", "pov_character_id": pov, "chapter_role": "起疑",
             "location": "地下修复室"}
    if deep:
        scene.update({"crucible": P, "scene_crucible": P, "goal": P, "conflict": P, "setback": P})
    return scene


def _payload(*, n_scenes: int = 40, n_chars: int = 8, focus_ids: list[str] | None = None) -> dict:
    focus_ids = focus_ids or ["SC001", "SC002"]
    scenes = [_scene(i) for i in range(1, n_scenes + 1)]
    payload = {
        "project": {"project_id": "big", "title": "何有", "outline_text": P},
        "step_key": "scene_details",
        "step_label": "场景规划",
        "step_instruction": P,
        "step_editor": {"kind": "form", "fields": [{"key": "scenes"}]},
        "scene_rules": {"proactive": ["goal", "conflict", "setback"]},
        "pressure_rubric": {"goal": P},
        "current_pressure_diagnosis": {"flags": []},
        "upstream_steps_how_to_use": P,
        "upstream_steps": [
            {"step_key": "long_synopsis", "label": "长梗概", "status": "approved",
             "confirmed": True, "draft": {"paragraphs": [P * 8] * 5}},
            {"step_key": "character_sheets", "label": "角色摘要表", "status": "approved",
             "confirmed": True, "draft": {"characters": [_character(i) for i in range(1, n_chars + 1)]}},
            {"step_key": "character_bibles", "label": "角色全档案", "status": "approved",
             "confirmed": True, "draft": {"characters": [_character(i) for i in range(1, n_chars + 1)]}},
            {"step_key": "scene_list", "label": "场景列表", "status": "approved",
             "confirmed": True, "draft": {"scenes": [_scene(i) for i in range(1, n_scenes + 1)]}},
        ],
        "current_draft": {"scenes": scenes},
        "focus_scenes": {
            "scenes": [s for s in scenes if s["scene_id"] in focus_ids],
            "how_to_use": P,
        },
    }
    return payload


def _upstream(payload: dict, step_key: str) -> dict:
    return next(i for i in payload["upstream_steps"] if i["step_key"] == step_key)


def test_a_payload_within_budget_is_returned_untouched():
    """没超预算就一个字都不动——降载是超限时的手段，不是常态开销。"""
    payload = _payload(n_scenes=3, n_chars=2)
    before = estimate_payload_tokens(payload)
    trimmed, report = apply_snowflake_prompt_budget(
        payload, budget_tokens=before + 1000, step_key="scene_details"
    )
    assert trimmed == payload
    assert report["applied"] == [] and report["within_budget"] is True
    assert report["estimated_before"] == report["estimated_after"] == before


def test_a_zero_budget_disables_shedding():
    """预算 0 = 不设预算（保留「没配就不管」的语义，与额度族一致）。"""
    payload = _payload()
    trimmed, report = apply_snowflake_prompt_budget(payload, budget_tokens=0, step_key="scene_details")
    assert trimmed == payload and report["applied"] == [] and report["within_budget"] is True


def test_the_step_contract_and_author_intent_are_never_shed():
    """本步契约与作者显式意图（采纳蓝本 / 修复清单 / 焦点成员）永不降载。"""
    payload = _payload(n_scenes=80, n_chars=10)
    payload["adopted_direction"] = {"text": "作者选定的方向蓝本", "how_to_use": P}
    payload["completeness_repair"] = {"empty_fields": ["SC001.goal"], "instruction": P}
    # 预算压到远低于下限，强制跑满整条阶梯
    trimmed, report = apply_snowflake_prompt_budget(payload, budget_tokens=500, step_key="scene_details")

    assert report["within_budget"] is False, "这个预算本就不可达，报告必须如实说仍超"
    for key in PROTECTED_KEYS:
        if key in payload:
            assert trimmed.get(key) == payload[key], f"受保护的 {key} 被降载了"
    focus_ids = [s["scene_id"] for s in trimmed["focus_scenes"]["scenes"]]
    assert focus_ids == ["SC001", "SC002"]
    # 焦点场在底稿里也必须保持全量（模型要在它们身上改）
    draft_by_id = {s["scene_id"]: s for s in trimmed["current_draft"]["scenes"]}
    assert draft_by_id["SC001"] == payload["current_draft"]["scenes"][0]


def test_the_relevant_character_keeps_full_detail_while_others_drop_to_identity():
    """与本批相关的角色（焦点场 POV）保留全档案，其余降到身份级但仍在名册里。"""
    payload = _payload(n_scenes=60, n_chars=8)
    trimmed, report = apply_snowflake_prompt_budget(
        payload, budget_tokens=6000, step_key="scene_details"
    )
    assert "reference_characters_to_identity" in report["applied"]

    for step_key in ("character_sheets", "character_bibles"):
        members = {m["character_id"]: m for m in _upstream(trimmed, step_key)["draft"]["characters"]}
        assert members["c1"].get("goal") or members["c1"].get("physical_profile"), \
            "焦点场 POV 的档案被削掉了"
        assert set(members) == {f"c{i}" for i in range(1, 9)}, "名册少人了，模型会现编一个"
        assert not members["c5"].get("goal") and not members["c5"].get("physical_profile"), \
            "无关角色的细节没有让出预算"
        assert members["c5"]["display_name"] == "角色5", "参照级角色必须留住身份"


def test_character_shedding_is_skipped_when_relevance_cannot_be_determined():
    """判不出相关角色时整级跳过——「无关」是猜的，猜错就是削掉主角的档案。"""
    payload = _payload(n_scenes=60, n_chars=8)
    for scene in payload["focus_scenes"]["scenes"]:
        scene.pop("pov_character_id", None)  # 没有 POV，角色名也不在场景文本里
    trimmed, report = apply_snowflake_prompt_budget(
        payload, budget_tokens=6000, step_key="scene_details"
    )
    assert "reference_characters_to_identity" not in report["applied"]
    members = {m["character_id"]: m for m in _upstream(trimmed, "character_bibles")["draft"]["characters"]}
    assert all(m.get("physical_profile") for m in members.values()), "靠猜削掉了角色档案"


def test_a_character_named_in_the_focus_scene_text_counts_as_relevant():
    """在焦点场文本里被点名的角色同样算相关——不能只认 POV 字段。"""
    payload = _payload(n_scenes=60, n_chars=8)
    for scene in payload["focus_scenes"]["scenes"]:
        scene["summary"] = f"她与角色7在码头交接，{P}"
    trimmed, _ = apply_snowflake_prompt_budget(payload, budget_tokens=6000, step_key="scene_details")
    members = {m["character_id"]: m for m in _upstream(trimmed, "character_bibles")["draft"]["characters"]}
    assert members["c7"].get("physical_profile"), "被点名的角色档案被当无关削掉了"


def test_the_upstream_scene_list_is_reduced_to_what_the_draft_does_not_carry():
    """上游场景列表与底稿高度重复，只留底稿种子没带走的字段（POV / 章内职能）。"""
    payload = _payload(n_scenes=60)
    trimmed, report = apply_snowflake_prompt_budget(
        payload, budget_tokens=20000, step_key="scene_details"
    )
    assert report["applied"][0] == "upstream_scene_list_delta", "这一级必须最先降（纯重复）"
    scenes = _upstream(trimmed, "scene_list")["draft"]["scenes"]
    assert len(scenes) == 60, "场景列表少了场，模型会以为这本书变短了"
    assert scenes[0]["pov_character_id"] == "c1" and scenes[0]["chapter_role"] == "起疑"
    assert "summary" not in scenes[0] and "crucible" not in scenes[0], "重复字段没削掉"


def test_the_scene_list_delta_rung_is_only_for_scene_planning():
    """别的步骤里场景列表不是重复材料，不能削。"""
    payload = _payload(n_scenes=60)
    payload["step_key"] = "scene_list"
    payload.pop("focus_scenes")
    _, report = apply_snowflake_prompt_budget(payload, budget_tokens=3000, step_key="scene_list")
    assert "upstream_scene_list_delta" not in report["applied"]


def test_long_upstream_prose_is_truncated_with_a_visible_marker():
    """长散文截断要留显式标记——模型不能把截断当成作者写完了。"""
    payload = _payload(n_scenes=10, n_chars=2)
    trimmed, report = apply_snowflake_prompt_budget(
        payload, budget_tokens=1200, step_key="scene_details"
    )
    assert "truncate_long_prose" in report["applied"]
    paragraphs = _upstream(trimmed, "long_synopsis")["draft"]["paragraphs"]
    assert all(p.endswith("（上下文预算已截断）") for p in paragraphs)
    assert all(estimate_tokens(p) <= 170 for p in paragraphs), f"截断后仍超上限：{[estimate_tokens(p) for p in paragraphs]}"


def test_shedding_is_idempotent():
    """对已降载的载荷再跑一次，不该谎报又腾出了空间，也不该叠加截断标记。"""
    payload = _payload(n_scenes=60, n_chars=8)
    once, first = apply_snowflake_prompt_budget(payload, budget_tokens=500, step_key="scene_details")
    twice, second = apply_snowflake_prompt_budget(once, budget_tokens=500, step_key="scene_details")
    assert second["applied"] == [], f"重复降载谎报生效：{second['applied']}"
    assert twice == once
    assert first["estimated_after"] == second["estimated_before"] == second["estimated_after"]


def test_the_ladder_stops_as_soon_as_it_fits():
    """达标即停：能少降就少降，不能一路削到底。"""
    payload = _payload(n_scenes=60, n_chars=8)
    _, report = apply_snowflake_prompt_budget(payload, budget_tokens=20000, step_key="scene_details")
    assert report["within_budget"] is True
    assert report["estimated_after"] <= 20000
    assert "drop_reference_scenes" not in report["applied"], "还没到兜底级就用了兜底"


def test_the_report_tracks_the_actual_reduction():
    """报告的数字必须与载荷实际体量吻合——它要进审计，不能是装饰。"""
    payload = _payload(n_scenes=60, n_chars=8)
    trimmed, report = apply_snowflake_prompt_budget(
        payload, budget_tokens=8000, step_key="scene_details"
    )
    assert report["estimated_before"] == estimate_payload_tokens(payload)
    assert report["estimated_after"] == estimate_payload_tokens(trimmed)
    assert report["estimated_after"] < report["estimated_before"]
    assert report["budget_tokens"] == 8000


def test_json_serializable_report():
    """报告要进 LLM 审计摘要，必须可序列化。"""
    payload = _payload(n_scenes=30)
    _, report = apply_snowflake_prompt_budget(payload, budget_tokens=5000, step_key="scene_details")
    assert json.loads(json.dumps(report)) == report


def test_advisory_node_payloads_are_shed_too():
    """代码评审回归：驻场教练用 approved_context、候选生成用 current_canonical_draft，
    阶梯若只认 upstream_steps / current_draft，这些节点就整条空转——报告说超预算，
    却把原样的超大载荷发出去，正是这套预算要防的事。"""
    big = P * 30
    payload = {
        "project": {"project_id": "p", "title": "何有"},
        "step_key": "scene_details",
        "message": "这一章的压力够吗",
        "approved_context": [
            {"step_key": "long_synopsis", "label": "长梗概", "confirmed": True,
             "draft": {"paragraphs": [big] * 5}},
            {"step_key": "character_bibles", "label": "角色全档案", "confirmed": True,
             "draft": {"characters": [_character(i) for i in range(1, 9)]}},
        ],
        "pressure_rubric": {"goal": P},
    }
    before = estimate_payload_tokens(payload)
    trimmed, report = apply_snowflake_prompt_budget(payload, budget_tokens=4000, step_key="scene_details")

    assert report["applied"], f"顾问型载荷整条阶梯空转：{report}"
    assert report["estimated_after"] < before * 0.6, f"没削下来：{before} → {report['estimated_after']}"
    assert "approved_context" in trimmed, "键名被换掉了，调用方会读不到上下文"
    assert trimmed["message"] == "这一章的压力够吗"


def test_the_candidates_node_draft_key_is_recognised():
    """候选生成的本步草稿叫 current_canonical_draft。"""
    payload = {
        "step_key": "scene_details",
        "upstream_steps": [{"step_key": "scene_list", "label": "场景列表", "confirmed": True,
                            "draft": {"scenes": [_scene(i) for i in range(1, 40)]}}],
        "current_canonical_draft": {"scenes": [_scene(i) for i in range(1, 40)]},
        "focus_scenes": {"scenes": [_scene(1)], "how_to_use": P},
    }
    trimmed, report = apply_snowflake_prompt_budget(payload, budget_tokens=1500, step_key="scene_details")
    assert "reference_scenes_to_identity" in report["applied"]
    assert "current_canonical_draft" in trimmed


def test_a_rung_that_violates_the_protected_keys_is_undone_and_reported():
    """PROTECTED_KEYS 必须是生产代码里生效的不变量，不能只是一句注释。"""
    import novel_system.services.snowflake_prompt_budget as mod

    def rogue_rung(payload, focus):
        # 一个「新增的」降载级别误伤了焦点场
        return {**payload, "focus_scenes": {"scenes": []}}

    original_ladder = mod._ladder
    mod._ladder = lambda step_key: (("rogue", rogue_rung),)
    try:
        payload = _payload(n_scenes=40)
        trimmed, report = apply_snowflake_prompt_budget(
            payload, budget_tokens=100, step_key="scene_details"
        )
    finally:
        mod._ladder = original_ladder

    assert trimmed["focus_scenes"] == payload["focus_scenes"], "受保护的焦点场被削掉了"
    assert "focus_scenes" in (report.get("protected_restored") or []), "恢复动作没有留痕"
