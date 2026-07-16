from __future__ import annotations

import json
from types import SimpleNamespace

import pytest
from sqlalchemy import select

from novel_system.db.models import ChapterGoal, QualityValueObservation, SceneCard, StoryProject
from novel_system.services.errors import DomainError
from novel_system.services.evaluation_experiment import EvaluationExperimentService
from novel_system.services.orchestrator import Orchestrator
from novel_system.services.quality_evidence import QualityEvidenceService, load_hidden_benchmark
from novel_system.services.quality_strategy import QualityStrategyResolver, QualityStrategyService
from novel_system.tools.quality_evidence import inspect_hidden_benchmark, main as quality_evidence_main


def _write_hidden_bundle(tmp_path, *, manifest_id: str, cells: list[tuple[str, str]], short_secret: str = "ZX"):
    public = {
        "schema_version": 1,
        "manifest_id": manifest_id,
        "manifest_version": "v1",
        "split_kind": "hidden",
        "isolation_mode": "external_holdout",
        "cases": [
            {
                "case_id": f"case_{index:03d}",
                "genre": genre,
                "scene_function": scene_function,
                "generation_input": {
                    "scene_goal": f"公开目标{index}",
                    "constraints": ["只使用公开输入"],
                },
            }
            for index, (genre, scene_function) in enumerate(cells)
        ],
    }
    private = {
        "schema_version": 1,
        "manifest_id": manifest_id,
        "manifest_version": "v1",
        "cases": [
            {
                "case_id": f"case_{index:03d}",
                "rubric": {"criterion": f"秘密准则丙丁{index}"},
                "expected_answer": short_secret if index == 0 else f"隐藏答案戊己{index}",
            }
            for index in range(len(cells))
        ],
    }
    public_path = tmp_path / f"{manifest_id}_public.json"
    private_path = tmp_path / f"{manifest_id}_private.json"
    public_path.write_text(json.dumps(public, ensure_ascii=False), encoding="utf-8")
    private_path.write_text(json.dumps(private, ensure_ascii=False), encoding="utf-8")
    return public_path, private_path


def _register(session, tmp_path, *, manifest_id: str, cells: list[tuple[str, str]]):
    public_path, private_path = _write_hidden_bundle(
        tmp_path,
        manifest_id=manifest_id,
        cells=cells,
    )
    bundle = load_hidden_benchmark(public_path, private_path)
    manifest = QualityEvidenceService(session).register_manifest(
        bundle,
        storage_ref=f"vault:{manifest_id}",
    )
    return bundle, manifest, public_path, private_path


def test_hidden_loader_and_tool_never_return_private_content(tmp_path) -> None:
    public_path, private_path = _write_hidden_bundle(
        tmp_path,
        manifest_id="manifest_no_leak",
        cells=[("悬疑", "reveal")],
        short_secret="Z",
    )
    bundle = load_hidden_benchmark(public_path, private_path)
    rendered = json.dumps(
        {
            "bundle": bundle.public_summary(),
            "tool": inspect_hidden_benchmark(public_path, private_path, case_id="case_000"),
        },
        ensure_ascii=False,
    )
    assert "Z" not in rendered
    assert "秘密准则" not in rendered
    assert "expected_answer" not in rendered
    assert "private.json" not in rendered
    with pytest.raises(DomainError) as leaked:
        bundle.assert_actual_prompt_clean("请把短 canary Z 原样用于生成")
    assert leaked.value.code == "HIDDEN_BENCHMARK_PROMPT_LEAK"


