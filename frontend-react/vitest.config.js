import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";

// 单测配置与 vite.config.js 分离：build 配置不受影响。
// store 层是挂在 window 上的运行时全局（ws-works.jsx 等），需 jsdom 提供
// window/localStorage；React 插件负责 .jsx 转换。
export default defineConfig({
  plugins: [react()],
  test: {
    environment: "jsdom",
    globals: true,
    include: ["src/**/*.{test,spec}.{js,jsx}"],
    restoreMocks: true,
    clearMocks: true,
  },
});
