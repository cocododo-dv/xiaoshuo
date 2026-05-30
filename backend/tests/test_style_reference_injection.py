"""PR-8 §5.1 — InjectionService.fragments_for 4 种 strategy + 边界用例。"""

from __future__ import annotations

import pytest

from novel_system.db.session import SessionLocal
from novel_system.services.style_reference.config_loader import clear_config_cache
from novel_system.services.style_reference.injection import (
    InjectionService,
    ordered_character_ids,
)
from novel_system.services.style_reference.repository import StyleReferenceRepository
from novel_system.services.style_reference.schemas import InjectionStrategy


@pytest.fixture(autouse=True)
def _reset_yaml_cache():
    clear_config_cache()
    yield
    clear_config_cache()


def _seed(
    *,
    seed: str,
    profile_json: dict | None = None,
    forbidden_findings: list[str] | None = None,
    strategy: str = "A",
    config_json: dict | None = None,
    project_id: str = "project_x",
    task_type: str = "scene_generation",
    scope: str = "project",
    profile_status: str = "active",
    extra_bindings: list[dict] | None = None,
) -> str:
    """落 1 个 book + run + profile + binding(可选 forbidden findings)。"""
    book_id = f"sr_book_{seed}"
    run_id = f"sr_run_{seed}"
    profile_id = f"sr_profile_{seed}"
    binding_id = f"sr_bind_{seed}"

    with SessionLocal() as session:
        repo = StyleReferenceRepository(session)
        repo.create_book(
            book_id=book_id, title="t", source_kind="upload", cloud_policy="local_only",
            text_checksum=f"chk_{seed}", total_chars=10, status="ready", stats_json={},
        )
        repo.create_run(run_id=run_id, book_id=book_id, status="done", phase="done")

        extraction_id = f"sr_ext_{seed}"
        if forbidden_findings:
            repo.create_extraction(
                extraction_id=extraction_id, run_id=run_id, book_id=book_id,
                layer="language", sub_dimension="language.vocabulary",
                status="done", raw_payload_json={}, purpose="extract",
            )
        finding_ids: list[str] = []
        for i, stmt in enumerate(forbidden_findings or []):
            fid = f"sr_find_{seed}_{i}"
            repo.create_finding(
                finding_id=fid, book_id=book_id, run_id=run_id,
                extraction_id=extraction_id, sub_dimension="language.vocabulary",
                finding_kind="forbidden_pattern", statement=stmt,
                confidence="high", status="approved",
            )
            finding_ids.append(fid)

        repo.create_profile(
            profile_id=profile_id, book_id=book_id, run_id=run_id, title="t",
            status=profile_status,
            profile_json=profile_json or {},
            coverage_json={},
            source_finding_ids_json=finding_ids,
        )
        repo.create_binding(
            binding_id=binding_id, profile_id=profile_id,
            scope=scope, scope_ref_id=project_id if scope == "project" else None,
            task_type=task_type, strategy=strategy,
            config_json=config_json or {}, status="active",
        )
        for i, extra in enumerate(extra_bindings or []):
            repo.create_binding(
                binding_id=f"sr_bind_{seed}_extra_{i}",
                profile_id=profile_id,
                scope=extra.get("scope", "global"),
                scope_ref_id=extra.get("scope_ref_id"),
                task_type=extra.get("task_type", task_type),
                strategy=extra.get("strategy", "A"),
                config_json=extra.get("config_json") or {},
                status=extra.get("status", "active"),
            )
        session.commit()
    return project_id


def test_strategy_a_renders_all_three_blocks():
    project_id = _seed(
        seed="sa",
        profile_json={
            "narrative_summary": "白话短句,克制留白。",
            "style_features": ["短句频繁", "动词驱动"],
            "narrative_patterns": ["回环结构"],
            "banned_replication_rules": ["禁堆砌华丽形容词"],
            "metrics_baseline": {
                "avg_sentence_length": {"mean": 18.0, "std": 4.0},
            },
        },
        forbidden_findings=["禁使用美轮美奂等套话"],
        strategy="A",
    )
    with SessionLocal() as session:
        fragments = InjectionService(session).fragments_for(project_id, "scene_generation")
    assert fragments.strategy == InjectionStrategy.A
    assert "正向风格特征" in fragments.positive_block
    assert "短句频繁" in fragments.positive_block
    assert "回环结构" in fragments.positive_block
    assert "禁堆砌华丽形容词" in fragments.forbidden_block
    assert "禁使用美轮美奂等套话" in fragments.forbidden_block
    assert "avg_sentence_length" in fragments.metric_anchor_block
    prefix = fragments.to_system_prompt_prefix()
    assert prefix.startswith("[STYLE_REFERENCE]\n")
    assert prefix.endswith("[/STYLE_REFERENCE]\n\n")


