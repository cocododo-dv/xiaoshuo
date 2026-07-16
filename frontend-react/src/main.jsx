import React from "react";
// 正式入口装配。CSS 与模块的顺序同时承载层叠和运行时注册语义；
// 调整顺序前必须补齐单元测试、构建与视觉回归。
import "./styles.css";
import "./screens.css";
import "./wr-redesign.css";
import "./wr-desk.css";
import "./ws-shell.css";
import "./wr-recovery.css";
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
import { mountWrRecoveryCenter } from "./wr-recovery-center.jsx";
import ReactDOMClient from "react-dom/client";

// 现有 store 是模块级单例并带副作用订阅，StrictMode 双挂载会触发非幂等订阅；
// 在这些订阅完成幂等化之前，不要直接启用 StrictMode。
ReactDOMClient.createRoot(document.getElementById("root")).render(React.createElement(App));
mountWrRecoveryCenter();
