# PROGRESS — FE 主线对齐 · 进度账本

> Claude Code：每完成一项勾选并填提交号；「核对发现」一栏记录与简报假设不符的实际情况
> （简报基于 2026-06-11 的代码核对，以仓库实际为准）。换会话续工时**先读本文件**。

## 状态

- [x] Phase 0 · 基线与陷阱 — 提交：（基线 c2044ae + Phase 0 提交见下）
- [ ] Phase 1 · 前端工程化 — 提交：
- [ ] Phase 2 · 作品域与聚合 — 提交：
- [ ] Phase 3 · 目录统一 — 提交：
- [ ] Phase 4 · 回收站 — 提交：
- [ ] Phase 5 · 待办收件箱 — 提交：
- [ ] Phase 6 · 资料库 — 提交：
- [ ] Phase 7 · 控制塔桥 — 提交：
- [ ] Phase 8 · 收尾退役 — 提交：

## 决策点确认（开工前人工填写；空白 = 按默认）

- D1 前端栈：默认（React → frontend-react/，Vue 并行保留）
- D2 统计服务端化：默认（服务端算，Asia/Shanghai）
- D3 回收站清理：默认（仅手动永久删除）
- D4 effect 后端执行：默认
- D5 派生半自动：默认
- D6 新端点走 v2：默认

## Phase 0 基线记录（2026-06-11）

- 分支：`fe-align`；基线提交 `c2044ae`（固化开工时工作树里既有的未提交改动：
  library/longform_tower 后端 + 迁移 0041–0046 + Vue 设计迁移 WIP + 本简报包。
  这批改动即简报「已核实」所基于的代码状态，不属于任何 Phase 的产出）。
- `alembic heads` = `20260611_0046`（单头），`alembic current` = head。
- Vue 端 `npm run test`：59 文件 / 536 测试全绿 + smoke ok。
- 后端 `python -m pytest -m "not chroma_integration"`（仓库根运行）：**808 passed, 12 deselected**（4m31s）。
  注意：须从仓库根运行（个别测试用仓库根相对路径读 golden 文件）；Windows 解释器为 Anaconda python。
- 基线截图：`baseline-shots/01-home.png … 15-trash.png`（1600×1000，两部种子作品各打开一遍后截取；
  生成脚本 `baseline-shots/capture.mjs`，静态服务 8077 端口）。
- 陷阱清单 T1–T13 逐条核对属实：T1 缓存串/T2 CSS 14 文件层叠顺序/T3 JSX 46 脚本顺序
  （终端入口 ws-app.jsx）/T4 createRoot 在 ws-app.jsx:459/T5 splash+CDN React 18.3.1/
  T6 EDITMODE 注释包 WS_DEFAULTS/T7 __activate_edit_mode 两处（ws-app.jsx:143,448）/
  T8 运行时探测 9 处 6 文件/T11 无前缀 localStorage 键。
  T12：design/ 下无 merge-plan-*、design-canvas、*-standalone 文件，index.html 引用即搬运清单。

## 核对发现（实际代码 vs 简报假设）

| Phase | 简报假设 | 实际情况 | 处理 |
|---|---|---|---|
| 2 | 正文保存写路径 | ✅ 已核实：`ensure` + `PATCH author-drafts/{draft_id}` | 埋点加在 PATCH 服务层 |
| 4 | 章/场景 trash 的实现机制（软删标记 or 移表）；两套是否同一服务 | （待核对 services 层） | |
| 5 | ReviewItem 状态机可扩展为统一 state | （待核对） | |
| 6 | library 实体模型字段差集 | （待核对） | |
| 7 | adjudicate 幂等性 | （待核对） | |

## 遗留 / 例外

（如：某视图保留 WsDemoTag 的原因、迁不动的本地数据、推迟项）
