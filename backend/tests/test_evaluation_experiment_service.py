"""Wave 5 — 实验服务：建实验/加对/盲化取对/投票/可复算报告（§6.2 / §9.4）。

human-only 契约（迁移 20260717_0075 冻结）：evidence_provenance 只承认 'human'，
默认即 human；synthetic 通道已废除（服务层 422 + 库侧 CHECK）。因此人类证据纪律
（先冻结题包、真人 reviewer）对所有新建实验生效——投票类用例一律先凑满 30 对并冻结。
"""
from __future__ import annotations

import pytest

from novel_system.services.errors import DomainError
from novel_system.services.evaluation_experiment import EvaluationExperimentService


def _svc(session):
    return EvaluationExperimentService(session)


def _human_exp(svc, name="x", **kw):
    """默认（human）实验 + 冻结所需的隔离登记（§6.2）。"""
    kw.setdefault("isolation_mode", "seed_project")
    kw.setdefault("snapshot_source_ref", "project:seed")
    return svc.create_experiment(name=name, **kw)


def _add_30_pairs(svc, exp_id, *, text_prefix=("T", "C")):
    t, c = text_prefix
    return [
        svc.add_pair(
            exp_id, scene_snapshot_hash=f"snap_{i:03d}",
            treatment_text=f"{t}{i}", control_text=f"{c}{i}",
        )
        for i in range(30)
    ]


def _seed_30_pairs(svc, exp_id, *, wins: int = 21, ties: int = 0):
    """建 30 对（30 个互异快照）→ 冻结 → 投票：wins 对选 treatment、其余选 control、
    ties 对平局。human-only 契约下投票必须发生在冻结之后。"""
    votes = []
    for i, pair in enumerate(_add_30_pairs(svc, exp_id)):
        slot = pair.blind_mapping_json["treatment_slot"]  # "left"|"right"
        if i < ties:
            choice = "tie"
        elif (i - ties) < wins:
            choice = slot                                 # 选中 treatment
        else:
            choice = "right" if slot == "left" else "left"  # 选中 control
        votes.append((pair.pair_id, choice))
    svc.freeze_experiment(exp_id)
    for pair_id, choice in votes:
        svc.record_vote(pair_id, choice=choice, reviewer_ref="u1", duration_ms=1000)


def test_create_experiment_persists(session) -> None:
    svc = _svc(session)
    exp = svc.create_experiment(
        name="BoN vs 单发", hypothesis="Best-of-N 终选提升偏好",
        treatment_policy={"best_of_n": True}, control_policy={"best_of_n": False},
        isolation_mode="seed_project", snapshot_source_ref="proj_eval_seed",
    )
    session.commit()
    assert exp.experiment_id
    assert exp.treatment_policy_json["best_of_n"] is True
    assert exp.isolation_mode == "seed_project"
    assert exp.evidence_provenance == "human"     # human-only 契约默认


def test_create_experiment_rejects_synthetic_provenance(session) -> None:
    svc = _svc(session)
    with pytest.raises(DomainError) as ei:
        svc.create_experiment(name="x", evidence_provenance="synthetic")
    assert ei.value.code == "INVALID_EVIDENCE_PROVENANCE"
    assert ei.value.status_code == 422


def test_add_pair_blinds_and_records_hidden_key(session) -> None:
    svc = _svc(session)
    exp = svc.create_experiment(name="x")
    pair = svc.add_pair(exp.experiment_id, scene_snapshot_hash="h1",
                        treatment_text="TREAT", control_text="CTRL")
    session.commit()
    slot = pair.blind_mapping_json["treatment_slot"]
    assert slot in ("left", "right")
    treatment_text = pair.left_text if slot == "left" else pair.right_text
    assert treatment_text == "TREAT"
    assert pair.no_contrast == 0


def test_add_pair_no_contrast_when_identical(session) -> None:
    svc = _svc(session)
    exp = svc.create_experiment(name="x")
    pair = svc.add_pair(exp.experiment_id, scene_snapshot_hash="h1",
                        treatment_text="SAME", control_text="SAME")
    assert pair.no_contrast == 1