def test_strategy_b_truncates_by_budget():
    long_features = ["特点描述" * 200]  # 单条 800 字
    project_id = _seed(
        seed="sb",
        profile_json={
            "narrative_summary": "summary",
            "style_features": long_features,
            "banned_replication_rules": ["rule" * 200],
            "metrics_baseline": {"avg_sentence_length": {"mean": 18.0, "std": 4.0}},
        },
        strategy="B",
    )
    with SessionLocal() as session:
        fragments = InjectionService(session).fragments_for(project_id, "scene_generation")
    assert fragments.strategy == InjectionStrategy.B
    # 默认 800 token,positive=0.6=480 字以内
    assert len(fragments.positive_block) <= 480 + 5
    assert len(fragments.forbidden_block) <= 240 + 5
    assert len(fragments.metric_anchor_block) <= 80 + 5


def test_strategy_c_drops_metric_and_summarizes_forbidden():
    project_id = _seed(
        seed="sc",
        profile_json={
            "narrative_summary": "summary",
            "style_features": ["要点 1"],
            "banned_replication_rules": ["规则" * 200],  # 800 字
            "metrics_baseline": {"avg_sentence_length": {"mean": 18.0, "std": 4.0}},
        },
        strategy="C",
    )
    with SessionLocal() as session:
        fragments = InjectionService(session).fragments_for(project_id, "scene_generation")
    assert fragments.strategy == InjectionStrategy.C
    assert fragments.positive_block  # 全文保留
    assert len(fragments.forbidden_block) <= 200 + 2  # 摘要 200 字
    assert fragments.metric_anchor_block == ""


def test_strategy_mixed_respects_config_switches():
    project_id = _seed(
        seed="sm",
        profile_json={
            "narrative_summary": "summary",
            "style_features": ["要点"],
            "banned_replication_rules": ["规则"],
            "metrics_baseline": {"avg_sentence_length": {"mean": 18.0, "std": 4.0}},
        },
        strategy="mixed",
        config_json={
            "include_positive": True,
            "include_forbidden": False,
            "include_metric": True,
        },
    )
    with SessionLocal() as session:
        fragments = InjectionService(session).fragments_for(project_id, "scene_generation")
    assert fragments.strategy == InjectionStrategy.MIXED
    assert fragments.positive_block
    assert fragments.forbidden_block == ""
    assert fragments.metric_anchor_block


def test_empty_when_no_binding():
    with SessionLocal() as session:
        fragments = InjectionService(session).fragments_for("no_such_project", "scene_generation")
    assert fragments.positive_block == ""
    assert fragments.forbidden_block == ""
    assert fragments.metric_anchor_block == ""
    assert fragments.to_system_prompt_prefix() == ""


def test_empty_when_profile_not_active():
    project_id = _seed(
        seed="inactive",
        profile_json={"narrative_summary": "x", "style_features": ["y"]},
        strategy="A",
        profile_status="draft",
    )
    with SessionLocal() as session:
        fragments = InjectionService(session).fragments_for(project_id, "scene_generation")
    assert fragments.to_system_prompt_prefix() == ""


def test_profile_missing_fields_yields_empty_blocks():
    project_id = _seed(
        seed="empty",
        profile_json={},  # 全空
        strategy="A",
    )
    with SessionLocal() as session:
        fragments = InjectionService(session).fragments_for(project_id, "scene_generation")
    assert fragments.positive_block == ""
    assert fragments.forbidden_block == ""
    assert fragments.metric_anchor_block == ""
    assert fragments.to_system_prompt_prefix() == ""


def test_project_binding_wins_over_global():
    """同一 task_type 同时有 project 与 global binding 时,project 优先。"""
    project_id = _seed(
        seed="prio",
        profile_json={"narrative_summary": "n", "style_features": ["project 专属要点"]},
        strategy="A",
        scope="project",
        extra_bindings=[
            {
                "scope": "global",
                "scope_ref_id": None,
                "task_type": "scene_generation",
                "strategy": "C",
            }
        ],
    )
    with SessionLocal() as session:
        fragments = InjectionService(session).fragments_for(project_id, "scene_generation")
    assert fragments.strategy == InjectionStrategy.A
    assert "project 专属要点" in fragments.positive_block


