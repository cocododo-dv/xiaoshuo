# FE-ALIGN 后续任务简报 — DEFERRED D1–D7 收尾（F 系列）

> 前置：FE-主线对齐 Phase 0–8 已全部交付（账本 `PROGRESS.md`，收口提交 `7ac4118`）。
> 本简报把账本「遗留 / 例外（DEFERRED）」表的 D1–D7 整理为可执行的后续阶段 F1–F7，
> 按「小→大、无 LLM 依赖优先、纯机械清理殿后」排序。

## 执行规则（沿用主简报，差异处显式标注）

- 决策默认沿用 D1–D6（React 主线 / 服务端统计 Asia/Shanghai / 仅手动永久删除 /
  effect 后端事务 / 派生半自动 / 新端点走 `/api/v2/projects/{id}/…`）。
- 红线沿用：`design/` 只读；不动 Vue `frontend/` 业务代码；前端只动 store 层，
  视图层契约（方法签名 / 数据形状 / 事件）不可变；不顺手重构；alembic 单头；
  每个 F 阶段一次提交、禁 squash；不伪造/跳过测试。
- **红线差异（本简报新增）**：P8 加上的 `WsDemoTag` 是我们自己的诚实标注，
  不属于原型契约——某条管线接真后**允许且应当**移除对应 DemoTag；
  极小的视图「同步接缝」沿用 P3/P5/P6 先例（一行钩子级别），必须记入账本。
- 每阶段完成定义：自检过 + `cd backend && python -m pytest` 全绿
  （涉前端的另加 `cd frontend-react && npm run build` + 对应冒烟）+
  git commit（信息 `FE-ALIGN F<N>: <主题>`）+ 更新 `PROGRESS.md` 新增
  「后续 F 系列」小节。
- 卡死规则沿用：同一问题 3 种修法仍失败 → 记 DEFERRED（编号续 D8…）继续。
- 简报与代码不符以代码为准，记入账本「核对发现」。

## 阶段顺序与验收

### F1（源 D7）— 根治负载敏感 flaky：utcnow 严格单调

**现状**：`test_scene_generation.py::test_run_scene_records_style_routing_failure`、
`test_qc_engine.py` 两例等按 `created_at` 排序的断言，高负载下多行落入同一
Windows 时钟 tick，排序回退随机 id 翻车。预存在（P0 基线即有）。

**方案**：`db/models.py` 的 `utcnow()` 改为进程内严格单调（同 tick 时微秒 +1 兜底），
所有 `default=utcnow` 列一次性根治；不改 schema、不改任何测试断言。
若 utcnow 在多处定义（services/ 里有副本），统一指向同一实现。

**验收**：受影响测试循环 20 遍不翻车（`pytest --count` 或脚本循环）；全量绿。

### F2（源 D4）— author-draft 修订历史 + 成稿中心版本对比接真

**现状**：`AuthorDraft` 只有当前行（`revision_no` 就地自增）；`edited` 事件
只记 revision 号不存正文快照 → 历史不可恢复。ws-manuscripts 版本对比区
为静态演示（带 DemoTag）。

**后端**：
- 新表 `author_draft_revisions`（revision_id PK / draft_id / revision_no /
  content / created_by / created_at + (draft_id, revision_no) 唯一）+ alembic 迁移（单头续链）。
- `AuthorDraftService.save` 保存时快照**新内容**一行（ensure 初版也补快照）。
- 端点（v1，与 author-drafts 族同居）：
  `GET /api/v1/author-drafts/{draft_id}/revisions`（倒序、分页）、
  `GET /api/v1/author-drafts/{draft_id}/revisions/{revision_no}`（含 content）。
- 后端测试：保存两次 → 两行快照；冲突 409 不产快照；revision 内容可取回。

**前端**：ws-manuscripts 版本对比区 store 接真（按目录 slug → scene_id →
draft → revisions 列表 + 两版内容对比）；移除该区 DemoTag。
视图契约形状以现行 jsx 为准先核对再动。

**验收**：写穿两版正文后对比区能列出两版且 diff 内容正确（冒烟脚本断言）。

### F3（源 D5）— ws-snow 雪花构思接 snowflake-workspace v2

**现状**：构思 state 存 `ws_snow_state_v2` 本地键；「物化→目录」边界已 API 化
（P3 adoptOutline 走 catalog diff）。后端 v2 工作台**全套端点已存在**：
workspace GET / steps generate / PATCH 草稿 / approve / history / restore /
accept-stale / assistant / scene-triage(+suggest/apply) / materialize / resync /
outline approve。

**方案**：
- ws-snow store 改 API 背书：workspace GET 水合步骤草稿与状态；步骤编辑
  PATCH 上行（乐观+回滚）；approve / 历史 / 恢复走对应端点；generate 在
  LLM 关闭时按 author_action 引导（既有模式），开启时走真生成。