def test_add_pair_rejects_duplicate_snapshot(session) -> None:
    svc = _svc(session)
    exp = svc.create_experiment(name="x")
    svc.add_pair(exp.experiment_id, scene_snapshot_hash="dup",
                 treatment_text="a", control_text="b")
    with pytest.raises(DomainError) as ei:
        svc.add_pair(exp.experiment_id, scene_snapshot_hash="dup",
                     treatment_text="c", control_text="d")
    assert ei.value.code == "SNAPSHOT_ALREADY_USED"


def test_next_pair_leaks_no_metadata(session) -> None:
    svc = _svc(session)
    exp = _human_exp(svc)
    _add_30_pairs(svc, exp.experiment_id, text_prefix=("TREAT", "CTRL"))
    # human 证据：冻结前取对即拒绝。
    with pytest.raises(DomainError) as unfrozen:
        svc.next_pair(exp.experiment_id, reviewer_ref="u1")
    assert unfrozen.value.code == "HUMAN_EVIDENCE_NOT_FROZEN"
    svc.freeze_experiment(exp.experiment_id)
    session.commit()
    view = svc.next_pair(exp.experiment_id, reviewer_ref="u1")
    assert set(view.keys()) == {"pair", "done", "progress"}
    assert set(view["pair"].keys()) == {"pair_id", "left_text", "right_text"}   # 盲化视图只出这三键
    assert set(view["progress"].keys()) == {"total_pairs", "voted_pairs", "remaining_pairs"}
    import json as _json
    blob = _json.dumps(view, ensure_ascii=False)
    assert "treatment_slot" not in blob and "blind_mapping" not in blob
    assert "token_cost" not in blob and "scene_snapshot_hash" not in blob


def test_next_pair_advances_and_exhausts(session) -> None:
    svc = _svc(session)
    exp = _human_exp(svc)
    _add_30_pairs(svc, exp.experiment_id, text_prefix=("a", "b"))
    svc.freeze_experiment(exp.experiment_id)
    session.commit()
    v1 = svc.next_pair(exp.experiment_id, reviewer_ref="u1")
    assert v1["done"] is False
    assert v1["progress"] == {"total_pairs": 30, "voted_pairs": 0, "remaining_pairs": 30}
    first_pair_id = v1["pair"]["pair_id"]
    svc.record_vote(first_pair_id, choice="left", reviewer_ref="u1", duration_ms=500)
    v2 = svc.next_pair(exp.experiment_id, reviewer_ref="u1")   # 已投对被跳过
    assert v2["pair"]["pair_id"] != first_pair_id
    assert v2["progress"] == {"total_pairs": 30, "voted_pairs": 1, "remaining_pairs": 29}
    while True:                                                # 投完全部后耗尽
        view = svc.next_pair(exp.experiment_id, reviewer_ref="u1")
        if view["pair"] is None:
            break
        svc.record_vote(view["pair"]["pair_id"], choice="left", reviewer_ref="u1")
    exhausted = svc.next_pair(exp.experiment_id, reviewer_ref="u1")
    assert exhausted["pair"] is None
    assert exhausted["done"] is True
    assert exhausted["progress"] == {"total_pairs": 30, "voted_pairs": 30, "remaining_pairs": 0}


def test_list_experiments_and_overview_progress(session) -> None:
    svc = _svc(session)
    other = svc.create_experiment(name="较早的实验")
    svc.add_pair(other.experiment_id, scene_snapshot_hash="o1", treatment_text="a", control_text="b")
    exp = _human_exp(svc, name="进行中的实验", hypothesis="BoN 更好",
                     experiment_id="exp_zzz_newest")
    pairs = _add_30_pairs(svc, exp.experiment_id)
    svc.add_pair(exp.experiment_id, scene_snapshot_hash="same", treatment_text="SAME", control_text="SAME")
    svc.freeze_experiment(exp.experiment_id)
    svc.record_vote(pairs[0].pair_id, choice="tie", reviewer_ref="u1")
    session.commit()

    listing = svc.list_experiments()
    assert [row["name"] for row in listing][0] == "进行中的实验"   # 新建在前
    row = next(r for r in listing if r["experiment_id"] == exp.experiment_id)
    assert row["total_pairs"] == 31 and row["contrastive_pairs"] == 30
    assert row["voted_pairs"] == 1 and row["remaining_pairs"] == 30
    assert row["can_freeze"] is False and row["freeze_required_contrastive"] == 30   # 已冻结
    # 摘要不含盲化隐藏键
    import json as _json
    blob = _json.dumps(listing, ensure_ascii=False)
    assert "treatment_slot" not in blob and "blind_mapping" not in blob and "token_cost" not in blob

    overview = svc.experiment_overview(exp.experiment_id)
    assert overview["voted_pairs"] == 1 and overview["total_pairs"] == 31
    assert overview["treatment_policy"] == {} and "frozen_pair_manifest_hash" in overview

    with pytest.raises(DomainError) as missing:
        svc.experiment_overview("exp_missing")
    assert missing.value.code == "EXPERIMENT_NOT_FOUND"


