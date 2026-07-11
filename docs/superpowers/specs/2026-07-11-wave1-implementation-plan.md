# Wave 1 实施计划：统一正文真值和归档

> 设计依据：`docs/superpowers/specs/2026-07-10-ai-novel-outcome-governance-design.md` v1.1 §5.2/§5.3/§6.1 + Wave 1 条目
>
> 纪律：不新增外围文学模块；不修改与本 Wave 无关的代码；测试先行（先红后绿）；
> Wave 0 完成门已过（提交 8de233c）。
>
> 完成门：**前端显示完成的场景必须存在可回放的后端归档稿；缓存清除不丢稿。**

## 1. 现状事实表（2026-07-11 逐项核实）

| # | 事实 | 位置 |
|---|---|---|
| F1 | `Archiver.archive_final_scene` 是后端归档唯一实现，但只置 `SceneRunState.scene_status="archived"`，**不改 `FinalScene.status`**（orchestrator 创建时写 `near_final_ready`，模型默认 `approved`）——状态词表未统一 | `services/archiver.py:76`、`services/orchestrator.py:365`、`db/models.py:1159` |
| F2 | 归档只发生在 `orchestrator.run_scene` 全通路径；停在 `human_review_required` / `critical_scene_human_gate` / blocked 的场**没有作者采纳归档端点** | `services/orchestrator.py:392` |
| F3 | `FinalScene.status` 有 4 处消费方按 `"approved"` / `("approved","near_final_ready")` 过滤，词表加 `archived` 必须同步扩展，否则上下文构建/漂移检测漏掉已归档正文 | `services/bundle_builder.py:650,801,826`、`services/style_drift_detector.py:138`、显示映射 `api/routes/scenes.py:878` |
| F4 | `SceneRunState` 无 `latest_valid_draft_row_id` / `author_state` 列；失败/重写路径会把 `current_neutral/style_draft_row_id` **清空**（稿行还在但指针丢失） | `db/models.py:528`、`orchestrator.py:473`、`qc_engine.py:1201,1769`、`scene_execution.py:552` |
| F5 | 草稿指针写点共 5 处（neutral 1 处 + style 4 处） | `services/scene_generation.py:269,548,762,895,1010` |
| F6 | generating/failed 的派生源是 `ChapterRunJob`（job_type=scene_full，status ∈ queued/running/completed/blocked/failed/cancelled） | `services/scene_run_jobs.py` |
| F7 | `chapter_manuscripts` 聚合已以 `FinalScene` 为源（设计 §2.3 确认合规，**不重写**）；但 detail 的 `_final_scene_payload` 无 `content` 字段，FE 逐场换源缺数据 | `services/chapter_manuscripts.py:124` |
| F8 | FE 采纳归档 `scnAdoptToDoc` = 写 localStorage `wr-doc:{sid}` + 目录卡置 `done`（经 catalog PATCH 写 SceneCard.state 展示态），**无任何后端归档调用**——G-02 主体 | `frontend-react/src/ws-scene-run.jsx:346`、`ws-catalog.jsx:240(catScenePatch)` |
| F9 | `ws-manuscripts.jsx` 正文源 = localStorage `wr-doc:{sid}`（`manuDocParas`）；tide 演示章回落种子 M_BODY；导出 `manuCompile` 同源 | `frontend-react/src/ws-manuscripts.jsx:132-165` |
| F10 | `wr-doc-store.jsx` 已服务端优先水合 + PATCH 409 冲突副本；缺口：`dirty` 只在内存 `docMeta`，**保存失败后重启浏览器 → hydrate 用服务端旧版覆盖本地较新稿** | `frontend-react/src/wr-doc-store.jsx:21,86,121` |
| F11 | 本机可跑 vitest（`NODE_OPTIONS="--require ./crypto-polyfill.cjs"`，已验证 wr-doc-store 7/7 通过）；已有 `ws-scene-run.test.jsx` / `wr-doc-store.test.jsx` | `frontend-react/src/*.test.jsx` |

## 2. 架构决策

