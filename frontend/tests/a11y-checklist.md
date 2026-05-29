# Style Reference a11y 覆盖清单(PR-13)

无 axe-core 依赖;ARIA / 键盘用原生 HTML + Vue,测试用 vitest jsdom getAttribute 断言。

## 组件 a11y 覆盖矩阵

| 组件 | ARIA | 键盘 | 焦点可见 | 备注 |
|---|---|---|---|---|
| ProfileApplyDialog | role=dialog / aria-modal / aria-labelledby | Escape 关闭 / mask @click.self 关闭 / 打开初始 focus | dialog-close focus-visible | 完整 Tab trap 留 PR-14 |
| InjectionStrategyPicker | role=group / 4 button aria-pressed | 原生 button Enter/Space | strat-btn focus-visible | Arrow-key radiogroup 导航留 PR-14 |
| IntensitySlider | aria-label / aria-valuetext | 原生 range ←→/PageUp/Down | range focus-visible | — |
| DimensionMultiSelect | role=group / aria-label / 快捷 button aria-label | 原生 checkbox Space / button Enter | action/checkbox focus-visible | — |
| InjectionBundlePreview | toggle aria-expanded / aria-controls | 原生 button Enter/Space | toggle focus-visible | 复用 LazySection 模式 |
| StyleReferenceMetricsPanel | window-tabs role=group / aria-pressed | 原生 button Enter/Space | win-btn focus-visible | — |
| FindingCard | 3 badge aria-label(类型/置信度/状态) | 原生 BaseButton | BaseButton 自带 | article 语义标签 |

## 对比度核对(局部 scoped,不动全局 app.css)

浅背景 ≈ #fffdf7(panel-solid);棕色文本 rgba(33,26,21,α)。WCAG AA 正文 ≥ 4.5:1。

| 类 | 原 α | 改后 α | 组件 |
|---|---|---|---|
| .dialog-close | 0.55 | 0.72 | ProfileApplyDialog |
| .strat-desc | 0.62 | 0.72 | InjectionStrategyPicker |
| .intensity-scale / .ticks | 0.6 / 0.55 | 0.72 | IntensitySlider |
| .bp-strategy / .bp-loading / .bp-empty / .bp-prefix-toggle | 0.6~0.62 | 0.72~0.78 | InjectionBundlePreview |
| .metric-label / .metric-hint / .sr-metrics-foot / loading-empty | 0.55~0.65 | 0.72 | StyleReferenceMetricsPanel |

> rgba(33,26,21,0.72) 对 #fffdf7 估算 ≈ 5.5:1,满足 AA。仅提 alpha,不改色相;局部 scoped 不影响其他 view。

## 未覆盖(留 PR-14+)

- 完整 focus trap(Tab/Shift+Tab 循环捕获)
- InjectionStrategyPicker arrow-key radiogroup 导航
- 全局 app.css token 对比度根治(本 PR 只局部覆盖)
- axe-core 自动 a11y 审计(无新依赖政策下不引入)

## 新加 testid 时同步

a11y 属性是 attribute 增量,不改 DOM 结构 / class / testid;E2E getByTestId 不受影响。
