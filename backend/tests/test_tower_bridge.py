"""FE-ALIGN Phase 7: 控制塔桥（裁决同源 / onceTask dedupe / 归档写回）。"""
from __future__ import annotations

from novel_system.db.models import ChapterAuditFinding

_seq = 0


def _post(client, path, body=None, expect=200):
    global _seq
    _seq += 1
    response = client.post(path, json=body or {}, headers={"X-Idempotency-Key": f"tb-{_seq}"})
    assert response.status_code == expect, response.text
    return response.json()["data"] if expect == 200 else response.json()


def _create_project(client) -> str:
    global _seq
    _seq += 1
    response = client.post(
        "/api/v2/projects",
        json={"title": f"塔桥测试 {_seq}", "outline_text": "大纲"},
        headers={"X-Idempotency-Key": f"tb-create-{_seq}"},
    )
    assert response.status_code == 200, response.text
    return response.json()["data"]["project"]["project_id"]


def _chapter(client, pid) -> str:
    return _post(client, f"/api/v2/projects/{pid}/catalog/chapters", {"title": "测试章"})["chapter"]["chapter_id"]


def test_finding_creates_canon_card_same_transaction(client):
    pid = _create_project(client)
    cid = _chapter(client, pid)
    finding = _post(
        client,
        f"/api/v2/projects/{pid}/longform/chapters/{cid}/audit",
        {
            "kind": "drift", "severity": "block",
            "text": "第 5 章「还在念中学」与第 1 章「28 岁」冲突",
            "meta": {"subject": "林岑 · 年龄", "value": "28 岁", "source": 1, "drift": True},
        },
    )
    items = client.get(f"/api/v1/review-items?state=open&project_id={pid}").json()["data"]["items"]
    card = next(i for i in items if i.get("dedupe_key") == f"canon:{finding['finding_id']}")
    assert card["kind"] == "risk"  # drift → risk
    assert card["priority"] == 1
    assert any(a.get("effect", {}).get("type") == "rule_canon" for a in card["actions"])
    assert "统一为「28 岁」" in card["actions"][0]["label"]


def test_resolve_card_rule_canon_adjudicates_finding(client, session):
    pid = _create_project(client)
    cid = _chapter(client, pid)
    finding = _post(
        client,
        f"/api/v2/projects/{pid}/longform/chapters/{cid}/audit",
        {"kind": "drift", "severity": "warn", "text": "盐钟材质冲突",
         "meta": {"subject": "盐钟 · 材质", "value": "铜", "source": 1, "drift": False}},
    )
    items = client.get(f"/api/v1/review-items?state=open&project_id={pid}").json()["data"]["items"]
    card = next(i for i in items if i.get("dedupe_key") == f"canon:{finding['finding_id']}")
    resolved = _post(client, f"/api/v1/review-items/{card['id']}/resolve", {"action_index": 0, "project_id": pid})
    assert resolved["effect_result"]["status"] == "adjudicated"
    row = session.get(ChapterAuditFinding, finding["finding_id"])
    assert row.status == "adjudicated"
    assert row.decision_note == "铜"
    # 收件箱里同一条消失
    items = client.get(f"/api/v1/review-items?state=open&project_id={pid}").json()["data"]["items"]
    assert all(i["id"] != card["id"] for i in items)


def test_adjudicate_resolves_card_reverse_direction(client):
    pid = _create_project(client)
    cid = _chapter(client, pid)
    finding = _post(
        client,
        f"/api/v2/projects/{pid}/longform/chapters/{cid}/audit",
        {"kind": "drift", "severity": "warn", "text": "时间线冲突",
         "meta": {"subject": "时间线", "value": "案发后第三天", "source": 3}},
    )
    _post(client, f"/api/v2/projects/{pid}/longform/audit/{finding['finding_id']}/adjudicate",
          {"decision": "accept_fix", "note": "案发后第三天"})
    items = client.get(f"/api/v1/review-items?state=open&project_id={pid}").json()["data"]["items"]
    assert all(i.get("dedupe_key") != f"canon:{finding['finding_id']}" for i in items)
    # 项目级清单可见裁决态
    audit = client.get(f"/api/v2/projects/{pid}/longform/audit").json()["data"]
    row = next(f for f in audit["findings"] if f["finding_id"] == finding["finding_id"])
    assert row["status"] == "adjudicated"


