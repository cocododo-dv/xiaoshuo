from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from pathlib import Path

import pytest

from novel_system.services.style_reference.benchmark import (
    build_blind_review_artifacts,
    load_style_benchmark,
    load_style_benchmark_manifest,
    score_style_benchmark,
)
from novel_system.services.style_reference.benchmark.features import (
    HiddenStyleEvaluator,
    StyleFeatureExtractor,
)
from novel_system.services.style_reference.benchmark.live import (
    PromptRecordingClient,
    StyleBenchmarkLiveRunner,
)
from novel_system.services.style_reference.benchmark.manifest import StyleBenchmarkError
from novel_system.services.style_reference.benchmark.workspace import (
    prepare_generation_workspace,
    write_json,
)
from novel_system.services.llm_client import (
    LLMRequest,
    LLMResponse,
    OnlineAccountedExecution,
)
from novel_system.db.models import (
    ChapterState,
    SceneCard,
    SceneRunState,
    StoryProject,
)


ROOT = Path(__file__).resolve().parents[2]
PUBLIC = (
    ROOT / "config" / "evals" / "style_reference" / "style_benchmark_v1.public.json"
)
PRIVATE = (
    ROOT / "config" / "evals" / "style_reference" / "style_benchmark_v1.private.json"
)


def _bundle():
    return load_style_benchmark(PUBLIC, PRIVATE, workspace_root=ROOT)


def _synthetic_text(case, *, arm: str, target: str | None) -> str:  # noqa: ANN001
    facts = "。".join(group[0] for group in case.required_term_groups) + "。"
    if arm == "neutral":
        units = [
            f"第{index}次查看时，他检查眼前的物件，听完对方的话，停了一会，随后用动作作出决定。"
            for index in range(1, 19)
        ]
    elif target == "luxun":
        units = [
            f"第{index}回，事情原是明白的么？众人不说，他便也不说；然而第{index}回的沉默并不等于没有答案。"
            for index in range(1, 19)
        ]
    else:
        units = [
            f"第{index}刻，微暗的光缓缓移过窗沿，像一层薄水；人的话很轻，这一刻的余意却在静处慢慢展开。"
            for index in range(1, 19)
        ]
    return facts + "".join(units)


def _results_payload(bundle):  # noqa: ANN001
    neutral_texts = {
        case.case_id: _synthetic_text(case, arm="neutral", target=None)
        for case in bundle.public.cases
    }
    generations = []
    for case in bundle.public.cases:
        neutral = neutral_texts[case.case_id]
        generations.append(
            {
                "case_id": case.case_id,
                "arm": "neutral",
                "target_author_id": None,
                "generated_text": neutral,
                "actual_prompt_text": f"公开场景 {case.case_id} 的中性结构生成提示。",
                "generation_metadata": {
                    "generation_path": "neutral_draft",
                    "reference_profile_ids": [],
                },
            }
        )
        neutral_hash = hashlib.sha256(neutral.encode("utf-8")).hexdigest()
        for author in bundle.public.authors:
            generations.append(
                {
                    "case_id": case.case_id,
                    "arm": "styled",
                    "target_author_id": author.author_id,
                    "generated_text": _synthetic_text(
                        case,
                        arm="styled",
                        target=author.author_id,
                    ),
                    "actual_prompt_text": f"公开场景 {case.case_id} 与抽象风格契约。",
                    "generation_metadata": {
                        "generation_path": "style_reference_module",
                        "style_reference_profile_id": f"profile_{author.author_id}",
                        "reference_profile_ids": [f"profile_{author.author_id}"],
                        "training_corpus_checksum": author.training_checksum,
                        "source_neutral_sha256": neutral_hash,
                    },
                }
            )
    return {
        "schema_version": 1,
        "benchmark_id": bundle.public.benchmark_id,
        "manifest_version": bundle.public.manifest_version,
        "public_manifest_hash": bundle.public.public_manifest_hash,
        "generations": generations,
    }


def test_manifest_uses_disjoint_whole_work_splits() -> None:
    bundle = _bundle()

    assert len(bundle.public.authors) == 2
    assert len(bundle.public.cases) == 8
    for author in bundle.public.authors:
        hidden = bundle.hidden_for(author.author_id)
        assert {work.title for work in author.train_works}.isdisjoint(
            work.title for work in hidden.holdout_works
        )
        assert len(hidden.holdout_works) >= 3
        assert sum(work.char_count for work in author.train_works) > 5000
        assert sum(work.char_count for work in hidden.holdout_works) > 2500