def test_mixed_intensity_scales_block_lengths():
    """PR-9 §"intensity 语义" — intensity 缩放 ratio:0=0.3x / 50=0.9x / 100=1.5x。"""
    long_features = ["要点" * 600]  # 1200 字,确保 low/mid/hi 都被截断
    common = {
        "profile_json": {
            "narrative_summary": "summary",
            "style_features": long_features,
            "banned_replication_rules": ["规则" * 100],
            "metrics_baseline": {"m1": {"mean": 1.0, "std": 0.1}},
        },
        "strategy": "mixed",
    }
    proj_low = _seed(
        seed="low",
        config_json={"intensity": 0, "include_metric": True},
        project_id="proj_intensity_low",
        **common,
    )
    proj_mid = _seed(
        seed="mid",
        config_json={"intensity": 50, "include_metric": True},
        project_id="proj_intensity_mid",
        **common,
    )
    proj_hi = _seed(
        seed="hi",
        config_json={"intensity": 100, "include_metric": True},
        project_id="proj_intensity_hi",
        **common,
    )
    with SessionLocal() as session:
        svc = InjectionService(session)
        low = svc.fragments_for(proj_low, "scene_generation")
        mid = svc.fragments_for(proj_mid, "scene_generation")
        hi = svc.fragments_for(proj_hi, "scene_generation")
    # positive_block 长度应单调递增:low < mid < hi
    assert len(low.positive_block) < len(mid.positive_block) < len(hi.positive_block)
    # forbidden_block 同理(若有内容)
    assert len(low.forbidden_block) < len(mid.forbidden_block) <= len(hi.forbidden_block)
    # 高强度上限不会超过 budget * 1.5 余量
    assert len(hi.positive_block) <= 800 * 0.6 * 1.5 + 5


def test_mixed_sub_dimensions_filters_forbidden_findings():
    """PR-9 §"sub_dim 过滤" — MIXED 时 config["sub_dimensions"] 只取匹配的 forbidden_pattern。"""
    project_id = _seed(
        seed="subdim_miss",
        profile_json={"narrative_summary": "n", "style_features": ["短"]},
        forbidden_findings=["禁堆叠形容词"],  # sub_dimension=language.vocabulary
        strategy="mixed",
        config_json={
            # 只选 narrative 层 — language 层的 finding 应被过滤掉
            "sub_dimensions": ["narrative.pacing", "narrative.perspective"],
        },
        project_id="proj_subdim_miss",
    )
    with SessionLocal() as session:
        fragments = InjectionService(session).fragments_for(project_id, "scene_generation")
    # banned_replication_rules 无,findings 因 sub_dim 不匹配被过滤 → forbidden_block 为空
    assert fragments.forbidden_block == ""

    # 对比:sub_dimensions 含 language.vocabulary 时应保留
    project_id_2 = _seed(
        seed="subdim_hit",
        profile_json={"narrative_summary": "n", "style_features": ["短"]},
        forbidden_findings=["禁堆叠形容词"],
        strategy="mixed",
        config_json={"sub_dimensions": ["language.vocabulary"]},
        project_id="proj_subdim_hit",
    )
    with SessionLocal() as session:
        fragments2 = InjectionService(session).fragments_for(project_id_2, "scene_generation")
    assert "禁堆叠形容词" in fragments2.forbidden_block


def test_to_system_prompt_prefix_ordering():
    """positive → forbidden → metric_anchor;空 block 跳过。"""
    project_id = _seed(
        seed="order",
        profile_json={
            "narrative_summary": "concept_a",
            "banned_replication_rules": ["concept_b"],
            "metrics_baseline": {"m1": {"mean": 1.0, "std": 0.1}},
        },
        strategy="A",
    )
    with SessionLocal() as session:
        prefix = InjectionService(session).fragments_for(project_id, "scene_generation").to_system_prompt_prefix()
    pos_idx = prefix.index("正向风格特征")
    forbid_idx = prefix.index("禁忌模式")
    metric_idx = prefix.index("量化锚点")
    assert pos_idx < forbid_idx < metric_idx


# ---------------------------------------------------------------------------
# PR-14 — character scope binding(优先级单选 character > project > global)
# ---------------------------------------------------------------------------