def test_hidden_loader_requires_version_and_nonempty_private_rubric(tmp_path) -> None:
    public_path, private_path = _write_hidden_bundle(
        tmp_path,
        manifest_id="manifest_invalid_private",
        cells=[("悬疑", "reveal")],
    )
    private = json.loads(private_path.read_text(encoding="utf-8"))
    private.pop("manifest_version")
    private_path.write_text(json.dumps(private, ensure_ascii=False), encoding="utf-8")
    with pytest.raises(DomainError) as version_error:
        load_hidden_benchmark(public_path, private_path)
    assert version_error.value.code == "HIDDEN_BENCHMARK_VERSION_MISMATCH"

    private["manifest_version"] = "v1"
    private["cases"][0] = {"case_id": "case_000", "notes": "not a rubric"}
    private_path.write_text(json.dumps(private, ensure_ascii=False), encoding="utf-8")
    with pytest.raises(DomainError) as rubric_error:
        load_hidden_benchmark(public_path, private_path)
    assert rubric_error.value.code == "HIDDEN_BENCHMARK_PRIVATE_RUBRIC_REQUIRED"


def test_result_evidence_is_server_verified_strict_and_fully_idempotent(session, tmp_path) -> None:
    bundle, manifest, _, _ = _register(
        session,
        tmp_path,
        manifest_id="manifest_result_rules",
        cells=[("悬疑", "reveal")],
    )
    evidence = QualityEvidenceService(session)
    with pytest.raises(DomainError) as path_ref:
        evidence.register_manifest(bundle, storage_ref=r"C:\hidden\rubric.json")
    assert path_ref.value.code == "HIDDEN_BENCHMARK_STORAGE_REF_INVALID"

    with pytest.raises(DomainError) as missing_policy:
        evidence.start_run(manifest.manifest_id, generator_ref="gen:v1", policy_id="missing")
    assert missing_policy.value.code == "QUALITY_BENCHMARK_POLICY_NOT_APPLICABLE"

    run = evidence.start_run(manifest.manifest_id, generator_ref="gen:v1")
    payload = bundle.payload_for("case_000")
    kwargs = dict(
        bundle=bundle,
        case_id="case_000",
        generation_payload=payload,
        actual_prompt_text="仅含公开目标的生成提示",
        output_text="生成正文甲乙。",
        artifact_ref="artifact:result_000",
        automated_metrics={"machine": {"score": 0.8}},
        cost_tokens=None,
        latency_ms=None,
    )
    with pytest.raises(DomainError) as nested_human:
        evidence.record_generation_result(
            run.run_id,
            **{**kwargs, "automated_metrics": {"nested": {"first_usable": True}}},
        )
    assert nested_human.value.code == "QUALITY_HUMAN_METRIC_PROVENANCE_REQUIRED"
    with pytest.raises(DomainError) as fractional_tokens:
        evidence.record_generation_result(run.run_id, **{**kwargs, "cost_tokens": 1.5})
    assert fractional_tokens.value.code == "QUALITY_COST_INVALID"
    with pytest.raises(DomainError) as incomplete_money:
        evidence.record_generation_result(run.run_id, **{**kwargs, "cost_micros": 100})
    assert incomplete_money.value.code == "QUALITY_MONETARY_COST_INCOMPLETE"

    result = evidence.record_generation_result(run.run_id, **kwargs)
    same = evidence.record_generation_result(run.run_id, **kwargs)
    assert same.result_id == result.result_id
    assert result.cost_tokens is None and result.latency_ms is None and result.cost_micros is None
    with pytest.raises(DomainError) as changed_artifact:
        evidence.record_generation_result(
            run.run_id,
            **{**kwargs, "artifact_ref": "artifact:different"},
        )
    assert changed_artifact.value.code == "QUALITY_BENCHMARK_RESULT_CONFLICT"
    evidence.complete_run(run.run_id)
    assert evidence.record_generation_result(run.run_id, **kwargs).result_id == result.result_id

    with pytest.raises(DomainError) as model_metric:
        evidence.record_human_observation(
            result.result_id,
            reviewer_ref="model:gpt",
            provenance="model",
            first_usable=True,
        )
    assert model_metric.value.code == "QUALITY_HUMAN_PROVENANCE_REQUIRED"
    with pytest.raises(DomainError) as disguised_model_metric:
        evidence.record_human_observation(
            result.result_id,
            reviewer_ref="model:gpt",
            provenance="human",
            first_usable=True,
        )
    assert disguised_model_metric.value.code == "QUALITY_HUMAN_PROVENANCE_REQUIRED"
    with pytest.raises(DomainError) as wrong_source:
        evidence.record_human_observation(
            result.result_id,
            reviewer_ref="human:1",
            provenance="human",
            source_text="任意替代文本",
            edited_text="替代编辑文本",
        )
    assert wrong_source.value.code == "QUALITY_EDIT_SOURCE_MISMATCH"
    with pytest.raises(DomainError) as fractional_intent:
        evidence.record_human_observation(
            result.result_id,
            reviewer_ref="human:1",
            provenance="human",
            follow_read_intent=4.5,
        )
    assert fractional_intent.value.code == "QUALITY_FOLLOW_READ_INVALID"

    observation = evidence.record_human_observation(
        result.result_id,
        reviewer_ref="human:1",
        provenance="human",
        source_text="生成正文甲乙。",
        edited_text="生成正文甲乙。",
        first_usable=True,
        follow_read_intent=4,
    )
    assert observation.human_edit_distance == 0


