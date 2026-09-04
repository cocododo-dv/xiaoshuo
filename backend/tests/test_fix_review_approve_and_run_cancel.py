"""回归：审核批准 / 风格参考 run 取消路径上的裸 500 与终态污染。

三条契约(修复前都是 500 或静默改写终态):
1. 已批准的向量审核项再次 approve(新幂等 key)→ 修复前 reindex_/verify_ job_id 撞库
   IntegrityError 500;修复后 409 REVIEW_ALREADY_APPROVED,且不改动已物化状态。
2. 知识注册表不认识的 item_type:创建候选时即 400 REVIEW_ITEM_TYPE_INVALID;
   历史遗留行 approve 时 409 REVIEW_ITEM_TYPE_UNSUPPORTED(修复前 KeyError 500)。
3. 风格参考 run 只有 pending/running 可取消;done/failed 取消 → 409
   STYLE_REFERENCE_RUN_CANCEL_CONFLICT 且 run 行原样保留(修复前被无条件改写为 cancelled);
   已取消的 run 重复取消是幂等 no-op。
"""

from __future__ import annotations

import pytest

from novel_system.db.models import ReviewItem
from novel_system.db.session import SessionLocal
from novel_system.services.style_reference.repository import StyleReferenceRepository

PREFIX = "/api/v2/style-reference"


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _import_style_review(
    client, review_id: str, lineage_key: str, *, item_type: str = "style_observation"
) -> str:
    """镜像 test_review_release_state.import_style_review:经 fixture 导入边界建一条
    pending 候选。默认 style_observation(向量物化链路);style_rule_set 走 direct 链路,
    两者的 candidate_payload_json 形状相同。"""
    candidate_text = "让收尾停在半句，把情绪压在门后。"
    response = client.post(
        "/api/v1/review-items/import-demo",
        json={
            "review_id": review_id,
            "scene_id": "CH001_SC01",
            "chapter_id": "CH001",
            "item_type": item_type,
            "candidate_text": candidate_text,
            "candidate_payload_json": {
                "scope": "global",
                "scope_ref_id": "global",
                "lineage_key": lineage_key,
                "text": candidate_text,
            },
            "active_on_approve": 0,
        },
        headers={"X-Idempotency-Key": f"import-{review_id}"},
    )
    assert response.status_code == 200, response.text
    return review_id


def _approve(client, review_id: str, *, key: str):
    return client.post(
        f"/api/v1/review-items/{review_id}/approve",
        headers={"X-Idempotency-Key": key},
    )


def _review_jobs(client, review_id: str) -> list[dict]:
    items = client.get("/api/v1/index/jobs").json()["data"]["items"]
    return [job for job in items if job["review_id"] == review_id]


def _seed_run(
    suffix: str,
    *,
    status: str,
    dispatch_state: str,
    finished_at: str | None = None,
) -> str:
    """直接用 repository 建 book + run,绕过上传与 LLM(镜像
    test_style_reference_review_fixes._seed_binding)。"""
    book_id = f"sr_book_fixcancel_{suffix}"
    run_id = f"sr_run_fixcancel_{suffix}"
    with SessionLocal() as session:
        repo = StyleReferenceRepository(session)
        repo.create_book(
            book_id=book_id,
            title="取消契约测试",
            source_kind="upload",
            cloud_policy="segments_only",
            text_checksum=f"chk_fixcancel_{suffix}",
            total_chars=10,
            status="ready",
            stats_json={
                "rights_declaration": {
                    "declared": True,
                    "analysis_rights": True,
                    "send_rights": True,
                }
            },
        )
        repo.create_run(
            run_id=run_id,
            book_id=book_id,
            status=status,
            phase="extract",
            dispatch_state=dispatch_state,
            finished_at=finished_at,
        )
        session.commit()
    return run_id


def _get_run(client, run_id: str) -> dict:
    response = client.get(f"{PREFIX}/runs/{run_id}")
    assert response.status_code == 200, response.text
    return response.json()["data"]["run"]


# ---------------------------------------------------------------------------
# (1) 重复 approve
# ---------------------------------------------------------------------------