def test_record_vote_rejects_bad_choice(session) -> None:
    svc = _svc(session)
    exp = svc.create_experiment(name="x")
    p = svc.add_pair(exp.experiment_id, scene_snapshot_hash="h1",
                     treatment_text="a", control_text="b")
    with pytest.raises(DomainError) as ei:
        svc.record_vote(p.pair_id, choice="middle", reviewer_ref="u1")
    assert ei.value.code == "INVALID_VOTE_CHOICE"


def test_record_vote_idempotent_same_choice(session) -> None:
    svc = _svc(session)
    exp = _human_exp(svc)
    pairs = _add_30_pairs(svc, exp.experiment_id, text_prefix=("a", "b"))
    svc.freeze_experiment(exp.experiment_id)
    p = pairs[0]
    v1 = svc.record_vote(p.pair_id, choice="left", reviewer_ref="u1", duration_ms=500)
    v2 = svc.record_vote(p.pair_id, choice="left", reviewer_ref="u1", duration_ms=999)
    assert v1.vote_id == v2.vote_id            # 幂等，不双计


def test_record_vote_rejects_changed_choice(session) -> None:
    svc = _svc(session)
    exp = _human_exp(svc)
    pairs = _add_30_pairs(svc, exp.experiment_id, text_prefix=("a", "b"))
    svc.freeze_experiment(exp.experiment_id)
    p = pairs[0]
    svc.record_vote(p.pair_id, choice="left", reviewer_ref="u1")
    with pytest.raises(DomainError) as ei:
        svc.record_vote(p.pair_id, choice="right", reviewer_ref="u1")
    assert ei.value.code == "VOTE_ALREADY_RECORDED"


def test_default_human_report_statistics_on_21_of_30(session) -> None:
    """21/30 过统计门；但缺隐藏题包 → 仍非策略证据（synthetic 路径已在建实验时 422）。"""
    svc = _svc(session)
    exp = _human_exp(svc, name="BoN", treatment_policy={"best_of_n": True})
    _seed_30_pairs(svc, exp.experiment_id, wins=21, ties=0)
    session.commit()
    report = svc.build_report(exp.experiment_id)
    assert report["evidence_provenance"] == "human"
    assert report["non_tie_n"] == 30
    assert report["treatment_wins"] == 21
    assert report["preference_rate"] == pytest.approx(0.70, abs=1e-2)
    assert report["p_value"] < 0.05
    assert report["statistical_decision"] == "upgrade_to_default"
    assert report["decision"] == "not_eligible_for_policy"
    assert report["policy_evidence_eligible"] is False
    assert "evidence_provenance_not_human" not in report["policy_eligibility_reasons"]
    assert "hidden_benchmark_manifest_not_verified" in report["policy_eligibility_reasons"]
    assert report["distinct_snapshot_count"] == 30       # 30 组来自 30 个互异快照
    assert report["pseudo_replication_ok"] is True


def test_report_keep_optional_on_20_of_30(session) -> None:
    svc = _svc(session)
    exp = _human_exp(svc, name="BoN")
    _seed_30_pairs(svc, exp.experiment_id, wins=20, ties=0)
    session.commit()
    report = svc.build_report(exp.experiment_id)
    assert report["statistical_decision"] == "keep_optional"
    assert report["decision"] == "not_eligible_for_policy"


