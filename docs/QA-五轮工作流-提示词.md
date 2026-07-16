# 潮汐工作台 · 五轮浏览器 QA 工作流 v5

> 适用于正式 React 工作台，核查日期：2026-07-16。
> 本文件可作为执行 Agent 的任务说明，但不得覆盖仓库当前代码、固定配置或结果门禁。旧 v4 的 legacy URL、旧参考书接口和“三章手工补两章”说明已经退役。

## 1. 目标与不可冒充原则

目标是从真实作者入口验证“新建作品 → 雪花十步 → 物化章节/场景 → AI 或人工写作 → 作者复核 → 权威正文 → 五章结果门”的完整链路。

任何轮次都必须遵守：

1. 合成投票不能记作真人盲评。
2. 离线、fake provider 或模拟运行不能记作真实供应商结果。
3. UI 显示成功不能替代后端权威状态、非空正文和可回放产物。
4. 原始产物缺失、配置不完整、门禁与进程退出码不一致时，结论必须为未通过。
5. 不得用 Node 内部 API 调用冒充关键作者 UI 动作；UI 阶段必须有浏览器交互和成功响应回执。
6. 文学、安全和版权诊断不是自动出版许可。真实作品仍需作者、编辑、政策与权利复核。

## 2. 当前主线与环境

- React 正式前端：`http://127.0.0.1:5174`
- 开发后端：`http://127.0.0.1:8000`
- React 契约 E2E 隔离后端：`http://127.0.0.1:8009`
- 实际端口以 `.codex-run/frontend-react.url` 和 `.codex-run/backend.url` 为准。
- `frontend/` Vue 应用仅为兼容回归，不得作为产品主线验收入口。

关键作者路径：

```text
#home → #snowflake → #writer / #scene → #manuscripts → #longform
```

`#scene` 与章节任务走真实后端运行状态；`#writer` 的浏览器缓存是恢复与写穿缓存，不是唯一正文真相。五章完成必须同时具备服务端正文、规范状态和门禁证据。

## 3. 固定 QA lane