- **D1 · author_state 纯投影**：新建 `services/author_state.py`，迁移期由 API 计算不落列（设计 §6.1 授权）。判定先分「有稿性」：无稿 → 空稿三态（`not_started` / `generating` / `generation_failed`+`recovery_action`）；有稿 → `draft_ready` / `quality_warning` / `awaiting_author_choice` / `hard_blocked` / `archived`。挂载到 `GET /scenes/{id}/status`、`GET /scenes/{id}/workbench`、`GET /scene-run-states` 三处，返回 §5.3 全部契约字段（`latest_valid_draft_row_id` / `current_final_scene_row_id` / `blocking_findings` / `quality_warnings` / `recommended_actions` / `can_edit` / `can_archive` / `recovery_action`）。Wave 1 落**字段契约**；`blocking_findings`/`quality_warnings` 内容从现有 QC/审阅摘要粗粒度透出，Q0–Q3 精化归 Wave 2。
- **D2 · 最小加列**：`SceneRunState` 只加 `latest_valid_draft_row_id: str|null`（Wave 1 明确要求，须落库以便崩溃恢复）。`run_policy` / `scene_token_budget` / `scene_tokens_used` 是 Wave 2/3/6 的列，本 Wave 不加。Alembic 迁移 + ORM 同步 + `test_metadata_isolation.py` 漂移守卫保持通过。
- **D3 · 归档词表统一**：`archive_final_scene` 事务内统一置 `final_scene.status = "archived"`；F3 的 4 处消费方同步扩展词表；迁移里做历史映射（被 `scene_status='archived'` 的 state 指向的 `current_final_scene_row_id` 行 → `status='archived'`）。
- **D4 · 作者采纳归档单入口**：新端点 `POST /api/v1/scenes/{scene_id}/adopt-current`（幂等，`execute_with_idempotency`）。内容源优先级：未归档的 `current_final_scene_row_id` → 提升归档；否则 `current_style_draft` > `current_neutral_draft` >（兜底）非空 author-draft（人工手写场，`source_bundle_id` 用哨兵 `author_draft:{draft_id}`，消费方已有 bundle-None 容错）→ 创建 `FinalScene` 再经 `Archiver` 归档。守卫：无任何有效稿 → 409 `NO_VALID_DRAFT`；确定性来源安全扫描命中保护词 → 409 `SOURCE_SAFETY_BLOCKED`（保留草稿可重试，设计红线 8）；已归档重复调用幂等返回。复用 `Archiver`，不建第二实现。
- **D5 · latest_valid_draft_row_id 语义**：管线体系内维护（F5 的 5 个生成写点 + 候选 select + adopt），**失败/重写路径不清空**（区别于 `current_*`）；仅项目级运行时失效（`project_runtime_invalidation`）才清。author-draft 人工编辑不写此指针（自有 revision 链，恢复语义由 wr-doc 服务端水合覆盖）——边界记入风险。
- **D6 · 成稿中心换源**：后端 detail 的 `_final_scene_payload` 加 `content`（最小增量，非重写聚合）；FE 新建薄 store `ws-manuscripts-store.jsx`（`WsManuscripts`：API-backed + 同步缓存，挂 window，契约同其余 store），`manuBuildBody` 的 live 正文改从该 store 取，**localStorage 不再作正文源**；tide 演示种子回落保留；导出同源换。
- **D7 · wr-doc 跨会话冲突**：`pushSave` 失败时写持久化标记 `wr-doc-pending:{sid}`（`{html,at}`）；启动 hydrate 发现标记且内容 ≠ 服务端 → 建冲突副本（复用 409 备份机制）并提示作者选择；保存成功清标记。
- **D8 · E2E 折衷**：设计项 7 的"清 localStorage、重启服务、重新加载恢复"E2E——本机以 vitest 模拟（清 localStorage 后 store 仍从 mock API 渲染正文）落地可复算证明；Playwright smoke 级验证归 Windows lane 下一次实跑（与 Wave 0 的 R0 工装信任门同批）。

## 3. 改动清单