def test_public_workspace_never_materializes_holdout_works(tmp_path: Path) -> None:
    manifest = load_style_benchmark_manifest(PUBLIC, workspace_root=ROOT)

    prepared = prepare_generation_workspace(manifest, tmp_path)

    assert prepared["matrix_cell_count"] == 24
    assert (tmp_path / "generation_plan.json").exists()
    template = json.loads(
        (tmp_path / "results_template.json").read_text(encoding="utf-8")
    )
    assert all(
        "reference_profile_ids" in row["generation_metadata"]
        for row in template["generations"]
    )
    for author in manifest.authors:
        training = (
            tmp_path
            / "training"
            / manifest.public_manifest_hash[:16]
            / f"{author.anonymous_corpus_id}.txt"
        ).read_text(encoding="utf-8")
        assert training == author.anonymous_training_text
        assert author.label not in training
        assert all(f"《{work.title}》" not in training for work in author.train_works)
    assert all(
        "luxun" not in path.lower() and "zhuziqing" not in path.lower()
        for path in prepared["training_corpus_paths"]
    )


def test_public_manifest_rejects_hidden_fields() -> None:
    manifest = load_style_benchmark_manifest(PUBLIC, workspace_root=ROOT)
    payload = deepcopy(manifest.source_payload)
    payload["authors"][0]["holdout_works"] = ["阿Q正传"]

    with pytest.raises(StyleBenchmarkError, match="隐藏字段"):
        load_style_benchmark_manifest(payload, workspace_root=ROOT)


def test_benchmark_corpus_excludes_wikisource_license_boilerplate() -> None:
    manifest = load_style_benchmark_manifest(PUBLIC, workspace_root=ROOT)
    zhu = manifest.author_for("zhuziqing").source_path.read_text(encoding="utf-8")

    assert "属于公有领域" not in zhu
    assert "版权期限" not in zhu
    assert "Public domain" not in zhu
    assert "维基文库" not in zhu


def test_public_manifest_rejects_changed_source_corpus(tmp_path: Path) -> None:
    original = load_style_benchmark_manifest(PUBLIC, workspace_root=ROOT)
    payload = deepcopy(original.source_payload)
    author = original.authors[0]
    corpus_path = tmp_path / "training-corpus.txt"
    corpus_path.write_text(author.training_text, encoding="utf-8")
    payload["authors"][0]["source_path"] = str(corpus_path)
    payload["authors"][0]["source_text_sha256"] = hashlib.sha256(
        author.training_text.encode("utf-8")
    ).hexdigest()

    load_style_benchmark_manifest(payload, workspace_root=ROOT)
    corpus_path.write_text(author.training_text + "新增字符", encoding="utf-8")

    with pytest.raises(StyleBenchmarkError, match="source_text_sha256"):
        load_style_benchmark_manifest(payload, workspace_root=ROOT)


def test_hidden_reference_classifier_has_audited_signal() -> None:
    bundle = _bundle()
    evaluator = HiddenStyleEvaluator(
        {author.author_id: author.holdout_works for author in bundle.hidden_authors}
    )

    calibration = evaluator.calibration_report()

    assert calibration["active_feature_count"] >= 80
    assert calibration["calibration_split_unit"] == "whole_work"
    assert calibration["calibration_feature_fit"] == "per_fold_without_held_work"
    assert calibration["calibration_min_active_feature_count"] >= 80
    assert calibration["macro_accuracy"] >= 0.65
    assert all(row["work_count"] >= 2 for row in calibration["per_author"].values())


def test_hidden_classifier_stays_calibrated_without_profile_metrics_family() -> None:
    bundle = _bundle()
    evaluator = HiddenStyleEvaluator(
        {author.author_id: author.holdout_works for author in bundle.hidden_authors},
        extractor=StyleFeatureExtractor(include_shared_metrics=False),
    )

    calibration = evaluator.calibration_report()

    assert calibration["shared_metrics_engine_features"] is False
    assert calibration["active_feature_count"] >= 80
    assert calibration["macro_accuracy"] >= 0.65