### 3.1 工程契约门

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\verify_windows.ps1
powershell -ExecutionPolicy Bypass -File .\scripts\verify_react_e2e.ps1
```

完整发布还需 WSL Chroma：

```powershell
wsl -d Ubuntu-24.04 bash -lc "cd <当前检出目录的 WSL 路径> && bash scripts/verify_wsl_strict.sh"
```

### 3.2 当前库五章闭环

脚本名保留历史命名 `run-currentdb-three-chapter-qa.cjs`，但当前默认配置是 5 章 × 3 场；不要按文件名误判运行规模。

```powershell
$env:PLAYWRIGHT_FRONTEND_URL = "http://127.0.0.1:5174"
$env:PLAYWRIGHT_API_BASE = "http://127.0.0.1:8000"
node .\scripts\run-currentdb-three-chapter-qa.cjs
```

可用 `QA_CHAPTER_COUNT` 和 `QA_SCENES_PER_CHAPTER` 缩小诊断规模，但缩小后的运行不能记作五章通过。

### 3.3 公有领域来源安全五章

固定配置：`config/qa/public-domain-source-safety-five-chapter.json`。该 lane 使用仓库内公有领域语料、显式权属声明和 `segments_only` 云策略。

```powershell
$env:PLAYWRIGHT_FRONTEND_URL = "http://127.0.0.1:5174"
$env:PLAYWRIGHT_API_BASE = "http://127.0.0.1:8000"
node .\scripts\run-public-domain-source-safety-five-chapter-qa.cjs
```

自定义语料不得继承固定公有领域配置的权属或云发送许可。

### 3.4 全云对照

```powershell
$env:PLAYWRIGHT_FRONTEND_URL = "http://127.0.0.1:5174"
$env:PLAYWRIGHT_API_BASE = "http://127.0.0.1:8000"
node .\scripts\run-longzu-full-cloud-qa.cjs
```

该 lane 需要有效的真实供应商凭据和明确的发送授权。供应商拒绝、回退或缺少 usage 必须进入报告，不能改写成成功。

### 3.5 从零运行

重置作者态是破坏性操作，只能在服务停止且数据库已备份后执行：

```powershell
$env:QA_RESET_AUTHOR_STATE = "1"
$env:QA_ASSUME_SERVICES_STOPPED = "1"
$env:PLAYWRIGHT_FRONTEND_URL = "http://127.0.0.1:5174"
$env:PLAYWRIGHT_API_BASE = "http://127.0.0.1:8000"
node .\scripts\run-currentdb-three-chapter-qa.cjs
```

## 4. 五轮执行法

### R0：工装与基线

- 确认 Git 工作区、Python/Node 版本、Alembic 单一 head、`/live` 与 `/ready`。
- 运行脚本契约测试和前后端基础门禁。
- 记录固定配置哈希、provider/model、数据库 revision 和起始作品状态。
- 若工装本身失败，先标记 `HARNESS_BLOCKED`；只允许做解除阻断所需的最小修复。

### R1：全站健康巡检

- 以 React `5174` 遍历作家与高级模式视图。
- 收集 `console`、`pageerror`、`requestfailed`、HTTP 4xx/5xx、error boundary 和截图。
- 检查真实作品与演示作品隔离，确认非演示作品不会消费潮汐种子。

可使用：

```powershell
cd frontend
node ..\frontend-react\scripts\qa-crawl.mjs http://127.0.0.1:5174 http://127.0.0.1:8000
```

### R2：作者主链与五章结果

- 从新建作品开始，经雪花十步、急救和物化得到稳定章节/场景身份。
- 每个关键阶段使用浏览器交互，并保存请求回执。
- 15/15 场必须有非空服务端归档正文，5/5 章必须聚合成功。
- 清理当前站点的正文缓存后重载，服务端正文仍应可恢复。
- 来源安全 lane 必须为保护词 0 命中，并保存逐场扫描结果。

### R3：对抗性故障与恢复

至少覆盖：

- 模型未配置、额度不足和供应商失败不冒充成功。
- 重复提交、幂等重放和取消竞态不会产生双重归档或重复计费。
- 草稿 `409`、离线与配额失败会留下可比较、可导出的恢复记录。
- 重启后后台任务、正文哈希和权威状态收敛。
- 内容与来源风险新增后，旧确认不能自动覆盖新 finding code。

### R4：修复与定向回归

- 每个修复先保留可复现失败，再运行最小定向测试。
- 不把模型审美问题伪装成代码缺陷：文笔平、钩子弱默认属于模型/编辑评价；约束未进入运行包、状态假绿、正文丢失和门禁失效才属于系统缺陷。
- 定向通过后重跑受影响的作者路径和工程门。

### R5：独立验收

- 重新执行固定 lane，不复用 R2 的主观结论。
- 核对配置、原始产物、汇总报告和复算命令能相互回指。
- 输出明确结论：通过、未通过或被外部条件阻塞；禁止使用“基本通过”掩盖硬门失败。

## 5. 结果门与证据

五章通过至少要求：

- 5 章 × 3 场的计划身份完整且唯一。
- 15 场非空服务端正文、5 章聚合成功。
- 关键 UI 阶段具有浏览器动作、成功响应和稳定目标身份。
- outcome gate、source-safety gate 与进程退出码一致。
- 保护词扫描、内容安全、模型调用、token/成本和失败记录可回溯。
- 报告不包含密钥、完整提示词副本或无必要的正文副本。

原始运行产物写入 `output/playwright/<run-id>/`，该目录被 Git 忽略。需要长期提交的最小证据由 harness 归档到 `docs/evidence/<run-id>/`，通常只保留门禁判定、报告摘要和可复算标识，不提交批量截图、日志、PID 或临时数据库。

## 6. 阻塞与停止条件

出现以下任一情况立即停止当前“通过”结论：

- 真实 provider 凭据无效、权限不足或请求被拒绝。
- 权属声明、云发送许可或固定配置不完整。
- 原始产物缺失，或报告不能回指本次 run。
- UI 阶段只有内部 API 调用，没有浏览器交互证据。
- 场景正文为空、状态与结果不一致、门禁与退出码矛盾。
- 使用合成数据冒充真人、真实模型或真实耐久证据。

真实五章、真人盲评和 30 章耐久的发布顺序与当前状态见[结果治理路线图](outcome-governance-roadmap-2026-07-15.md)。