def _seed_scoped_bindings(
    *,
    seed: str,
    project_id: str,
    character_id: str,
    char_feature: str = "角色专属特征",
    project_feature: str = "项目通用特征",
    char_status: str = "active",
    include_character: bool = True,
) -> None:
    """落 1 book/run + 2 profile(character / project)+ 对应 2 binding。

    两 profile 的 style_features 不同,便于断言注入命中哪个。
    """
    book_id = f"sr_book_{seed}"
    run_id = f"sr_run_{seed}"
    with SessionLocal() as session:
        repo = StyleReferenceRepository(session)
        repo.create_book(
            book_id=book_id, title="t", source_kind="upload", cloud_policy="local_only",
            text_checksum=f"chk_{seed}", total_chars=10, status="ready", stats_json={},
        )
        repo.create_run(run_id=run_id, book_id=book_id, status="done", phase="done")
        # project profile + binding
        repo.create_profile(
            profile_id=f"sr_profile_{seed}_proj", book_id=book_id, run_id=run_id, title="proj",
            status="active",
            profile_json={"narrative_summary": "n", "style_features": [project_feature]},
            coverage_json={}, source_finding_ids_json=[],
        )
        repo.create_binding(
            binding_id=f"sr_bind_{seed}_proj", profile_id=f"sr_profile_{seed}_proj",
            scope="project", scope_ref_id=project_id,
            task_type="scene_generation", strategy="A", config_json={}, status="active",
        )
        if include_character:
            repo.create_profile(
                profile_id=f"sr_profile_{seed}_char", book_id=book_id, run_id=run_id, title="char",
                status="active",
                profile_json={"narrative_summary": "n", "style_features": [char_feature]},
                coverage_json={}, source_finding_ids_json=[],
            )
            repo.create_binding(
                binding_id=f"sr_bind_{seed}_char", profile_id=f"sr_profile_{seed}_char",
                scope="character", scope_ref_id=character_id,
                task_type="scene_generation", strategy="A", config_json={}, status=char_status,
            )
        session.commit()


def test_character_overlay_merges_with_project_base():
    """PR-16 — character(overlay)叠加 project(base):两层 positive 都注入。"""
    _seed_scoped_bindings(
        seed="charwin", project_id="proj_cw", character_id="char_cw",
        char_feature="角色专属特征CW", project_feature="项目通用特征CW",
    )
    with SessionLocal() as session:
        fragments = InjectionService(session).fragments_for(
            "proj_cw", "scene_generation", character_ids=["char_cw"],
        )
    # 两层叠加:overlay(character)+ base(project)均在
    assert "角色专属特征CW" in fragments.positive_block
    assert "项目通用特征CW" in fragments.positive_block


def test_character_id_mismatch_falls_back_to_project():
    _seed_scoped_bindings(
        seed="charmiss", project_id="proj_cm", character_id="char_cm",
        char_feature="角色专属特征CM", project_feature="项目通用特征CM",
    )
    with SessionLocal() as session:
        # 传一个不匹配任何 character binding 的 character_id
        fragments = InjectionService(session).fragments_for(
            "proj_cm", "scene_generation", character_ids=["char_other"],
        )
    assert "项目通用特征CM" in fragments.positive_block
    assert "角色专属特征CM" not in fragments.positive_block


def test_character_id_none_skips_character_binding():
    _seed_scoped_bindings(
        seed="charnone", project_id="proj_cn", character_id="char_cn",
        char_feature="角色专属特征CN", project_feature="项目通用特征CN",
    )
    with SessionLocal() as session:
        # character_id=None(默认)→ 跳过 character rank,回落 project
        fragments = InjectionService(session).fragments_for("proj_cn", "scene_generation")
    assert "项目通用特征CN" in fragments.positive_block
    assert "角色专属特征CN" not in fragments.positive_block


def test_disabled_character_binding_falls_back_to_project():
    _seed_scoped_bindings(
        seed="chardis", project_id="proj_cd", character_id="char_cd",
        char_feature="角色专属特征CD", project_feature="项目通用特征CD",
        char_status="disabled",
    )
    with SessionLocal() as session:
        fragments = InjectionService(session).fragments_for(
            "proj_cd", "scene_generation", character_ids=["char_cd"],
        )
    # character binding disabled → 不命中,回落 project
    assert "项目通用特征CD" in fragments.positive_block
    assert "角色专属特征CD" not in fragments.positive_block


# ---------------------------------------------------------------------------
# PR-15 — scene scope binding(优先级单选 scene > character > project > global)
# ---------------------------------------------------------------------------


def _seed_four_level_bindings(
    *,
    seed: str,
    project_id: str,
    character_id: str,
    scene_id: str,
    include_scene: bool = True,
    scene_feature: str = "场景专属特征",
    char_feature: str = "角色专属特征",
    project_feature: str = "项目通用特征",
) -> None:
    """落 1 book/run + 3 profile(scene/character/project)+ 对应 binding。

    profile style_features 各异,便于断言命中哪个。
    """
    book_id = f"sr_book_{seed}"
    run_id = f"sr_run_{seed}"
    with SessionLocal() as session:
        repo = StyleReferenceRepository(session)
        repo.create_book(
            book_id=book_id, title="t", source_kind="upload", cloud_policy="local_only",
            text_checksum=f"chk_{seed}", total_chars=10, status="ready", stats_json={},
        )
        repo.create_run(run_id=run_id, book_id=book_id, status="done", phase="done")

        def _mk(suffix, feature, scope, ref):
            repo.create_profile(
                profile_id=f"sr_profile_{seed}_{suffix}", book_id=book_id, run_id=run_id,
                title=suffix, status="active",
                profile_json={"narrative_summary": "n", "style_features": [feature]},
                coverage_json={}, source_finding_ids_json=[],
            )
            repo.create_binding(
                binding_id=f"sr_bind_{seed}_{suffix}", profile_id=f"sr_profile_{seed}_{suffix}",
                scope=scope, scope_ref_id=ref,
                task_type="scene_generation", strategy="A", config_json={}, status="active",
            )

        _mk("proj", project_feature, "project", project_id)
        _mk("char", char_feature, "character", character_id)
        if include_scene:
            _mk("scene", scene_feature, "scene", scene_id)
        session.commit()


