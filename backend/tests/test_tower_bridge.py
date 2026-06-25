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


def test_audit_receipt_deterministic_scan(client, session):
    """FE-ALIGN H2：审计回执 = 契约 + 产出 + 锚点在场扫描（检出带真实引用句 / 未检出待人工核对）。"""
    import json as _json

    pid = _create_project(client)
    cid = _chapter(client, pid)
    # 契约 + 锚点：一条会命中（铜），一条不会（28 岁），一条到期承诺（本章号=1）
    client.put(f"/api/v2/projects/{pid}/longform/chapters/{cid}/contract", json={"constraints": [{"text": "盐钟材质保持为铜"}]})
    base = f"/api/v2/projects/{pid}/longform/anchors"
    _post(client, base, {"kind": "setting", "text": "盐钟 · 材质 = 铜", "note": _json.dumps({"fe": {"id": "c2", "subject": "盐钟 · 材质", "value": "铜"}}, ensure_ascii=False)})
    _post(client, base, {"kind": "trait", "text": "林岑 · 年龄 = 28 岁", "note": _json.dumps({"fe": {"id": "c1", "subject": "林岑 · 年龄", "value": "28 岁"}}, ensure_ascii=False)})
    _post(client, base, {"kind": "promise", "text": "楼梯间的第二组脚印", "note": _json.dumps({"fe": {"id": "l6", "title": "楼梯间的第二组脚印", "setup": 2, "payoff": 1, "state": "open"}}, ensure_ascii=False)})

    # 无正文：has_text=False（FE 据此回落演示静态）
    empty = client.get(f"/api/v2/projects/{pid}/longform/chapters/{cid}/audit-receipt").json()["data"]
    assert empty["has_text"] is False

    # 用目录建章自动带的首场写正文（含「铜」，不含「28 岁」）
    tree = client.get(f"/api/v2/projects/{pid}/catalog").json()["data"]
    scene_id = tree["chapters"][0]["scenes"][0]["scene_id"]
    ensure = client.post(f"/api/v1/author-drafts/scene/{scene_id}/ensure", headers={"X-Idempotency-Key": "rcpt-ensure"})
    draft = ensure.json()["data"]["draft"]
    save = client.patch(
        f"/api/v1/author-drafts/{draft['draft_id']}",
        json={"content": "<p>她把铜制的盐钟扣回掌心。</p><p>夜班的灯还亮着。</p>", "base_revision_no": draft["revision_no"]},
    )
    assert save.status_code == 200, save.text

    receipt = client.get(f"/api/v2/projects/{pid}/longform/chapters/{cid}/audit-receipt").json()["data"]
    assert receipt["has_text"] is True
    assert receipt["chapter_no"] == 1
    assert receipt["contract"]["status"] in {"drafting", "ready"}
    assert receipt["scenes"][0]["has_draft"] is True and receipt["scenes"][0]["words"] > 0
    hits = {h["id"]: h for h in receipt["anchor_hits"]}
    assert "c2" in hits and "铜" in hits["c2"]["evidence"] and "段 1" in hits["c2"]["at"]
    assert [m["id"] for m in receipt["anchor_misses"]] == ["c1"]
    assert receipt["pending"] and receipt["pending"][0]["id"] == "l6"


def _write_scene_prose(client, pid, cid, content) -> str:
    """建章自带的首场写入正文，返回 scene_id。"""
    tree = client.get(f"/api/v2/projects/{pid}/catalog").json()["data"]
    scene_id = tree["chapters"][0]["scenes"][0]["scene_id"]
    ensure = client.post(
        f"/api/v1/author-drafts/scene/{scene_id}/ensure",
        headers={"X-Idempotency-Key": f"adj-ensure-{scene_id}"},
    )
    draft = ensure.json()["data"]["draft"]
    save = client.patch(
        f"/api/v1/author-drafts/{draft['draft_id']}",
        json={"content": content, "base_revision_no": draft["revision_no"]},
    )
    assert save.status_code == 200, save.text
    return scene_id


def test_adjudicate_draft_degrades_without_llm(client):
    """FE-ALIGN P2(D13)：LLM 未配置 → 诚实降级（只声明检出/未检出，drifted 留空 + author_action），
    不机器判违约、不落 finding。"""
    pid = _create_project(client)
    cid = _chapter(client, pid)
    client.put(
        f"/api/v2/projects/{pid}/longform/chapters/{cid}/contract",
        json={"constraints": [{"text": "档案室保持在地下，不得出现在三楼"}]},
    )
    _write_scene_prose(client, pid, cid, "<p>他们走上三楼，推开了档案室的门。</p>")

    resp = client.post(
        f"/api/v2/projects/{pid}/longform/chapters/{cid}/audit/adjudicate-draft",
        json={},
        headers={"X-Idempotency-Key": "adj-degrade-1"},
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]
    assert data["skipped"] is True
    assert data["reason"] == "llm_disabled"
    assert data["violations"] == []
    assert data["findings_created"] == 0
    assert data["author_action"]["target_view"] == "system-config"
    # 确定性回执仍在（诚实口径：检出/未检出可见）
    assert "anchor_hits" in data["receipt"] and "anchor_misses" in data["receipt"]
    # 未落任何 finding
    findings = client.get(f"/api/v2/projects/{pid}/longform/chapters/{cid}/audit").json()["data"]["findings"]
    assert findings == []


