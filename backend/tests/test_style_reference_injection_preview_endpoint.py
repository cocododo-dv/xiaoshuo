"""PR-9 §5.1 — GET /bindings/{id}/injection-preview + POST /profiles/{id}/injection-preview。"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from novel_system.db.session import SessionLocal
from novel_system.services.style_reference.repository import StyleReferenceRepository

PREFIX = "/api/v2/style-reference"


def _seed_profile_with_binding(
    *,
    seed: str,
    profile_status: str = "active",
    strategy: str = "A",
    config_json: dict | None = None,
) -> tuple[str, str]:
    book_id = f"sr_book_{seed}"
    run_id = f"sr_run_{seed}"
    profile_id = f"sr_profile_{seed}"
    binding_id = f"sr_bind_{seed}"
    with SessionLocal() as session:
        repo = StyleReferenceRepository(session)
        repo.create_book(
            book_id=book_id, title="t", source_kind="upload", cloud_policy="local_only",
            text_checksum=f"chk_{seed}", total_chars=10, status="ready", stats_json={},
        )
        repo.create_run(run_id=run_id, book_id=book_id, status="done", phase="done")
        repo.create_profile(
            profile_id=profile_id, book_id=book_id, run_id=run_id, title="t",
            status=profile_status,
            profile_json={
                "narrative_summary": "短句白话",
                "style_features": ["短句", "动词驱动"],
                "banned_replication_rules": ["禁堆砌"],
            },
            coverage_json={},
            source_finding_ids_json=[],
        )
        repo.create_binding(
            binding_id=binding_id, profile_id=profile_id,
            scope="project", scope_ref_id=f"proj_{seed}",
            task_type="scene_generation", strategy=strategy,
            config_json=config_json or {}, status="active",
        )
        session.commit()
    return binding_id, profile_id


def test_get_binding_preview_200_happy(client: TestClient) -> None:
    binding_id, _ = _seed_profile_with_binding(seed="gethappy", strategy="A")
    resp = client.get(f"{PREFIX}/bindings/{binding_id}/injection-preview")
    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]
    assert "fragments" in data
    assert "prefix" in data
    assert data["fragments"]["strategy"] == "A"
    assert "短句" in data["fragments"]["positive_block"]
    assert data["prefix"].startswith("[STYLE_REFERENCE]\n")


def test_get_binding_preview_404(client: TestClient) -> None:
    resp = client.get(f"{PREFIX}/bindings/sr_bind_nonexistent/injection-preview")
    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "STYLE_REFERENCE_BINDING_NOT_FOUND"


def test_dryrun_preview_200(client: TestClient) -> None:
    _, profile_id = _seed_profile_with_binding(seed="dryrun")
    resp = client.post(
        f"{PREFIX}/profiles/{profile_id}/injection-preview",
        json={
            "strategy": "mixed",
            "intensity": 70,
            "sub_dimensions": ["language.vocabulary"],
            "include_positive": True,
            "include_forbidden": True,
            "include_metric": False,
        },
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]
    assert data["fragments"]["strategy"] == "mixed"
    assert "短句" in data["fragments"]["positive_block"]
    # metric 关闭 → metric_anchor_block 空
    assert data["fragments"]["metric_anchor_block"] == ""


def test_dryrun_preview_422_invalid_intensity(client: TestClient) -> None:
    _, profile_id = _seed_profile_with_binding(seed="invalid")
    resp = client.post(
        f"{PREFIX}/profiles/{profile_id}/injection-preview",
        json={"strategy": "mixed", "intensity": 999},  # 超出 0-100
    )
    assert resp.status_code == 422


def test_dryrun_preview_404_profile(client: TestClient) -> None:
    resp = client.post(
        f"{PREFIX}/profiles/sr_profile_nonexistent/injection-preview",
        json={"strategy": "A"},
    )
    assert resp.status_code == 404


def test_dryrun_strategy_a_ignores_intensity_and_sub_dim(client: TestClient) -> None:
    """strategy=A 时 intensity / sub_dimensions 不参与渲染(全文注入)。"""
    _, profile_id = _seed_profile_with_binding(seed="strata")
    resp_a = client.post(
        f"{PREFIX}/profiles/{profile_id}/injection-preview",
        json={"strategy": "A", "intensity": 0, "sub_dimensions": []},
    )
    resp_a2 = client.post(
        f"{PREFIX}/profiles/{profile_id}/injection-preview",
        json={"strategy": "A", "intensity": 100, "sub_dimensions": ["language.vocabulary"]},
    )
    assert resp_a.status_code == 200
    assert resp_a2.status_code == 200
    # A 全文注入,positive_block 长度应一致(不受 intensity 影响)
    a_pos = resp_a.json()["data"]["fragments"]["positive_block"]
    a2_pos = resp_a2.json()["data"]["fragments"]["positive_block"]
    assert a_pos == a2_pos


def test_dryrun_mixed_empty_sub_dim_equals_all_selected(client: TestClient) -> None:
    """MIXED 时 sub_dimensions=[] 等同全选(_render_forbidden 兜底)。"""
    _, profile_id = _seed_profile_with_binding(seed="empty_subdim")
    resp_empty = client.post(
        f"{PREFIX}/profiles/{profile_id}/injection-preview",
        json={"strategy": "mixed", "intensity": 50, "sub_dimensions": []},
    )
    assert resp_empty.status_code == 200
    # banned_replication_rules 应当在 forbidden_block 中(sub_dim=[] 不过滤)
    assert "禁堆砌" in resp_empty.json()["data"]["fragments"]["forbidden_block"]
