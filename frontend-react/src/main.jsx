import React from "react";
// 入口装配（Phase 1）。CSS 与模块均按 design/index.html 的原始引用顺序导入 —
// 两者的顺序都有语义（CSS 层叠 / window 注册先后），禁止重排。
import "./styles.css";
import "./screens.css";
import "./wr-redesign.css";
import "./wr-desk.css";
import "./ws-shell.css";
import "./ws-library.css";
import "./ws-author.css";
import "./ws-review.css";
import "./ct.css";
import "./ws-deep.css";
import "./lf2.css";
import "./lf2-parts.css";
import "./lf3.css";
import "./lf6.css";

import "./icons.jsx";
import "./tweaks-panel.jsx";
import "./ws-works.jsx";
import "./ws-author-data.jsx";
import "./ws-catalog.jsx";
import "./ct-data.jsx";
import "./ct-map.jsx";
import "./ct-panels.jsx";
import "./ct-edit.jsx";
import "./ct-app.jsx";
import "./ws-deep.jsx";
import "./ws-writer.jsx";
import "./ws-review.jsx";
import "./ws-home.jsx";
import "./ws-snow.jsx";
import "./ws-snow-sync.jsx"; // FE-ALIGN F3：构思 ↔ snowflake-workspace v2 同步（store 层新增，不在原型清单内）
import "./ws-flowmap.jsx";
import "./ws-styleref-val.jsx";
import "./ws-styleref.jsx";
import "./ws-library-data.jsx";
import "./ws-library-derive.jsx";
import "./ws-library-graph.jsx";
import "./ws-library-timeline.jsx";
import "./ws-library-overview.jsx";
import "./ws-library-edit.jsx";
import "./ws-library.jsx";
import "./ws-author-loom.jsx";
import "./ws-author-pacing.jsx";
import "./ws-author-doctor.jsx";
import "./ws-author.jsx";
import "./ws-scene-run.jsx";
import "./ws-scene.jsx";
import "./ws-manuscripts.jsx";
import "./lf2-data.jsx";
import "./lf3-data.jsx";
import "./lf7-bridge.jsx";
import "./lf3-atlas.jsx";
import "./lf3-guard.jsx";
import "./lf3-console.jsx";
import "./lf3-app.jsx";
import "./lf4-console.jsx";
import "./lf5-guard.jsx";
import "./lf6-app.jsx";
import "./ws-ops.jsx";
import "./ws-settings.jsx";
import "./ws-palette.jsx";
import { App } from "./ws-app.jsx";
import ReactDOMClient from "react-dom/client";

// 原型的 store 是模块级单例 + 副作用订阅，StrictMode 双挂载会暴露非幂等订阅；
// 保真优先不包 StrictMode（陷阱 T4），治理留到 Phase 8。
ReactDOMClient.createRoot(document.getElementById("root")).render(React.createElement(App));
