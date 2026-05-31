# Style Reference 模块重构 — 进度总览

> 依据《风格参考模块重构执行手册 v1.1》。本文件随 PR 推进滚动更新。
> 更新日期:2026-05-31 · 分支 `main` · 24 commits(22 PR + 2 hotfix)
> 测试规模:后端目标 ~343 测试 / 前端 522 测试(57 文件)+ smoke,全绿。

## 一、阶段与 commit 清单

| Phase | PR | commit | 内容 |
|---|---|---|---|
| **1 落地** | PR-1 | `cb5ddf4` | schema 落地(表 + ORM + migration) |
| | hotfix | `a61e9de` | CloudPolicy enum 值对齐代码事实 |
| | hotfix | `e11157d` | findings UNIQUE 改 statement_hash + 4 列复合(允许同维多观察) |
| | PR-2 | `9f1c9df` | ingest + 分段 segmentation + metrics 骨架 |
| | PR-3 | `2df3307` | extractors 半盘(language + narrative) |
| | PR-4 | `21a0978` | synthesize + materialization + Phase 1 routes + preview |
| | PR-5 | `65a5699` | 前端 Phase 1 |
| **2 抽取/注入** | PR-6 | `dcaa5a2` | extractors 全盘(scene + theme) |
| | PR-7 | `110d98d` | validation 三路 + 双路径 |
| | PR-8 | `c8e3573` | injection + qc gate + `_call_llm` 统一 |
| | PR-9 | `a77813b` | 前端组件 + injection 微扩展 |
| **3 可观测/性能/a11y/精化** | PR-10 | `4d47954` | §13 可观测性 + metrics 上报(MetricsRecorder/Aggregator) |
| | PR-11 | `ab792a8` | E2E 重写 + metric_events cleanup |
| | PR-12 | `5b66cd4` | 性能(metrics TTL cache + findings 虚拟滚动) |
| | PR-13 | `c530e77` | a11y 轨道(ARIA + 键盘导航 + 局部对比度) |
| | PR-14 | `1d50465` | character scope binding |
| | PR-15 | `84a4474` | scene scope binding |
| | PR-16 | `e8000b8` | fragments 两层叠加合并(base + 最具体增量) |
| | PR-17 | `55e9e08` | a11y 深化(完整 focus trap + radiogroup 导航) |
| | PR-18 | `96df6cd` | onstage 多角色 character 匹配(pov ∪ onstage) |
| | PR-19 | `73e46b3` | 三层叠加 base+character+scene(加权预算) |
| | PR-20 | `96eca2f` | 多 character 叠加(onstage 配角全叠) |
| | PR-21 | `402ea52` | Dialog a11y 推广(useFocusTrap composable) |
| | PR-22 | `745db6c` | metric 趋势图(无依赖 SVG) |

## 二、Phase 3 叠加注入弧线(PR-14~PR-20)

注入从「单选一个 binding」逐步演进为「多层加权全叠」:

- **优先级 rank**(单一真相源 `_binding_rank` + `_char_order`):`scene=0 > character=1 > project=2 > global=3`,不匹配=99。
- **PR-14/15**:落 character / scene scope binding(单选优先级)。
- **PR-16**:两层叠加 = base(project/global)+ 最具体增量一层;token 各半;forbidden 行级去重;metric 取最具体。
- **PR-18**:character 匹配集 = `ordered_character_ids(pov, onstage)`(pov 排首 + onstage 去重)。
- **PR-19**:三层全叠 `[base, character, scene]`,由泛到具体;token **加权** `weights=range(1,n+1)`(越具体预算越多,scene 最大);单层零回归走原路径。
- **PR-20**:character 层从单选进化为 **onstage 多配角全叠**,`[base, char_pov, char_b, …, scene]`;同角色多 binding 按 created_at 去重(每角色一层)。
- **不变**:`resolve_active_binding`(qc gate 单选)、调用方接口(`fragments_for` 返合并单 fragments)始终透明。

## 三、Phase 3 其余轨道(PR-21~PR-22)