- adoptOutline 升级：当后端存在已批准 scene plans 时走 **materialize 主路径**
  （简报 P3 核对发现的正解），否则保留 catalog-diff 兜底。
- `ws_snow_state_v2` 退化为读缓存或迁移上行后废弃（一次性上行模式沿用 P5/P6）。
- demo 种子需保证 tide 的雪花步骤数据完整可演示（seed 已有 scene_details，核对）。

**验收**：清 localStorage 重载后构思十步草稿/状态从后端水合；改一步草稿
刷新仍在；materialize 路径在有批准 plans 的项目上能建章（冒烟断言）。
此条完成后主简报全局验收①的括号注记（雪花本地暂存）即可销账。

### F4（源 D3）— lf6 控制塔可视化数据接锚点/审计 API

**现状**：桥三链路（裁决/任务/归档）已后端同源；lf6 塔的悬念债/伏笔/弧线等
可视化仍吃 lf2/lf3 静态数据。后端已有：`GET/POST/PATCH /api/v2/projects/{id}/longform/anchors`、
`GET …/longform/audit`、contract 端点。

**方案**：先核对 lf6 视图实际消费的 lf2/lf3 数据形状（以代码为准），
store 层把 anchors（悬念/伏笔类锚点）+ audit findings + 契约状态适配为该形状；
demo 种子给 tide 补一批锚点（seed_fe_demo_works 扩展，幂等）；
接真区域移除 DemoTag，接不了的子区保留并记账。

**验收**：塔视图可视化随后端锚点数据变化（POST 一个锚点 → 刷新可见）；冒烟断言。

### F5（源 D2）— ws-styleref 接 style_reference v2 API

**现状**：后端子系统完整（books import-path/import-upload/list/get/delete/
reclassify、runs start/get/cancel/findings、finding review、synthesize、
profiles list/get/preview/apply/bindings、validate、reports、injection-preview、
metrics）。卡片桥已通（synthesize→全局决策卡→bind_style_profile effect）。
视图整页 DemoTag。

**方案**（按 LLM 依赖分层接真）：
- 无 LLM 即可真：books 列表/导入（import-upload）/删除、profiles 列表与
  绑定状态（bindings）、报告列表。store 接真。
- LLM 依赖：runs 启动/轮询/取消、findings 审阅、synthesize——LLM 关闭时
  按后端实际行为（author_action 或失败信封）降级引导，开启时全程真。
- DemoTag 收窄：从整页降到仅 LLM 依赖子区（或全部移除，视降级体验定）。

**验收**：导入一本 txt → books 列表可见、可删除；LLM 关时启动 run 得到
明确引导而非假进度；冒烟断言。

### F6（源 D1）— ws-scene 起草引擎接 scenes run 管线

**现状**：原型用 `window.claude.complete`（宿主 API，不存在）；采纳/字数/
状态写回已接真。后端管线已存在：`POST /api/v1/scenes/{id}/run/full`（同步）、
`POST …/run/jobs` + `GET /api/v1/run-jobs/{job_id}`（异步轮询）、
`GET …/status` / `attempts` / `generation-history` / `workbench`。

**方案**：
- scnRun 改走 run/jobs 异步管线：投递 job → 轮询 → 产出落 workbench/attempts
  → 现有采纳路径（已真）收尾。`scn-run`/`scn-queue` 本地键退化为运行态缓存。
- LLM 关闭：保留「AI 接口不可用」明确报错（换成后端 author_action 文案引导）。
- 这是最大单体改造，允许拆「投递+轮询」「产出回流」两步自检，但仍一次提交。

**验收**：LLM 关：点击起草得到配置引导（无假输出）；LLM 开（如环境允许）：
起草产出真实正文进采纳流。后端侧用既有 pytest 覆盖，前端冒烟断言降级路径。

### F7（源 D6）— window.* 兼容赋值与运行时探测清理

**现状**：纯机械大改、回归风险 > 收益，主任务记账缓办。9 处运行时探测 +
模块间 window.* 兼容赋值。

**方案**：独立最终阶段处理：逐文件把 window.* 跨模块访问改为显式 import
（注意加载序防环——P1 codemod 的教训）；保留确属运行时注入的（rvResolveAction
等授权接缝按账本保留）。改完 build + run-smokes 全批必须绿。

**验收**：`npm run build` 绿 + run-smokes 六套全过 + smoke-acceptance 7/7。

## 完成标准（整个 F 系列）

1. F1–F7 各一次提交，PROGRESS.md「后续 F 系列」小节全勾选。
2. 后端全量 pytest 绿；frontend-react build 绿；run-smokes 批跑全过；
   smoke-acceptance 7/7。
3. WsDemoTag 残留数量 ≤ 实际仍为演示的子区数，且每处都在账本有对应记录。
4. 输出总结：各阶段提交号 + 新增 DEFERRED（D8…）清单。