def _build_evidenced_experiment(
    session,
    tmp_path,
    *,
    manifest_id: str,
    cells: list[tuple[str, str]],
    treatment_wins: int,
    observe_cells: set[tuple[str, str]] | None = None,
    ablation: bool = False,
):
    bundle, manifest, _, _ = _register(
        session,
        tmp_path,
        manifest_id=manifest_id,
        cells=cells,
    )
    strategy = QualityStrategyService(session)
    target_genre, target_function = cells[-1]
    policy = strategy.create_policy(
        genre=target_genre,
        scene_function=target_function,
        best_of_n_requested=True,
        best_of_n_n=3,
        benchmark_manifest_id=manifest.manifest_id,
    )
    treatment_policy = {
        "quality_strategy_policy_id": policy.policy_id,
        "best_of_n": 3,
        **({"ablation": True} if ablation else {}),
    }
    control_policy = {"best_of_n": 1}
    experiments = EvaluationExperimentService(session)
    experiment = experiments.create_experiment(
        name="hidden human blind A/B",
        treatment_policy=treatment_policy,
        control_policy=control_policy,
        evidence_provenance="human",
        isolation_mode="external_holdout",
        snapshot_source_ref="artifact:external_holdout_v1",
        benchmark_manifest_id=manifest.manifest_id,
    )
    evidence = QualityEvidenceService(session)
    treatment_run = evidence.start_run(
        manifest.manifest_id,
        generator_ref="generator:treatment",
        policy_id=policy.policy_id,
        generation_policy=treatment_policy,
        generation_arm="treatment",
    )
    control_run = evidence.start_run(
        manifest.manifest_id,
        generator_ref="generator:control",
        generation_policy=control_policy,
        generation_arm="control",
    )
    treatment_results = []
    control_results = []
    treatment_texts = []
    control_texts = []
    for index, case in enumerate(bundle.cases):
        treatment_text = f"治疗臂正文{index}甲乙丙丁"
        control_text = f"对照臂正文{index}戊己庚辛"
        treatment_texts.append(treatment_text)
        control_texts.append(control_text)
        treatment_results.append(
            evidence.record_generation_result(
                treatment_run.run_id,
                bundle=bundle,
                case_id=case.case_id,
                generation_payload=bundle.payload_for(case.case_id),
                actual_prompt_text=f"公开治疗提示{index}",
                output_text=treatment_text,
                artifact_ref=f"artifact:treatment_{index:03d}",
                automated_metrics={"machine_quality": 0.9},
                cost_tokens=3000,
                cost_micros=300_000,
                cost_currency="CNY",
                cost_basis="estimated",
                latency_ms=1000,
            )
        )
        control_results.append(
            evidence.record_generation_result(
                control_run.run_id,
                bundle=bundle,
                case_id=case.case_id,
                generation_payload=bundle.payload_for(case.case_id),
                actual_prompt_text=f"公开对照提示{index}",
                output_text=control_text,
                artifact_ref=f"artifact:control_{index:03d}",
                automated_metrics={"machine_quality": 0.5},
                cost_tokens=1000,
                cost_micros=100_000,
                cost_currency="CNY",
                cost_basis="estimated",
                latency_ms=500,
            )
        )
    evidence.complete_run(treatment_run.run_id)
    evidence.complete_run(control_run.run_id)

    pairs = []
    for index, (treatment_result, control_result) in enumerate(zip(treatment_results, control_results)):
        pair = experiments.add_pair(
            experiment.experiment_id,
            scene_snapshot_hash=f"caller_forged_snapshot_{index}",
            treatment_text=treatment_texts[index],
            control_text=control_texts[index],
            token_cost={"treatment": 1, "control": 999999},
            treatment_benchmark_result_id=treatment_result.result_id,
            control_benchmark_result_id=control_result.result_id,
            seed=index,
        )
        assert pair.scene_snapshot_hash == treatment_result.generation_input_hash
        assert pair.token_cost_json == {
            "treatment": 3000,
            "control": 1000,
            "source": "quality_benchmark_results",
        }
        slot = pair.blind_mapping_json["treatment_slot"]
        assert (
            pair.left_artifact_ref if slot == "left" else pair.right_artifact_ref
        ) == treatment_result.artifact_ref
        pairs.append(pair)
    experiments.freeze_experiment(experiment.experiment_id)
    for index, pair in enumerate(pairs):
        treatment_slot = pair.blind_mapping_json["treatment_slot"]
        choice = (
            treatment_slot
            if index < treatment_wins
            else ("right" if treatment_slot == "left" else "left")
        )
        experiments.record_vote(
            pair.pair_id,
            choice=choice,
            reviewer_ref=f"human_blind:{index:03d}",
            duration_ms=1500,
        )
    observed = observe_cells if observe_cells is not None else set(cells)
    for index, result in enumerate(treatment_results):
        if cells[index] not in observed:
            continue
        evidence.record_human_observation(
            result.result_id,
            reviewer_ref=f"human_value:{index:03d}",
            provenance="human",
            source_text=treatment_texts[index],
            edited_text=treatment_texts[index],
            first_usable=True,
            follow_read_intent=4,
        )
    strategy.bind_evidence(
        policy.policy_id,
        evidence_experiment_id=experiment.experiment_id,
        benchmark_manifest_id=manifest.manifest_id,
    )
    return SimpleNamespace(
        bundle=bundle,
        manifest=manifest,
        policy=policy,
        experiment=experiment,
        pairs=pairs,
        treatment_results=treatment_results,
        control_results=control_results,
    )


