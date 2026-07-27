"""把仓库 config/prompts.yaml 里的模板改动同步进库内活动 prompts 快照。

为什么需要这个工具：一旦系统配置界面存过一版 prompts 配置，运行时读的就是库内活动
快照（`load_active_config_payload("prompts")`），仓库里的 `config/prompts.yaml` 便
不再生效——改了文件也不会到达正在跑的实例，而且是**静默**不生效。整份重新导入又会
把界面上改过的模板一起冲掉，所以这里逐模板、逐字段地合并。

**不会覆盖作者在界面上改过的提示词**：仅当仓库与快照的 `version` 不同时才同步正文
（版本号变了 = 仓库这一版有意取代旧版）；`version` 相同而正文不同，判定为界面上的
本地改写，原样保留并在报告里点名。`input_token_budget` 是代码侧实测定出的运行参数、
不承载创作意图，只要不同就对齐。

默认只处理雪花工作台模板族（名字以 `snowflake_` 开头的那 14 个），因为「库内快照盖过
仓库文件」这个坑最常在改这一族时踩到。

    python -m novel_system.tools.sync_prompt_templates              # 干跑，只看会改什么
    python -m novel_system.tools.sync_prompt_templates --execute    # 落库并激活新快照
    python -m novel_system.tools.sync_prompt_templates --all        # 处理全部模板
    python -m novel_system.tools.sync_prompt_templates --template snowflake_generate_scene_details
    python -m novel_system.tools.sync_prompt_templates --force-text # 连界面改写的正文一起覆盖
"""

from __future__ import annotations

import argparse
from copy import deepcopy
from pathlib import Path
from typing import Any

import yaml

from novel_system.db.session import SessionLocal
from novel_system.services.system_config import SystemConfigService

# 版本号变了才同步的字段——它们承载创作意图，可能被作者在界面上改过。
TEXT_FIELDS = ("version", "system_prompt", "task_prompt", "structured_schema")
# 运行参数，与创作意图无关，不同即对齐。
RUNTIME_FIELDS = ("input_token_budget",)
DEFAULT_PREFIX = "snowflake_"
ACTOR = "sync_prompt_templates"


def _repo_prompts_path() -> Path:
    return Path(__file__).resolve().parents[4] / "config" / "prompts.yaml"


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "--template", action="append", dest="templates",
        help=f"要同步的模板名，可重复；默认全部 {DEFAULT_PREFIX}* 模板",
    )
    parser.add_argument("--all", action="store_true", help="处理仓库文件里的全部模板")
    parser.add_argument(
        "--force-text", action="store_true",
        help="版本号相同但正文不同（界面改写）时也覆盖——默认保留界面版本",
    )
    parser.add_argument("--execute", action="store_true", help="真正写入并激活新快照（默认只干跑）")
    return parser.parse_args(argv)


def _select(repo_templates: dict[str, Any], args: argparse.Namespace) -> list[str]:
    if args.templates:
        return list(args.templates)
    if args.all:
        return sorted(repo_templates)
    return sorted(name for name in repo_templates if name.startswith(DEFAULT_PREFIX))


def plan_changes(
    repo_templates: dict[str, Any],
    snapshot_templates: dict[str, Any],
    names: list[str],
    *,
    force_text: bool,
) -> tuple[list[dict[str, Any]], list[str]]:
    """算出每个模板要改什么。返回 (变更计划, 问题清单)。"""
    changes: list[dict[str, Any]] = []
    problems: list[str] = []
    for name in names:
        repo = repo_templates.get(name)
        if not isinstance(repo, dict):
            problems.append(f"{name}: 仓库 config/prompts.yaml 里没有这个模板")
            continue
        live = snapshot_templates.get(name)
        if not isinstance(live, dict):
            changes.append({"name": name, "kind": "add", "fields": {}, "skipped_text": False})
            continue

        fields: dict[str, Any] = {}
        for key in RUNTIME_FIELDS:
            if key in repo and repo[key] != live.get(key):
                fields[key] = {"from": live.get(key), "to": repo[key]}

        version_differs = repo.get("version") != live.get("version")
        text_differs = any(
            key in repo and repo[key] != live.get(key) for key in TEXT_FIELDS if key != "version"
        )
        skipped_text = False
        if version_differs or (text_differs and force_text):
            for key in TEXT_FIELDS:
                if key in repo and repo[key] != live.get(key):
                    fields[key] = {"from": live.get(key), "to": repo[key]}
        elif text_differs:
            # 版本号相同而正文不同 = 界面上改写过，保留它
            skipped_text = True

        if fields or skipped_text:
            changes.append(
                {"name": name, "kind": "update", "fields": fields, "skipped_text": skipped_text}
            )
    return changes, problems


