# Style Reference E2E testid Registry

PR-11 §"自决决策" 文档化命名约定 + 当前已注册 testid。每次新加 testid 时同步更新本文件。

## 命名约定

- **kebab-case + 前缀 + 功能[-id]**
- 容器级:`{domain}-{noun}` 或 `{domain}-{noun}-{role}`(如 `reference-learning-view` / `reference-book-list`)
- 操作按钮:`{domain}-{verb}-{noun?}`(如 `reference-start-run` / `reference-import-submit`)
- 表单元素:`{domain}-{field-name}`(如 `reference-import-path`)
- 条目级:`{domain}-{type}-{id}`(如 `reference-finding-{finding_id}` / `reference-approve-{finding_id}`)
- 多选/层级:`{noun}-{layer}-{value}`(如 `sub-dim-language.sentence_structure` / `strategy-A`)
- 状态指示:`{component}-{state}`(如 `bundle-preview-loading` / `bundle-preview-error` / `metrics-empty`)

## 已注册 testid 索引

### ReferenceLearningView.vue + FindingCard.vue(PR-11 加)

| testid | 元素 | 来源 |
|---|---|---|
| `reference-learning-view` | view 根 main | PR-11 |
| `reference-import-toggle` / `reference-import-toggle-upload` | 路径/上传 tab | PR-11 |
| `reference-import-path` | 文件路径 input | PR-11 |
| `reference-import-submit` | 开始导入 btn | PR-11 |
| `reference-book-list` | 参考书列表 ul | PR-11 |
| `reference-start-run` | 启动抽取 btn | PR-11 |
| `reference-advance-run` | 聚合为 Profile btn | PR-11 |
| `reference-finding-list` | findings 容器 div | PR-11 |
| `reference-finding-{finding_id}` | finding 卡片 article | PR-11 |
| `reference-approve-{finding_id}` | finding 通过 btn | PR-11 |
| `reference-reject-{finding_id}` | finding 驳回 btn | PR-11 |
| `reference-reset-{finding_id}` | finding 重置 btn | PR-11 |
| `reference-apply-button` | 应用 Profile btn | PR-11 |

### PR-9 4 组件

| testid | 元素 | 来源 |
|---|---|---|
| `strategy-A` / `strategy-B` / `strategy-C` / `strategy-mixed` | 4 strategy 按钮 | PR-9 |
| `mixed-controls` | MIXED 展开容器 | PR-9 |
| `intensity-input` | range slider input | PR-9 |
| `select-all` / `clear-all` | 全选/全反选 btn | PR-9 |
| `select-layer-{layer_key}` | 各层全选 btn(language/narrative/scene/theme)| PR-9 |
| `sub-dim-{dimension_path}` | 16 个 sub_dim checkbox | PR-9 |
| `bundle-preview` | 预览根 section | PR-9 |
| `bundle-preview-loading` / `bundle-preview-error` / `bundle-preview-empty` | 三态 | PR-9 |
| `bundle-preview-prefix` | system_prompt 前缀容器 | PR-9 |
| `confirm-apply` | 应用确认 btn | PR-9 |

### PR-10 Metrics Panel

| testid | 元素 | 来源 |
|---|---|---|
| `style-reference-metrics-panel` | panel 根 section | PR-10 |
| `metrics-loading` / `metrics-error` / `metrics-empty` | 三态 | PR-10 |
| `metric-injection` / `metric-qc-reject` / `metric-auto-rewrite` / `metric-p95` | 4 指标卡 | PR-10 |
| `window-168` / `window-720` / `window-0` | 时间窗口 btn | PR-10 |
| `knowledge-toggle-style-reference-metrics` | KnowledgeConsole 内 LazySection toggle | PR-10 |

## 新加 testid 流程

1. 在被改组件加 `:data-testid="..."` 或 `data-testid="..."`
2. 同步本表(类型 / 元素 / 来源 PR)
3. 写 E2E spec 用 `page.getByTestId(...)` 调用
4. commit 时一并提交本文件改动