def test_three_layer_full_merge():
    """PR-19 — 三层全叠:scene + character + project 都注入(PR-16 曾跳过 character)。"""
    _seed_four_level_bindings(
        seed="scenewin", project_id="proj_sw", character_id="char_sw", scene_id="scene_sw",
        scene_feature="场景专属SW", char_feature="角色专属SW", project_feature="项目通用SW",
    )
    with SessionLocal() as session:
        fragments = InjectionService(session).fragments_for(
            "proj_sw", "scene_generation", character_ids=["char_sw"], scene_id="scene_sw",
        )
    pos = fragments.positive_block
    # 三层全叠:base(project)+ character + scene 都在
    assert "项目通用SW" in pos
    assert "角色专属SW" in pos
    assert "场景专属SW" in pos


def test_three_layer_order_general_to_specific():
    """PR-19 — 拼接顺序由泛到具体:project → character → scene。"""
    _seed_four_level_bindings(
        seed="order3", project_id="proj_o3", character_id="char_o3", scene_id="scene_o3",
        scene_feature="场景O3", char_feature="角色O3", project_feature="项目O3",
    )
    with SessionLocal() as session:
        pos = InjectionService(session).fragments_for(
            "proj_o3", "scene_generation", character_ids=["char_o3"], scene_id="scene_o3",
        ).positive_block
    assert pos.index("项目O3") < pos.index("角色O3") < pos.index("场景O3")


def test_three_layer_token_weighted_scene_largest():
    """PR-19 — token 加权:scene 段预算最大(权重 3/6),project 基底最小(1/6)。"""
    # 手工 seed 长 style_features(各层 ~900 字),确保都被 cap 截断,验证加权差异
    with SessionLocal() as session:
        repo = StyleReferenceRepository(session)
        repo.create_book(
            book_id="sr_book_w3b", title="t", source_kind="upload", cloud_policy="local_only",
            text_checksum="chk_w3b", total_chars=10, status="ready", stats_json={},
        )
        repo.create_run(run_id="sr_run_w3b", book_id="sr_book_w3b", status="done", phase="done")
        for suffix, scope, ref, feat in [
            ("proj", "project", "proj_w3b", "项" * 900),
            ("char", "character", "char_w3b", "角" * 900),
            ("scene", "scene", "scene_w3b", "景" * 900),
        ]:
            repo.create_profile(
                profile_id=f"sr_profile_w3b_{suffix}", book_id="sr_book_w3b", run_id="sr_run_w3b",
                title=suffix, status="active",
                profile_json={"narrative_summary": "n", "style_features": [feat]},
                coverage_json={}, source_finding_ids_json=[],
            )
            repo.create_binding(
                binding_id=f"sr_bind_w3b_{suffix}", profile_id=f"sr_profile_w3b_{suffix}",
                scope=scope, scope_ref_id=ref,
                task_type="scene_generation", strategy="A", config_json={}, status="active",
            )
        session.commit()
    with SessionLocal() as session:
        fragments = InjectionService(session).fragments_for(
            "proj_w3b", "scene_generation", character_ids=["char_w3b"], scene_id="scene_w3b",
        )
    pos = fragments.positive_block
    # scene 段(景)应比 project 段(项)长(加权 3:1)
    assert pos.count("景") > pos.count("项")