def test_score_covers_style_content_copy_leakage_and_lineage() -> None:
    bundle = _bundle()
    report = score_style_benchmark(bundle, _results_payload(bundle))

    assert report["summary"]["generation_count"] == 24
    assert report["summary"]["styled_generation_count"] == 16
    assert report["summary"]["content_preservation_mean"] == 1.0
    assert report["summary"]["plagiarism_pass_rate"] == 1.0
    assert report["summary"]["prompt_leakage_pass_rate"] == 1.0
    assert report["summary"]["identity_blinding_pass_rate"] == 1.0
    assert report["summary"]["module_lineage_coverage"] == 1.0
    assert report["summary"]["styled_non_neutral_rate"] == 1.0
    assert set(report["summary"]["per_author"]) == set(bundle.public.author_ids)
    assert set(report["gates"]) == {
        "reference_calibrated",
        "style_attribution",
        "balanced_style_attribution",
        "paired_contrast",
        "balanced_paired_contrast",
        "styled_output_changed",
        "positive_neutral_gain",
        "content_preserved",
        "all_required_facts_preserved",
        "length_compliant",
        "no_reference_copy",
        "prompt_holdout_clean",
        "author_identity_blinded",
        "no_exact_metric_target_leakage",
        "hard_naturalness_clean",
        "naturalness_non_regressed",
        "module_lineage_verified",
    }
    assert report["summary"]["metric_target_leakage_pass_rate"] == 1.0
    assert report["summary"]["hard_naturalness_pass_rate"] == 1.0
    assert report["evaluation_independence"]["shared_metrics_engine_features"] is False
    assert report["evidence_governance"]["human_verified"] is False
    assert report["evidence_governance"]["policy_evidence_eligible"] is False


def test_hidden_prompt_leak_is_detected_without_echoing_secret_text() -> None:
    bundle = _bundle()
    payload = _results_payload(bundle)
    hidden_excerpt = bundle.hidden_for("zhuziqing").holdout_works[0].text[:80]
    payload["generations"][0]["actual_prompt_text"] += hidden_excerpt

    report = score_style_benchmark(bundle, payload)

    leaked = next(
        sample
        for sample in report["samples"]
        if sample["case_id"] == payload["generations"][0]["case_id"]
        and sample["arm"] == "neutral"
    )
    assert leaked["prompt_leakage"]["verified"] is True
    assert leaked["prompt_leakage"]["passed"] is False
    assert leaked["prompt_leakage"]["hidden_ngram_hit_count"] > 0
    assert hidden_excerpt not in str(report)
    assert report["gates"]["prompt_holdout_clean"] is False


def test_every_sample_must_preserve_every_required_fact_group() -> None:
    bundle = _bundle()
    payload = _results_payload(bundle)
    case = bundle.public.cases[0]
    sample = payload["generations"][0]
    for variant in case.required_term_groups[0]:
        sample["generated_text"] = sample["generated_text"].replace(variant, "某人")

    report = score_style_benchmark(bundle, payload)

    assert report["summary"]["content_preservation_mean"] >= 0.9
    assert report["summary"]["content_full_pass_rate"] < 1.0
    assert report["gates"]["all_required_facts_preserved"] is False
    assert report["benchmark_passed"] is False


def test_generation_prompt_cannot_use_explicit_author_identity() -> None:
    bundle = _bundle()
    payload = _results_payload(bundle)
    payload["generations"][0]["actual_prompt_text"] += " 请模仿鲁迅。"

    report = score_style_benchmark(bundle, payload)

    assert report["summary"]["identity_blinding_pass_rate"] < 1.0
    assert report["gates"]["author_identity_blinded"] is False


def test_generation_prompt_cannot_expose_exact_style_metric_quotas() -> None:
    bundle = _bundle()
    payload = _results_payload(bundle)
    styled = next(row for row in payload["generations"] if row["arm"] == "styled")
    styled["actual_prompt_text"] += (
        "\n[STYLE_REFERENCE]\n[风格分布指导]\n句均字数：当前约12.0，目标约18.0。"
        "\n[/STYLE_REFERENCE]"
    )

    report = score_style_benchmark(bundle, payload)
    sample = next(
        row
        for row in report["samples"]
        if row["case_id"] == styled["case_id"]
        and row["arm"] == "styled"
        and row["target_author_id"] == styled["target_author_id"]
    )

    assert sample["metric_target_leakage"]["verified"] is True
    assert sample["metric_target_leakage"]["passed"] is False
    assert report["gates"]["no_exact_metric_target_leakage"] is False


def test_repeated_substantive_sentence_fails_hard_naturalness_gate() -> None:
    bundle = _bundle()
    payload = _results_payload(bundle)
    styled = next(row for row in payload["generations"] if row["arm"] == "styled")
    case = bundle.public.case_for(styled["case_id"])
    facts = "。".join(group[0] for group in case.required_term_groups) + "。"
    styled["generated_text"] = facts + (
        "他把同一句话说完，又把目光移回门边。" * 18
    )

    report = score_style_benchmark(bundle, payload)
    sample = next(
        row
        for row in report["samples"]
        if row["case_id"] == styled["case_id"]
        and row["arm"] == "styled"
        and row["target_author_id"] == styled["target_author_id"]
    )

    assert "self_repetition" in sample["naturalness_diagnostic"][
        "hard_risk_dimensions"
    ]
    assert sample["naturalness_diagnostic"]["hard_passed"] is False
    assert report["gates"]["hard_naturalness_clean"] is False