def test_repeated_approve_on_approved_vector_review_is_a_clean_conflict(client) -> None:
    review_id = _import_style_review(client, "review_fix_repeat_approve", "STY_FIX_REPEAT_APPROVE")

    first = _approve(client, review_id, key="approve-fix-repeat-1")
    assert first.status_code == 200, first.text
    row_id = first.json()["data"]["approved_item_row_id"]
    assert row_id

    # 同一 key 重放仍是幂等回放(不受新守卫影响)。
    replay = _approve(client, review_id, key="approve-fix-repeat-1")
    assert replay.status_code == 200, replay.text
    assert replay.json()["data"]["approved_item_row_id"] == row_id

    # 新 key 的重复批准:修复前在 flush reindex_/verify_ job 时 IntegrityError → 500。
    second = _approve(client, review_id, key="approve-fix-repeat-2")
    assert second.status_code == 409, second.text
    error = second.json()["error"]
    assert error["code"] == "REVIEW_ALREADY_APPROVED"
    assert error["details"]["review_id"] == review_id
    assert error["details"]["approved_item_row_id"] == row_id
    assert error["details"]["materialize_status"] == "succeeded"

    # 已物化状态原样保留:仍只有第一次批准产生的一对 reindex/verify job。
    detail = client.get(f"/api/v1/review-items/{review_id}")
    assert detail.status_code == 200
    data = detail.json()["data"]
    assert data["status"] == "approved"
    assert data["materialize_status"] == "succeeded"
    assert data["approved_item_row_id"] == row_id
    assert sorted(job["job_type"] for job in _review_jobs(client, review_id)) == ["reindex", "verify"]


def _reject(client, review_id: str, *, key: str):
    return client.post(
        f"/api/v1/review-items/{review_id}/reject",
        headers={"X-Idempotency-Key": key},
    )


def test_reapprove_of_rejected_vector_review_is_a_clean_conflict(client) -> None:
    """同一根因的另一入口:拒绝后再批准会再次 INSERT 固定 id 的索引 job(修复前 500)。
    向量候选不支持二次批准 → 409,且在改动任何行之前回绝。"""
    review_id = _import_style_review(client, "review_fix_reapprove_vector", "STY_FIX_REAPPROVE")
    assert _approve(client, review_id, key="approve-fix-reapprove-1").status_code == 200
    rejected = _reject(client, review_id, key="reject-fix-reapprove")
    assert rejected.status_code == 200, rejected.text
    assert rejected.json()["data"]["status"] == "rejected"

    again = _approve(client, review_id, key="approve-fix-reapprove-2")
    assert again.status_code == 409, again.text
    error = again.json()["error"]
    assert error["code"] == "REVIEW_REAPPROVE_UNSUPPORTED"
    assert error["details"]["status"] == "rejected"
    assert sorted(error["details"]["existing_job_ids"]) == [f"reindex_{review_id}", f"verify_{review_id}"]

    data = client.get(f"/api/v1/review-items/{review_id}").json()["data"]
    assert data["status"] == "rejected"
    assert data["materialize_status"] == "rejected"
    assert data["approved_item_row_id"] is None
    assert sorted(job["job_type"] for job in _review_jobs(client, review_id)) == ["reindex", "verify"]


def test_reapprove_of_rejected_direct_review_still_creates_a_new_version(client) -> None:
    """守卫只针对向量候选:direct 落库类型(style_rule_set)拒绝后再批准仍产出 v2。"""
    review_id = _import_style_review(
        client, "review_fix_reapprove_direct", "RULE_FIX_REAPPROVE", item_type="style_rule_set"
    )
    first = _approve(client, review_id, key="approve-fix-direct-1")
    assert first.status_code == 200, first.text
    assert first.json()["data"]["approved_item_row_id"].endswith("_v1")
    assert _reject(client, review_id, key="reject-fix-direct").status_code == 200

    again = _approve(client, review_id, key="approve-fix-direct-2")
    assert again.status_code == 200, again.text
    assert again.json()["data"]["approved_item_row_id"].endswith("_v2")


# ---------------------------------------------------------------------------
# (2) 注册表外 item_type
# ---------------------------------------------------------------------------


def test_create_review_candidate_rejects_item_type_unknown_to_registry(client) -> None:
    response = client.post(
        "/api/v1/review-items",
        json={
            "review_id": "review_fix_unknown_type",
            "item_type": "mystery_candidate",
            "candidate_text": "没有物化落点的候选",
            "candidate_payload_json": {"lineage_key": "MYSTERY_001"},
        },
        headers={"X-Idempotency-Key": "create-fix-unknown-type"},
    )
    assert response.status_code == 400, response.text
    error = response.json()["error"]
    assert error["code"] == "REVIEW_ITEM_TYPE_INVALID"
    assert error["details"]["item_type"] == "mystery_candidate"
    assert "style_observation" in error["details"]["supported_item_types"]
    assert "author_preference_profile" in error["details"]["supported_item_types"]
    # 未落库
    assert client.get("/api/v1/review-items/review_fix_unknown_type").status_code == 404