def test_report_ties_recorded_not_in_denominator(session) -> None:
    svc = _svc(session)
    exp = _human_exp(svc, name="BoN")
    # 5 平局 + 21 treatment 胜 + 4 control：非平局 n=25
    _seed_30_pairs(svc, exp.experiment_id, wins=21, ties=5)
    session.commit()
    report = svc.build_report(exp.experiment_id)
    assert report["ties"] == 5
    assert report["non_tie_n"] == 25


def test_human_frozen_report_without_hidden_manifest_is_not_policy_evidence(session) -> None:
    svc = _svc(session)
    exp = svc.create_experiment(
        name="BoN 真人盲评",
        treatment_policy={"best_of_n": True},
        control_policy={"best_of_n": False},
        evidence_provenance="human",
        isolation_mode="seed_project",
        snapshot_source_ref="project:blind-eval-seed-v1",
    )
    _seed_30_pairs(svc, exp.experiment_id, wins=21)
    session.commit()

    report = svc.build_report(exp.experiment_id)

    assert report["frozen_manifest_verified"] is True
    assert report["policy_evidence_eligible"] is False
    assert "hidden_benchmark_manifest_not_verified" in report["policy_eligibility_reasons"]
    assert report["decision"] == "not_eligible_for_policy"


def test_human_vote_requires_frozen_pool_and_reviewer(session) -> None:
    svc = _svc(session)
    exp = svc.create_experiment(
        name="human",
        evidence_provenance="human",
        isolation_mode="seed_project",
        snapshot_source_ref="project:seed",
    )
    first = None
    for i in range(30):
        pair = svc.add_pair(
            exp.experiment_id,
            scene_snapshot_hash=f"human_{i}",
            treatment_text=f"T{i}",
            control_text=f"C{i}",
        )
        first = first or pair
    with pytest.raises(DomainError) as before_freeze:
        svc.record_vote(first.pair_id, choice="left", reviewer_ref="u1")
    assert before_freeze.value.code == "HUMAN_EVIDENCE_NOT_FROZEN"

    svc.freeze_experiment(exp.experiment_id)
    with pytest.raises(DomainError) as missing_reviewer:
        svc.record_vote(first.pair_id, choice="left")
    assert missing_reviewer.value.code == "HUMAN_REVIEWER_REQUIRED"
    with pytest.raises(DomainError) as automated_reviewer:
        svc.record_vote(first.pair_id, choice="left", reviewer_ref="model:gpt")
    assert automated_reviewer.value.code == "HUMAN_REVIEWER_REQUIRED"


def test_freeze_rejects_small_pool_and_blocks_later_pairs(session) -> None:
    svc = _svc(session)
    exp = _human_exp(svc, name="small")
    svc.add_pair(exp.experiment_id, scene_snapshot_hash="one", treatment_text="T", control_text="C")
    with pytest.raises(DomainError) as too_small:
        svc.freeze_experiment(exp.experiment_id)
    assert too_small.value.code == "EVALUATION_POOL_TOO_SMALL"

    for i in range(1, 30):
        svc.add_pair(exp.experiment_id, scene_snapshot_hash=f"snap_{i}", treatment_text=f"T{i}", control_text=f"C{i}")
    svc.freeze_experiment(exp.experiment_id)
    with pytest.raises(DomainError) as frozen:
        svc.add_pair(exp.experiment_id, scene_snapshot_hash="late", treatment_text="T", control_text="C")
    assert frozen.value.code == "EXPERIMENT_FROZEN"


def test_freeze_default_experiment_requires_isolation_registration(session) -> None:
    """默认实验即 human：不登记隔离（isolation_mode/snapshot_source_ref）就不能冻结。"""
    svc = _svc(session)
    exp = svc.create_experiment(name="no-isolation")
    for i in range(30):
        svc.add_pair(exp.experiment_id, scene_snapshot_hash=f"iso_{i}",
                     treatment_text=f"T{i}", control_text=f"C{i}")
    with pytest.raises(DomainError) as ei:
        svc.freeze_experiment(exp.experiment_id)
    assert ei.value.code == "HUMAN_EVIDENCE_ISOLATION_REQUIRED"


# ===========================================================================
# Wave 5 — 可复算报告 CLI 工具（纯离线 report_from_pairs）
# ===========================================================================