后端（`backend/`）：
1. `src/novel_system/db/models.py` — SceneRunState + `latest_valid_draft_row_id`
2. `alembic/versions/<new>_wave1_truth_unification.py` — 加列 + FinalScene 历史状态映射
3. `src/novel_system/services/author_state.py`（新） — 投影纯函数
4. `src/novel_system/services/archiver.py` — 事务内置 `FinalScene.status="archived"`
5. `src/novel_system/services/scene_generation.py` — 5 写点同步维护 latest 指针
6. `src/novel_system/services/bundle_builder.py` / `style_drift_detector.py` — status 过滤词表扩展
7. `src/novel_system/api/routes/scenes.py` — 三处挂投影；新增 adopt-current；select 维护 latest 指针；status 显示映射加 archived
8. `src/novel_system/services/chapter_manuscripts.py` — `_final_scene_payload` 加 content
9. `tests/test_author_state_projection.py`（新）+ `tests/test_scene_adopt_archive.py`（新）

前端（`frontend-react/src/`）：
10. `ws-scene-run.jsx` — `scnAdoptToDoc` 改 async：先 POST adopt-current，成功才写缓存 + 置 done + 重拉 workbench；失败给结构化引导
11. `ws-manuscripts-store.jsx`（新）+ `ws-manuscripts.jsx` — 换源
12. `wr-doc-store.jsx` — pending 持久化 + 启动冲突检测
13. `ws-manuscripts.test.jsx`（新）+ `ws-scene-run.test.jsx` / `wr-doc-store.test.jsx` 扩展

文档：14. 本计划；15. `docs/outcome-governance-progress.md` Wave 1 段。

## 4. 测试先行顺序

1. 后端两个新测试文件先写（先红）：投影八态判定表逐态、契约字段齐备、adopt 成功归档（FinalScene.status=archived + 聚合含正文 + author_state=archived）、无稿 409、幂等重放、来源安全阻断保留草稿、latest 指针失败路径不清空
2. 后端实现 → pytest 绿 → 漂移守卫 + 全量回归
3. 前端测试先写（先红）：done 只在 adopt 成功响应后置位（mock 拒绝时不置）、清 localStorage 后成稿中心正文仍来自 API、无归档章显示无稿、wr-doc pending 冲突副本
4. 前端实现 → vitest 绿 → 全量 vitest
5. 隔离 DB `alembic upgrade head` 验证迁移

## 5. 本机验证命令

```bash
cd backend && .venv/bin/python -m pytest tests/test_author_state_projection.py tests/test_scene_adopt_archive.py tests/test_metadata_isolation.py -q
cd backend && .venv/bin/python -m pytest -q                       # 全量回归
cd frontend-react && NODE_OPTIONS="--require ./crypto-polyfill.cjs" npx vitest run
# 迁移验证（隔离库）
NOVEL_SYSTEM_DATABASE_URL=sqlite:///<scratch>/wave1.db backend/.venv/bin/python -m alembic upgrade head
```

## 6. 完成门自证

- 「前端显示完成的场景必须存在可回放的后端归档稿」：vitest 断言 done 置位唯一路径是 adopt 成功响应（后端拒绝 → 不置 done）；pytest 断言 adopt 后 workbench / chapter-manuscripts 可回放全文。
- 「缓存清除不丢稿」：vitest 构造已归档场景（mock API）→ 清空 localStorage → 成稿中心 store 重建后正文仍完整来自 API；wr-doc 服务端水合已有测试基础上补跨会话 pending 场景。

## 7. 边界与剩余风险

- adopt 端点 Wave 1 只做确定性来源安全 Q0 守卫，不实现 Q0–Q3 分级阻断策略（Wave 2 范围）。
- author-draft 人工编辑不维护 `latest_valid_draft_row_id`（两个 id 体系，D5 边界）；人工稿归档经 adopt 的 author-draft 兜底路径覆盖。
- `ws-manuscripts.jsx` 890 行视图换源，阅读器/导出/对比多处引用旧取数函数——vitest 覆盖主路径，视觉回归需 Windows lane 实跑复核。
- Playwright 级"清缓存重启恢复"E2E 本机无法实跑（node16 无 fetch / 无 Windows 服务栈），vitest 模拟为本 Wave 的可复算证明，smoke 验证与 Wave 0 采集侧复核同批。
