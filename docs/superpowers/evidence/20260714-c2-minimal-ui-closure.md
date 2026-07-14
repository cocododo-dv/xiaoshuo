# C2 最小真实 UI 闭环证据（1 章 × 1 场）

> 执行日期：2026-07-14
>
> 分支：`codex/outcome-governance-closure`
>
> 代码基线：`d01a338` 及本轮 C2 收尾修复
>
> 结论：最小真实 UI 链已完成；原始自动 outcome gate 仍为失败，C2 与五章发布门未关闭。

## 1. 范围与对象

- 真实数据库：`E:/codex/xiaoshuo/codex/backend/novel_system.db`
- 项目：`PRJ_7F82A90111`（玻璃雨停在零点 · 20260714220922）
- 章节：`CDBQA_20260714220922_01`
- 场景：`CDBQA_20260714220922_01_SC01`
- 自动运行目录：`output/playwright/currentdb-three-chapter-qa-20260714-220922`
- 规模：1 章 × 1 场，仅用于最低成本主链验证，不代表 5 章 × 3 场发布验收。

## 2. 执行事实

1. 自动 harness 经页面创建空白项目，导入/批准雪花十步并物化一章一场。
2. 场景通过真实模型生成并进入匿名候选终选；页面完成候选选择和预算追加。
3. 修复前，预算追加后的新幂等续跑在 `soft_qc_ready` 断点返回 409。原始 `outcome-gate.json` 因此如实判定 FAIL，没有覆盖或伪造。
4. 根因有两层：
   - 作者可见 `soft_qc_patch_required` 被错误当成恢复真值，遮蔽了持久化 post-selection checkpoint。
   - 新的 HTTP 幂等续跑把上一 HTTP 续跑产物错误按 scene job 校验，强制要求不存在的 `run_job_id`。
5. 修复后在同一失败现场重新调用续跑，HTTP 200，返回 `author_state=quality_warning`、`can_archive=true`，已完成产物未重复生成。
6. 页面点击“采纳并归档”，确认队列和详情均为“已归档”；页面再点击“生成/刷新章节汇总”，显示“章节汇总已刷新”。

## 3. 服务端终态

| 对象 | 终态 |
|---|---|
| SceneRunState | `scene_status=archived`；token budget 61560，used 40651；provider attempts 12/32 |
| FinalScene | `final_scene_CDBQA_20260714220922_01_SC01_adopt_11804ed748`；非空；SQLite `length(trim(content))=381` |
| 页面正文计数 | 359 字；已写回正文文档与场景卡 |
| ChapterState | passed scene 1，backfill pending 0，final memory 指向 `chapter_memory_final_CDBQA_20260714220922_01_v1` |
| ChapterMemory | final，381 字符，`active_flag=1`，`runtime_eligible=1`，basis=`direct_read` |

需保留的状态债务：归档后 `run_execution_status=failed`、`run_checkpoint=soft_qc_ready` 仍在，页面运行任务横幅仍显示旧 `awaiting_candidate_selection`。权威作者态和成稿不受影响，但运维/展示会被误导。

## 4. 新鲜回归

- 前端：14 个文件、130 tests passed。
- 前端生产构建：Vite build passed；保留既有大 chunk 与动态/静态混合导入 warning。
- 后端关键链路：候选 gate 与断点恢复 22 passed；新增“新幂等执行继承完整 soft 子游标”回归先红后绿。
- harness 契约：11 passed；诊断规模的候选门槛改为 `min(3, plannedSceneList.length)`，完整 15 场仍要求至少三次终选。
- Python `compileall` 与 `git diff --check` 通过。

## 5. 证据与哈希

| 文件 | SHA-256 | 说明 |
|---|---|---|
| `outcome-gate.json` | `3D0D23E48AC22B3D3C9C1C0ED28ED3AE4FB581D6B25FE44A03667E23656BCC3A` | 修复前自动运行的真实 FAIL |
| `qa-live-results.json` | `FBA5EDA3130ABCBCD749776340C2DDEED21AAE2203C82244CDFE906696D2C8A0` | 自动运行明细与失败现场 |
| `manual-ui-archive-after-resume.png` | `5D91C76656EBC621E24D65120EA2949922B677D11C19FDCDA50BC939CE904D01` | 修复后页面归档终态 |
| `manual-ui-chapter-aggregate.png` | `FE161112CEBA25EB1ECBE9DD13C17940669D339674FE14B25D817D0545D6814A` | 页面章节汇总成功 |

截图是原失败运行的人工 UI 续跑补充，不会反向修改自动 gate 回执。

## 6. 未完成与影响

- 未运行 1 章 × 3 场和 5 章 × 3 场；无法证明吞吐、跨场状态、至少三次候选、15/15 归档或 5/5 聚合。
- 未完成清缓存、重启、重载后的正文/选择/聚合哈希复算；只能证明本轮后端重启后页面可恢复当前数据库对象。
- 自动 harness 不能从失败点续接并补齐六阶段 UI receipt，原运行仍报 `NORTHSTAR_PHASE_NOT_UI`；机器发布门没有通过。
- 未做五章级 Q0/Q1、来源泄漏、首次产稿率、真实计费和 5× token 约束验证。
- 未执行真人 30 组盲评、真实 30 章耐久与 FK 结论。

本证据只支持：**真实 UI 最小闭环已经接通，两个关键恢复缺陷已在真实现场关闭。** 它不支持“C2 完成”或“可以发布”。
