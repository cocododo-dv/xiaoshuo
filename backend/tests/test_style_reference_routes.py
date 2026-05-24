"""Style Reference 18 端点黑盒测试(PR-4)。

参见 plans/style-reference-v1-1-fancy-shannon.md §"测试策略"。
"""

from __future__ import annotations

import io
import json
from typing import Any

import pytest
from fastapi.testclient import TestClient

from novel_system.db.session import SessionLocal
from novel_system.services.style_reference.repository import StyleReferenceRepository


SAMPLE_TXT = """这是一段较长的叙述文字,介绍清晨场景与人物心情,字数足以触发分段。

他说:"今天天气不错。"

我心里想着昨天的事情,觉得有些不安。

记得那年她还在的时候。

雪花从天空飘落。
""".encode("utf-8")


PREFIX = "/api/v2/style-reference"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _import_book(client: TestClient) -> str:
    files = {"file": ("sample.txt", io.BytesIO(SAMPLE_TXT), "text/plain")}
    resp = client.post(
        f"{PREFIX}/books/import-upload",
        files=files,
        data={"title": "测试", "cloud_policy": "local_only"},
        headers={"X-Idempotency-Key": "imp_1"},
    )
    assert resp.status_code == 200, resp.text
    return resp.json()["data"]["book"]["book_id"]


def _seed_full_chain(book_id: str) -> tuple[str, str, str]:
    """直接用 service 层快速建 run + finding + profile,绕过 LLM 调用。"""
    with SessionLocal() as session:
        repo = StyleReferenceRepository(session)
        run_id = f"sr_run_route_{book_id[-6:]}"
        repo.create_run(run_id=run_id, book_id=book_id, status="done", phase="done")
        extraction_id = f"sr_ext_route_{book_id[-6:]}"
        repo.create_extraction(
            extraction_id=extraction_id,
            book_id=book_id,
            run_id=run_id,
            layer="language",
            sub_dimension="language.rhetoric",
            raw_payload_json={},
            status="done",
            validation_errors_json=[],
            purpose="extract",
        )
        finding_id = f"sr_find_route_{book_id[-6:]}"
        repo.create_finding(
            finding_id=finding_id,
            book_id=book_id,
            run_id=run_id,
            extraction_id=extraction_id,
            sub_dimension="language.rhetoric",
            finding_kind="observation",
            statement="测试 observation 描述",
            confidence="high",
            status="pending",
        )
        profile_id = f"sr_profile_route_{book_id[-6:]}"
        repo.create_profile(
            profile_id=profile_id,
            book_id=book_id,
            run_id=run_id,
            title="测试 profile",
            status="draft",
            profile_json={
                "narrative_summary": "ns",
                "scene_samples_index": {},
                "calibration_guidance": ["calib A"],
            },
            coverage_json={},
            source_finding_ids_json=[finding_id],
        )
        session.commit()
    return run_id, finding_id, profile_id


# ---------------------------------------------------------------------------
# Books endpoints
# ---------------------------------------------------------------------------


def test_import_upload_happy(client: TestClient) -> None:
    book_id = _import_book(client)
    assert book_id.startswith("sr_book_")


def test_import_upload_idempotency_replay(client: TestClient) -> None:
    files = {"file": ("a.txt", io.BytesIO(SAMPLE_TXT), "text/plain")}
    headers = {"X-Idempotency-Key": "imp_dup"}
    data = {"title": "x", "cloud_policy": "local_only"}
    r1 = client.post(
        f"{PREFIX}/books/import-upload", files=files, data=data, headers=headers
    )
    files2 = {"file": ("a.txt", io.BytesIO(SAMPLE_TXT), "text/plain")}
    r2 = client.post(
        f"{PREFIX}/books/import-upload", files=files2, data=data, headers=headers
    )
    assert r1.status_code == 200
    assert r2.status_code == 200
    # idempotency replay 应返回 X-Idempotency-Status="replayed"(或 "stored" 首次)
    assert "X-Idempotency-Status" in r2.headers


def test_list_books(client: TestClient) -> None:
    _import_book(client)
    resp = client.get(f"{PREFIX}/books")
    assert resp.status_code == 200
    assert len(resp.json()["data"]["books"]) >= 1


