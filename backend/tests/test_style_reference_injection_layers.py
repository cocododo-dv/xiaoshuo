"""注入只读辅助端点:/injection/task-defaults + /injection/layers。

闭合前端「注入应用」页两处示意数据:任务卡片的默认策略/刷新周期、
「叠加注入层」卡片(此前为写死的 SR_LAYER_STACK)。
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from novel_system.api.app import create_app
from novel_system.db.session import SessionLocal
from novel_system.services.llm_node_registry import get_llm_node_spec
from novel_system.services.style_reference.injection import InjectionService
from novel_system.services.style_reference.repository import StyleReferenceRepository

PREFIX = "/api/v2/style-reference"


def _seed_profile(seed: str) -> str:
    with SessionLocal() as session:
        repo = StyleReferenceRepository(session)
        book_id = f"sr_book_il_{seed}"
        repo.create_book(
            book_id=book_id,
            title="t",
            source_kind="upload",
            cloud_policy="segments_only",
            text_checksum=f"chk_il_{seed}",
            total_chars=1000,
            status="ready",
            stats_json={"rights_declaration": {
                "declared": True, "analysis_rights": True, "send_rights": True,
            }},
        )
        run_id = f"sr_run_il_{seed}"
        profile_id = f"sr_profile_il_{seed}"
        repo.create_run(run_id=run_id, book_id=book_id, status="done", phase="done")
        repo.create_profile(
            profile_id=profile_id,
            book_id=book_id,
            run_id=run_id,
            title=f"画像{seed}",
            status="active",
            profile_json={
                "narrative_summary": "短句白描,逗号顿连。",
                "style_features": ["短句为主", "喻体即收"],
                "banned_replication_rules": ["禁止排比抒情"],
            },
            coverage_json={},
            source_finding_ids_json=[],
        )
        session.commit()
    return profile_id


def _bind(profile_id: str, *, binding_id: str, scope: str, scope_ref_id: str, strategy: str = "A") -> None:
    with SessionLocal() as session:
        StyleReferenceRepository(session).create_binding(
            binding_id=binding_id,
            profile_id=profile_id,
            scope=scope,
            scope_ref_id=scope_ref_id,
            task_type="scene_generation",
            strategy=strategy,
            config_json={},
            status="active",
        )
        session.commit()


# ---------------------------------------------------------------------------
# task-defaults
# ---------------------------------------------------------------------------


def test_task_defaults_endpoint_matches_node_registry() -> None:
    with TestClient(create_app()) as client:
        resp = client.get(f"{PREFIX}/injection/task-defaults")
        assert resp.status_code == 200
        tasks = {t["task_type"]: t for t in resp.json()["data"]["tasks"]}
    assert set(tasks) == {
        "project_init", "scene_generation", "fine_tuning",
        "long_form_continuation", "key_chapter",
    }
    assert tasks["scene_generation"]["default_strategy"] == "mixed"
    assert tasks["key_chapter"]["default_strategy"] == "C"
    # refresh 真源:llm_node_registry 的 long_form_continuation 节点
    spec = get_llm_node_spec("long_form_continuation")
    assert tasks["long_form_continuation"]["refresh_every_chars"] == spec.refresh_every_chars
    assert tasks["long_form_continuation"]["refresh_every_chars"] > 0
    assert tasks["scene_generation"]["refresh_every_chars"] == 0


# ---------------------------------------------------------------------------
# layers
# ---------------------------------------------------------------------------


def test_layers_endpoint_empty_when_no_bindings() -> None:
    with TestClient(create_app()) as client:
        resp = client.get(f"{PREFIX}/injection/layers", params={"project_id": "proj_il_none"})
        assert resp.status_code == 200
        data = resp.json()["data"]
    assert data["layers"] == []
    assert data["merged"] is None
    assert data["budget_total"] > 0


def test_layers_single_binding_gets_full_budget() -> None:
    profile_id = _seed_profile("single")
    _bind(profile_id, binding_id="sr_bind_il_single", scope="project", scope_ref_id="proj_il_s")
    with TestClient(create_app()) as client:
        resp = client.get(f"{PREFIX}/injection/layers", params={"project_id": "proj_il_s"})
        data = resp.json()["data"]
    assert len(data["layers"]) == 1
    layer = data["layers"][0]
    assert layer["scope"] == "project"
    assert layer["weight"] == 1
    assert layer["budget_chars"] == data["budget_total"]
    assert layer["profile_title"] == "画像single"
    assert data["merged"]["layer_count"] == 1
    assert data["merged"]["prefix_chars"] > 0


def test_layers_stacked_weights_and_order() -> None:
    """project + scene 双层:由泛到具体,scene 层权重/预算更大,合并概要一致。"""
    profile_id = _seed_profile("stack")
    _bind(profile_id, binding_id="sr_bind_il_p", scope="project", scope_ref_id="proj_il_x")
    _bind(profile_id, binding_id="sr_bind_il_sc", scope="scene", scope_ref_id="scene_il_1", strategy="mixed")
    with TestClient(create_app()) as client:
        resp = client.get(
            f"{PREFIX}/injection/layers",
            params={"project_id": "proj_il_x", "scene_id": "scene_il_1"},
        )
        data = resp.json()["data"]
    assert [l["scope"] for l in data["layers"]] == ["project", "scene"]
    weights = [l["weight"] for l in data["layers"]]
    assert weights == [1, 2]
    total = data["budget_total"]
    assert data["layers"][0]["budget_chars"] == total * 1 // 3
    assert data["layers"][1]["budget_chars"] == total * 2 // 3
    assert data["layers"][1]["rank"] < data["layers"][0]["rank"]  # scene 更具体
    assert data["merged"]["layer_count"] == 2
    # 合并 strategy 取最具体层
    assert data["merged"]["strategy"] == "mixed"
    assert all(l["fragment_count"] >= 1 for l in data["layers"])


def test_describe_layers_is_read_only() -> None:
    """describe 不写 metric 事件(可随 UI 反复调用)。"""
    profile_id = _seed_profile("ro")
    _bind(profile_id, binding_id="sr_bind_il_ro", scope="project", scope_ref_id="proj_il_ro")
    with SessionLocal() as session:
        from novel_system.db.models import StyleReferenceMetricEvent

        before = session.query(StyleReferenceMetricEvent).count()
        InjectionService(session).describe_binding_layers("proj_il_ro", "scene_generation")
        after = session.query(StyleReferenceMetricEvent).count()
    assert after == before
