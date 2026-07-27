"""sync_prompt_templates：把仓库模板改动送进活动快照，但不碰界面改写过的提示词。

存在意义见工具 docstring——库内有活动 prompts 快照时，改 config/prompts.yaml 不会
到达运行中的实例，而且是**静默**不生效；整份重新导入又会把界面上改过的模板冲掉。

这个文件里最要紧的是那条红线：版本号相同、正文不同 = 作者在界面上改写过，默认必须
原样保留。提示词是创作意图的载体，工具无权替作者做决定。
"""
from __future__ import annotations

from pathlib import Path

import yaml

from novel_system.services.system_config import SystemConfigService
from novel_system.tools import sync_prompt_templates as tool


def _template(**overrides) -> dict:
    base = {
        "version": "2026-07-01.v1",
        "input_token_budget": 3600,
        "system_prompt": "You are an editor.",
        "task_prompt": "Do the work.",
        "structured_schema": {
            "type": "object",
            "required": ["scenes"],
            "properties": {"scenes": {"type": "array", "items": {"type": "object"}}},
        },
    }
    base.update(overrides)
    return base


REPO = {
    "templates": {
        "snowflake_generate_scene_details": _template(
            version="2026-07-26.v6", input_token_budget=24000,
            system_prompt="仓库新版 system", task_prompt="仓库新版 task",
        ),
        "snowflake_generate_scene_list": _template(input_token_budget=24000),
        "snowflake_workspace_assistant": _template(input_token_budget=24000),
        "chapter_plan_review": _template(input_token_budget=3200),
    }
}


def _write_repo(tmp_path: Path, monkeypatch, payload: dict) -> Path:
    path = tmp_path / "prompts.yaml"
    path.write_text(yaml.safe_dump(payload, allow_unicode=True, sort_keys=False), encoding="utf-8")
    monkeypatch.setattr(tool, "_repo_prompts_path", lambda: path)
    return path


def _activate(session, payload: dict) -> None:
    service = SystemConfigService(session)
    created = service.create_draft(
        category="prompts", yaml_raw=yaml.safe_dump(payload, allow_unicode=True, sort_keys=False),
        secrets=None, actor_ref="test",
    )
    service.activate(created["snapshot"]["snapshot_id"], actor_ref="test")


def _active(session) -> dict:
    category = SystemConfigService(session).overview()["categories"]["prompts"]
    return yaml.safe_load(category["yaml_raw"])["templates"]


def _stale_snapshot() -> dict:
    """一份「界面存过、但落后于仓库」的快照。"""
    return {
        "templates": {
            "snowflake_generate_scene_details": _template(
                version="2026-07-22.v5", input_token_budget=3600,
                system_prompt="旧版 system", task_prompt="旧版 task",
            ),
            "snowflake_generate_scene_list": _template(input_token_budget=3200),
            "chapter_plan_review": _template(input_token_budget=3200),
        }
    }


def test_dry_run_reports_the_plan_and_writes_nothing(session, tmp_path, monkeypatch, capsys):
    _write_repo(tmp_path, monkeypatch, REPO)
    _activate(session, _stale_snapshot())

    assert tool.main([]) == 0
    out = capsys.readouterr().out
    assert "干跑" in out
    assert "snowflake_generate_scene_details" in out and "3600 → 24000" in out
    # 库里一个字都没变
    live = _active(session)
    assert live["snowflake_generate_scene_details"]["input_token_budget"] == 3600
    assert live["snowflake_generate_scene_details"]["system_prompt"] == "旧版 system"


def test_execute_syncs_budget_and_text_when_the_version_moved(session, tmp_path, monkeypatch):
    _write_repo(tmp_path, monkeypatch, REPO)
    _activate(session, _stale_snapshot())

    assert tool.main(["--execute"]) == 0
    live = _active(session)

    target = live["snowflake_generate_scene_details"]
    assert target["input_token_budget"] == 24000
    assert target["version"] == "2026-07-26.v6"
    assert target["system_prompt"] == "仓库新版 system"
    assert target["task_prompt"] == "仓库新版 task"
    # 版本号没动的模板只对齐运行参数，正文原样
    assert live["snowflake_generate_scene_list"]["input_token_budget"] == 24000
    assert live["snowflake_generate_scene_list"]["system_prompt"] == "You are an editor."


