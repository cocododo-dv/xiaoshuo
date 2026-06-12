"""构思视图候选生成节点（FE-ALIGN G5：snowflake_step_candidates）。"""

from __future__ import annotations

from novel_system.services.llm_node_registry import get_llm_node_spec
from novel_system.services.snowflake_workspace_llm import _normalize_candidates_output


def _create_project(client) -> str:
    response = client.post(
        "/api/v2/projects",
        json={"title": "候选之书", "outline_text": "构思候选验证用项目。"},
        headers={"X-Idempotency-Key": "fe-cands-project"},
    )
    assert response.status_code == 200, response.text
    return response.json()["data"]["project"]["project_id"]


def test_fe_candidates_llm_disabled_falls_back(client) -> None:
    pid = _create_project(client)
    response = client.post(
        f"/api/v2/projects/{pid}/snowflake-workspace/steps/one_sentence_summary/fe-candidates",
        json={"context": "【01 读者定位】文学悬疑", "draft": "她发现恩师改写了档案。", "target_chars": 120},
        headers={"X-Idempotency-Key": "fe-cands-fallback"},
    )
    assert response.status_code == 200, response.text
    data = response.json()["data"]
    # LLM 关闭：诚实回退（FE 据此展示本地启发式候选 + 引导），绝不伪造生成
    assert data["source"] == "fallback"
    assert data["candidates"] == []
    assert data["llm_call_id"] is None


def test_fe_candidates_rejects_unknown_step(client) -> None:
    pid = _create_project(client)
    response = client.post(
        f"/api/v2/projects/{pid}/snowflake-workspace/steps/nonsense/fe-candidates",
        json={},
        headers={"X-Idempotency-Key": "fe-cands-bad-step"},
    )
    assert response.status_code in {400, 404}


def test_normalize_candidates_output_clips_to_contract_shape() -> None:
    raw = {
        "candidates": [
            {"label": "一个超长的标签会被截断", "tag": "x" * 40, "text": "  候选正文一  ", "notes": ["很长的要点会被截断啊", "短", "", "第四条被丢弃"]},
            {"label": "", "tag": "", "text": "候选正文二", "notes": "not-a-list"},
            {"text": "   "},
            {"text": "候选正文三"},
            {"text": "第五条被截掉"},
        ]
    }
    out = _normalize_candidates_output(raw)["candidates"]
    assert [c["text"] for c in out] == ["候选正文一", "候选正文二", "候选正文三"]
    assert len(out[0]["label"]) <= 8
    assert len(out[0]["tag"]) <= 16
    assert all(len(n) <= 10 for n in out[0]["notes"]) and len(out[0]["notes"]) == 2
    assert out[1]["label"].startswith("方向")
    assert out[1]["notes"] == []


def test_candidates_node_registered_with_routing_and_template() -> None:
    """三件套铁律：registry + models.yaml task_routing + prompts.yaml 模板缺一不可。"""
    import yaml
    from pathlib import Path

    node = get_llm_node_spec("snowflake_step_candidates")
    assert node is not None, "registry missing snowflake_step_candidates"
    root = Path(__file__).resolve().parents[2]
    models = yaml.safe_load((root / "config" / "models.yaml").read_text(encoding="utf-8"))
    assert "snowflake_step_candidates" in models.get("task_routing", {})
    prompts = yaml.safe_load((root / "config" / "prompts.yaml").read_text(encoding="utf-8"))
    template = prompts.get("templates", {}).get("snowflake_step_candidates")
    assert template and template.get("structured_schema", {}).get("required") == ["candidates"]
