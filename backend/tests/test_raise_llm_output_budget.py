"""raise_llm_output_budget：只抬输出预算，不碰界面配好的路由。

存在意义见工具 docstring——库内有活动 models 快照时，改 config/models.yaml 不会
到达运行中的实例；而整份重新导入会把界面上配的 provider/model 一起冲掉。
"""
from __future__ import annotations

import yaml

from novel_system.services.system_config import SystemConfigService
from novel_system.tools import raise_llm_output_budget as tool

BASE_CONFIG = {
    "model_profiles": {"quality_strong": {"description": "d", "provider": "openai_compatible", "model": "gpt-5"}},
    "task_routing": {
        "snowflake_step_generate": {
            "provider": "openai_compatible", "model": "my-relay-model", "temperature": 0.25,
            "max_output_tokens": 3200, "response_format": "json_object", "model_profile": "quality_strong",
        },
        "scene_draft": {
            "provider": "openai_compatible", "model": "another-model", "temperature": 0.7,
            "max_output_tokens": 2400, "response_format": "text",
        },
    },
}


def _activate(session, payload: dict) -> None:
    service = SystemConfigService(session)
    created = service.create_draft(
        category="models", yaml_raw=yaml.safe_dump(payload, allow_unicode=True, sort_keys=False),
        secrets=None, actor_ref="test",
    )
    service.activate(created["snapshot"]["snapshot_id"], actor_ref="test")


def _active_routing(session) -> dict:
    category = SystemConfigService(session).overview()["categories"]["models"]
    return yaml.safe_load(category["yaml_raw"])["task_routing"]


def test_dry_run_changes_nothing(session, capsys):
    _activate(session, BASE_CONFIG)

    assert tool.main([]) == 0
    out = capsys.readouterr().out
    assert "3200 → 8192" in out and "干跑" in out
    assert _active_routing(session)["snowflake_step_generate"]["max_output_tokens"] == 3200


def test_execute_raises_only_the_budget_and_keeps_ui_routing(session, capsys):
    _activate(session, BASE_CONFIG)

    assert tool.main(["--execute"]) == 0
    routing = _active_routing(session)

    target = routing["snowflake_step_generate"]
    assert target["max_output_tokens"] == 8192
    # 界面配的 provider/model/temperature 必须原样保留——这是不做整份重导的全部理由
    assert target["model"] == "my-relay-model"
    assert target["provider"] == "openai_compatible"
    assert target["temperature"] == 0.25
    # 未点名的节点一律不动
    assert routing["scene_draft"] == BASE_CONFIG["task_routing"]["scene_draft"]


def test_already_high_enough_is_a_no_op(session, capsys):
    payload = {**BASE_CONFIG, "task_routing": {
        **BASE_CONFIG["task_routing"],
        "snowflake_step_generate": {**BASE_CONFIG["task_routing"]["snowflake_step_generate"],
                                    "max_output_tokens": 8192},
    }}
    _activate(session, payload)

    assert tool.main(["--execute"]) == 0
    assert "无需改动" in capsys.readouterr().out


def test_node_all_covers_every_low_node(session, capsys):
    _activate(session, BASE_CONFIG)

    assert tool.main(["--node", "all", "--floor", "4096", "--execute"]) == 0
    routing = _active_routing(session)
    assert routing["snowflake_step_generate"]["max_output_tokens"] == 4096
    assert routing["scene_draft"]["max_output_tokens"] == 4096


def test_no_active_snapshot_says_the_repo_file_is_live(session, capsys):
    assert tool.main([]) == 0
    assert "config/models.yaml" in capsys.readouterr().out
