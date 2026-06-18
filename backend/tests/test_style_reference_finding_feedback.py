"""立项 B — finding 用户反馈聚合 → confidence 持续校准 测试。

服务级(apply_feedback,确定性):持久化 / 一人一票幂等 / 改向 / 升降档 / clamp /
基线可逆 / 404 / 非法 vote。路由级:端点 200 + 幂等键契约。
"""

from __future__ import annotations

import pytest

from novel_system.db.session import SessionLocal
from novel_system.services.errors import DomainError
from novel_system.services.style_reference.finding_feedback import (
    apply_feedback,
    shift_confidence,
)
from novel_system.services.style_reference.repository import StyleReferenceRepository

ADMIN_HEADERS = {"X-Admin-Token": "admin-token"}


def _seed_finding(session, *, seed="f1", confidence="medium", finding_kind="observation"):
    repo = StyleReferenceRepository(session)
    book, run, ext = f"book_{seed}", f"run_{seed}", f"ext_{seed}"
    fid = f"finding_{seed}"
    repo.create_book(
        book_id=book, title="t", source_kind="upload", cloud_policy="allow_full_cloud",
        text_checksum=f"chk_{seed}", total_chars=10, status="ready", stats_json={},
    )
    repo.create_run(run_id=run, book_id=book, status="done", phase="done")
    repo.create_extraction(
        extraction_id=ext, book_id=book, run_id=run,
        layer="language", sub_dimension="language.sentence_structure", status="done",
    )
    repo.create_finding(
        finding_id=fid, book_id=book, run_id=run, extraction_id=ext,
        sub_dimension="language.sentence_structure", finding_kind=finding_kind,
        statement=f"测试 finding {seed}", confidence=confidence,
    )
    session.flush()
    return fid


# --------------------------------------------------------------------------- 纯函数 shift


def test_shift_confidence_promote_demote_clamp():
    assert shift_confidence("medium", 2, promote_net=2, demote_net=-2) == "high"
    assert shift_confidence("medium", -2, promote_net=2, demote_net=-2) == "low"
    assert shift_confidence("medium", 0, promote_net=2, demote_net=-2) == "medium"
    assert shift_confidence("high", 2, promote_net=2, demote_net=-2) == "high"   # 封顶
    assert shift_confidence("low", -2, promote_net=2, demote_net=-2) == "low"    # 触底
    assert shift_confidence("medium", 1, promote_net=2, demote_net=-2) == "medium"  # 未达阈值
    assert shift_confidence(None, 2, promote_net=2, demote_net=-2) == "high"     # None→medium 基线


# --------------------------------------------------------------------------- 服务级


def test_first_vote_persists_and_captures_base(session):
    fid = _seed_finding(session, seed="a", confidence="medium")
    out = apply_feedback(session, fid, operator_ref="u1", vote="up")
    assert out["net"] == 1 and out["up"] == 1 and out["down"] == 0
    assert out["base_confidence"] == "medium"
    assert out["confidence"] == "medium"  # net=1 未达 promote=2
    repo = StyleReferenceRepository(session)
    assert len(repo.list_finding_feedback(fid)) == 1
    assert repo.get_finding(fid).base_confidence == "medium"


def test_two_distinct_up_votes_promote(session):
    fid = _seed_finding(session, seed="b", confidence="medium")
    apply_feedback(session, fid, operator_ref="u1", vote="up")
    out = apply_feedback(session, fid, operator_ref="u2", vote="up")
    assert out["net"] == 2
    assert out["confidence"] == "high"
    assert StyleReferenceRepository(session).get_finding(fid).confidence == "high"


def test_two_distinct_down_votes_demote(session):
    fid = _seed_finding(session, seed="c", confidence="medium")
    apply_feedback(session, fid, operator_ref="u1", vote="down")
    out = apply_feedback(session, fid, operator_ref="u2", vote="down")
    assert out["net"] == -2 and out["confidence"] == "low"


