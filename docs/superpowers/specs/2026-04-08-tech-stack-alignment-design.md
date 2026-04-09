# 技术栈对齐阶段设计

> 日期：2026-04-08  
> 目标阶段：在当前可运行 `L3 MVP` 基线之上，推进到“技术栈与设计文档一致、可稳定演示、可继续扩展”的下一交付层。

---

## 1. 背景与当前状态

当前仓库已经具备一条可运行闭环：

- 后端可完成 `scene_card -> bundle -> draft -> final -> archive`
- `review approve / release`
- `vector verify gate`
- `replay / export`
- 前端有可用的单页控制台

但它仍有三处“临时实现”：

1. 向量层仍使用本地文件型适配器，而不是设计目标里的真实 `Chroma`
2. 前端仍是单文件脚本，不是文档约定的 `Vue 3 + Vite + Pinia`
3. 缺少稳定的首章演示 seed，首次启动后需要人工造数据

这三项并不是同一层问题，若同时硬推，容易把前端、后端和演示数据互相绑死。因此本阶段必须先把顺序固定。

---

## 2. 本阶段目标

本阶段只做三件事：

1. 用真实 `Chroma` 替换当前文件型向量存储，但保持现有 API 与 `VerifyGate` 语义不变
2. 提供一个可重复执行、幂等的首章 demo seed，让系统启动后即可演示完整链路
3. 把前端重构为 `Vue 3 + Pinia + Vite`，同时保留当前“编辑部控制台”视觉方向与三个主页面

成功标准：

- runtime 的向量查询真实走 `vector_alias_registry -> active_alias -> Chroma collection`
- verify 失败时旧 active alias 继续服务
- 新环境启动后，执行一次 seed 即可在前端看见 Workbench / Review Inbox / Index Console 的演示数据
- 前端不再依赖单文件 DOM 脚本，而是基于组件、store、API client 驱动

---

## 3. 非目标

本阶段不处理以下事项：

- 不重写现有业务 API 合同
- 不引入新的生产级鉴权、用户体系或多租户能力
- 不在本阶段补齐设计文档里所有未落地的知识对象族
- 不把 demo seed 变成第二套 schema 或隐式业务分支

---

## 4. 方案对比与决策

### 4.1 方案 A：先做真实 Chroma，再做 seed，最后重构前端

优点：

- 最稳定，前端可以直接接最终后端语义
- 向量行为先收口，后续 UI 不会因 alias / verify 细节返工
- demo seed 可以按最终数据形态一次成型

缺点：

- 前端视觉进度不会最先体现

### 4.2 方案 B：先重构前端，再追后端

优点：

- 视觉变化最快

缺点：

- 后端一旦替换真实 Chroma，前端 store 与状态展示大概率要返工

### 4.3 方案 C：先做 demo seed，后面边演示边补底层

优点：

- 最快能看演示

缺点：

- 会把“临时 vector adapter + 临时前端脚本”的债继续固化

### 4.4 决策

采用 **方案 A**：

1. 真实 Chroma
2. Demo seed
3. Vue 3 + Pinia 前端重构

原因：这条路径能先稳定底层语义，再稳定演示数据，最后再把 UI 接到最终接口上，整体返工最少。

---

## 5. 架构设计

### 5.1 向量层分层

保留“运行时逻辑源只认 SQLite `vector_alias_registry`”这一规则不变。

新结构拆成三层：

1. `VectorStore` 抽象接口  
   负责 `write_collection / query / collection_exists / delete_collection`
2. `ChromaVectorStore` 生产实现  
   负责把 candidate / active collection 真正写入 Chroma
3. `FakeVectorStore` 或 `FileVectorStore` 测试实现  
   只在测试中保留，用于快速、稳定地跑单元测试

约束：

- 生产代码默认走 `ChromaVectorStore`
- 测试可以注入 fake store，但 API、`VersionManager`、`VerifyGate` 不得分叉第二套业务逻辑
- collection 名继续由 `vector_alias_registry.active_alias / candidate_alias` 决定

### 5.2 Demo Seed 分层

demo seed 不是脚本随便插数据，而是一条正式的开发入口。

提供一个幂等入口：

- CLI：`python -m novel_system.tools.seed_demo`

它负责：

1. 初始化首章 `chapter_goal`
2. 初始化 3 个 `scene_card`
3. 生成至少 1 条可审批的 `review_item`
4. 在需要时补齐可观察的 alias / job 初始状态

约束：

- 同一 demo seed 可重复执行
- 重复执行时只能 upsert / supersede，不得制造重复脏数据
- seed 数据仍走当前 schema，不允许引入隐藏表或单独 dev schema

### 5.3 前端重构分层

前端从单文件脚本拆成：

1. `views/`
   - `SceneWorkbenchView`
   - `ReviewInboxView`
   - `IndexConsoleView`
2. `stores/`
   - `workbenchStore`
   - `reviewInboxStore`
   - `indexConsoleStore`
3. `components/`
   - timeline、review card、alias card、human review drawer、bundle replay panel 等