def _describe(key: str, delta: dict[str, Any]) -> str:
    before, after = delta["from"], delta["to"]
    if isinstance(after, str) or isinstance(before, str):
        if key == "version":
            return f"    {key}: {before!r} → {after!r}"
        return f"    {key}: 正文改写（{len(str(before or ''))} → {len(str(after))} 字符）"
    if isinstance(after, dict):
        return f"    {key}: 结构改写"
    return f"    {key}: {before} → {after}"


def _apply(snapshot_templates: dict[str, Any], repo_templates: dict[str, Any], changes: list[dict[str, Any]]) -> None:
    for change in changes:
        name = change["name"]
        if change["kind"] == "add":
            snapshot_templates[name] = deepcopy(repo_templates[name])
            continue
        for key, delta in change["fields"].items():
            snapshot_templates[name][key] = delta["to"]


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    repo_path = _repo_prompts_path()
    try:
        repo_payload = yaml.safe_load(repo_path.read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError) as exc:
        print(f"读不了仓库提示词文件 {repo_path}：{exc}")
        return 2
    repo_templates = repo_payload.get("templates")
    if not isinstance(repo_templates, dict):
        print(f"{repo_path} 里没有 templates 段，无法同步。")
        return 2

    session = SessionLocal()
    try:
        service = SystemConfigService(session)
        category = service.overview()["categories"]["prompts"]
        snapshot = category.get("active_snapshot")
        if not snapshot:
            print("库内没有活动的 prompts 快照——运行时直接读 config/prompts.yaml，改文件即已生效，无需同步。")
            return 0

        payload = yaml.safe_load(category["yaml_raw"]) or {}
        snapshot_templates = payload.get("templates")
        if not isinstance(snapshot_templates, dict):
            print("活动快照里没有 templates 段，形状异常——请先在系统配置界面检查这一版。")
            return 2

        names = _select(repo_templates, args)
        changes, problems = plan_changes(
            repo_templates, snapshot_templates, names, force_text=args.force_text
        )
        for problem in problems:
            print(f"跳过 {problem}")

        actionable = [c for c in changes if c["fields"] or c["kind"] == "add"]
        # 只被保留、没有任何可写改动的模板单独列——避免与上面的清单重复报一遍
        preserved_only = [c for c in changes if c["skipped_text"] and c not in actionable]

        print(f"\n活动快照 v{snapshot['version']}（{snapshot['snapshot_id']}）· 检查 {len(names)} 个模板")
        if not actionable and not preserved_only:
            print("仓库与快照一致，无需改动。")
            return 0

        for change in actionable:
            if change["kind"] == "add":
                print(f"  + {change['name']}：快照里没有，将整份加入")
                continue
            print(f"  ~ {change['name']}")
            for key, delta in change["fields"].items():
                print(_describe(key, delta))
            if change["skipped_text"]:
                print("    （正文版本号相同但内容不同 → 判为界面改写，保留不动）")
        for change in preserved_only:
            print(f"  = {change['name']}：正文在界面上改写过（版本号未变），保留不动")

        if (preserved_only or any(c["skipped_text"] for c in actionable)) and not args.force_text:
            print("\n提示：上面标「保留不动」的模板若确实要用仓库版本，加 --force-text。")

        if not actionable:
            print("\n没有需要写入的改动。")
            return 0
        if not args.execute:
            print("\n干跑结束——加 --execute 才会写入并激活新快照。")
            return 0

        _apply(snapshot_templates, repo_templates, actionable)
        created = service.create_draft(
            category="prompts",
            yaml_raw=yaml.safe_dump(payload, allow_unicode=True, sort_keys=False),
            secrets=None,
            actor_ref=ACTOR,
        )
        activated = service.activate(created["snapshot"]["snapshot_id"], actor_ref=ACTOR)
        print(f"\n已激活新快照 v{activated['snapshot']['version']}（{activated['snapshot']['snapshot_id']}）。")
        print("重启后端后生效。")
        return 0
    finally:
        session.close()


if __name__ == "__main__":  # pragma: no cover - CLI 入口
    raise SystemExit(main())
