"""Wave 5 — evaluation-experiments 路由（§6.3）：建实验/加对/盲化取对/投票/报告。

盲化契约的核心 API 断言：next-pair 响应体只含 pair_id + 左右纯文本，不泄漏映射/token/快照哈希。

human-only 契约（迁移 20260717_0075 冻结）：evidence_provenance 只承认 'human'（payload
默认即 human，显式传 synthetic 直接 422）；人类证据纪律对全部实验生效——取对/投票
必须发生在题包冻结之后，故相关用例先凑满 30 对并冻结。
"""
from __future__ import annotations


import uuid


def _create(client, **kw):
    body = {"name": "BoN vs 单发", "treatment_policy": {"best_of_n": True}, **kw}
    r = client.post("/api/v1/evaluation-experiments", json=body,
                    headers={"X-Idempotency-Key": f"exp-{uuid.uuid4().hex}"})
    assert r.status_code == 200, r.text
    return r.json()["data"]


def _create_frozen(client, n_pairs=30, **kw):
    """human 实验（含冻结所需隔离登记）+ n_pairs 对 + 冻结题包。"""
    exp = _create(client, isolation_mode="seed_project",
                  snapshot_source_ref="project:seed", **kw)
    exp_id = exp["experiment_id"]
    pairs = [
        _add_pair(client, exp_id, f"snap_{i:03d}", f"T{i}", f"C{i}",
                  token_cost={"treatment": 5000, "control": 1000})
        for i in range(n_pairs)
    ]
    r = client.post(f"/api/v1/evaluation-experiments/{exp_id}/freeze", json={},
                    headers={"X-Idempotency-Key": f"freeze-{exp_id}"})
    assert r.status_code == 200, r.text
    return exp, pairs


def _vote(client, pair_id, choice, reviewer="u1", key=None, duration_ms=500):
    return client.post(
        f"/api/v1/evaluation-pairs/{pair_id}/vote",
        json={"choice": choice, "reviewer_ref": reviewer, "duration_ms": duration_ms},
        headers={"X-Idempotency-Key": key or f"vote-{pair_id}-{reviewer}"},
    )


def _add_pair(client, exp_id, snap, t, c, token_cost=None):
    r = client.post(
        f"/api/v1/evaluation-experiments/{exp_id}/pairs",
        json={"scene_snapshot_hash": snap, "treatment_text": t, "control_text": c,
              "token_cost": token_cost or {}},
        headers={"X-Idempotency-Key": f"pair-{exp_id}-{snap}"},
    )
    assert r.status_code == 200, r.text
    return r.json()["data"]


def test_create_experiment(client) -> None:
    data = _create(client, hypothesis="Best-of-N 提升偏好", isolation_mode="seed_project")
    assert data["experiment_id"]
    assert data["isolation_mode"] == "seed_project"
    assert data["evidence_provenance"] == "human"     # human-only 契约默认


def test_create_experiment_defaults_human_and_rejects_synthetic(client) -> None:
    """回归：默认 payload → human；显式 synthetic → 422（明确拒绝，而非落库时 500）。"""
    data = _create(client)
    assert data["evidence_provenance"] == "human"

    r = client.post(
        "/api/v1/evaluation-experiments",
        json={"name": "旧通道", "evidence_provenance": "synthetic"},
        headers={"X-Idempotency-Key": f"exp-{uuid.uuid4().hex}"},
    )
    assert r.status_code == 422, r.text
    assert r.json()["error"]["code"] == "REQUEST_VALIDATION_FAILED"


def test_next_pair_response_leaks_no_metadata(client) -> None:
    exp, _ = _create_frozen(client)
    r = client.get(f"/api/v1/evaluation-experiments/{exp['experiment_id']}/next-pair",
                   params={"reviewer_ref": "u1"})
    assert r.status_code == 200, r.text
    view = r.json()["data"]
    assert set(view.keys()) == {"pair", "done", "progress"}
    assert set(view["pair"].keys()) == {"pair_id", "left_text", "right_text"}
    assert view["progress"] == {"total_pairs": 30, "voted_pairs": 0, "remaining_pairs": 30}
    blob = r.text
    assert "treatment_slot" not in blob and "blind_mapping" not in blob
    assert "scene_snapshot_hash" not in blob and "token_cost" not in blob


def test_next_pair_requires_frozen_pool(client) -> None:
    """human-only 契约：冻结前取对 409（人类盲评题包必须先封存）。"""
    exp = _create(client, isolation_mode="seed_project", snapshot_source_ref="project:seed")
    _add_pair(client, exp["experiment_id"], "h1", "a", "b")
    r = client.get(f"/api/v1/evaluation-experiments/{exp['experiment_id']}/next-pair",
                   params={"reviewer_ref": "u1"})
    assert r.status_code == 409
    assert r.json()["error"]["code"] == "HUMAN_EVIDENCE_NOT_FROZEN"


def test_next_pair_empty_when_all_voted(client) -> None:
    exp, pairs = _create_frozen(client)
    for pair in pairs:
        r = _vote(client, pair["pair_id"], "left", duration_ms=400)
        assert r.status_code == 200, r.text
    r = client.get(f"/api/v1/evaluation-experiments/{exp['experiment_id']}/next-pair",
                   params={"reviewer_ref": "u1"})
    data = r.json()["data"]
    assert data["pair"] is None
    assert data["done"] is True
    assert data["progress"] == {"total_pairs": 30, "voted_pairs": 30, "remaining_pairs": 0}


