from __future__ import annotations

import copy
from types import SimpleNamespace

import pytest

from novel_system.db.models import (
    ChapterGoal,
    SceneCard,
    StoryProject,
    StyleReferenceBook,
    StyleReferenceInjectionBinding,
    StyleReferenceProfile,
    StyleReferenceRun,
)
from novel_system.services.style_reference.candidate_rerank import (
    CandidateRerankPolicy,
    StyleCandidateReranker,
    assess_candidate_text,
    build_style_target,
    rerank_candidate_pairs,
)
from novel_system.services.style_reference.repository import StyleReferenceRepository
from novel_system.services.style_reference.runtime_contract import (
    build_style_runtime_contract,
)
from novel_system.services.style_reference.validation.quantitative import (
    compute_generated_metrics,
)


REFERENCE_TEXT = (
    "雨脚斜斜地落在青石上，檐铃隔一阵才轻轻响一下。"
    "她没有催问，只把灯芯拨低，让桌沿那道旧划痕重新沉进阴影里。"
    "巷口传来车轮碾水的细声，近了，又慢慢远去。"
) * 12

FAR_TEXT = (
    "快跑！快跑！为什么还不走？他喊道：现在就走！"
    "真的，真的，真的，一切都结束了！你听见了吗？"
) * 18

SAFE_TEXT = (
    "晨雾沿着荒坡退去，牧人收紧缰绳，望见远处新垒的石墙。"
    "炊烟还没有升起，几只寒鸦先从枯树上散开。"
) * 14


def _profile(profile_id: str, text: str, *, std: float = 0.0):
    metrics = compute_generated_metrics(text)
    return SimpleNamespace(
        profile_id=profile_id,
        profile_json={
            "metrics_baseline": {
                name: {"mean": value, "std": std, "sample_count": 20}
                for name, value in metrics.items()
            }
        },
    )


def _active_policy(**overrides) -> CandidateRerankPolicy:
    values = {
        "requested_mode": "active",
        "effective_mode": "active",
        "style_weight": 0.25,
        "max_quality_drop": 0.04,
        "min_substantive_chars": 300,
        "min_metric_count": 12,
        "min_confidence": 0.65,
        "plagiarism_guard": True,
        "plagiarism_ngram_size": 8,
        "plagiarism_threshold_chars": 12,
    }
    values.update(overrides)
    return CandidateRerankPolicy(**values)


def test_policy_defaults_to_shadow_and_active_requires_frozen_human_evidence() -> None:
    default = CandidateRerankPolicy.from_mapping({})
    missing = CandidateRerankPolicy.from_mapping({"mode": "active"})
    authorized = CandidateRerankPolicy.from_mapping(
        {
            "mode": "active",
            "activation_evidence": {
                "human_verified": True,
                "policy_evidence_eligible": True,
                "report_id": "human_blind_eval_001",
                "report_sha256": "a" * 64,
            },
        }
    )

    assert default.effective_mode == "shadow"
    assert missing.effective_mode == "shadow"
    assert "active_mode_missing_frozen_human_evidence" in missing.configuration_errors
    assert authorized.effective_mode == "active"
    assert authorized.activation_report_id == "human_blind_eval_001"


@pytest.mark.parametrize(
    "field,value",
    [
        ("style_weight", 0.5),
        ("max_quality_drop", 0.2),
        ("min_substantive_chars", 10),
        ("min_metric_count", 2),
        ("min_confidence", 0.1),
        ("plagiarism_threshold_chars", 30),
        ("plagiarism_guard", False),
    ],
)
def test_permissive_policy_values_fail_closed(field: str, value: float) -> None:
    policy = CandidateRerankPolicy.from_mapping(
        {
            "mode": "active",
            field: value,
            "activation_evidence": {
                "human_verified": True,
                "policy_evidence_eligible": True,
                "report_id": "verified",
                "report_sha256": "b" * 64,
            },
        }
    )
    assert policy.effective_mode == "shadow"
    assert any(error.startswith(field) for error in policy.configuration_errors)


