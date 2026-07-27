"""把库内活动 models 配置里过低的 max_output_tokens 抬到下限。

为什么需要这个工具：一旦系统配置界面存过一版 models 配置，运行时读的就是库内活动
快照，仓库里的 `config/models.yaml` 便不再生效——改了文件也不会到达正在跑的实例。
而整份重新导入 models.yaml 会把界面上配好的 provider/model 路由（比如自建中转的
模型名）一起冲掉，所以这里只改 max_output_tokens，其余字段原样保留。

背景：整步生成一次要吐出全表（场景列表/场景规划几十场、角色全档案多人多维），
3200 装不下——reasoning 模型光思考就能吃满，正文被 max_tokens 砍断。

    python -m novel_system.tools.raise_llm_output_budget            # 干跑，只看会改什么
    python -m novel_system.tools.raise_llm_output_budget --execute  # 落库并激活新快照
"""

from __future__ import annotations

import argparse
import json
from typing import Any

import yaml

from novel_system.db.session import SessionLocal
from novel_system.services.system_config import SystemConfigService

# 客户端降级阶梯的上限（MAX_OUTPUT_TOKENS_CEILING），配置值与之对齐才有意义。
DEFAULT_FLOOR = 8192
# 默认只管整步生成——它是唯一"一次调用要输出整张表"的节点。
DEFAULT_NODES = ("snowflake_step_generate",)


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--floor", type=int, default=DEFAULT_FLOOR, help=f"输出预算下限（默认 {DEFAULT_FLOOR}）")
    parser.add_argument(
        "--node",
        action="append",
        dest="nodes",
        help=f"要抬高的节点，可重复；默认 {', '.join(DEFAULT_NODES)}。传 --node all 表示全部节点",
    )
    parser.add_argument("--execute", action="store_true", help="真正写入并激活新快照（默认只干跑）")
    return parser.parse_args(argv)


def _targets(routing: dict[str, Any], nodes: list[str] | None, floor: int) -> dict[str, int]:
    selected = nodes or list(DEFAULT_NODES)
    keys = routing.keys() if selected == ["all"] else selected
    hits: dict[str, int] = {}
    for key in keys:
        config = routing.get(key)
        if not isinstance(config, dict):
            continue
        current = config.get("max_output_tokens")
        if isinstance(current, int) and current < floor:
            hits[key] = current
    return hits


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    session = SessionLocal()
    try:
        service = SystemConfigService(session)
        category = service.overview()["categories"]["models"]
        snapshot = category.get("active_snapshot")
        if not snapshot:
            print("库内没有活动的 models 配置快照——运行时直接读 config/models.yaml，改文件即可生效。")
            return 0

        payload = yaml.safe_load(category["yaml_raw"]) or {}
        routing = payload.get("task_routing")
        if not isinstance(routing, dict):
            print("活动快照里没有 task_routing，无需处理。")
            return 0

        hits = _targets(routing, args.nodes, args.floor)
        if not hits:
            print(f"活动快照 v{snapshot['version']}：目标节点的输出预算都已达到 {args.floor}，无需改动。")
            return 0

        print(f"活动快照 v{snapshot['version']}（{snapshot['snapshot_id']}）将被抬高的节点：")
        for node_id, current in sorted(hits.items()):
            print(f"  {node_id}: {current} → {args.floor}")

        if not args.execute:
            print("\n干跑结束——加 --execute 才会写入并激活新快照。")
            return 0

        for node_id in hits:
            routing[node_id]["max_output_tokens"] = args.floor
        created = service.create_draft(
            category="models",
            yaml_raw=yaml.safe_dump(payload, allow_unicode=True, sort_keys=False),
            secrets=None,
            actor_ref="raise_llm_output_budget",
        )
        activated = service.activate(created["snapshot"]["snapshot_id"], actor_ref="raise_llm_output_budget")
        print(f"\n已激活新快照 v{activated['snapshot']['version']}（{activated['snapshot']['snapshot_id']}）。")
        print("重启后端后生效。")
        return 0
    finally:
        session.close()


if __name__ == "__main__":  # pragma: no cover - CLI 入口
    raise SystemExit(main())