def test_list_and_overview_endpoints(client) -> None:
    exp, pairs = _create_frozen(client, name="工作台清单实验")
    _vote(client, pairs[0]["pair_id"], "tie")

    r = client.get("/api/v1/evaluation-experiments")
    assert r.status_code == 200, r.text
    rows = r.json()["data"]
    row = next(x for x in rows if x["experiment_id"] == exp["experiment_id"])
    assert row["name"] == "工作台清单实验"
    assert row["total_pairs"] == 30 and row["voted_pairs"] == 1 and row["remaining_pairs"] == 29
    assert row["can_freeze"] is False      # 已冻结
    blob = r.text
    assert "treatment_slot" not in blob and "blind_mapping" not in blob and "token_cost" not in blob

    r2 = client.get(f"/api/v1/evaluation-experiments/{exp['experiment_id']}/overview")
    assert r2.status_code == 200, r2.text
    overview = r2.json()["data"]
    assert overview["voted_pairs"] == 1
    assert overview["treatment_policy"] == {"best_of_n": True}

    r3 = client.get("/api/v1/evaluation-experiments/exp_missing/overview")
    assert r3.status_code == 404
    assert r3.json()["error"]["code"] == "EXPERIMENT_NOT_FOUND"


def test_add_pair_scene_function_passthrough(client) -> None:
    exp = _create(client)
    r = client.post(
        f"/api/v1/evaluation-experiments/{exp['experiment_id']}/pairs",
        json={"scene_snapshot_hash": "sf1", "treatment_text": "a", "control_text": "b",
              "genre": "悬疑", "scene_function": "reveal"},
        headers={"X-Idempotency-Key": "pair-sf1"},
    )
    assert r.status_code == 200, r.text
    assert r.json()["data"]["scene_function"] == "reveal"

    bad = client.post(
        f"/api/v1/evaluation-experiments/{exp['experiment_id']}/pairs",
        json={"scene_snapshot_hash": "sf2", "treatment_text": "a", "control_text": "b",
              "scene_function": "not-a-tag"},
        headers={"X-Idempotency-Key": "pair-sf2"},
    )
    assert bad.status_code == 422
    assert bad.json()["error"]["code"] == "EVALUATION_SCENE_FUNCTION_INVALID"


def test_vote_idempotent_replay(client) -> None:
    _, pairs = _create_frozen(client)
    pair = pairs[0]
    hdr = {"X-Idempotency-Key": "vote-1"}
    r1 = client.post(f"/api/v1/evaluation-pairs/{pair['pair_id']}/vote",
                     json={"choice": "left", "reviewer_ref": "u1", "duration_ms": 400}, headers=hdr)
    r2 = client.post(f"/api/v1/evaluation-pairs/{pair['pair_id']}/vote",
                     json={"choice": "left", "reviewer_ref": "u1", "duration_ms": 400}, headers=hdr)
    assert r1.status_code == 200 and r2.status_code == 200
    assert r1.json()["data"]["vote_id"] == r2.json()["data"]["vote_id"]


def test_vote_invalid_choice_rejected(client) -> None:
    exp = _create(client)
    pair = _add_pair(client, exp["experiment_id"], "h1", "a", "b")
    r = _vote(client, pair['pair_id'], "middle")
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "INVALID_VOTE_CHOICE"


def test_duplicate_snapshot_rejected(client) -> None:
    exp = _create(client)
    _add_pair(client, exp["experiment_id"], "dup", "a", "b")
    r = client.post(
        f"/api/v1/evaluation-experiments/{exp['experiment_id']}/pairs",
        json={"scene_snapshot_hash": "dup", "treatment_text": "c", "control_text": "d"},
        headers={"X-Idempotency-Key": "pair-different-key"},
    )
    assert r.status_code == 409
    assert r.json()["error"]["code"] == "SNAPSHOT_ALREADY_USED"


def test_report_reproducible_verdict(client) -> None:
    # 30 组、30 个互异快照，冻结后模拟盲评 21 胜 treatment。
    exp, pairs = _create_frozen(client)
    exp_id = exp["experiment_id"]
    for i, pair in enumerate(pairs):
        # 从盲化视图无法知道哪边是 treatment；这里用报告前的服务端事实构造投票：
        # 直接投 left/right，令恰好 21 对命中 treatment。用 report 折叠核对。
        # （测试侧借 DB 事实决定投票；真实用户是盲的，此处仅验证折叠与判据可复算）
        choice = _treatment_side(client, pair["pair_id"]) if i < 21 else _control_side(client, pair["pair_id"])
        r = _vote(client, pair["pair_id"], choice)
        assert r.status_code == 200, r.text
    r = client.get(f"/api/v1/evaluation-experiments/{exp_id}/report")
    report = r.json()["data"]
    assert report["evidence_provenance"] == "human"
    assert report["non_tie_n"] == 30
    assert report["treatment_wins"] == 21
    assert report["p_value"] < 0.05
    assert report["statistical_decision"] == "upgrade_to_default"
    assert report["decision"] == "not_eligible_for_policy"
    assert report["policy_evidence_eligible"] is False
    assert report["distinct_snapshot_count"] == 30
    assert report["token_cost"]["token_multiplier"] == 5.0


# --- 测试辅助：从 DB 读隐藏键决定投票（真实用户是盲的，此处仅为构造可核对的投票） ---
def _treatment_side(client, pair_id: str) -> str:
    from novel_system.db.session import SessionLocal
    from novel_system.db.models import EvaluationPair
    s = SessionLocal()
    try:
        return s.get(EvaluationPair, pair_id).blind_mapping_json["treatment_slot"]
    finally:
        s.close()


def _control_side(client, pair_id: str) -> str:
    return "right" if _treatment_side(client, pair_id) == "left" else "left"