@pytest.mark.parametrize(
    "item_type",
    ["style_observation", "scene_summary", "author_preference_profile", "longform_structure_guidance"],
)
def test_create_review_candidate_keeps_every_approvable_item_type(client, item_type: str) -> None:
    """守卫只拦注册表 + 路由专属类型之外的值:注册表类型与两种路由专属类型都仍可创建。"""
    review_id = f"review_fix_known_{item_type}"
    response = client.post(
        "/api/v1/review-items",
        json={
            "review_id": review_id,
            "scene_id": "CH001_SC01",
            "chapter_id": "CH001",
            "item_type": item_type,
            "candidate_text": "可批准类型的候选",
            "candidate_payload_json": {"lineage_key": f"KNOWN_{item_type}", "text": "可批准类型的候选"},
        },
        headers={"X-Idempotency-Key": f"create-fix-known-{item_type}"},
    )
    assert response.status_code == 200, response.text
    assert response.json()["data"]["item_type"] == item_type


def test_approve_review_with_unregistered_item_type_is_a_domain_error(client, session) -> None:
    """历史遗留行(创建守卫之前写入)approve 时必须是 DomainError 而不是 KeyError 500。"""
    session.add(
        ReviewItem(
            review_id="review_fix_legacy_unknown_type",
            scene_id="CH001_SC01",
            chapter_id="CH001",
            item_type="mystery_candidate",
            status="pending",
            candidate_text="没有物化落点的遗留候选",
            candidate_payload_json={"lineage_key": "MYSTERY_LEGACY"},
        )
    )
    session.commit()

    response = _approve(client, "review_fix_legacy_unknown_type", key="approve-fix-legacy-unknown")
    assert response.status_code == 409, response.text
    error = response.json()["error"]
    assert error["code"] == "REVIEW_ITEM_TYPE_UNSUPPORTED"
    assert error["details"]["item_type"] == "mystery_candidate"

    # 行未被半途改写(status 在物化前就被置 approved 是修复前的另一处污染点)。
    detail = client.get("/api/v1/review-items/review_fix_legacy_unknown_type")
    assert detail.status_code == 200, detail.text
    data = detail.json()["data"]
    assert data["status"] == "pending"
    assert data["materialize_status"] == "pending"
    assert data["approved_item_row_id"] is None


# ---------------------------------------------------------------------------
# (3) 风格参考 run 取消
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("terminal_status", "dispatch_state"),
    [("done", "completed"), ("failed", "failed")],
)
def test_cancel_terminal_run_is_a_conflict_and_leaves_the_run_untouched(
    client, terminal_status: str, dispatch_state: str
) -> None:
    finished_at = "2026-01-01T00:00:00+00:00"
    run_id = _seed_run(
        terminal_status,
        status=terminal_status,
        dispatch_state=dispatch_state,
        finished_at=finished_at,
    )

    response = client.post(
        f"{PREFIX}/runs/{run_id}/cancel",
        headers={"X-Idempotency-Key": f"cancel-fix-{terminal_status}"},
    )
    assert response.status_code == 409, response.text
    error = response.json()["error"]
    assert error["code"] == "STYLE_REFERENCE_RUN_CANCEL_CONFLICT"
    assert error["details"] == {"run_id": run_id, "status": terminal_status}

    # 修复前:status/dispatch_state/finished_at 全被改写成 cancelled/now。
    run = _get_run(client, run_id)
    assert run["status"] == terminal_status
    assert run["dispatch_state"] == dispatch_state
    assert run["finished_at"] == finished_at


@pytest.mark.parametrize(
    ("live_status", "dispatch_state"),
    [("pending", "queued"), ("running", "running")],
)
def test_cancel_live_run_marks_it_cancelled(client, live_status: str, dispatch_state: str) -> None:
    run_id = _seed_run(live_status, status=live_status, dispatch_state=dispatch_state)

    response = client.post(
        f"{PREFIX}/runs/{run_id}/cancel",
        headers={"X-Idempotency-Key": f"cancel-fix-{live_status}"},
    )
    assert response.status_code == 200, response.text
    data = response.json()["data"]
    assert (data["run_id"], data["status"]) == (run_id, "cancelled")

    run = _get_run(client, run_id)
    assert run["status"] == "cancelled"
    assert run["dispatch_state"] == "cancelled"
    assert run["finished_at"]
    assert run["retryable"] is False


def test_cancel_already_cancelled_run_is_an_idempotent_noop(client) -> None:
    finished_at = "2026-01-02T00:00:00+00:00"
    run_id = _seed_run("cancelled", status="cancelled", dispatch_state="cancelled", finished_at=finished_at)

    response = client.post(
        f"{PREFIX}/runs/{run_id}/cancel",
        headers={"X-Idempotency-Key": "cancel-fix-cancelled-again"},
    )
    assert response.status_code == 200, response.text
    data = response.json()["data"]
    assert (data["run_id"], data["status"]) == (run_id, "cancelled")
    # 不重写 finished_at
    assert _get_run(client, run_id)["finished_at"] == finished_at
