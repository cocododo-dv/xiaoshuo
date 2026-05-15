# 雪花法驱动小说系统

这是当前仓库唯一保留的项目说明。

系统主线已经升级为“雪花法驱动”：你提供小说大纲和可选参考书，系统先按雪花法逐层生成候选，作者逐层确认，再把已确认的场景列表和场景规划整理成章节结构草案。当前 `雪花工作台` 前端覆盖项目创建、十步雪花、场景急救、章节结构草案整理和结构确认；逐章运行、终稿批准和更细的运行证据仍是后续支撑接口/高级链路能力。`写作房间` 保留为小范围人工修改工具；旧的大纲驱动页和深改台下沉到高级模式，不再作为普通作家模式的主流程。

## 当前入口

前端默认进入 `雪花工作台`。

作家模式只保留：

- `雪花工作台`：创建小说项目，逐步确认十步雪花，做场景急救，整理章节结构草案，并确认生成 `ChapterGoal` / `SceneCard` 的结构基础。
- `小修写作`：进入当前章节或场景的正文小修。
- `参考书学习`：导入参考书、学习抽象风格画像、绑定 ready 画像到项目。
- `待处理建议`：处理中途异常、QC 阻塞、参考安全风险和其他需要作者决策的建议。

高级模式保留全部后台工具，包括章节编排、运行场景、成稿中心、深改台、长篇控制、文学质检、索引、知识、导入导出和系统配置。

## 首次使用最短路径

1. 准备依赖：后端使用 Python 3.12，前端使用 Node/npm；首次运行前在 `frontend` 下执行 `npm install`。
2. 迁移数据库：进入 `backend` 后执行 `python -m alembic upgrade head`。
3. 如需清空旧作者态数据，先执行 `python -m novel_system.tools.reset_author_state` 查看 dry-run，再执行 `python -m novel_system.tools.reset_author_state --execute --yes`。
4. 回到仓库根目录执行 `.\start-dev.cmd`，打开前端 `http://127.0.0.1:5173`。
5. 在左侧 `界面模式` 选择 `作家`，进入默认的 `雪花工作台`。
6. 点击 `项目 / 新建`，填写标题、题材、目标章节数/字数，并粘贴故事起始大纲。
7. 在 `规划` 模式中逐步 `生成候选`、编辑、`保存步骤`、`确认步骤`。
8. 完成 `场景列表` 和 `场景规划` 后进入 `急救`，生成急救建议，按 `合格 / 需修改 / 废除重写` 修正并保存。
9. 回到 `规划`，在 `整理章节结构` 中点击 `整理成章节结构`，检查章节计划后点击 `确认结构`。
10. 如需正文小修、参考画像或人工决策，分别进入 `小修写作`、`参考书学习`、`待处理建议`。逐章运行与终稿批准可走已保留的支撑接口或高级链路，不是当前雪花页的直接按钮。

## 标准流程

1. 在 `雪花工作台` 创建项目，普通作家模式只创建 `snowflake` 项目。
2. 粘贴小说大纲，可选填写标题、题材、目标字数、章节数。
3. 如需参考书，先在 `参考书学习` 导入、学习，并把 `ready` 状态画像绑定到项目。
4. 在 `雪花工作台` 逐步生成、编辑并确认十步雪花：读者定位、一句话概括、一段话概括、角色摘要表、一页梗概、角色背景故事、长篇大纲、角色全档案、场景列表、场景规划。
5. 雪花步骤允许带原因跳过；整理章节结构前，`读者定位`、`一句话概括`、`一段话概括`、`场景列表`、`场景规划` 是硬性检查项，其余角色/长纲步骤会以预警形式提示。
6. 在工作台中完成 `场景急救`，把场景标记为 `合格 / 需修改 / 废除重写`。
7. 点击 `整理成章节结构`，系统把已确认的场景列表和场景规划转成待确认结构计划。
8. 在工作台中确认结构计划，系统创建 `ChapterGoal` 和 `SceneCard`，并把主动场景的 `Goal / Conflict / Setback` 或反应场景的 `Reaction / Dilemma / Decision` 写入场景戏剧卡。
9. 后续逐章运行、终稿批准和章节级审核包由保留的项目支撑接口承担；当前 `雪花工作台` 前端不直接暴露 `运行本章` 或 `批准终稿` 按钮。
10. 需要人工微调正文时进入 `小修写作`；需要处理异常、QC 或安全项时进入 `待处理建议`。

v1 不一次性生成整本书，只做逐章推进。

## 参考书边界

参考书只用于生成抽象风格画像，例如节奏、句法、叙事手法、结构技巧和禁复刻规则。

系统不得复制参考书原文表达、人物、设定、桥段、特殊意象或标志性句式。项目运行包只携带抽象画像和安全提示。

## 项目接口

雪花工作台主接口：

- `POST /api/v2/projects`
- `GET /api/v2/projects`
- `GET /api/v2/projects/{project_id}/snowflake-workspace`
- `POST /api/v2/projects/{project_id}/snowflake-workspace/steps/{step_key}/generate`
- `PATCH /api/v2/projects/{project_id}/snowflake-workspace/steps/{step_key}`
- `POST /api/v2/projects/{project_id}/snowflake-workspace/steps/{step_key}/approve`
- `POST /api/v2/projects/{project_id}/snowflake-workspace/assistant`
- `POST /api/v2/projects/{project_id}/snowflake-workspace/scene-triage/suggest`
- `POST /api/v2/projects/{project_id}/snowflake-workspace/scene-triage`
- `PATCH /api/v2/projects/{project_id}/snowflake-workspace/scenes/{scene_plan_id}`
- `POST /api/v2/projects/{project_id}/snowflake-workspace/scene-triage/{triage_id}/apply`
- `POST /api/v2/projects/{project_id}/snowflake-workspace/materialize`
- `POST /api/v2/projects/{project_id}/snowflake-workspace/outline/approve`