- **PR-21 Dialog a11y 推广**:抽 PR-17 内联 focus trap 为 `useFocusTrap(dialogElRef) → {onTab}`(纯 JS,无依赖);ProfileApplyDialog 迁入(零回归)+ 推广到 SnowflakeSkipStepDialog、WriterRoomView reject dialog(后者补 esc / 初始聚焦 / aria-labelledby)。全站 3 dialog 键盘可达性一致。
- **PR-22 metric 趋势图**:后端 `MetricsAggregator.daily_injection_counts`(`substr(created_at,1,10)` GROUP BY + Python 零填充连续日期轴,window 钳 [1,90],不缓存)+ `GET /metrics/daily`;前端手写 SVG 柱状 `MetricsTrendChart.vue`(无 Chart.js,峰值归一 / 零值空档 / role=img),入 MetricsPanel,window 7/30/90 映射。

## 四、全局纪律(PR-1~PR-22 全程遵守)

- **A** 文档/代码冲突 → 以**代码事实**为准(不改 v1.1 手册,累积 v1.2 修订清单)。
- **B** **不新增 Enum**(event_kind / scope 等用文档约束的字符串常量)。
- **C** 新模块**不依赖旧模块**(如不 import reference_learning)。
- **D** v1.1 内部矛盾 → 按**产品意图**裁决。
- **贯穿**:继续优先**无新依赖**(PR-21 手写 composable、PR-22 手写 SVG + 纯 SQL,均未引入依赖)。

## 五、v1.2 文档修订清单(常驻,累计 9 条)

| # | 来源 | 章节 | 问题 |
|---|---|---|---|
| 1 | PR-1 | §4.1 | `review_finding_%` → `review_reffind_%` |
| 2 | PR-1 | §14 | 文件清单未列 cleanup.py |
| 3 | PR-1 | §4.1 | backup 路径未指定 |
| 4 | PR-1 | §14 | migration 日期 `20260521_*` 已过期 |
| 5 | PR-1 | — | `0001_init_schema` create_all → `if X not in tables` 防御 |
| 6 | hotfix | §附录B | cloud_policy 正确三档 |
| 7 | PR-2 | §6.1 | `quality_balanced` model_profile 不存在 |
| 8 | PR-3 | §4.2/§6.5 | findings UNIQUE → `statement_hash` + 4 列复合 |
| 9 | PR-8 | §11 | auto_rewrite 触发不改 `SceneAutoRewriteService.run` 签名,trigger_source 落 `qc_report.resolution_code` |

## 六、已知遗留 / 剩余工作

- **既有 flaky(非本系列引入)**:`test_qc_engine.py::test_run_scene_soft_qc_patch_repeat_waives_with_carry_note` —— 组合跑必现、单跑通过的 test-ordering 状态泄漏(PR-20 已用 `git stash` 在改动前代码上复现确认无关);根因未定位。
- **PR-23+ 候选**:
  - scheduled cleanup CLI(复用 `cleanup_metric_events` + OS cron,无依赖)/ 或 APScheduler(需依赖)
  - i18n(vue-i18n + 文案抽取,需依赖)
  - 趋势图进阶(多序列 / 比率趋势 / Chart.js 升级)
  - 多 character 叠加进阶 / 其余 dialog a11y 细节

## 七、关键文件索引

- 注入核心:`backend/src/novel_system/services/style_reference/injection.py`
- metrics:`.../style_reference/metrics_aggregator.py`、`metrics_recorder.py`、`cleanup.py`
- 路由:`backend/src/novel_system/api/routes/style_reference.py`(`PATH_PREFIX = /api/v2/style-reference`)
- 前端组件:`frontend/src/components/styleReference/`(ProfileApplyDialog / StyleReferenceMetricsPanel / MetricsTrendChart / InjectionStrategyPicker 等)
- 前端 composable:`frontend/src/composables/useFocusTrap.js`
- 宿主视图:`frontend/src/views/KnowledgeConsoleView.vue`(metrics 面板)、`ReferenceLearningView.vue`

## 八、2026-05-31 收口勘误

- 运行时已下线旧 `/api/v1/reference-books/*` 入口，应用仅保留 `/api/v2/style-reference/*` 作为参考书学习主公开面。
- `POST /api/v2/style-reference/books/{book_id}/reclassify` 已从占位状态改为真实执行：会重跑段落分类、回写 `classifier_calibration` / `paragraph_type_distribution`，并清理旧 runs / findings / profiles / bindings / validation reports / banned terms / 相关 ReviewItem。
- 前端主流程已切到四层全开，默认覆盖 `language + narrative + scene + theme` 共 16 个 sub-dim；文案不再以 “8 sub-dim” 作为主路径描述。
- 当前仓库运行时已移除旧 `reference_books` 路由与旧 `reference_*` ORM 映射；legacy backup / cleanup 能力仅作为迁移安全网保留。