def test_hidden_pair_binding_requires_completed_distinct_policy_arms(session, tmp_path) -> None:
    bundle, manifest, _, _ = _register(
        session,
        tmp_path,
        manifest_id="manifest_pair_gate",
        cells=[("悬疑", "reveal")],
    )
    exp_svc = EvaluationExperimentService(session)
    experiment = exp_svc.create_experiment(
        name="arms",
        treatment_policy={"best_of_n": 3},
        control_policy={"best_of_n": 1},
        benchmark_manifest_id=manifest.manifest_id,
        isolation_mode="external_holdout",
    )
    evidence = QualityEvidenceService(session)
    run = evidence.start_run(
        manifest.manifest_id,
        generator_ref="same",
        generation_policy={"best_of_n": 3},
        generation_arm="treatment",
    )
    treatment = evidence.record_generation_result(
        run.run_id,
        bundle=bundle,
        case_id="case_000",
        generation_payload=bundle.payload_for("case_000"),
        actual_prompt_text="公开提示",
        output_text="正文A",
        artifact_ref="artifact:arm_a",
        cost_tokens=10,
        latency_ms=1,
    )
    with pytest.raises(DomainError) as collecting_run:
        exp_svc.add_pair(
            experiment.experiment_id,
            scene_snapshot_hash="forged",
            treatment_text="正文A",
            control_text="正文A",
            treatment_benchmark_result_id=treatment.result_id,
            control_benchmark_result_id=treatment.result_id,
        )
    assert collecting_run.value.code == "HIDDEN_BENCHMARK_RUN_NOT_ELIGIBLE"


