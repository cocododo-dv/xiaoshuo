# AI 小说创作系统

这是一个面向单机、单作者工作流的长篇小说创作系统。正式界面是 `frontend-react/` 的 React 工作台；旧 `frontend/` 仅用于兼容回归。

当前产品主线是：新建作品 → 雪花十步构思 → 物化章节与场景 → 逐场 AI 起草或人工写作 → 作者复核并提升权威正文。系统提供长篇契约、连续性检查、内容与来源安全提示、LLM 额度、后台任务恢复和审计证据，但不应被理解为多用户 SaaS、生产级高可用服务或自动出版裁决器。

## 当前界面与能力边界

启动后默认进入 `主页`，不是雪花页。作家模式的日常入口包括：

- `主页`、`流程`：查看当前作品和下一步。
- `构思`：真实项目创建、雪花十步、场景急救、结构物化与回流。
- `写作`：人工编辑、AI 候选、草稿保存、内容安全复核和权威正文提升。
- `风格`：上传参考书并学习抽象风格画像。
- `待办`、`资料`：处理人工决策与故事资料。

切到高级模式后会显示 `章节编排`、`AI 起草台`、`成稿中心`、`长篇控制塔`、质量/盲评和运维工具。

当前需要特别区分：

- 新建作品、雪花步骤保存/批准、结构物化、逐场 AI 起草、草稿同步和权威正文提升都有真实后端链路。
- `潮汐档案` 的结构控制塔和部分装饰数据是演示内容；控制塔只对该演示作品开放，真实作品不会混入其剧情种子。
- 离线演示必须由用户显式选择，并标记为演示来源；它不是供应商真实生成结果。
- 高级 `章节编排` 的 `运行本章` 会启动持久化章节任务、轮询真实进度，并明确展示阻断、失败与模型未配置状态；它不会静默切到离线演示。
- `成稿中心` 的终稿批准必须先显式确认已通读当前服务端正文，随后依次写入正文哈希确认和项目级 `approve-final`。目录不能直接伪造 `approved`；重开终稿必须填写原因，并由服务端级联撤销受影响的后续批准。

## 本地快速启动

依赖：Python 3.12、Node.js/npm。

```powershell
cd frontend-react
npm install
cd ..
.\start-dev.cmd
```

启动脚本会先执行 `alembic upgrade head`，随后启动后端与 React 前端；默认也会补齐演示数据。默认地址：

- React：`http://127.0.0.1:5174`
- 后端：`http://127.0.0.1:8000`
- 存活检查：`http://127.0.0.1:8000/live`
- 就绪检查：`http://127.0.0.1:8000/ready`

若端口被占用，脚本会选择可用端口，并把后端地址写入 `.codex-run/backend.url`。

```powershell
.\stop-dev.cmd
.\restart-dev.cmd
```