def test_finding_id_idempotent_and_card_deduped(client):
    pid = _create_project(client)
    cid = _chapter(client, pid)
    body = {"finding_id": "c-once", "kind": "drift", "severity": "warn", "text": "同一冲突",
            "meta": {"subject": "主题", "value": "值", "source": 1}}
    first = _post(client, f"/api/v2/projects/{pid}/longform/chapters/{cid}/audit", body)
    second = _post(client, f"/api/v2/projects/{pid}/longform/chapters/{cid}/audit", body)
    assert first["finding_id"] == second["finding_id"] == "c-once"
    items = client.get(f"/api/v1/review-items?state=open&project_id={pid}").json()["data"]["items"]
    assert sum(1 for i in items if i.get("dedupe_key") == "canon:c-once") == 1


def test_archive_transition_writes_back_chapter_state_and_derive(client, session):
    pid = _create_project(client)
    cid = _chapter(client, pid)
    base = f"/api/v2/projects/{pid}/longform/chapters/{cid}/contract"
    put = client.put(base, json={"constraints": [{"text": "保持地下档案室设定"}]})
    assert put.status_code == 200, put.text
    _post(client, f"{base}/transition", {"status": "ready"})
    _post(client, f"{base}/transition", {"status": "dispatched"})
    result = _post(client, f"{base}/transition", {"status": "archived", "force": True})
    assert result["status"] == "archived"
    assert result["write_back"]["chapter_state"] == "draft"
    assert result["write_back"]["derive"]["skipped"] is True  # LLM 未配置静默跳过
    tree = client.get(f"/api/v2/projects/{pid}/catalog").json()["data"]
    assert tree["chapters"][0]["state"] == "draft"


def test_archive_blocked_by_open_findings_without_force(client):
    pid = _create_project(client)
    cid = _chapter(client, pid)
    base = f"/api/v2/projects/{pid}/longform/chapters/{cid}/contract"
    client.put(base, json={"constraints": [{"text": "约束"}]})
    _post(client, f"{base}/transition", {"status": "ready"})
    _post(client, f"{base}/transition", {"status": "dispatched"})
    _post(client, f"/api/v2/projects/{pid}/longform/chapters/{cid}/audit",
          {"kind": "drift", "severity": "block", "text": "未裁决冲突", "meta": {"subject": "x", "value": "y"}})
    blocked = client.post(
        f"{base}/transition",
        json={"status": "archived"},
        headers={"X-Idempotency-Key": "tb-blocked"},
    )
    assert blocked.status_code == 409


def test_anchor_fe_kinds_promise_thread_arc(client):
    """FE-ALIGN F4：悬念债/故事线/弧线以扩展 kind 存锚点库，note 携带 FE 形状 JSON。"""
    import json as _json

    pid = _create_project(client)
    base = f"/api/v2/projects/{pid}/longform/anchors"
    fe = {"id": "l1", "title": "钩子", "setup": 1, "payoff": 9, "state": "open", "pri": "high", "pinned": True}
    created = _post(client, base, {"kind": "promise", "text": "钩子", "note": _json.dumps({"fe": fe}, ensure_ascii=False)})
    assert created["kind"] == "promise"
    for kind in ("thread", "arc"):
        _post(client, base, {"kind": kind, "text": f"k-{kind}"})
    bad = client.post(base, json={"kind": "nonsense", "text": "x"}, headers={"X-Idempotency-Key": "tb-anc-bad"})
    assert bad.status_code == 400

    listed = client.get(base).json()["data"]["anchors"]
    assert {a["kind"] for a in listed} >= {"promise", "thread", "arc"}
    target = next(a for a in listed if a["kind"] == "promise")
    fe2 = {**fe, "payoff": 15}
    patched = client.patch(f"{base}/{target['anchor_id']}", json={"note": _json.dumps({"fe": fe2}, ensure_ascii=False)},
                           headers={"X-Idempotency-Key": "tb-anc-patch"})
    assert patched.status_code == 200
    import json
    assert json.loads(patched.json()["data"]["note"])["fe"]["payoff"] == 15