def test_one_vote_per_operator_idempotent(session):
    fid = _seed_finding(session, seed="d")
    apply_feedback(session, fid, operator_ref="u1", vote="up")
    out = apply_feedback(session, fid, operator_ref="u1", vote="up")  # 同向重复
    assert out["net"] == 1 and out["up"] == 1  # 不重复计票
    assert len(StyleReferenceRepository(session).list_finding_feedback(fid)) == 1


def test_change_direction_updates_vote(session):
    fid = _seed_finding(session, seed="e")
    apply_feedback(session, fid, operator_ref="u1", vote="up")
    out = apply_feedback(session, fid, operator_ref="u1", vote="down")  # 改向
    assert out["net"] == -1 and out["up"] == 0 and out["down"] == 1
    assert len(StyleReferenceRepository(session).list_finding_feedback(fid)) == 1


def test_confidence_reversible_to_base(session):
    # 先 2 up 升到 high,再让两人改向 down(net=-2)→ 从基线 medium 降到 low;
    # 再各自改回 up(net=+2)→ 回升 high;net 回 0 → 复位基线 medium(可逆)。
    fid = _seed_finding(session, seed="f", confidence="medium")
    apply_feedback(session, fid, operator_ref="u1", vote="up")
    apply_feedback(session, fid, operator_ref="u2", vote="up")
    assert StyleReferenceRepository(session).get_finding(fid).confidence == "high"
    apply_feedback(session, fid, operator_ref="u1", vote="down")
    out = apply_feedback(session, fid, operator_ref="u2", vote="down")
    assert out["net"] == -2 and out["confidence"] == "low"
    apply_feedback(session, fid, operator_ref="u1", vote="up")
    out2 = apply_feedback(session, fid, operator_ref="u2", vote="up")
    assert out2["net"] == 2 and out2["confidence"] == "high"
    # base 始终保留为 medium(从未被覆盖)
    assert StyleReferenceRepository(session).get_finding(fid).base_confidence == "medium"


def test_clamp_does_not_exceed_bounds(session):
    fid = _seed_finding(session, seed="g", confidence="high")
    apply_feedback(session, fid, operator_ref="u1", vote="up")
    out = apply_feedback(session, fid, operator_ref="u2", vote="up")
    assert out["net"] == 2 and out["confidence"] == "high"  # 已 high,封顶


def test_apply_feedback_unknown_finding_404(session):
    with pytest.raises(DomainError) as exc:
        apply_feedback(session, "nope", operator_ref="u1", vote="up")
    assert exc.value.status_code == 404


def test_apply_feedback_invalid_vote_400(session):
    fid = _seed_finding(session, seed="h")
    with pytest.raises(DomainError) as exc:
        apply_feedback(session, fid, operator_ref="u1", vote="sideways")
    assert exc.value.status_code == 400


# --------------------------------------------------------------------------- 路由级


def _seed_finding_committed(seed="r1"):
    with SessionLocal() as s:
        fid = _seed_finding(s, seed=seed)
        s.commit()
    return fid


def test_route_user_feedback_ok_and_idempotent(client):
    fid = _seed_finding_committed("r1")
    headers = {**ADMIN_HEADERS, "X-Idempotency-Key": "fb-key-1", "X-Operator-Ref": "op_a"}
    r = client.post(
        f"/api/v2/style-reference/findings/{fid}/user-feedback",
        headers=headers, json={"vote": "up"},
    )
    assert r.status_code == 200, r.text
    data = r.json()["data"]
    assert data["vote"] == "up" and data["net"] == 1 and data["operator_ref"] == "op_a"
    # 幂等重放(同 key)→ 仍 200,不重复计票
    r2 = client.post(
        f"/api/v2/style-reference/findings/{fid}/user-feedback",
        headers=headers, json={"vote": "up"},
    )
    assert r2.status_code == 200
    d2 = r2.json()["data"]
    assert d2["net"] == 1 and d2["up"] == 1 and d2["down"] == 0  # 重放不翻倍