旧 Vue 界面不会默认启动。仅做兼容回归时使用：

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\dev.ps1 -IncludeLegacyVue
```

## 推荐创作路径

1. 从作品切换器选择 `新建作品`，填写标题、题材、目标字数/章节数和起始大纲。
2. 进入 `构思`，逐步生成、编辑、保存并确认雪花十步。
3. 完成场景列表与场景规划后运行场景急救，处理 `合格 / 需修改 / 废除重写`。
4. 使用 `整理成章节结构` 将已确认内容物化为 `ChapterGoal` 与 `SceneCard`。
5. 直接进入 `写作`、在 `AI 起草台` 逐场生成，或在高级 `章节编排` 中运行当前整章并观察持久化进度。
6. 人工审阅 AI 候选；提升权威正文时按准确的内容安全发现码逐项确认。
7. 在 `成稿中心` 通读当前服务端正文并批准终稿；需要重开时填写可审计原因。再到长篇控制塔检查契约、锚点、连续性和最终状态。文学质量提示始终需要作者判断。

雪花步骤允许带原因跳过，但读者定位、一句话概括、一段话概括、场景列表和场景规划是结构物化前的硬检查项。

## 数据库与迁移

当前代码要求 Alembic head `20260716_0073`。

```powershell
cd backend
python -m alembic current
python -m alembic heads
python -m alembic upgrade head
```

`0073` 会把历史 LLM 审计中的提示词、草稿、模型输出和供应商错误正文改写为有界指纹；正文仍保留在各自权威业务表中。该脱敏不可逆，升级已有数据库前应先备份。若要先只统计历史审计风险：

```powershell
python -m novel_system.tools.llm_audit_scrub --database .\novel_system.db --dry-run
```

升级后可做严格预检：

```powershell
python -m novel_system.tools.database_preflight .\novel_system.db --expected-revision 20260716_0073
```

`/live` 只表示进程存活；`/ready` 还会检查数据库连接、迁移版本和必需结构，部署探针应使用两者的不同语义。

## 网络与令牌

后端默认 `NOVEL_SYSTEM_LOCAL_ONLY=true`，只接受回环请求并拒绝转发头。若明确需要远程访问，必须同时设置：

```powershell
$env:NOVEL_SYSTEM_LOCAL_ONLY = "false"
$env:NOVEL_SYSTEM_REMOTE_ACCESS_TOKEN = "使用足够长的随机值"
$env:NOVEL_SYSTEM_CORS_ORIGINS = "https://你的前端域名"
```

`start-dev.cmd` 仍只监听 `127.0.0.1`；以上变量不会自动把端口暴露到网络。远程部署还需要单独配置监听地址或可信反向代理，并遵守运行安全文档中的边界。

浏览器客户端通过 `X-Novel-Access-Token` 发送令牌；可用 `VITE_NOVEL_SYSTEM_ACCESS_TOKEN` 注入默认值，运行时值只保存在 `sessionStorage`。这是共享访问令牌，不是用户登录、RBAC 或租户隔离；构建进前端的值也不能视为对浏览器用户保密。

完整的网络、额度、内容复核、路径导入和恢复边界见 [运行安全与资源边界](docs/runtime-safety.md)。长篇冻结与最终状态语义见 [长篇运行时契约与终稿状态](docs/longform-runtime-contract.md)。本轮整改与残余盲区见 [系统整改记录（2026-07-16）](docs/system-remediation-2026-07-16.md)。

## 恢复与数据重置

服务启动时会尝试恢复可安全重放的场景、章节、风格学习和验证后台任务；持久化租约用于避免重复接管。写作界面的 `同步与恢复中心` 会收集浏览器本地冲突稿、离线稿和配额失败稿，可比较、导出、重试或恢复。

浏览器恢复记录不是服务端备份，清理站点数据、换浏览器/设备、无痕模式或存储配额耗尽都可能令其不可用。

`reset_author_state` 会批量删除作者态项目与运行产物，不属于首次启动步骤。只有在已有数据库备份且确认要清空作者态时才执行：

```powershell
cd backend
python -m novel_system.tools.reset_author_state
python -m novel_system.tools.reset_author_state --execute --yes
```

第一条命令仅做 dry-run。

## 验证

```powershell
cd frontend-react
npm run test
npm run build
```

```powershell
cd backend
python -m pytest -m "not chroma_integration"
```

关键代码入口：

- 前端导航：`frontend-react/src/ws-app.jsx`
- 雪花工作台：`frontend-react/src/ws-snow.jsx`
- 写作与本地恢复：`frontend-react/src/ws-writer.jsx`、`frontend-react/src/wr-doc-store.jsx`
- API 客户端：`frontend-react/src/lib/client.js`
- 后端应用与健康检查：`backend/src/novel_system/api/app.py`
- 场景执行与归档：`backend/src/novel_system/api/routes/scenes.py`
- 长篇契约：`backend/src/novel_system/services/longform_tower.py`