def test_adjudicate_draft_llm_violations_create_findings(client, session, monkeypatch):
    """FE-ALIGN P2(D13)：LLM 开（mock）→ 每条违约落 ChapterAuditFinding(kind=drift) + 同事务产裁决卡；
    确定性 finding_id 使重跑幂等（不重复落库）。"""
    import types

    import novel_system.services.longform_tower as tower_mod

    pid = _create_project(client)
    cid = _chapter(client, pid)
    client.put(
        f"/api/v2/projects/{pid}/longform/chapters/{cid}/contract",
        json={"constraints": [{"text": "档案室保持在地下，不得出现在三楼"}]},
    )
    _write_scene_prose(client, pid, cid, "<p>他们走上三楼，推开了档案室的门。</p><p>灯还亮着。</p>")

    # 强制 llm_enabled + 注入返回固定违约的 fake client（不触网）
    monkeypatch.setattr(tower_mod, "get_settings", lambda: types.SimpleNamespace(llm_enabled=True))
    violation = {
        "clause_ref": "1",
        "kind": "drift",
        "severity": "block",
        "text": "档案室被写到三楼，违反契约第 1 条（应在地下）",
        "evidence_sentence": "他们走上三楼，推开了档案室的门。",
        "at": "测试章",
        "suggested_fix": "把档案室位置改回地下，删除三楼相关描写",
    }

    class _Resp:
        def __init__(self, data):
            self.structured_output = data

    class _Client:
        def __init__(self, data):
            self._data = data

        def generate(self, request):  # noqa: ARG002 — 测试桩
            return _Resp(self._data)

    result = tower_mod.LongformTowerService(session).adjudicate_draft(
        pid, cid, llm_client=_Client({"violations": [violation]})
    )
    session.commit()
    assert result["skipped"] is False
    assert len(result["violations"]) == 1
    assert result["violations"][0]["kind"] == "drift"
    assert result["findings_created"] == 1

    rows = (
        session.query(ChapterAuditFinding)
        .filter(ChapterAuditFinding.project_id == pid, ChapterAuditFinding.chapter_id == cid)
        .all()
    )
    assert len(rows) == 1 and rows[0].kind == "drift" and rows[0].severity == "block"
    fid = rows[0].finding_id
    # 同事务产了裁决卡（drift → risk，priority 1）
    items = client.get(f"/api/v1/review-items?state=open&project_id={pid}").json()["data"]["items"]
    card = next(i for i in items if i.get("dedupe_key") == f"canon:{fid}")
    assert card["kind"] == "risk" and card["priority"] == 1

    # 同样违约重跑 → 幂等，不重复落库
    result2 = tower_mod.LongformTowerService(session).adjudicate_draft(
        pid, cid, llm_client=_Client({"violations": [violation]})
    )
    session.commit()
    assert result2["findings_created"] == 0
    rows2 = (
        session.query(ChapterAuditFinding)
        .filter(ChapterAuditFinding.project_id == pid, ChapterAuditFinding.chapter_id == cid)
        .all()
    )
    assert len(rows2) == 1


def test_anchor_create_honors_idempotency_replay(client):
    """FE-ALIGN 修复：锚点/审计创建端点兑现幂等键（重放不建重复行）。"""
    pid = _create_project(client)
    key = "tb-idem-anchor-1"
    body = {"kind": "fact", "text": "幂等锚点", "note": "{\"fe\": {\"id\": \"idem1\"}}"}
    first = client.post(f"/api/v2/projects/{pid}/longform/anchors", json=body, headers={"X-Idempotency-Key": key})
    replay = client.post(f"/api/v2/projects/{pid}/longform/anchors", json=body, headers={"X-Idempotency-Key": key})
    assert first.status_code == replay.status_code == 200, replay.text
    assert replay.headers.get("X-Idempotency-Status") == "replayed"
    assert replay.json()["data"]["anchor_id"] == first.json()["data"]["anchor_id"]
    anchors = client.get(f"/api/v2/projects/{pid}/longform/anchors").json()["data"]["anchors"]
    assert sum(1 for a in anchors if a["text"] == "幂等锚点") == 1

    cid = _chapter(client, pid)
    audit_key = "tb-idem-audit-1"
    audit_body = {"kind": "drift", "severity": "warn", "text": "幂等 finding", "meta": {"subject": "s", "value": "v"}}
    f1 = client.post(f"/api/v2/projects/{pid}/longform/chapters/{cid}/audit", json=audit_body, headers={"X-Idempotency-Key": audit_key})
    f2 = client.post(f"/api/v2/projects/{pid}/longform/chapters/{cid}/audit", json=audit_body, headers={"X-Idempotency-Key": audit_key})
    assert f1.status_code == f2.status_code == 200, f2.text
    assert f2.json()["data"]["finding_id"] == f1.json()["data"]["finding_id"]
    findings = client.get(f"/api/v2/projects/{pid}/longform/chapters/{cid}/audit").json()["data"]["findings"]
    assert sum(1 for f in findings if f["text"] == "幂等 finding") == 1