def test_every_sample_must_stay_inside_the_length_band() -> None:
    bundle = _bundle()
    payload = _results_payload(bundle)
    case = bundle.public.cases[0]
    payload["generations"][0]["generated_text"] = (
        "。".join(group[0] for group in case.required_term_groups) + "。动作" * 25
    )

    report = score_style_benchmark(bundle, payload)

    assert report["summary"]["length_full_pass_rate"] < 1.0
    assert report["gates"]["length_compliant"] is False
    assert report["benchmark_passed"] is False


def test_whitespace_cannot_pad_a_short_generation_into_the_length_band() -> None:
    bundle = _bundle()
    payload = _results_payload(bundle)
    case = bundle.public.cases[0]
    payload["generations"][0]["generated_text"] = (
        "。".join(group[0] for group in case.required_term_groups)
        + "。动作" * 25
        + " " * 1000
    )

    report = score_style_benchmark(bundle, payload)
    row = next(
        item
        for item in report["samples"]
        if item["case_id"] == case.case_id and item["arm"] == "neutral"
    )

    assert row["generated_char_count"] < case.min_chars
    assert row["length_score"] < 1.0
    assert report["gates"]["length_compliant"] is False


def test_neutral_lineage_rejects_any_style_profile() -> None:
    bundle = _bundle()
    payload = _results_payload(bundle)
    payload["generations"][0]["generation_metadata"]["reference_profile_ids"] = [
        "profile_luxun"
    ]

    report = score_style_benchmark(bundle, payload)

    assert report["summary"]["module_lineage_coverage"] < 1.0
    assert report["gates"]["module_lineage_verified"] is False


def test_exact_neutral_fallback_cannot_count_as_successful_style_generation() -> None:
    bundle = _bundle()
    payload = _results_payload(bundle)
    case_id = bundle.public.cases[0].case_id
    neutral = next(
        row
        for row in payload["generations"]
        if row["case_id"] == case_id and row["arm"] == "neutral"
    )
    styled = next(
        row
        for row in payload["generations"]
        if row["case_id"] == case_id and row["arm"] == "styled"
    )
    styled["generated_text"] = neutral["generated_text"]

    report = score_style_benchmark(bundle, payload)

    assert report["summary"]["exact_neutral_fallback_count"] == 1
    assert report["summary"]["styled_non_neutral_rate"] < 1.0
    assert report["gates"]["styled_output_changed"] is False
    assert report["benchmark_passed"] is False


def test_neutral_reformat_cannot_count_as_successful_style_generation() -> None:
    bundle = _bundle()
    payload = _results_payload(bundle)
    case_id = bundle.public.cases[0].case_id
    neutral = next(
        row
        for row in payload["generations"]
        if row["case_id"] == case_id and row["arm"] == "neutral"
    )
    styled = next(
        row
        for row in payload["generations"]
        if row["case_id"] == case_id and row["arm"] == "styled"
    )
    # 只增加段间空白，原始哈希会变化，但规范化正文仍与中性稿完全相同。
    styled["generated_text"] = neutral["generated_text"].replace("。", "。\n\n")

    report = score_style_benchmark(bundle, payload)

    assert report["summary"]["exact_neutral_fallback_count"] == 0
    assert report["summary"]["neutral_equivalent_fallback_count"] == 1
    assert report["summary"]["styled_non_neutral_rate"] < 1.0
    assert report["gates"]["styled_output_changed"] is False
    assert report["benchmark_passed"] is False


def test_result_matrix_must_be_complete() -> None:
    bundle = _bundle()
    payload = _results_payload(bundle)
    payload["generations"].pop()

    with pytest.raises(StyleBenchmarkError, match="结果矩阵不完整"):
        score_style_benchmark(bundle, payload)


def test_frozen_thresholds_cannot_be_weakened() -> None:
    bundle = _bundle()

    with pytest.raises(StyleBenchmarkError, match="不能降低"):
        score_style_benchmark(
            bundle,
            _results_payload(bundle),
            thresholds={"style_attribution_accuracy": 0.1},
        )


