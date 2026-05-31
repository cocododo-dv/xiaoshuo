"""PR-10 §13 — GET /api/v2/style-reference/metrics endpoint。"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from novel_system.db.session import SessionLocal
from novel_system.services.style_reference.repository import StyleReferenceRepository

PREFIX = "/api/v2/style-reference"


def _seed(events: list[dict]) -> None:
    with SessionLocal() as session:
        repo = StyleReferenceRepository(session)
        for i, ev in enumerate(events):
            repo.create_metric_event(event_id=f"sr_metric_e_{i}", **ev)
        session.commit()


def test_metrics_endpoint_empty_returns_zeros(client: TestClient) -> None:
    resp = client.get(f"{PREFIX}/metrics")
    assert resp.status_code == 200
    metrics = resp.json()["data"]["metrics"]
    assert metrics["injection_hit_rate"] == 0.0
    assert metrics["qc_gate_reject_rate"] == 0.0
    assert metrics["auto_rewrite_pass_rate"] == 0.0
    assert metrics["validation_p95_latency_ms"] == 0.0
    assert metrics["window_hours"] == 168
    assert "computed_at" in metrics
    assert metrics["sample_counts"]["injection_invoked"] == 0


def test_metrics_endpoint_respects_window_hours_param(client: TestClient) -> None:
    _seed([
        {"event_kind": "injection_invoked", "outcome": "hit"},
        {"event_kind": "injection_invoked", "outcome": "miss"},
    ])
    resp = client.get(f"{PREFIX}/metrics?window_hours=24")
    assert resp.status_code == 200
    metrics = resp.json()["data"]["metrics"]
    assert metrics["window_hours"] == 24
    assert metrics["sample_counts"]["injection_invoked"] == 2
    assert metrics["injection_hit_rate"] == 0.5


def test_metrics_endpoint_aggregates_all_5_event_kinds(client: TestClient) -> None:
    _seed([
        {"event_kind": "injection_invoked", "outcome": "hit"},
        {"event_kind": "injection_invoked", "outcome": "hit"},
        {"event_kind": "qc_gate_decided", "outcome": "pass"},
        {"event_kind": "qc_gate_decided", "outcome": "fail"},
        {"event_kind": "validation_executed", "outcome": "pass", "latency_ms": 45},
        {"event_kind": "auto_rewrite_triggered", "outcome": None},
        {"event_kind": "auto_rewrite_completed", "outcome": "success"},
    ])
    resp = client.get(f"{PREFIX}/metrics")
    assert resp.status_code == 200
    counts = resp.json()["data"]["metrics"]["sample_counts"]
    assert counts == {
        "injection_invoked": 2,
        "qc_gate_decided": 2,
        "validation_executed": 1,
        "auto_rewrite_triggered": 1,
        "auto_rewrite_completed": 1,
    }


def test_metrics_endpoint_negative_window_hours_clamped_to_zero(client: TestClient) -> None:
    """window_hours=-1 应被夹到 0(全部历史),不报错。"""
    _seed([{"event_kind": "injection_invoked", "outcome": "hit"}])
    resp = client.get(f"{PREFIX}/metrics?window_hours=-1")
    assert resp.status_code == 200
    metrics = resp.json()["data"]["metrics"]
    assert metrics["window_hours"] == 0
    assert metrics["sample_counts"]["injection_invoked"] == 1


# --- PR-22 — GET /metrics/daily ---


def test_metrics_daily_endpoint_empty_zero_fills(client: TestClient) -> None:
    resp = client.get(f"{PREFIX}/metrics/daily?window_days=7")
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["window_days"] == 7
    assert len(data["daily"]) == 7
    assert all(row["count"] == 0 for row in data["daily"])
    assert "computed_at" in data


def test_metrics_daily_endpoint_counts_injection_today(client: TestClient) -> None:
    _seed([
        {"event_kind": "injection_invoked", "outcome": "hit"},
        {"event_kind": "injection_invoked", "outcome": "miss"},
        {"event_kind": "qc_gate_decided", "outcome": "fail"},  # 不计入
    ])
    resp = client.get(f"{PREFIX}/metrics/daily?window_days=14")
    assert resp.status_code == 200
    data = resp.json()["data"]
    # 末项为今天,injection 计 2(qc 不计)
    assert data["daily"][-1]["count"] == 2
    assert sum(row["count"] for row in data["daily"]) == 2


def test_metrics_daily_endpoint_window_clamped(client: TestClient) -> None:
    resp = client.get(f"{PREFIX}/metrics/daily?window_days=999")
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["window_days"] == 90
    assert len(data["daily"]) == 90