def test_global_significance_cannot_enable_under_sampled_exact_cell(session, tmp_path) -> None:
    cells = [("科幻", "advance")] * 30 + [("悬疑", "reveal")]
    built = _build_evidenced_experiment(
        session,
        tmp_path,
        manifest_id="manifest_stratified_gate",
        cells=cells,
        treatment_wins=22,
        observe_cells={("悬疑", "reveal")},
    )
    report = EvaluationExperimentService(session).build_report(built.experiment.experiment_id)
    assert report["policy_evidence_eligible"] is True
    resolved = QualityStrategyResolver(session).resolve("悬疑", "reveal")
    assert resolved.best_of_n_enabled is False
    assert resolved.best_of_n_n == 1
    assert "blind_cell_sample_insufficient" in resolved.blockers


def test_complete_exact_cell_human_proof_enables_and_production_consumes_policy(session, tmp_path) -> None:
    built = _build_evidenced_experiment(
        session,
        tmp_path,
        manifest_id="manifest_complete_gate",
        cells=[("悬疑", "reveal")] * 30,
        treatment_wins=21,
    )
    resolved = QualityStrategyResolver(session).resolve("悬疑", "reveal")
    assert resolved.fallback_level == "exact"
    assert resolved.best_of_n_enabled is True
    assert resolved.best_of_n_n == 3
    assert resolved.blockers == ()

    observation = session.execute(
        select(QualityValueObservation).where(
            QualityValueObservation.result_id == built.treatment_results[0].result_id
        )
    ).scalars().one()
    observation.first_usable = None
    session.flush()
    missing_human = QualityStrategyResolver(session).resolve("悬疑", "reveal")
    assert missing_human.best_of_n_enabled is False
    assert "first_usable_sample_insufficient" in missing_human.blockers
    observation.first_usable = True
    session.flush()

    first_result = built.treatment_results[0]
    first_result.cost_micros = first_result.cost_currency = first_result.cost_basis = None
    session.flush()
    missing_money = QualityStrategyResolver(session).resolve("悬疑", "reveal")
    assert missing_money.best_of_n_enabled is False
    assert "monetary_cost_sample_insufficient" in missing_money.blockers
    first_result.cost_micros = 300_000
    first_result.cost_currency = "CNY"
    first_result.cost_basis = "estimated"
    session.flush()
    assert QualityStrategyResolver(session).resolve("悬疑", "reveal").best_of_n_enabled is True

    project = StoryProject(project_id="project_quality", title="质量项目", genre="悬疑", outline_text="大纲")
    session.add(project)
    session.flush()
    chapter = ChapterGoal(chapter_id="chapter_quality", project_id=project.project_id, chapter_goal="目标")
    session.add(chapter)
    session.flush()
    scene = SceneCard(
        scene_id="scene_quality",
        chapter_id=chapter.chapter_id,
        project_id=project.project_id,
        scene_seq=1,
        scene_goal="揭示真相",
        writer_brief_json={"function_tag": "reveal"},
    )
    session.add(scene)
    session.flush()
    orchestrator = SimpleNamespace(
        session=session,
        scene_generation_service=SimpleNamespace(
            _llm_runner=SimpleNamespace(provider_execution_mode="online")
        ),
    )
    contract = SimpleNamespace(scene_id=scene.scene_id, payload_json={})
    criticality = SimpleNamespace(
        reasons=["constraint_intensity_full_rigor"],
        initial_best_of_n=3,
        max_best_of_n=5,
    )
    assert Orchestrator._best_of_n_count(orchestrator, contract, criticality=criticality) == 3
    assert Orchestrator._best_of_n_max_count(
        orchestrator,
        criticality=criticality,
        initial_count=3,
    ) == 3