def test_tool_report_from_pairs_reproducible() -> None:
    from novel_system.tools.evaluation_experiment_report import report_from_pairs

    pairs = []
    for i in range(30):
        slot = "left" if i % 2 == 0 else "right"
        vote = slot if i < 21 else ("right" if slot == "left" else "left")
        pairs.append({
            "blind_mapping": {"treatment_slot": slot},
            "no_contrast": False,
            "vote": vote,
            "scene_snapshot_hash": f"snap_{i:03d}",
            "token_cost": {"treatment": 5000, "control": 1000},
        })
    r1 = report_from_pairs(pairs)
    r2 = report_from_pairs(pairs)
    assert r1 == r2                                   # 同输入同输出（可复算）
    assert r1["treatment_wins"] == 21
    assert r1["non_tie_n"] == 30
    assert r1["statistical_decision"] == "upgrade_to_default"
    assert r1["decision"] == "not_eligible_for_policy"
    assert r1["p_value"] < 0.05
    assert r1["token_multiplier"] == 5.0
    assert r1["distinct_snapshot_count"] == 30


# ===========================================================================
# 分题材差异 + Wilson 置信区间 + 题材标签进入冻结清单（防赛后改标签）
# ===========================================================================

def test_report_includes_wilson_ci_and_genre_breakdown(session) -> None:
    svc = _svc(session)
    exp = _human_exp(svc, name="genre")
    genres = ["悬疑", "悬疑", "悬疑", "都市", "都市", None]
    labeled_pairs = []
    for i, genre in enumerate(genres):
        labeled_pairs.append(svc.add_pair(
            exp.experiment_id, scene_snapshot_hash=f"snap_{i}",
            treatment_text=f"T{i}", control_text=f"C{i}", genre=genre,
        ))
    for i in range(len(genres), 30):                 # 补足冻结所需 30 对（保持未投）
        svc.add_pair(exp.experiment_id, scene_snapshot_hash=f"snap_{i}",
                     treatment_text=f"T{i}", control_text=f"C{i}")
    svc.freeze_experiment(exp.experiment_id)
    for pair, genre in zip(labeled_pairs, genres):
        slot = pair.blind_mapping_json["treatment_slot"]
        if genre == "悬疑":
            choice = slot                                    # treatment 胜
        elif genre == "都市":
            choice = "right" if slot == "left" else "left"   # control 胜
        else:
            choice = "tie"
        svc.record_vote(pair.pair_id, choice=choice, reviewer_ref="u1")
    report = svc.build_report(exp.experiment_id)
    assert report["by_genre"]["悬疑"] == {
        "voted_pairs": 3, "treatment_wins": 3, "control_wins": 0, "ties": 0,
        "non_tie_n": 3, "preference_rate": 1.0,
    }
    assert report["by_genre"]["都市"]["preference_rate"] == 0.0
    assert report["by_genre"]["unlabeled"]["ties"] == 1
    ci = report["preference_ci95"]                # 3/5 非平局票
    assert ci["low"] == pytest.approx(0.2307, abs=2e-3)
    assert ci["high"] == pytest.approx(0.8824, abs=2e-3)


def test_wilson_ci_saturates_on_30_straight_wins(session) -> None:
    svc = _svc(session)
    exp = _human_exp(svc, name="ci30")
    _seed_30_pairs(svc, exp.experiment_id, wins=30)
    ci = svc.build_report(exp.experiment_id)["preference_ci95"]
    assert ci["low"] > 0.85
    assert ci["high"] == 1.0


def test_frozen_manifest_detects_genre_tampering(session) -> None:
    svc = _svc(session)
    exp = _human_exp(svc, name="tamper")
    pairs = [
        svc.add_pair(exp.experiment_id, scene_snapshot_hash=f"snap_{i}",
                     treatment_text=f"T{i}", control_text=f"C{i}", genre="悬疑")
        for i in range(30)
    ]
    svc.freeze_experiment(exp.experiment_id)
    pairs[0].genre = "都市"
    session.flush()
    with pytest.raises(DomainError) as tampered:
        svc.freeze_experiment(exp.experiment_id)
    assert tampered.value.code == "EXPERIMENT_MANIFEST_TAMPERED"
    assert svc.build_report(exp.experiment_id)["frozen_manifest_verified"] is False
