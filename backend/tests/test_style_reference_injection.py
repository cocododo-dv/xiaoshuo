"""PR-8 §5.1 — InjectionService.fragments_for 4 种 strategy + 边界用例。"""

from __future__ import annotations

import pytest

from novel_system.db.session import SessionLocal
from novel_system.services.style_reference.config_loader import clear_config_cache
from novel_system.services.style_reference.injection import InjectionService
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
