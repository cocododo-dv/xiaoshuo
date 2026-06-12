"""控制塔(锚点 + 交接契约)— 后端 P0 回归测试。"""
from __future__ import annotations

import uuid


def _idem() -> dict:
    return {"X-Idempotency-Key": f"twr-test-{uuid.uuid4().hex[:10]}"}


def _create_project(client) -> dict:
    response = client.post(
        "/api/v1/projects",
        json={
            "title": "潮汐档案",
            "genre": "悬疑",
            "target_chapter_count": 2,
            "target_word_count": 100000,
            "outline_text": "林岑修复一批潮汐档案。\n她发现补写笔迹。\n真相浮出。",
            "planning_mode": "snowflake",
        },
        headers={"X-Idempotency-Key": f"create-{uuid.uuid4().hex}"},
    )
    assert response.status_code == 200, response.text
    return response.json()["data"]["project"]


def test_anchor_crud_and_fade(client) -> None:
    project = _create_project(client)
    base = f"/api/v2/projects/{project['project_id']}/longform/anchors"

    missing = client.post(base, json={"kind": "fact", "text": "  "}, headers=_idem())
    assert missing.status_code == 400
    assert missing.json()["error"]["code"] == "TOWER_ANCHOR_TEXT_REQUIRED"

    created = client.post(base, json={"kind": "trait", "text": "林岑 28 岁", "source_ref": "character:CHAR_LC"}, headers=_idem())
    assert created.status_code == 200, created.text
    anchor = created.json()["data"]
    assert anchor["status"] == "pinned"

    faded = client.patch(f"{base}/{anchor['anchor_id']}", json={"status": "faded", "note": "第 6 章后淡出"})
    assert faded.status_code == 200
    assert faded.json()["data"]["status"] == "faded"

    listing = client.get(base)
    assert listing.status_code == 200
    anchors = listing.json()["data"]["anchors"]
    assert [item["text"] for item in anchors] == ["林岑 28 岁"]


def test_contract_gates_and_transitions(client) -> None:
    project = _create_project(client)
    base = f"/api/v2/projects/{project['project_id']}/longform/chapters/CH09/contract"

    fetched = client.get(base)
    assert fetched.status_code == 200, fetched.text
    contract = fetched.json()["data"]
    assert contract["status"] == "drafting"
    assert contract["constraints"] == []

    # 空契约不能 ready —— 守门
    blocked = client.post(f"{base}/transition", json={"status": "ready"})
    assert blocked.status_code == 409
    assert blocked.json()["error"]["code"] == "TOWER_CONTRACT_EMPTY"

    anchor = client.post(
        f"/api/v2/projects/{project['project_id']}/longform/anchors",
        json={"kind": "fact", "text": "档案室在地下,不在三楼"},
        headers=_idem(),
    ).json()["data"]

    updated = client.put(
        base,
        json={
            "constraints": [
                {"text": "回收第 6 章的脚印线索", "scene_id": "CH09_SC03"},
                {"text": "档案室位置保持地下", "anchor_id": anchor["anchor_id"]},
            ]
        },
    )
    assert updated.status_code == 200, updated.text
    assert len(updated.json()["data"]["constraints"]) == 2

    # 非法锚点引用被拒
    bad_anchor = client.put(base, json={"constraints": [{"text": "x", "anchor_id": "ANC_NOPE"}]})
    assert bad_anchor.status_code == 404
    assert bad_anchor.json()["error"]["code"] == "TOWER_ANCHOR_NOT_FOUND"

    ready = client.post(f"{base}/transition", json={"status": "ready"})
    assert ready.status_code == 200
    assert ready.json()["data"]["status"] == "ready"

    # 不能跳级 ready→archived
    skip = client.post(f"{base}/transition", json={"status": "archived"})
    assert skip.status_code == 409
    assert skip.json()["error"]["code"] == "TOWER_CONTRACT_TRANSITION_INVALID"

    dispatched = client.post(f"{base}/transition", json={"status": "dispatched"})
    assert dispatched.status_code == 200
    assert dispatched.json()["data"]["dispatched_at"]

    # 下发后契约不可改 —— 守门归档语义
    locked = client.put(base, json={"constraints": [{"text": "改不动了"}]})
    assert locked.status_code == 409
    assert locked.json()["error"]["code"] == "TOWER_CONTRACT_LOCKED"

    archived = client.post(f"{base}/transition", json={"status": "archived"})
    assert archived.status_code == 200
    assert archived.json()["data"]["archived_at"]


def test_audit_findings_gate_archive(client) -> None:
    project = _create_project(client)
    pid = project["project_id"]
    contract_base = f"/api/v2/projects/{pid}/longform/chapters/CH09/contract"
    audit_base = f"/api/v2/projects/{pid}/longform/chapters/CH09/audit"

    # 契约推进到 dispatched
    client.get(contract_base)
    client.put(contract_base, json={"constraints": [{"text": "回收脚印线索"}]})
    client.post(f"{contract_base}/transition", json={"status": "ready"})
    client.post(f"{contract_base}/transition", json={"status": "dispatched"})

    # 登记一条审计发现(漂移)
    created = client.post(audit_base, json={"kind": "drift", "severity": "block", "text": "档案室写成了三楼", "evidence": "第 2 场"}, headers=_idem())
    assert created.status_code == 200, created.text
    finding = created.json()["data"]
    assert finding["status"] == "open"

    bad_kind = client.post(audit_base, json={"kind": "vibes", "text": "x"}, headers=_idem())
    assert bad_kind.status_code == 400
    assert bad_kind.json()["error"]["code"] == "TOWER_AUDIT_KIND_INVALID"

    # 有 open 发现时归档被守门
    blocked = client.post(f"{contract_base}/transition", json={"status": "archived"})
    assert blocked.status_code == 409
    assert blocked.json()["error"]["code"] == "TOWER_AUDIT_OPEN"

    # 带病归档需显式 force
    forced_preview = client.get(audit_base)
    assert forced_preview.json()["data"]["open_count"] == 1

    # 裁决后正常归档
    adjudicated = client.post(
        f"/api/v2/projects/{pid}/longform/audit/{finding['finding_id']}/adjudicate",
        json={"decision": "accept_fix", "note": "统一为地下档案室"},
    )
    assert adjudicated.status_code == 200
    assert adjudicated.json()["data"]["status"] == "adjudicated"

    archived = client.post(f"{contract_base}/transition", json={"status": "archived"})
    assert archived.status_code == 200
    assert archived.json()["data"]["status"] == "archived"


def test_audit_force_archive_with_open_findings(client) -> None:
    project = _create_project(client)
    pid = project["project_id"]
    contract_base = f"/api/v2/projects/{pid}/longform/chapters/CH10/contract"
    audit_base = f"/api/v2/projects/{pid}/longform/chapters/CH10/audit"

    client.get(contract_base)
    client.put(contract_base, json={"constraints": [{"text": "x"}]})
    client.post(f"{contract_base}/transition", json={"status": "ready"})
    client.post(f"{contract_base}/transition", json={"status": "dispatched"})
    client.post(audit_base, json={"kind": "stall", "text": "中段三场原地踏步"}, headers=_idem())

    forced = client.post(f"{contract_base}/transition", json={"status": "archived", "force": True})
    assert forced.status_code == 200
    assert forced.json()["data"]["status"] == "archived"