仍保留的支撑接口：

- `GET /api/v1/projects/{project_id}/dashboard`
- `POST /api/v1/projects/{project_id}/chapters/{chapter_id}/run-job`
- `POST /api/v1/projects/{project_id}/chapters/{chapter_id}/run`
- `GET /api/v1/chapters/{chapter_id}/run-status`
- `GET /api/v1/chapter-manuscripts/{chapter_id}`
- `POST /api/v1/projects/{project_id}/chapters/{chapter_id}/approve-final`
- `POST /api/v1/projects/{project_id}/reference-profiles`

`写作总控` 现在是普通作者模式的结构确认后入口：雪花结构批准后进入项目 dashboard，按 `next_action` 启动后台章节起草、轮询运行进度、展示终稿审阅正文并批准当前章。LLM 未启用时，章节起草会被明确阻止，除非显式选择离线演示；离线演示内容会明确标记为演示来源，不当作真实正文来源。

后端新增：

- `StoryProject`
- `OutlinePlan`
- `SnowflakeArtifact`
- `StoryCharacter`
- `ProjectService`
- `SnowflakeWorkspaceService`
- `SnowflakeWorkspaceAssistantService`
- `SnowflakeStepCatalog`
- `ProjectChapterFlowService`
- `reset_author_state` CLI

章节和场景现在可以通过 nullable `project_id` / `outline_plan_id` 追踪项目归属。雪花整理出的场景会把 proactive 场景的 `Goal / Conflict / Setback` 或 reactive 场景的 `Reaction / Dilemma / Decision` 同步到 `SceneCard.writer_brief_json`。

## 数据重置

切换到新的雪花工作台前，推荐先执行一次作者态重置，清掉旧项目、旧雪花、旧章节运行产物和旧作者修订数据。

先看 dry-run：

```powershell
cd backend
python -m novel_system.tools.reset_author_state
```

确认后再真正执行：

```powershell
cd backend
python -m novel_system.tools.reset_author_state --execute --yes
```

重置会删除：

- `StoryProject / OutlinePlan / SnowflakeArtifact / StoryCharacter`
- `ChapterGoal / SceneCard / ChapterState / SceneRunState`
- 作者草稿、提案、结构候选、QC、自动重写、运行产物、审核项、索引作业和相关审计记录

重置会保留：

- `ReferenceBook / ReferenceBookSegment / ReferenceLearningRun / ReferenceLearningRound / ReferenceFinding / ReferenceProfile`
- `SystemConfigSnapshot / SystemSecret`
- `config/models.yaml` 与 `config/prompts.yaml`

## 本地启动

推荐使用根目录脚本：

```powershell
.\start-dev.cmd
```

停止服务：

```powershell
.\stop-dev.cmd
```

重启服务：

```powershell
.\restart-dev.cmd
```

默认地址：

- 前端：`http://127.0.0.1:5173`
- 后端：`http://127.0.0.1:8000`

如果后端端口被占用，脚本会选择下一个可用端口，并写入 `.codex-run/backend.url`。

本地首次切到新工作台时，推荐顺序：

1. `cd backend`
2. `python -m alembic upgrade head`
3. `python -m novel_system.tools.reset_author_state`
4. `python -m novel_system.tools.reset_author_state --execute --yes`
5. 回到仓库根目录运行 `.\start-dev.cmd`

## 数据库迁移

代码依赖最新 Alembic 迁移。页面出现 `database operation failed` 时，优先检查数据库版本。

```powershell
cd backend
python -m alembic current
python -m alembic heads
python -m alembic upgrade head
```

## 代码入口

- 前端壳层：`frontend/src/App.vue`
- 前端导航：`frontend/src/router.js`
- 雪花工作台页：`frontend/src/views/SnowflakeWorkbenchView.vue`
- 雪花工作台状态：`frontend/src/stores/snowflakeWorkbench.js`
- 前端 API：`frontend/src/lib/api/`（域模块，通过 `index.js` 统一导出）
- 后端应用：`backend/src/novel_system/api/app.py`
- 项目接口：`backend/src/novel_system/api/routes/projects.py`
- 雪花工作台接口：`backend/src/novel_system/api/routes/snowflake_workspace.py`
- 项目服务：`backend/src/novel_system/services/projects.py`
- 雪花工作台服务：`backend/src/novel_system/services/snowflake_workspace.py`
- 重置工具：`backend/src/novel_system/tools/reset_author_state.py`
- 数据模型：`backend/src/novel_system/db/models.py`

## 验证

后端项目流：

```powershell
python -m pytest backend/tests/test_snowflake_workspace_v2.py backend/tests/test_snowflake_planner.py backend/tests/test_reset_author_state.py
```

前端工作台和导航：

```powershell
cd frontend
npx vitest run tests/snowflakeWorkbench.spec.js tests/workflowUx.spec.js
```

完整前端单测：

```powershell
cd frontend
npm run test
```