def test_layered_target_uses_generic_to_specific_weights_and_total_variance() -> None:
    first = SimpleNamespace(
        profile_id="base",
        profile_json={
            "metrics_baseline": {
                "avg_sentence_length": {"mean": 10.0, "std": 1.0},
            }
        },
    )
    second = SimpleNamespace(
        profile_id="specific",
        profile_json={
            "metrics_baseline": {
                "avg_sentence_length": {"mean": 20.0, "std": 2.0},
            }
        },
    )

    target = build_style_target([first, second], floors={"avg_sentence_length": 0.1})

    assert target is not None
    metric = target.metrics["avg_sentence_length"]
    assert metric.mean == pytest.approx(50.0 / 3.0)
    assert metric.std > 2.0  # includes the between-profile distance
    assert metric.component_count == 2
    assert target.profile_ids == ("base", "specific")


def test_candidate_closer_to_profile_scores_higher_with_group_balancing() -> None:
    target = build_style_target([_profile("profile", REFERENCE_TEXT)])
    policy = _active_policy()

    close = assess_candidate_text("close", REFERENCE_TEXT, 0.8, target, policy)
    far = assess_candidate_text("far", FAR_TEXT, 0.8, target, policy)

    assert close.style_eligible is True
    assert far.style_eligible is True
    assert close.metric_count == 18
    assert close.style_score == pytest.approx(1.0)
    assert close.style_score > far.style_score
    assert set(close.group_scores) == {
        "sentence_shape",
        "punctuation_rhythm",
        "register",
        "figurative_proxy",
        "sensory_proxy",
    }


def test_shadow_mode_records_style_but_preserves_quality_order() -> None:
    target = build_style_target([_profile("profile", REFERENCE_TEXT)])
    policy = CandidateRerankPolicy(
        requested_mode="shadow",
        effective_mode="shadow",
        min_substantive_chars=300,
        min_metric_count=12,
        min_confidence=0.65,
    )
    quality_leader = SimpleNamespace(row_id="quality", content=FAR_TEXT)
    style_leader = SimpleNamespace(row_id="style", content=REFERENCE_TEXT)

    outcome = rerank_candidate_pairs(
        [(quality_leader, 0.81), (style_leader, 0.80)],
        target=target,
        policy=policy,
    )

    assert [item.row_id for item in outcome.ordered_candidates] == ["quality", "style"]
    assert (
        outcome.assessments["style"].style_score
        > outcome.assessments["quality"].style_score
    )
    assert outcome.audit["applied_mode"] == "shadow"
    assert outcome.audit["selected_changed"] is False


def test_shadow_mode_preserves_input_order_for_equal_quality_scores() -> None:
    first = SimpleNamespace(row_id="z_last_lexically", content=SAFE_TEXT)
    second = SimpleNamespace(row_id="a_first_lexically", content=FAR_TEXT)

    outcome = rerank_candidate_pairs(
        [(first, 0.80), (second, 0.80)],
        target=None,
        policy=CandidateRerankPolicy(requested_mode="shadow", effective_mode="shadow"),
    )

    assert [item.row_id for item in outcome.ordered_candidates] == [
        "z_last_lexically",
        "a_first_lexically",
    ]


def test_active_mode_can_choose_better_style_only_inside_quality_guardrail() -> None:
    target = build_style_target([_profile("profile", REFERENCE_TEXT)])
    quality_leader = SimpleNamespace(row_id="quality", content=FAR_TEXT)
    style_leader = SimpleNamespace(row_id="style", content=REFERENCE_TEXT)

    within = rerank_candidate_pairs(
        [(quality_leader, 0.81), (style_leader, 0.80)],
        target=target,
        policy=_active_policy(max_quality_drop=0.04),
    )
    outside = rerank_candidate_pairs(
        [(quality_leader, 0.90), (style_leader, 0.80)],
        target=target,
        policy=_active_policy(max_quality_drop=0.04),
    )

    assert within.ordered_candidates[0].row_id == "style"
    assert within.audit["applied_mode"] == "active"
    assert within.audit["selected_changed"] is True
    assert outside.ordered_candidates[0].row_id == "quality"
    assert outside.audit["applied_mode"] == "shadow"
    assert outside.audit["reason"] == "insufficient_comparable_candidates"