def test_three_layer_metric_prefers_most_specific():
    """PR-19 — metric_anchor 取最具体层(scene)优先。"""
    with SessionLocal() as session:
        repo = StyleReferenceRepository(session)
        repo.create_book(
            book_id="sr_book_m3", title="t", source_kind="upload", cloud_policy="local_only",
            text_checksum="chk_m3", total_chars=10, status="ready", stats_json={},
        )
        repo.create_run(run_id="sr_run_m3", book_id="sr_book_m3", status="done", phase="done")
        for suffix, scope, ref, metric_name in [
            ("proj", "project", "proj_m3", "proj_metric"),
            ("scene", "scene", "scene_m3", "scene_metric"),
        ]:
            repo.create_profile(
                profile_id=f"sr_profile_m3_{suffix}", book_id="sr_book_m3", run_id="sr_run_m3",
                title=suffix, status="active",
                profile_json={
                    "narrative_summary": "n",
                    "metrics_baseline": {metric_name: {"mean": 1.0, "std": 0.1}},
                },
                coverage_json={}, source_finding_ids_json=[],
            )
            repo.create_binding(
                binding_id=f"sr_bind_m3_{suffix}", profile_id=f"sr_profile_m3_{suffix}",
                scope=scope, scope_ref_id=ref,
                task_type="scene_generation", strategy="A", config_json={}, status="active",
            )
        session.commit()
    with SessionLocal() as session:
        fragments = InjectionService(session).fragments_for(
            "proj_m3", "scene_generation", scene_id="scene_m3",
        )
    assert "scene_metric" in fragments.metric_anchor_block
    assert "proj_metric" not in fragments.metric_anchor_block


def test_scene_id_mismatch_falls_back_to_character():
    _seed_four_level_bindings(
        seed="scenemiss", project_id="proj_sm", character_id="char_sm", scene_id="scene_sm",
        scene_feature="场景专属SM", char_feature="角色专属SM", project_feature="项目通用SM",
    )
    with SessionLocal() as session:
        # scene_id 不匹配任何 scene binding → 回落 character
        fragments = InjectionService(session).fragments_for(
            "proj_sm", "scene_generation", character_ids=["char_sm"], scene_id="scene_other",
        )
    assert "角色专属SM" in fragments.positive_block
    assert "场景专属SM" not in fragments.positive_block


def test_scene_id_none_skips_scene_binding():
    _seed_four_level_bindings(
        seed="scenenone", project_id="proj_sn", character_id="char_sn", scene_id="scene_sn",
        scene_feature="场景专属SN", char_feature="角色专属SN", project_feature="项目通用SN",
    )
    with SessionLocal() as session:
        # scene_id=None → 跳过 scene rank,overlay=character;叠加 project base
        fragments = InjectionService(session).fragments_for(
            "proj_sn", "scene_generation", character_ids=["char_sn"],
        )
    assert "角色专属SN" in fragments.positive_block
    assert "场景专属SN" not in fragments.positive_block


# ---------------------------------------------------------------------------
# PR-16 — 两层叠加合并(forbidden 去重 / token 各半 / 单层等价 / metric 优先)
# ---------------------------------------------------------------------------


def _seed_overlay_pair(
    *,
    seed: str,
    project_id: str,
    character_id: str,
    base_json: dict,
    overlay_json: dict,
    base_strategy: str = "A",
    overlay_strategy: str = "A",
    include_base: bool = True,
    include_overlay: bool = True,
) -> None:
    """落 project(base)+ character(overlay)两 profile/binding,profile_json 自定义。"""
    book_id = f"sr_book_{seed}"
    run_id = f"sr_run_{seed}"
    with SessionLocal() as session:
        repo = StyleReferenceRepository(session)
        repo.create_book(
            book_id=book_id, title="t", source_kind="upload", cloud_policy="local_only",
            text_checksum=f"chk_{seed}", total_chars=10, status="ready", stats_json={},
        )
        repo.create_run(run_id=run_id, book_id=book_id, status="done", phase="done")
        if include_base:
            repo.create_profile(
                profile_id=f"sr_profile_{seed}_base", book_id=book_id, run_id=run_id,
                title="base", status="active", profile_json=base_json,
                coverage_json={}, source_finding_ids_json=[],
            )
            repo.create_binding(
                binding_id=f"sr_bind_{seed}_base", profile_id=f"sr_profile_{seed}_base",
                scope="project", scope_ref_id=project_id,
                task_type="scene_generation", strategy=base_strategy, config_json={}, status="active",
            )
        if include_overlay:
            repo.create_profile(
                profile_id=f"sr_profile_{seed}_ov", book_id=book_id, run_id=run_id,
                title="ov", status="active", profile_json=overlay_json,
                coverage_json={}, source_finding_ids_json=[],
            )
            repo.create_binding(
                binding_id=f"sr_bind_{seed}_ov", profile_id=f"sr_profile_{seed}_ov",
                scope="character", scope_ref_id=character_id,
                task_type="scene_generation", strategy=overlay_strategy, config_json={}, status="active",
            )
        session.commit()