4. `lib/api.ts`
   - 统一处理请求、错误、幂等头与返回 envelope

界面仍保持“编辑部控制台”方向：

- 纸张感底色
- 深色侧栏
- 强调 bundle hash、review 状态、alias 状态

也就是说，本阶段改的是技术组织方式，不推翻已经形成的视觉方向。

---

## 6. 数据流设计

### 6.1 Review -> Reindex -> Verify -> Alias Flip

链路保持不变，只替换向量底座：

1. `POST /review-items/{id}/approve`
2. `materialize_review()`
3. 创建 / 更新 `reindex_job` 与 `verify_job`
4. `ChromaVectorStore.write_collection(candidate_alias, docs)`
5. `run_verify(job_id)` 对 candidate collection 发起样本查询
6. 成功时由 `VerifyGate` 执行 alias flip
7. 失败时保留旧 active alias，并留下 candidate 待重试

### 6.2 Demo Seed -> 前端演示

1. 启动后端
2. 运行 demo seed CLI
3. 前端调用现有 GET/list 接口
4. Workbench 展示首场场景
5. Review Inbox 展示待审批项
6. Index Console 展示 alias 与 jobs

### 6.3 前端交互

前端继续只依赖 API：

- 不直连 SQLite
- 不拼底表
- 不在前端维护第二套状态机

Store 的职责只是：

- 拉取数据
- 缓存页面状态
- 调用 approve / release / verify / recovery 等 action

---

## 7. 错误处理与运行约束

### 7.1 Chroma 不可用

若 Chroma 不可连接或 collection 写入失败：

- reindex job 标记失败
- 不得影响现有 active alias 服务
- 写 `operation_logs`
- 必要时写 `reconcile_faults`

### 7.2 Verify 失败

必须继续遵守当前契约：

- 有旧 active alias：继续服务
- 无旧 active alias：保留 candidate，返回降级结果
- 不得因 verify 失败把 `active_alias` 与 `candidate_alias` 同时清空

### 7.3 Demo Seed 冲突

重复 seed 时：

- 若对象已存在，更新或跳过
- 不得制造双 active、双 candidate、重复 review item

### 7.4 前端错误展示

前端统一消费 API envelope：

- `ok = false` 显示错误条
- 不在组件里散落自定义错误结构

---

## 8. 测试设计

### 8.1 后端测试

新增三类测试：

1. `ChromaVectorStore` 集成测试  
   验证 collection 写入、查询、删除与 alias 读取路径
2. Demo seed 测试  
   验证幂等执行、不重复造脏数据、首章数据完整
3. API 回归测试  
   确认当前 `approve / release / verify / recovery / replay` 行为在替换 Chroma 后仍保持通过

### 8.2 前端测试

新增两层：

1. Store/API smoke tests  
   验证页面能从真实 envelope 取值
2. Build + minimal UI tests  
   验证三个主页面都能渲染并触发基本 action

### 8.3 回归底线

本阶段完成时，至少要保证：

- 现有 backend pytest 全绿
- 新增 Chroma / seed / front-end tests 全绿
- `vite build` 全绿

---

## 9. 实施顺序

### 9.1 步骤一：真实 Chroma 接入

- 新建向量抽象接口
- 把当前文件型实现下沉为测试替身
- 新增 `ChromaVectorStore`
- 把 `VersionManager` 的 reindex / verify 改为依赖注入向量接口
- 补集成测试

### 9.2 步骤二：demo seed

- 新建 seed CLI
- 固化首章 3 场样例
- 让 seed 可重复执行
- 补 seed 测试与 README 使用说明

### 9.3 步骤三：Vue 3 + Pinia 前端重构

- 初始化 Vue 3 + Vite + Pinia
- 拆分 views / stores / components
- 接现有 API
- 保留当前视觉基调并补最小测试

---

## 10. 交付结果

本阶段交付后，仓库应满足：

1. 向量链路不再依赖临时文件 adapter
2. 启动后端 + 执行 seed 后可直接演示
3. 前端技术栈与设计文档对齐到 `Vue 3 + Vite + Pinia`
4. 当前 API 语义、verify gate 规则、alias registry 单一逻辑源原则继续成立

---

## 11. 自检结论

本设计已检查以下四项：

1. **占位符**：无 `TODO / TBD`
2. **一致性**：先真实 Chroma，再 seed，再前端；顺序与目标一致
3. **范围**：聚焦一个子项目链，不扩散到新增业务域
4. **歧义**：明确保留现有 API 与 alias 规则，避免“前端先改 / schema 再漂移”
## Implementation Status Note

- Task 1 is complete: real Chroma integration has been verified in WSL Ubuntu-24.04, including the smoke check, focused Chroma/release/verify tests, and the full backend suite.
- Demo seed is implemented and idempotent.
- The frontend has been rebuilt as Vue 3 + Pinia on top of the existing API contract.
- Native Windows remains a non-Chroma verification lane. Strict real-Chroma write-path verification must continue to run in WSL/Linux because the embedded Windows Chroma runtime is unstable in this environment.