def test_plagiarism_guard_is_independent_of_uncalibrated_style_score() -> None:
    copied = SimpleNamespace(row_id="copied", content=REFERENCE_TEXT)
    safe = SimpleNamespace(row_id="safe", content=SAFE_TEXT)
    policy = CandidateRerankPolicy(requested_mode="shadow", effective_mode="shadow")

    outcome = rerank_candidate_pairs(
        [(copied, 0.90), (safe, 0.70)],
        target=None,
        policy=policy,
        plagiarism_corpus=[REFERENCE_TEXT],
    )

    assert [item.row_id for item in outcome.ordered_candidates] == ["safe", "copied"]
    assert outcome.assessments["copied"].plagiarism_passed is False
    assert outcome.assessments["safe"].plagiarism_passed is True
    assert outcome.assessments["safe"].selection_reason == "plagiarism_guard"
    assert outcome.audit["plagiarism_guard_applied"] is True
    # Audit stores only counts/lengths, never the matched source excerpt.
    assert REFERENCE_TEXT[:40] not in str(outcome.assessments["copied"].to_audit_dict())


def test_all_plagiarized_candidates_preserve_quality_order_for_downstream_qc() -> None:
    first = SimpleNamespace(row_id="first", content=REFERENCE_TEXT)
    second = SimpleNamespace(row_id="second", content=REFERENCE_TEXT + "尾声")

    outcome = rerank_candidate_pairs(
        [(first, 0.90), (second, 0.80)],
        target=None,
        policy=CandidateRerankPolicy(requested_mode="shadow", effective_mode="shadow"),
        plagiarism_corpus=[REFERENCE_TEXT],
    )

    assert [item.row_id for item in outcome.ordered_candidates] == ["first", "second"]
    assert outcome.audit["plagiarism_guard_applied"] is False
    assert all(item.plagiarism_passed is False for item in outcome.assessments.values())


def test_service_requires_live_binding_to_match_frozen_bundle_before_active_rerank(
    session,
) -> None:
    project = StoryProject(
        project_id="rerank_project", title="重排项目", outline_text=""
    )
    chapter = ChapterGoal(
        chapter_id="rerank_chapter",
        project_id=project.project_id,
        chapter_goal="等待一封迟到的信",
    )
    scene = SceneCard(
        scene_id="rerank_scene",
        project_id=project.project_id,
        chapter_id=chapter.chapter_id,
        scene_seq=1,
        pov_character_id="rerank_pov",
        onstage_chars_json=["rerank_pov"],
        scene_goal="等待并读完那封迟到的信",
    )
    book = StyleReferenceBook(
        book_id="rerank_book",
        title="匿名参考",
        source_kind="upload",
        cloud_policy="local_only",
        text_checksum="c" * 64,
        total_chars=len(REFERENCE_TEXT),
        status="ready",
    )
    run = StyleReferenceRun(
        run_id="rerank_run",
        book_id=book.book_id,
        status="completed",
    )
    profile = StyleReferenceProfile(
        profile_id="rerank_profile",
        book_id=book.book_id,
        run_id=run.run_id,
        title="匿名风格",
        status="active",
        profile_json=_profile("unused", REFERENCE_TEXT).profile_json,
    )
    binding = StyleReferenceInjectionBinding(
        binding_id="rerank_binding",
        profile_id=profile.profile_id,
        scope="project",
        scope_ref_id=project.project_id,
        task_type="scene_generation",
        strategy="A",
        status="active",
    )
    session.add_all([project, chapter, scene, book, run, profile, binding])
    session.flush()

    quality_leader = SimpleNamespace(row_id="quality", content=FAR_TEXT)
    style_leader = SimpleNamespace(row_id="style", content=REFERENCE_TEXT)
    bundle = {
        "snapshot": {
            "source_version_refs": {"reference_profile_ids": [profile.profile_id]}
        }
    }
    reranker = StyleCandidateReranker(session, policy=_active_policy())

    matched = reranker.rerank(
        scene,
        bundle,
        [quality_leader, style_leader],
        quality_scores={"quality": 0.81, "style": 0.80},
    )
    binding.status = "disabled"
    session.flush()
    mismatched = reranker.rerank(
        scene,
        bundle,
        [quality_leader, style_leader],
        quality_scores={"quality": 0.81, "style": 0.80},
    )

    assert matched.ordered_candidates[0].row_id == "style"
    assert matched.audit["applied_mode"] == "active"
    assert matched.audit["lineage_match"] is True
    assert mismatched.ordered_candidates[0].row_id == "quality"
    assert mismatched.audit["applied_mode"] == "shadow"
    assert mismatched.audit["reason"] == "live_binding_differs_from_frozen_bundle"
    assert mismatched.audit["lineage_match"] is False