def test_a_ui_edited_prompt_is_preserved_when_the_version_matches(session, tmp_path, monkeypatch, capsys):
    """红线：版本号相同而正文不同 = 界面改写，默认绝不覆盖。"""
    _write_repo(tmp_path, monkeypatch, REPO)
    snapshot = _stale_snapshot()
    # 作者在界面上改写了 scene_list 的提示词，版本号没动
    snapshot["templates"]["snowflake_generate_scene_list"]["system_prompt"] = "作者亲手改的提示词"
    _activate(session, snapshot)

    assert tool.main(["--execute"]) == 0
    out = capsys.readouterr().out
    live = _active(session)

    assert live["snowflake_generate_scene_list"]["system_prompt"] == "作者亲手改的提示词", \
        "界面上改写的提示词被工具覆盖了"
    # 同一个模板的运行参数仍然对齐——它不承载创作意图
    assert live["snowflake_generate_scene_list"]["input_token_budget"] == 24000
    assert "保留不动" in out and "--force-text" in out, "覆盖被跳过了，但没告诉操作者"


def test_force_text_overrides_a_ui_edit_when_asked(session, tmp_path, monkeypatch):
    _write_repo(tmp_path, monkeypatch, REPO)
    snapshot = _stale_snapshot()
    snapshot["templates"]["snowflake_generate_scene_list"]["system_prompt"] = "作者亲手改的提示词"
    _activate(session, snapshot)

    assert tool.main(["--force-text", "--execute"]) == 0
    assert _active(session)["snowflake_generate_scene_list"]["system_prompt"] == "You are an editor."


def test_a_template_missing_from_the_snapshot_is_added_whole(session, tmp_path, monkeypatch, capsys):
    """快照建立之后新增的模板：整份加入，否则运行时会报「模板未就绪」。"""
    _write_repo(tmp_path, monkeypatch, REPO)
    _activate(session, _stale_snapshot())  # 里面没有 snowflake_workspace_assistant

    assert tool.main(["--execute"]) == 0
    assert "snowflake_workspace_assistant" in _active(session)
    assert "将整份加入" in capsys.readouterr().out


def test_templates_outside_the_snowflake_family_are_untouched_by_default(session, tmp_path, monkeypatch):
    """默认只处理雪花族——不点名的模板一律不动。"""
    _write_repo(tmp_path, monkeypatch, {
        "templates": {
            **REPO["templates"],
            "chapter_plan_review": _template(version="9999.v9", input_token_budget=99999,
                                             system_prompt="别动我"),
        }
    })
    _activate(session, _stale_snapshot())

    assert tool.main(["--execute"]) == 0
    kept = _active(session)["chapter_plan_review"]
    assert kept["input_token_budget"] == 3200 and kept["system_prompt"] == "You are an editor."


def test_all_covers_every_template(session, tmp_path, monkeypatch):
    _write_repo(tmp_path, monkeypatch, {
        "templates": {
            **REPO["templates"],
            "chapter_plan_review": _template(version="9999.v9", input_token_budget=99999),
        }
    })
    _activate(session, _stale_snapshot())

    assert tool.main(["--all", "--execute"]) == 0
    assert _active(session)["chapter_plan_review"]["input_token_budget"] == 99999


def test_an_explicit_template_selection_limits_the_blast_radius(session, tmp_path, monkeypatch):
    _write_repo(tmp_path, monkeypatch, REPO)
    _activate(session, _stale_snapshot())

    assert tool.main(["--template", "snowflake_generate_scene_details", "--execute"]) == 0
    live = _active(session)
    assert live["snowflake_generate_scene_details"]["input_token_budget"] == 24000
    assert live["snowflake_generate_scene_list"]["input_token_budget"] == 3200, "点名之外的模板被改了"


def test_no_active_snapshot_says_the_repo_file_is_already_live(session, tmp_path, monkeypatch, capsys):
    _write_repo(tmp_path, monkeypatch, REPO)

    assert tool.main([]) == 0
    assert "config/prompts.yaml" in capsys.readouterr().out


def test_an_already_synced_snapshot_is_a_no_op(session, tmp_path, monkeypatch, capsys):
    _write_repo(tmp_path, monkeypatch, REPO)
    _activate(session, {"templates": dict(REPO["templates"])})

    assert tool.main(["--execute"]) == 0
    assert "无需改动" in capsys.readouterr().out


def test_a_template_missing_from_the_repo_is_reported_not_crashed(session, tmp_path, monkeypatch, capsys):
    _write_repo(tmp_path, monkeypatch, REPO)
    _activate(session, _stale_snapshot())

    assert tool.main(["--template", "no_such_template"]) == 0
    assert "没有这个模板" in capsys.readouterr().out


def test_the_written_snapshot_stays_valid_and_loadable(session, tmp_path, monkeypatch):
    """写回的快照必须过 prompts 校验并能被模板加载器读出来——否则等于把实例改瘫。"""
    from novel_system.services.prompt_builder import load_prompt_templates

    _write_repo(tmp_path, monkeypatch, REPO)
    _activate(session, _stale_snapshot())
    assert tool.main(["--execute"]) == 0

    templates = load_prompt_templates()
    target = templates["snowflake_generate_scene_details"]
    assert target.input_token_budget == 24000
    assert target.version == "2026-07-26.v6"
    assert target.system_prompt == "仓库新版 system"
