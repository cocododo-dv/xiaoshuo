# 契约附录 B · 后端既有端点清单（2026-06-11 逐文件核实）

> 按域整理，标注与原型视图的对应关系。Claude Code 不必再自己摸路由；
> 若与实际代码不符（后续有人改过），以代码为准并记 PROGRESS.md。
> 来源：`backend/src/novel_system/api/routes/` 各文件的 `@router` 装饰器。

## 项目（→ 作品切换器 / 主页）

| 端点 | 文件 | 备注 |
|---|---|---|
| `GET/POST /api/v2/projects` | snowflake_workspace.py | ⚠️ **v2 项目列表/创建已存在** —— Phase 2 用它，不要用 v1 |
| `GET/POST /api/v1/projects` | projects.py | legacy，留给旧 Vue 端 |
| `GET /api/v1/projects/{id}/dashboard` | projects.py | 已有聚合，Phase 2 对比扩展 |
| `GET /api/v1/projects/{id}/backtrack-items` + `POST …/{item_id}/resolve` | projects.py | 「resolve 即后端执行动作」先例（Phase 5 参考） |
| `POST /api/v1/projects/{id}/outline-plan` + `…/approve` | projects.py | legacy 大纲链 |

## 雪花构思（→ 构思视图）

`snowflake_workspace.py`，全部 `/api/v2/projects/{id}/snowflake-workspace…`：
工作台 `GET`；步骤 `steps/{key}/generate|patch|approve|history|restore|accept-stale`；
助手 `assistant`；场景分诊 `scene-triage/suggest`、`scene-triage`、`scene-triage/{id}/apply`、`scenes/{plan_id}` PATCH、`scenes/accept-stale`；
**物化 `materialize`**、`resync`、`outline/approve`。

## 正文与写作（→ 写作房间 / 深改）

| 端点 | 文件 | 对应 |
|---|---|---|
| `GET /api/v1/writer-room/{object_type}/{object_id}` | writer_room.py | 写作房间装载 |
| `GET /api/v1/author-drafts/{type}/{id}/current`、`POST …/ensure`、`…/ensure-blank` | author_drafts.py | 文档获取/创建 |
| **`PATCH /api/v1/author-drafts/{draft_id}`** | author_drafts.py | **正文保存主路径**（Phase 2 字数埋点处） |
| `…/{draft_id}/proposals/generate|generate-set`、`apply-proposal`、`author-draft-proposals/{id}/apply|reject` | author_drafts.py | AI 改稿提案 |
| `…/{draft_id}/structure-extract`、`author-structure-candidates/{id}/apply|reject|apply-to-snowflake` | author_drafts.py | 结构提取回写雪花 |
| `GET/POST /api/v1/scenes/{id}/deep-review`、`GET/POST /api/v1/chapters/{id}/deep-review` | writer_deep_review.py | 深改扫描（= WrDeepDrawer 的 issues/重扫） |
| `POST /api/v1/passages/patch-candidates`、`…/{patch_id}/accept|reject` | writer_deep_review.py | 深改 采纳/忽略；**undo 端点缺**（Phase 8 补） |
| `GET /api/v1/author-preference-profile` | writer_deep_review.py | 采纳偏好画像 |

## 目录与回收站（→ 编排 / 回收站）

| 端点 | 文件 | 备注 |
|---|---|---|
| `GET/POST /api/v1/chapters`、`GET /api/v1/chapters/{id}/status|author-workspace|scene-draft` | chapters.py | |
| `POST /api/v1/chapters/{id}/scene-order` | chapters.py | 排序已有 |
| **`POST /api/v1/chapters/trash|restore|purge`、`GET /api/v1/author-trash`** | chapters.py | 章级回收站已有 |
| **`POST /api/v1/scenes/trash|restore|purge`** | scenes.py | ⚠️ **场景级回收站也已有** —— Phase 4 只缺作品级 + 统一列表 |

## 起草与质检（→ AI 起草台）

`scenes.py`：`POST /api/v1/scenes`；`scenes/{id}/run/full`、`run/jobs`、`GET run-jobs/{job_id}`、`GET scenes/{id}/status|attempts|generation-history|workbench|quality-state`；
契约 `execution-contract` GET/POST、`quality-contract`、`literary-blueprint`、`triage`；
自动重写 `auto-rewrite` + `auto-rewrite-runs/{id}/promote|rollback`。
章级跑批：`chapters.py` 的 `chapters/{id}/run/full`、`run-status`、`runtime/backfill|aggregate/final|manual-hold(...)`。

## 成稿（→ 成稿中心）

`chapter_manuscripts.py`：`GET /api/v1/chapter-manuscripts`、`GET …/{chapter_id}`。归档/定稿动作在 `projects.py`：`chapters/{id}/approve-final`、`read-confirm`、`final-review`（Phase 7 写回链挂这里，开工核对三者语义）。

## 待办（→ 待办收件箱）

`review.py`：`GET/POST /api/v1/review-items`、`GET …/{id}`、`POST …/{id}/approve|release|reject`、`POST …/import-demo`；`GET /api/v1/human-review-events`、`…/{event_id}`、`POST …/{event_id}/actions`。

## 资料（→ 资料库）

`library.py`（v2）：`GET …/library`；`POST …/library/entities`、`PATCH …/entities/{id}`；`POST …/relations`、`DELETE …/relations/{id}`。
`knowledge.py`：`GET /api/v1/knowledge`、`GET …/{object_type}/{lineage_key}`。

## 长篇控制（→ 控制塔）

`longform_tower.py`（v2）：anchors `GET/POST/PATCH`；章节契约 `contract` GET/PUT + `transition`；审计 `audit` GET/POST + **`audit/{finding_id}/adjudicate`**。另有 `longform_control.py`、`longform_editor.py`（Phase 7 开工时核对其面）。

## 风格 / 发布 / 导入导出 / 设置

- `style_reference.py`：前缀 `/api/v2/style-reference`（ingest→…→materialize 全管线，CLAUDE.md 有图；Phase 8 对接时再列其面）。`style_profile.py`、`reference_safety.py` 为辅助。
- `indexing.py`：`GET /api/v1/index/alias-scopes(+/{scope})|jobs(+/{id})|runtime-ledger`；`POST index/verify/{job_id}/retry`、`runtime/recovery/sweep`、`runtime/promotions/run-due`。
- `interop.py`：`POST interop/preview|import/bundle-worksheet`、`GET interop/export/bundle-worksheet/{bundle_id}`、`GET replay/final-scene|draft/{row_id}`。
- `system_config.py`：`GET system-config`、`POST drafts`、`{snapshot_id}/activate`、`test-provider`、`GET export/{category}`；LLM：`GET llm`、`llm/calls/audit`、`POST llm/providers(+/{id}/default|probe)`、`llm/node-routes(+/sync-missing)`。

## 其余文件（开工相应 Phase 时再核对）

`domain.py`、`literary_eval.py`、`literary_quality.py`、`writer_review.py`、`snowflake.py`（legacy planner）、`longform_control.py`、`longform_editor.py`。
