# frontend-react — 创作工作台（正式前端）

「潮汐工作台」高保真原型（`codex-patches/FE-主线对齐/design/`，React 18 + Babel standalone）
的工程化版本：Vite + React 18，视觉与交互逐像素保留。FE 主线对齐任务的 D1 决策：
本工程是产品形态的最终前端；Vue 前端（`frontend/`，端口 5173）并行保留，
稳定一个写作周期后再退役。

## 双前端入口

| 前端 | 目录 | 端口 | 说明 |
|---|---|---|---|
| React（本工程） | `frontend-react/` | 5174 | 原型工程化，FE 对齐主线 |
| Vue（既有） | `frontend/` | 5173 | 旧前端，保留为备用 |

仓库根 `.\start-dev.cmd` 会同时启动后端 + 两个前端；`.\stop-dev.cmd` 一并停止。

## 命令

```powershell
cd frontend-react
npm install        # 首次
npm run dev        # http://127.0.0.1:5174
npm run build      # 产物到 dist/
```

## 结构与约定

- `src/` 由 `scripts/port-design.mjs` 从 `design/` 机械转换生成（import/export 化，
  逻辑零改动）；之后的 Phase 在此基础上演进，**不再重跑 codemod 覆盖**。
- CSS 与 JSX 模块在 `src/main.jsx` 中严格按 `design/index.html` 的原始引用顺序导入，
  顺序有层叠/注册语义，禁止重排。
- 过渡期保留 `window.*` 兼容赋值与 `wsKey()`（Phase 8 清理）。
- store 缝合面契约见 `codex-patches/FE-主线对齐/契约附录-store缝合面.md`：
  视图层零修改，store 公开签名不可变。
- `scripts/shoot-views.mjs` / `scripts/smoke-interact.mjs`：15 视图截图回归与交互冒烟
  （从 `frontend/` 目录运行以复用其 Playwright 安装）。
