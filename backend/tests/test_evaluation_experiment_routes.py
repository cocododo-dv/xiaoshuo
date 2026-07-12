"""Wave 5 — evaluation-experiments 路由（§6.3）：建实验/加对/盲化取对/投票/报告。

盲化契约的核心 API 断言：next-pair 响应体只含 pair_id + 左右纯文本，不泄漏映射/token/快照哈希。
"""
from __future__ import annotations


import uuid


def _create(client, **kw):
    body = {"name": "BoN vs 单发", "treatment_policy": {"best_of_n": True}, **kw}
    r = client.post("/api/v1/evaluation-experiments", json=body,
                    headers={"X-Idempotency-Key": f"exp-{uuid.uuid4().hex}"})
    assert r.status_code == 200, r.text
    return r.json()["data"]


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


def test_next_pair_response_leaks_no_metadata(client) -> None:
    exp = _create(client)
    _add_pair(client, exp["experiment_id"], "h1", "TREAT", "CTRL",
              token_cost={"treatment": 5000, "control": 1000})
    r = client.get(f"/api/v1/evaluation-experiments/{exp['experiment_id']}/next-pair",
                   params={"reviewer_ref": "u1"})
    assert r.status_code == 200, r.text
    view = r.json()["data"]
    assert set(view.keys()) == {"pair_id", "left_text", "right_text"}
    blob = r.text
    assert "treatment_slot" not in blob and "blind_mapping" not in blob
    assert "scene_snapshot_hash" not in blob and "token_cost" not in blob


def test_next_pair_empty_when_all_voted(client) -> None:
    exp = _create(client)
    pair = _add_pair(client, exp["experiment_id"], "h1", "a", "b")
    _vote(client, pair['pair_id'], "left", duration_ms=400)
    r = client.get(f"/api/v1/evaluation-experiments/{exp['experiment_id']}/next-pair",
                   params={"reviewer_ref": "u1"})
    assert r.json()["data"] is None


def test_vote_idempotent_replay(client) -> None:
    exp = _create(client)
    pair = _add_pair(client, exp["experiment_id"], "h1", "a", "b")
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
    exp = _create(client)
    exp_id = exp["experiment_id"]
    # 30 组、30 个互异快照，模拟盲评 21 胜 treatment。
    for i in range(30):
        pair = _add_pair(client, exp_id, f"snap_{i:03d}", f"T{i}", f"C{i}",
                         token_cost={"treatment": 5000, "control": 1000})
        # 从盲化视图无法知道哪边是 treatment；这里用报告前的服务端事实构造投票：
        # 直接投 left/right，令恰好 21 对命中 treatment。用 report 折叠核对。
        r = client.get(f"/api/v1/evaluation-experiments/{exp_id}/next-pair",
                       params={"reviewer_ref": "u1"})
        # 测试侧借 DB 事实决定投票（真实用户是盲的；此处仅验证折叠与判据可复算）
        choice = _treatment_side(client, pair["pair_id"]) if i < 21 else _control_side(client, pair["pair_id"])
        _vote(client, pair["pair_id"], choice)
    r = client.get(f"/api/v1/evaluation-experiments/{exp_id}/report")
    report = r.json()["data"]
    assert report["non_tie_n"] == 30
    assert report["treatment_wins"] == 21
    assert report["p_value"] < 0.05
    assert report["decision"] == "upgrade_to_default"
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