def test_overlay_forbidden_dedup():
    """两层相同禁忌规则去重,只保留一条。"""
    _seed_overlay_pair(
        seed="dedup", project_id="proj_dd", character_id="char_dd",
        base_json={"narrative_summary": "b", "banned_replication_rules": ["禁堆砌华丽形容词", "禁项目独有"]},
        overlay_json={"narrative_summary": "o", "banned_replication_rules": ["禁堆砌华丽形容词", "禁角色独有"]},
    )
    with SessionLocal() as session:
        fragments = InjectionService(session).fragments_for(
            "proj_dd", "scene_generation", character_ids=["char_dd"],
        )
    forbidden = fragments.forbidden_block
    # 共同的"禁堆砌华丽形容词"只出现一次
    assert forbidden.count("禁堆砌华丽形容词") == 1
    # 各自独有的都保留
    assert "禁项目独有" in forbidden
    assert "禁角色独有" in forbidden
    # 单个 [禁忌模式] 标题
    assert forbidden.count("[禁忌模式]") == 1


def test_overlay_token_each_half_capped():
    """base 与 overlay positive 各被截到 half*0.6 内。"""
    long_base = ["基底" * 500]      # 1000 字
    long_overlay = ["增量" * 500]   # 1000 字
    _seed_overlay_pair(
        seed="cap", project_id="proj_cap", character_id="char_cap",
        base_json={"narrative_summary": "b", "style_features": long_base},
        overlay_json={"narrative_summary": "o", "style_features": long_overlay},
    )
    with SessionLocal() as session:
        fragments = InjectionService(session).fragments_for(
            "proj_cap", "scene_generation", character_ids=["char_cap"],
        )
    # half=400,positive ratio 0.6 → 各 ≤ 240;合并后两段各受限
    # 总 positive 不应远超 2*240(+标题/换行余量)
    assert len(fragments.positive_block) <= 240 * 2 + 60


def test_overlay_only_base_is_single_layer():
    """仅 project base(无 overlay)→ 单层路径,strategy A 全文不截断。"""
    long_base = ["基底全文" * 500]  # 2000 字
    _seed_overlay_pair(
        seed="baseonly", project_id="proj_bo", character_id="char_bo",
        base_json={"narrative_summary": "b", "style_features": long_base},
        overlay_json={},
        include_overlay=False,
    )
    with SessionLocal() as session:
        # 无 character binding → overlay=None → 单层 base
        fragments = InjectionService(session).fragments_for(
            "proj_bo", "scene_generation", character_ids=["char_bo"],
        )
    # 单层 strategy A 全文不截断(远超 half cap)
    assert len(fragments.positive_block) > 1000


def test_overlay_only_character_is_single_layer():
    """仅 character overlay(无 project base)→ 单层路径。"""
    _seed_overlay_pair(
        seed="ovonly", project_id="proj_oo", character_id="char_oo",
        base_json={},
        overlay_json={"narrative_summary": "o", "style_features": ["角色独有OO"]},
        include_base=False,
    )
    with SessionLocal() as session:
        fragments = InjectionService(session).fragments_for(
            "proj_oo", "scene_generation", character_ids=["char_oo"],
        )
    assert "角色独有OO" in fragments.positive_block


def test_overlay_metric_prefers_overlay():
    """metric_anchor 取 overlay(更具体);overlay 有 metric 时不用 base 的。"""
    _seed_overlay_pair(
        seed="metric", project_id="proj_mt", character_id="char_mt",
        base_json={
            "narrative_summary": "b",
            "metrics_baseline": {"base_metric": {"mean": 10.0, "std": 1.0}},
        },
        overlay_json={
            "narrative_summary": "o",
            "metrics_baseline": {"overlay_metric": {"mean": 20.0, "std": 2.0}},
        },
    )
    with SessionLocal() as session:
        fragments = InjectionService(session).fragments_for(
            "proj_mt", "scene_generation", character_ids=["char_mt"],
        )
    assert "overlay_metric" in fragments.metric_anchor_block
    assert "base_metric" not in fragments.metric_anchor_block


# ---------------------------------------------------------------------------
# PR-18 — onstage 多角色 character 匹配(pov ∪ onstage,pov 优先决平)
# ---------------------------------------------------------------------------