def test_policy_fallback_order_is_explicit_and_never_enables_without_cell_evidence(session) -> None:
    strategy = QualityStrategyService(session)
    global_policy = strategy.create_policy(
        genre="*",
        scene_function="*",
        policy_version=1,
        weights={"model_voice": 0.1},
    )
    function_policy = strategy.create_policy(
        genre="*",
        scene_function="reveal",
        policy_version=1,
        weights={"model_voice": 0.2},
    )
    genre_policy = strategy.create_policy(
        genre="悬疑",
        scene_function="*",
        policy_version=1,
        weights={"model_voice": 0.3},
    )
    exact_policy = strategy.create_policy(
        genre="悬疑",
        scene_function="reveal",
        policy_version=1,
        weights={"model_voice": 0.4},
    )
    resolver = QualityStrategyResolver(session)
    assert resolver.resolve("悬疑", "reveal").matched_policy_id == exact_policy.policy_id
    strategy.retire_policy(exact_policy.policy_id)
    assert resolver.resolve("悬疑", "reveal").matched_policy_id == genre_policy.policy_id
    strategy.retire_policy(genre_policy.policy_id)
    assert resolver.resolve("悬疑", "reveal").matched_policy_id == function_policy.policy_id
    strategy.retire_policy(function_policy.policy_id)
    assert resolver.resolve("悬疑", "reveal").matched_policy_id == global_policy.policy_id
    strategy.retire_policy(global_policy.policy_id)
    assert resolver.resolve("悬疑", "reveal").fallback_level == "builtin_default"


def test_production_thresholds_cannot_be_relaxed_and_policy_integers_are_strict(session) -> None:
    strategy = QualityStrategyService(session)
    permissive_thresholds = (
        {"min_blind_non_tie_n": 1},
        {"min_human_value_n": 29},
        {"max_p_value": 0.1},
        {"max_human_edit_distance_ratio": 0.5},
        {"min_first_usable_rate": 0.5},
        {"min_follow_read_intent": 3.0},
        {"max_token_multiplier": 6.0},
        {"max_average_latency_ms": 120_001},
        {"require_cost_tokens": False},
        {"require_latency": False},
        {"require_monetary_cost": False},
    )
    for index, thresholds in enumerate(permissive_thresholds):
        with pytest.raises(DomainError) as error:
            strategy.create_policy(
                genre=f"relaxed_{index}",
                scene_function="reveal",
                thresholds=thresholds,
            )
        assert error.value.code == "QUALITY_POLICY_THRESHOLDS_TOO_PERMISSIVE"
    for field, value in (("best_of_n_n", 1.5), ("policy_version", 1.5)):
        with pytest.raises(DomainError) as error:
            strategy.create_policy(
                genre=f"fractional_{field}",
                scene_function="reveal",
                **{field: value},
            )
        assert error.value.code in {"QUALITY_POLICY_BEST_OF_N_INVALID", "QUALITY_POLICY_VERSION_INVALID"}
    for index, thresholds in enumerate(
        (
            {"min_blind_non_tie_n": "thirty"},
            {"max_p_value": "not-a-number"},
            {"min_follow_read_intent": float("nan")},
            {"max_average_latency_ms": float("inf")},
        )
    ):
        with pytest.raises(DomainError) as error:
            strategy.create_policy(
                genre=f"invalid_numeric_{index}",
                scene_function="reveal",
                thresholds=thresholds,
            )
        assert error.value.code == "QUALITY_POLICY_THRESHOLDS_INVALID"


def test_ablation_cannot_enable_before_fresh_human_replication(session, tmp_path) -> None:
    built = _build_evidenced_experiment(
        session,
        tmp_path,
        manifest_id="manifest_replication_gate",
        cells=[("悬疑", "reveal")] * 30,
        treatment_wins=21,
        ablation=True,
    )
    report = EvaluationExperimentService(session).build_report(built.experiment.experiment_id)
    assert report["requires_fresh_replication"] is True
    assert report["decision"] == "replication_required"
    resolved = QualityStrategyResolver(session).resolve("悬疑", "reveal")
    assert resolved.best_of_n_enabled is False
    assert "fresh_human_replication_required" in resolved.blockers
    assert "blind_experiment_not_approved_for_upgrade" in resolved.blockers


