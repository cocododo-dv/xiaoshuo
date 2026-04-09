# Scene Workbench Run Actions Design

> 日期：2026-04-09
> 目标阶段：让 `Scene Workbench` 从只读观察面板升级为可直接触发 scene pipeline 的执行面板，同时保留当前 bundle traceability 的可视化能力。

---

## 1. 背景

当前前端已经能展示：

- scene / chapter 基本信息
- current bundle / hash / status
- draft lineage / archive state
- attempt timeline
- bundle provenance

但 `Scene Workbench` 仍然缺少最关键的一步：用户不能在页面内直接执行 `POST /api/v1/scenes/{scene_id}/run/full`。这导致前端演示仍依赖命令行或外部 API 调用，工作台缺乏“操作闭环”。

---

## 2. 目标

本次只补齐 Workbench 的执行闭环，不扩展新的后端编排能力：

1. 在 Workbench 顶部增加 `Run Full Scene` 操作。
2. 点击后调用现有 `run/full` 接口。
3. 成功后自动刷新 workbench 与 human review 数据。
4. 在当前视图中显示本次运行的结果摘要。
5. 失败时保留现有视图数据，并通过 notice / 面板信息显示错误。

---

## 3. 非目标

- 不新增后端 API。
- 不拆分 `run/full` 为多步前端控制器。
- 不改动 Review Inbox / Index Console 的主流程。
- 不引入轮询、后台任务跟踪或实时流式状态。

---

## 4. 方案选择

### 方案 A：保持只读

优点：零实现成本。
缺点：前端演示链路仍然不完整。

### 方案 B：单动作执行并刷新

做法：在 `Scene Workbench` 中提供单个 `Run Full Scene` 按钮，调用现有接口，随后刷新已有数据源。

优点：改动集中、复用当前 store 结构、最贴近现有 Orchestrator 能力。
缺点：暂不支持分步控制。

### 方案 C：多动作编排器

优点：未来扩展性强。
缺点：当前后端只有单一 happy-path pipeline，提前做复杂控制台收益不高。

### 决策

采用方案 B。

---

## 5. 结构设计

### 5.1 API 层

在 `frontend/src/lib/api.js` 新增：

- `runFullScene(sceneId)`

它复用现有 `apiPost` 封装，调用：

- `/api/v1/scenes/${sceneId}/run/full`

### 5.2 Workbench Store

在 `frontend/src/stores/workbench.js` 增加：

- `actionId`
- `lastRunResult`

并新增 action：

- `runScene(sceneId = this.sceneId)`

行为：

1. 记录当前 action 为 `run-scene`
2. 清空旧错误
3. 调用 `runFullScene(sceneId)`
4. 保存返回摘要到 `lastRunResult`
5. 调用 `refreshAll(sceneId)` 拉取最新 workbench / human review
6. 出错时设置 `error` 并抛出异常
7. finally 清空 `actionId`

### 5.3 Scene Workbench View

在 `SceneWorkbenchView.vue`：

- 保留现有 `Load` 输入与读取逻辑
- 新增 `Run Full Scene` 按钮
- 运行中按钮禁用并显示 loading 文案
- 在正文中加入 `Run Receipt` 区块，展示：
  - latest scene status
  - current bundle id
  - current bundle hash
  - current final scene row id

### 5.4 视觉方向

保持现有“编辑部纸面控制台”风格，在 Workbench 头部加入更明显的操作区，新增运行回执卡片。样式延续当前暖色纸张 + 深色墨水体系，不引入新的主题方向。

---

## 6. 错误处理

- 如果 `run/full` 失败，保留当前 workbench 数据，不清空页面。
- 错误通过现有 `notice` 机制抛到 shell。
- `Workbench` store 中保留 `error`，页面可继续显示既有错误状态。

---

## 7. 测试设计

### 7.1 Store 行为测试

新增测试覆盖：

- `runScene()` 会调用运行接口并刷新数据
- `lastRunResult` 会保存运行回执

### 7.2 View 接入测试

新增静态源码测试覆盖：

- `SceneWorkbenchView.vue` 挂载 `Run Full Scene`
- view 使用 `workbench.runScene`
- view 展示 `lastRunResult`

---

## 8. 验收定义

满足以下条件即可视为完成：

- Workbench 可以直接触发 scene pipeline
- 成功后页面可见新的 bundle / status / provenance 数据
- 失败时用户能看到明确错误
- 前端测试与构建通过