def test_blind_packet_hides_candidate_arm_and_keeps_answer_key_separate() -> None:
    bundle = _bundle()
    packet, answer_key = build_blind_review_artifacts(
        bundle, _results_payload(bundle), seed="fixed"
    )

    assert len(packet["tasks"]) == 16
    assert all(len(task["candidates"]) == 3 for task in packet["tasks"])
    assert "target_author_id" not in _all_keys(packet)
    assert "arm" not in _all_keys(packet)
    assert len(answer_key["samples"]) == 48
    assert all(
        "arm" in row and "target_author_id" in row for row in answer_key["samples"]
    )


class _RecordingDelegate(OnlineAccountedExecution):
    def generate_accounted(self, request, *, accounting_hook):  # noqa: ANN001, ANN201
        return LLMResponse(
            request_id="recorded",
            provider=request.provider or "fake",
            model=request.model,
            text='{"scene_text":"ok"}',
            structured_output={"scene_text": "ok"},
            response_format="json_object",
            raw_response={},
            usage={"input_tokens": 1, "output_tokens": 1, "total_tokens": 2},
            finish_reason="stop",
        )


def test_prompt_recording_client_keeps_exact_messages_for_leak_audit() -> None:
    client = PromptRecordingClient(_RecordingDelegate())
    request = LLMRequest(
        model="fake-model",
        provider="openai_compatible",
        node_id="style_draft",
        messages=[
            {"role": "system", "content": "STYLE SYSTEM"},
            {"role": "user", "content": "SCENE USER"},
        ],
        temperature=0.2,
        max_output_tokens=256,
        response_format="json_object",
    )

    response = client.generate_accounted(request, accounting_hook=object())

    assert response.structured_output == {"scene_text": "ok"}
    assert client.combined_prompt_text(since=0) == (
        "[LLM_CALL 1 node=style_draft]\n" "[SYSTEM]\nSTYLE SYSTEM\n\n[USER]\nSCENE USER"
    )


def test_live_runner_seeds_isolated_scene_matrix_without_calling_llm(
    session, tmp_path: Path
) -> None:
    # Match run_live_benchmark_workspace: no query-triggered autoflush is
    # available to hide a missing FK-tier flush.
    session.autoflush = False
    manifest = load_style_benchmark_manifest(PUBLIC, workspace_root=ROOT)
    runner = StyleBenchmarkLiveRunner(
        session,
        manifest,
        llm_client=_RecordingDelegate(),
        results_path=tmp_path / "results.json",
    )

    runner._seed_project()

    assert session.get(StoryProject, runner.project_id)
    assert all(
        session.get(SceneCard, runner._scene_id(case)) for case in manifest.cases
    )
    assert all(
        session.get(ChapterState, runner._chapter_id(case))
        for case in manifest.cases
    )
    assert all(
        session.get(SceneRunState, runner._scene_id(case))
        for case in manifest.cases
    )


def test_live_runner_rejects_incompatible_resume_schema(
    session, tmp_path: Path
) -> None:
    manifest = load_style_benchmark_manifest(PUBLIC, workspace_root=ROOT)
    results_path = tmp_path / "results.json"
    write_json(
        results_path,
        {
            "schema_version": 999,
            "benchmark_id": manifest.benchmark_id,
            "manifest_version": manifest.manifest_version,
            "public_manifest_hash": manifest.public_manifest_hash,
            "generations": [],
        },
    )

    with pytest.raises(StyleBenchmarkError, match="schema_version"):
        StyleBenchmarkLiveRunner(
            session,
            manifest,
            llm_client=_RecordingDelegate(),
            results_path=results_path,
            resume=True,
        )


def test_live_runner_rejects_matrix_cells_outside_manifest(
    session, tmp_path: Path
) -> None:
    manifest = load_style_benchmark_manifest(PUBLIC, workspace_root=ROOT)
    runner = StyleBenchmarkLiveRunner(
        session,
        manifest,
        llm_client=_RecordingDelegate(),
        results_path=tmp_path / "results.json",
    )

    with pytest.raises(StyleBenchmarkError, match="矩阵外单元"):
        runner._validate_partial_generations(
            [
                {
                    "case_id": "not-a-case",
                    "arm": "neutral",
                    "target_author_id": None,
                    "generated_text": "有效正文",
                    "actual_prompt_text": "实际提示词",
                    "generation_metadata": {},
                }
            ]
        )


def _all_keys(value) -> set[str]:  # noqa: ANN001
    keys: set[str] = set()
    if isinstance(value, dict):
        keys.update(str(key) for key in value)
        for item in value.values():
            keys.update(_all_keys(item))
    elif isinstance(value, list):
        for item in value:
            keys.update(_all_keys(item))
    return keys