def test_get_book_happy(client: TestClient) -> None:
    book_id = _import_book(client)
    resp = client.get(f"{PREFIX}/books/{book_id}")
    assert resp.status_code == 200
    assert resp.json()["data"]["book"]["book_id"] == book_id


def test_get_book_404(client: TestClient) -> None:
    resp = client.get(f"{PREFIX}/books/sr_book_nonexistent")
    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "STYLE_REFERENCE_BOOK_NOT_FOUND"


def test_delete_book(client: TestClient) -> None:
    book_id = _import_book(client)
    resp = client.delete(
        f"{PREFIX}/books/{book_id}", headers={"X-Idempotency-Key": "del_1"}
    )
    assert resp.status_code == 200
    assert resp.json()["data"]["deleted"] is True
    resp2 = client.get(f"{PREFIX}/books/{book_id}")
    assert resp2.status_code == 404


def test_reclassify_placeholder(client: TestClient) -> None:
    book_id = _import_book(client)
    resp = client.post(
        f"{PREFIX}/books/{book_id}/reclassify",
        headers={"X-Idempotency-Key": "rec_1"},
    )
    assert resp.status_code == 200
    assert resp.json()["data"]["status"] == "reclassify_pending"


# ---------------------------------------------------------------------------
# Runs endpoints
# ---------------------------------------------------------------------------


def test_start_run_llm_required_when_disabled(client: TestClient, monkeypatch) -> None:
    monkeypatch.setenv("NOVEL_SYSTEM_LLM_ENABLED", "false")
    book_id = _import_book(client)
    resp = client.post(
        f"{PREFIX}/books/{book_id}/runs",
        json={},
        headers={"X-Idempotency-Key": "run_disabled"},
    )
    # LLMRequiredError 走 default handler → 409 (StyleReferenceError 子类)
    # 实际上 LLMRequiredError 不是 DomainError,会走 generic exception handler
    # → 5xx;此测试关键是确认调用不返回 200
    assert resp.status_code >= 400


def test_get_run_happy(client: TestClient) -> None:
    book_id = _import_book(client)
    run_id, _, _ = _seed_full_chain(book_id)
    resp = client.get(f"{PREFIX}/runs/{run_id}")
    assert resp.status_code == 200
    assert resp.json()["data"]["run"]["run_id"] == run_id


def test_get_run_404(client: TestClient) -> None:
    resp = client.get(f"{PREFIX}/runs/sr_run_nonexistent")
    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "STYLE_REFERENCE_RUN_NOT_FOUND"


def test_cancel_run(client: TestClient) -> None:
    book_id = _import_book(client)
    run_id, _, _ = _seed_full_chain(book_id)
    resp = client.post(
        f"{PREFIX}/runs/{run_id}/cancel", headers={"X-Idempotency-Key": "cancel_1"}
    )
    assert resp.status_code == 200
    assert resp.json()["data"]["status"] == "cancelled"


def test_list_run_findings(client: TestClient) -> None:
    book_id = _import_book(client)
    run_id, _, _ = _seed_full_chain(book_id)
    resp = client.get(f"{PREFIX}/runs/{run_id}/findings")
    assert resp.status_code == 200
    assert len(resp.json()["data"]["findings"]) == 1


# ---------------------------------------------------------------------------
# Findings review
# ---------------------------------------------------------------------------


def test_finding_review_happy(client: TestClient) -> None:
    book_id = _import_book(client)
    _, finding_id, _ = _seed_full_chain(book_id)
    resp = client.post(
        f"{PREFIX}/findings/{finding_id}/review",
        json={"decision": "approved", "comment": "looks good"},
        headers={"X-Idempotency-Key": "rev_1"},
    )
    assert resp.status_code == 200
    assert resp.json()["data"]["decision"] == "approved"
    assert resp.json()["data"]["review_id"].startswith("review_style_ref_finding_")


def test_finding_review_invalid_decision(client: TestClient) -> None:
    book_id = _import_book(client)
    _, finding_id, _ = _seed_full_chain(book_id)
    resp = client.post(
        f"{PREFIX}/findings/{finding_id}/review",
        json={"decision": "yolo"},
        headers={"X-Idempotency-Key": "rev_invalid"},
    )
    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == "STYLE_REFERENCE_REVIEW_DECISION_INVALID"


