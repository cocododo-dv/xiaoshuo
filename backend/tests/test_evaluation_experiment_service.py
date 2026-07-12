"""Wave 5 — 实验服务：建实验/加对/盲化取对/投票/可复算报告（§6.2 / §9.4）。"""
from __future__ import annotations

import pytest

from novel_system.services.errors import DomainError
from novel_system.services.evaluation_experiment import EvaluationExperimentService


def _svc(session):
    return EvaluationExperimentService(session)


def _seed_30_pairs(svc, exp_id, *, treatment_pref: bool = True, wins: int = 21, ties: int = 0):
    """建 30 对（30 个互异快照），模拟：wins 对选 treatment、其余选 control、ties 对平局。"""
    left_control = 0
    for i in range(30):
        pair = svc.add_pair(
            exp_id, scene_snapshot_hash=f"snap_{i:03d}",
            treatment_text=f"T{i}", control_text=f"C{i}",
        )
        slot = pair.blind_mapping_json["treatment_slot"]  # "left"|"right"
        if i < ties:
            choice = "tie"
        elif (i - ties) < wins:
            choice = slot                                 # 选中 treatment
        else:
            choice = "right" if slot == "left" else "left"  # 选中 control
        svc.record_vote(pair.pair_id, choice=choice, reviewer_ref="u1", duration_ms=1000)


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
    exp = svc.create_experiment(name="x")
    svc.add_pair(exp.experiment_id, scene_snapshot_hash="h1",
                 treatment_text="TREAT", control_text="CTRL",
                 token_cost={"treatment": 5000, "control": 1000})
    session.commit()
    view = svc.next_pair(exp.experiment_id, reviewer_ref="u1")
    assert set(view.keys()) == {"pair_id", "left_text", "right_text"}   # 只出这三键
    assert "treatment_slot" not in view and "blind_mapping" not in view
    assert "token_cost" not in view and "scene_snapshot_hash" not in view


def test_next_pair_advances_and_exhausts(session) -> None:
    svc = _svc(session)
    exp = svc.create_experiment(name="x")
    p = svc.add_pair(exp.experiment_id, scene_snapshot_hash="h1",
                     treatment_text="a", control_text="b")
    session.commit()
    v1 = svc.next_pair(exp.experiment_id, reviewer_ref="u1")
    assert v1["pair_id"] == p.pair_id
    svc.record_vote(p.pair_id, choice="left", reviewer_ref="u1", duration_ms=500)
    assert svc.next_pair(exp.experiment_id, reviewer_ref="u1") is None   # 投完无剩


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
    exp = svc.create_experiment(name="x")
    p = svc.add_pair(exp.experiment_id, scene_snapshot_hash="h1",
                     treatment_text="a", control_text="b")
    v1 = svc.record_vote(p.pair_id, choice="left", reviewer_ref="u1", duration_ms=500)
    v2 = svc.record_vote(p.pair_id, choice="left", reviewer_ref="u1", duration_ms=999)
    assert v1.vote_id == v2.vote_id            # 幂等，不双计


def test_record_vote_rejects_changed_choice(session) -> None:
    svc = _svc(session)
    exp = svc.create_experiment(name="x")
    p = svc.add_pair(exp.experiment_id, scene_snapshot_hash="h1",
                     treatment_text="a", control_text="b")
    svc.record_vote(p.pair_id, choice="left", reviewer_ref="u1")
    with pytest.raises(DomainError) as ei:
        svc.record_vote(p.pair_id, choice="right", reviewer_ref="u1")
    assert ei.value.code == "VOTE_ALREADY_RECORDED"


def test_report_upgrade_on_21_of_30(session) -> None:
    svc = _svc(session)
    exp = svc.create_experiment(name="BoN", treatment_policy={"best_of_n": True})
    _seed_30_pairs(svc, exp.experiment_id, wins=21, ties=0)
    session.commit()
    report = svc.build_report(exp.experiment_id)
    assert report["non_tie_n"] == 30
    assert report["treatment_wins"] == 21
    assert report["preference_rate"] == pytest.approx(0.70, abs=1e-2)
    assert report["p_value"] < 0.05
    assert report["decision"] == "upgrade_to_default"
    assert report["distinct_snapshot_count"] == 30       # 30 组来自 30 个互异快照
    assert report["pseudo_replication_ok"] is True


def test_report_keep_optional_on_20_of_30(session) -> None:
    svc = _svc(session)
    exp = svc.create_experiment(name="BoN")
    _seed_30_pairs(svc, exp.experiment_id, wins=20, ties=0)
    session.commit()
    report = svc.build_report(exp.experiment_id)
    assert report["decision"] == "keep_optional"


def test_report_ties_recorded_not_in_denominator(session) -> None:
    svc = _svc(session)
    exp = svc.create_experiment(name="BoN")
    # 5 平局 + 21 treatment 胜 + 4 control：非平局 n=25
    _seed_30_pairs(svc, exp.experiment_id, wins=21, ties=5)
    session.commit()
    report = svc.build_report(exp.experiment_id)
    assert report["ties"] == 5
    assert report["non_tie_n"] == 25


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
    assert r1["decision"] == "upgrade_to_default"
    assert r1["p_value"] < 0.05
    assert r1["token_multiplier"] == 5.0
    assert r1["distinct_snapshot_count"] == 30