def _seed_multi_character(
    *,
    seed: str,
    project_id: str,
    characters: list[dict],
    project_feature: str = "项目通用M",
) -> None:
    """落 1 book/run + 1 project binding + 多个 character binding。

    characters: [{character_id, feature, created_at?}]。
    """
    book_id = f"sr_book_{seed}"
    run_id = f"sr_run_{seed}"
    with SessionLocal() as session:
        repo = StyleReferenceRepository(session)
        repo.create_book(
            book_id=book_id, title="t", source_kind="upload", cloud_policy="local_only",
            text_checksum=f"chk_{seed}", total_chars=10, status="ready", stats_json={},
        )
        repo.create_run(run_id=run_id, book_id=book_id, status="done", phase="done")
        repo.create_profile(
            profile_id=f"sr_profile_{seed}_proj", book_id=book_id, run_id=run_id, title="proj",
            status="active",
            profile_json={"narrative_summary": "n", "style_features": [project_feature]},
            coverage_json={}, source_finding_ids_json=[],
        )
        repo.create_binding(
            binding_id=f"sr_bind_{seed}_proj", profile_id=f"sr_profile_{seed}_proj",
            scope="project", scope_ref_id=project_id,
            task_type="scene_generation", strategy="A", config_json={}, status="active",
        )
        for i, ch in enumerate(characters):
            repo.create_profile(
                profile_id=f"sr_profile_{seed}_c{i}", book_id=book_id, run_id=run_id, title=f"c{i}",
                status="active",
                profile_json={"narrative_summary": "n", "style_features": [ch["feature"]]},
                coverage_json={}, source_finding_ids_json=[],
            )
            kwargs = dict(
                binding_id=f"sr_bind_{seed}_c{i}", profile_id=f"sr_profile_{seed}_c{i}",
                scope="character", scope_ref_id=ch["character_id"],
                task_type="scene_generation", strategy="A", config_json={}, status="active",
            )
            if ch.get("created_at"):
                kwargs["created_at"] = ch["created_at"]
            repo.create_binding(**kwargs)
        session.commit()


def test_ordered_character_ids_helper():
    # pov 排首 + onstage 去重(pov 可能不在 onstage)
    assert ordered_character_ids("A", ["B", "C"]) == ["A", "B", "C"]
    assert ordered_character_ids("A", ["A", "B"]) == ["A", "B"]      # 去重
    assert ordered_character_ids(None, ["B", "C"]) == ["B", "C"]     # pov 空
    assert ordered_character_ids("A", []) == ["A"]                   # onstage 空
    assert ordered_character_ids("A", ["B"]) == ["A", "B"]           # pov 不在 onstage


def test_onstage_nonpov_character_matches():
    """pov 无 binding,但 onstage 配角有 binding → 命中配角。"""
    _seed_multi_character(
        seed="onstage1", project_id="proj_os1",
        characters=[{"character_id": "charB", "feature": "配角专属OS1"}],
    )
    # pov=charNoBind(无 binding),onstage=[charB]
    cids = ordered_character_ids("charNoBind", ["charB"])
    with SessionLocal() as session:
        fragments = InjectionService(session).fragments_for(
            "proj_os1", "scene_generation", character_ids=cids,
        )
    assert "配角专属OS1" in fragments.positive_block


def test_pov_character_wins_over_onstage():
    """pov 与 onstage 配角都有 binding → pov 优先(char_order 0)。"""
    _seed_multi_character(
        seed="onstage2", project_id="proj_os2",
        characters=[
            {"character_id": "charA", "feature": "主视角OS2"},
            {"character_id": "charB", "feature": "配角OS2"},
        ],
    )
    cids = ordered_character_ids("charA", ["charB"])  # [charA, charB]
    with SessionLocal() as session:
        fragments = InjectionService(session).fragments_for(
            "proj_os2", "scene_generation", character_ids=cids,
        )
    assert "主视角OS2" in fragments.positive_block
    assert "配角OS2" not in fragments.positive_block


def test_pov_not_in_onstage_union_matches():
    """pov 不在 onstage 列表里,但并集仍命中 pov binding。"""
    _seed_multi_character(
        seed="onstage3", project_id="proj_os3",
        characters=[{"character_id": "charA", "feature": "主视角OS3"}],
    )
    # pov=charA 不在 onstage=[charB];并集 [charA, charB]
    cids = ordered_character_ids("charA", ["charB"])
    assert cids == ["charA", "charB"]
    with SessionLocal() as session:
        fragments = InjectionService(session).fragments_for(
            "proj_os3", "scene_generation", character_ids=cids,
        )
    assert "主视角OS3" in fragments.positive_block


def test_pov_priority_overrides_created_at():
    """pov binding 创建较早,配角较新;char_order(pov 优先)盖过 created_at。"""
    _seed_multi_character(
        seed="onstage4", project_id="proj_os4",
        characters=[
            {"character_id": "charA", "feature": "主视角OS4", "created_at": "2026-01-01T00:00:00Z"},
            {"character_id": "charB", "feature": "配角OS4", "created_at": "2026-05-01T00:00:00Z"},
        ],
    )
    cids = ordered_character_ids("charA", ["charB"])  # pov=charA 排首
    with SessionLocal() as session:
        fragments = InjectionService(session).fragments_for(
            "proj_os4", "scene_generation", character_ids=cids,
        )
    # charA(pov,char_order 0)优先,即便 charB created_at 更新
    assert "主视角OS4" in fragments.positive_block
    assert "配角OS4" not in fragments.positive_block