def test_service_scores_from_frozen_contract_and_fails_active_mode_closed_on_edit(
    session,
) -> None:
    project = StoryProject(
        project_id="contract_rerank_project",
        title="冻结重排项目",
        outline_text="",
    )
    chapter = ChapterGoal(
        chapter_id="contract_rerank_chapter",
        project_id=project.project_id,
        chapter_goal="在雨夜等一封信。",
    )
    scene = SceneCard(
        scene_id="contract_rerank_scene",
        project_id=project.project_id,
        chapter_id=chapter.chapter_id,
        scene_seq=1,
        scene_goal="等到并读完来信。",
        onstage_chars_json=[],
    )
    book = StyleReferenceBook(
        book_id="contract_rerank_book",
        title="匿名参考",
        source_kind="upload",
        cloud_policy="local_only",
        text_checksum="d" * 64,
        total_chars=len(REFERENCE_TEXT),
        status="ready",
    )
    run = StyleReferenceRun(
        run_id="contract_rerank_run",
        book_id=book.book_id,
        status="completed",
    )
    profile = StyleReferenceProfile(
        profile_id="contract_rerank_profile",
        book_id=book.book_id,
        run_id=run.run_id,
        title="冻结画像",
        status="active",
        profile_json=_profile("unused", REFERENCE_TEXT).profile_json,
    )
    binding = StyleReferenceInjectionBinding(
        binding_id="contract_rerank_binding",
        profile_id=profile.profile_id,
        scope="project",
        scope_ref_id=project.project_id,
        task_type="scene_generation",
        strategy="A",
        config_json={"intensity": 50},
        status="active",
    )
    session.add_all([project, chapter, scene, book, run, profile, binding])
    session.flush()
    contract = build_style_runtime_contract(
        StyleReferenceRepository(session),
        [binding],
        task_type="scene_generation",
    )
    assert contract is not None
    bundle = {
        "snapshot": {
            "source_version_refs": {
                "style_reference_runtime_contract_version": contract[
                    "contract_version"
                ],
                "style_reference_runtime_contract_status": "frozen",
                "reference_profile_ids": [profile.profile_id],
            },
            "inline_digests": {"_style_reference_runtime_contract": contract},
        }
    }
    candidates = [
        SimpleNamespace(row_id="quality", content=FAR_TEXT),
        SimpleNamespace(row_id="style", content=REFERENCE_TEXT),
    ]
    reranker = StyleCandidateReranker(session, policy=_active_policy())

    matched = reranker.rerank(
        scene,
        bundle,
        candidates,
        quality_scores={"quality": 0.81, "style": 0.80},
    )
    frozen_style_score = matched.assessments["style"].style_score
    binding.config_json = {"intensity": 5}
    profile.profile_json = {
        "metrics_baseline": _profile("unused", FAR_TEXT).profile_json[
            "metrics_baseline"
        ]
    }
    session.flush()
    mismatched = reranker.rerank(
        scene,
        bundle,
        candidates,
        quality_scores={"quality": 0.81, "style": 0.80},
    )
    missing_contract_bundle = copy.deepcopy(bundle)
    missing_contract_bundle["snapshot"]["inline_digests"].pop(
        "_style_reference_runtime_contract"
    )
    missing_contract = reranker.rerank(
        scene,
        missing_contract_bundle,
        candidates,
        quality_scores={"quality": 0.81, "style": 0.80},
    )
    book.text_checksum = "changed-after-runtime-contract"
    session.flush()
    changed_source = reranker.rerank(
        scene,
        bundle,
        candidates,
        quality_scores={"quality": 0.81, "style": 0.80},
    )

    assert matched.audit["runtime_contract_hash"] == contract["contract_hash"]
    assert matched.audit["lineage_match"] is True
    assert matched.audit["applied_mode"] == "active"
    assert mismatched.audit["lineage_match"] is False
    assert mismatched.audit["applied_mode"] == "shadow"
    assert mismatched.audit["reason"] == "live_contract_differs_from_frozen_bundle"
    assert mismatched.assessments["style"].style_score == pytest.approx(
        frozen_style_score
    )
    assert missing_contract.audit["applied_mode"] == "shadow"
    assert missing_contract.audit["reason"] == "frozen_runtime_contract_unavailable"
    assert missing_contract.assessments["style"].style_score is None
    assert changed_source.audit["applied_mode"] == "shadow"
    assert changed_source.audit["reason"] == "frozen_reference_source_changed"
    assert changed_source.audit["frozen_sources_complete"] is False