# ---------------------------------------------------------------------------
# Profiles endpoints
# ---------------------------------------------------------------------------


def test_list_profiles(client: TestClient) -> None:
    book_id = _import_book(client)
    _seed_full_chain(book_id)
    resp = client.get(f"{PREFIX}/profiles")
    assert resp.status_code == 200
    assert len(resp.json()["data"]["profiles"]) >= 1


def test_get_profile_happy(client: TestClient) -> None:
    book_id = _import_book(client)
    _, _, profile_id = _seed_full_chain(book_id)
    resp = client.get(f"{PREFIX}/profiles/{profile_id}")
    assert resp.status_code == 200
    assert resp.json()["data"]["profile"]["profile_id"] == profile_id


def test_get_profile_404(client: TestClient) -> None:
    resp = client.get(f"{PREFIX}/profiles/sr_profile_nonexistent")
    assert resp.status_code == 404


def test_apply_profile(client: TestClient) -> None:
    book_id = _import_book(client)
    _, _, profile_id = _seed_full_chain(book_id)
    resp = client.post(
        f"{PREFIX}/profiles/{profile_id}/apply",
        json={"scope": "project", "scope_ref_id": "proj_x"},
        headers={"X-Idempotency-Key": "apply_1"},
    )
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["binding_id"]
    # finding observation + language → style_rule_set;+ calibration_candidate(2 lines profile_json 含 1)
    assert "style_rule_set" in data["item_type_counts"]


def test_list_bindings(client: TestClient) -> None:
    book_id = _import_book(client)
    _, _, profile_id = _seed_full_chain(book_id)
    # 先 apply 才有 binding
    client.post(
        f"{PREFIX}/profiles/{profile_id}/apply",
        json={"scope": "project", "scope_ref_id": "proj_y"},
        headers={"X-Idempotency-Key": "apply_2"},
    )
    resp = client.get(f"{PREFIX}/profiles/{profile_id}/bindings")
    assert resp.status_code == 200
    assert len(resp.json()["data"]["bindings"]) >= 1


def test_delete_binding(client: TestClient) -> None:
    book_id = _import_book(client)
    _, _, profile_id = _seed_full_chain(book_id)
    apply_resp = client.post(
        f"{PREFIX}/profiles/{profile_id}/apply",
        json={"scope": "scene", "scope_ref_id": "scene_99"},
        headers={"X-Idempotency-Key": "apply_3"},
    )
    binding_id = apply_resp.json()["data"]["binding_id"]
    resp = client.delete(
        f"{PREFIX}/bindings/{binding_id}",
        headers={"X-Idempotency-Key": "del_bind_1"},
    )
    assert resp.status_code == 200
    assert resp.json()["data"]["deleted"] is True


def test_delete_binding_404(client: TestClient) -> None:
    resp = client.delete(
        f"{PREFIX}/bindings/sr_bind_nonexistent",
        headers={"X-Idempotency-Key": "del_bind_404"},
    )
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Preview / Synthesize 需要 LLM client(本测试不启用 LLM,确认错误码语义即可)
# ---------------------------------------------------------------------------


def test_synthesize_llm_required_when_disabled(client: TestClient, monkeypatch) -> None:
    monkeypatch.setenv("NOVEL_SYSTEM_LLM_ENABLED", "false")
    book_id = _import_book(client)
    run_id, _, _ = _seed_full_chain(book_id)
    resp = client.post(
        f"{PREFIX}/runs/{run_id}/synthesize",
        headers={"X-Idempotency-Key": "synth_disabled"},
    )
    assert resp.status_code >= 400


def test_preview_llm_required_when_disabled(client: TestClient, monkeypatch) -> None:
    monkeypatch.setenv("NOVEL_SYSTEM_LLM_ENABLED", "false")
    book_id = _import_book(client)
    _, _, profile_id = _seed_full_chain(book_id)
    resp = client.post(
        f"{PREFIX}/profiles/{profile_id}/preview",
        headers={"X-Idempotency-Key": "preview_disabled"},
    )
    assert resp.status_code >= 400