def test_operator_cli_collects_full_lifecycle_without_echoing_raw_text(
    session,
    tmp_path,
    capsys,
) -> None:
    public_path, private_path = _write_hidden_bundle(
        tmp_path,
        manifest_id="manifest_cli_lifecycle",
        cells=[("悬疑", "reveal")],
        short_secret="绝密短语甲乙",
    )
    assert quality_evidence_main(
        [
            "register",
            "--public-cases",
            str(public_path),
            "--private-rubric",
            str(private_path),
            "--storage-ref",
            "vault:manifest_cli_lifecycle",
        ]
    ) == 0
    register_output = json.loads(capsys.readouterr().out)
    assert register_output["manifest_id"] == "manifest_cli_lifecycle"

    assert quality_evidence_main(
        [
            "start-run",
            "--manifest-id",
            "manifest_cli_lifecycle",
            "--generator-ref",
            "collector:test",
        ]
    ) == 0
    run_id = json.loads(capsys.readouterr().out)["run_id"]
    prompt_path = tmp_path / "actual_prompt.txt"
    output_path = tmp_path / "generated_output.txt"
    prompt_path.write_text("只含公开输入的提示", encoding="utf-8")
    output_path.write_text("不会被 CLI 回显的生成正文", encoding="utf-8")
    assert quality_evidence_main(
        [
            "record-result",
            "--public-cases",
            str(public_path),
            "--private-rubric",
            str(private_path),
            "--run-id",
            run_id,
            "--case-id",
            "case_000",
            "--actual-prompt-file",
            str(prompt_path),
            "--output-file",
            str(output_path),
            "--artifact-ref",
            "artifact:cli_result",
            "--cost-tokens",
            "100",
            "--cost-micros",
            "2000",
            "--cost-currency",
            "CNY",
            "--cost-basis",
            "actual",
            "--latency-ms",
            "25",
        ]
    ) == 0
    record_raw = capsys.readouterr().out
    assert "不会被 CLI 回显" not in record_raw
    assert "绝密短语" not in record_raw
    result_id = json.loads(record_raw)["result_id"]

    assert quality_evidence_main(["complete-run", "--run-id", run_id]) == 0
    capsys.readouterr()
    edited_path = tmp_path / "edited_output.txt"
    edited_path.write_text("不会被 CLI 回显的生成正文", encoding="utf-8")
    assert quality_evidence_main(
        [
            "human-observation",
            "--result-id",
            result_id,
            "--reviewer-ref",
            "human:cli-reviewer",
            "--source-file",
            str(output_path),
            "--edited-file",
            str(edited_path),
            "--first-usable",
            "true",
            "--follow-read-intent",
            "4",
        ]
    ) == 0
    human_raw = capsys.readouterr().out
    assert "不会被 CLI 回显" not in human_raw
    assert json.loads(human_raw)["human_edit_distance"] == 0

    assert quality_evidence_main(
        [
            "summarize",
            "--manifest-id",
            "manifest_cli_lifecycle",
            "--genre",
            "悬疑",
            "--scene-function",
            "reveal",
        ]
    ) == 0
    summary = json.loads(capsys.readouterr().out)
    assert summary["monetary_cost"]["observed_result_n"] == 1
    assert summary["latency_ms"]["observed_result_n"] == 1


def test_vote_duration_rejects_fractional_or_negative_values(session) -> None:
    service = EvaluationExperimentService(session)
    experiment = service.create_experiment(name="duration")
    pair = service.add_pair(
        experiment.experiment_id,
        scene_snapshot_hash="duration_snapshot",
        treatment_text="T",
        control_text="C",
    )
    for invalid in (-1, 1.5, True):
        with pytest.raises(DomainError) as error:
            service.record_vote(pair.pair_id, choice="left", duration_ms=invalid)
        assert error.value.code == "INVALID_VOTE_DURATION"