def test_route_user_feedback_requires_idempotency_key(client):
    fid = _seed_finding_committed("r2")
    r = client.post(
        f"/api/v2/style-reference/findings/{fid}/user-feedback",
        headers={**ADMIN_HEADERS, "X-Operator-Ref": "op_b"}, json={"vote": "up"},
    )
    assert r.status_code == 400  # IDEMPOTENCY_KEY_REQUIRED


# --------------------------------------------------------------------------- 审查补强


def test_fp_finding_vote_changes_confidence(session):
    # forbidden_pattern finding 投票与 observation 同等处理(后端不分 kind)
    fid = _seed_finding(session, seed="fp", confidence="medium", finding_kind="forbidden_pattern")
    apply_feedback(session, fid, operator_ref="u1", vote="up")
    out = apply_feedback(session, fid, operator_ref="u2", vote="up")
    assert out["net"] == 2 and out["confidence"] == "high"


def test_net_zero_reverts_to_base(session):
    # 一人 up 一人 down → net=0 → confidence 复位基线(可逆,清晰用例)
    fid = _seed_finding(session, seed="z", confidence="medium")
    apply_feedback(session, fid, operator_ref="u1", vote="up")
    out = apply_feedback(session, fid, operator_ref="u2", vote="down")
    assert out["net"] == 0 and out["confidence"] == "medium"
    assert StyleReferenceRepository(session).get_finding(fid).base_confidence == "medium"


def test_base_confidence_unchanged_on_subsequent_feedback(session):
    # 基线一旦固化不被后续反馈覆盖(即便 confidence 升档)
    fid = _seed_finding(session, seed="bc", confidence="medium")
    apply_feedback(session, fid, operator_ref="u1", vote="up")
    apply_feedback(session, fid, operator_ref="u2", vote="up")  # → high
    apply_feedback(session, fid, operator_ref="u3", vote="up")  # net=3,仍 high(±1 封顶)
    f = StyleReferenceRepository(session).get_finding(fid)
    assert f.base_confidence == "medium" and f.confidence == "high"


def test_deep_findings_returns_operator_user_vote(client):
    # 立项 B — 投票后深层 findings 按请求 operator 回显 user_vote(跨刷新持久);他人看不到
    fid = _seed_finding_committed("uv")  # run_id=run_uv, finding_id=finding_uv
    client.post(
        f"/api/v2/style-reference/findings/{fid}/user-feedback",
        headers={**ADMIN_HEADERS, "X-Idempotency-Key": "uv-1", "X-Operator-Ref": "op_a"},
        json={"vote": "up"},
    )
    r = client.get(
        "/api/v2/style-reference/runs/run_uv/findings?include=evidence",
        headers={**ADMIN_HEADERS, "X-Operator-Ref": "op_a"},
    )
    assert r.status_code == 200, r.text
    fa = next(x for x in r.json()["data"]["findings"] if x["finding_id"] == fid)
    assert fa["user_vote"] == "up"
    # 另一 operator 未投票 → 无 user_vote
    r2 = client.get(
        "/api/v2/style-reference/runs/run_uv/findings?include=evidence",
        headers={**ADMIN_HEADERS, "X-Operator-Ref": "op_b"},
    )
    fb = next(x for x in r2.json()["data"]["findings"] if x["finding_id"] == fid)
    assert fb.get("user_vote") is None


def test_purge_derived_data_deletes_feedback(session):
    from novel_system.services.style_reference.cleanup import purge_derived_data

    fid = _seed_finding(session, seed="pg")
    apply_feedback(session, fid, operator_ref="u1", vote="up")
    repo = StyleReferenceRepository(session)
    assert len(repo.list_finding_feedback(fid)) == 1
    purge_derived_data(session, "book_pg")
    assert repo.list_finding_feedback(fid) == []
