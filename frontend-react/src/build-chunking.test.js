import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";

import { domainChunk, productionChunk } from "../build-chunks.js";

describe("生产构建业务域分块", () => {
  it.each([
    ["ws-snow.jsx", "domain-snowflake"],
    ["ws-snow-sync.jsx", "domain-snowflake"],
    ["ws-styleref.jsx", "domain-style-reference"],
    ["ws-writer.jsx", "domain-writer"],
    ["ws-scene-run.jsx", "domain-scene"],
    ["ws-author.jsx", "domain-author"],
    ["ws-library-edit.jsx", "domain-library"],
    ["ws-manuscripts.jsx", "domain-manuscripts"],
    ["ws-eval.jsx", "domain-quality"],
    ["ws-ops.jsx", "domain-operations"],
    ["ws-settings-ai.jsx", "domain-settings"],
  ])("将 %s 放入 %s", (file, expected) => {
    expect(domainChunk(`E:\\repo\\frontend-react\\src\\${file}`)).toBe(expected);
  });

  it("将第三方依赖与核心入口分别处理", () => {
    expect(domainChunk("E:/repo/frontend-react/node_modules/react/index.js")).toBe("vendor");
    expect(domainChunk("E:/repo/frontend-react/src/ws-app.jsx")).toBeUndefined();
    expect(productionChunk("E:/repo/frontend-react/node_modules/react/index.js")).toBe("vendor");
    expect(productionChunk("E:/repo/frontend-react/src/ws-writer.jsx")).toBeUndefined();
  });

  it("入口不再用副作用导入预加载全部业务模块", () => {
    const srcRoot = path.dirname(fileURLToPath(import.meta.url));
    const main = fs.readFileSync(path.join(srcRoot, "main.jsx"), "utf8");
    const sideEffectJsImports = [...main.matchAll(/import\s+["'](\.\/[^"']+\.(?:js|jsx))["']/g)]
      .map((match) => match[1]);
    expect(sideEffectJsImports).toEqual([]);
    expect(main).toContain("<React.StrictMode>");
  });

  it("业务页面由路由动态导入，并以挂载握手投递跨页指令", () => {
    const srcRoot = path.dirname(fileURLToPath(import.meta.url));
    const app = fs.readFileSync(path.join(srcRoot, "ws-app.jsx"), "utf8");
    for (const moduleName of [
      "ws-home.jsx", "ws-snow.jsx", "ws-flowmap.jsx", "ws-styleref.jsx", "ws-library.jsx",
      "ws-author.jsx", "ws-scene.jsx", "ws-manuscripts.jsx", "ws-quality.jsx", "ws-eval.jsx",
      "ws-cost.jsx", "ws-ops.jsx", "ws-settings.jsx", "ws-writer.jsx",
    ]) {
      expect(app, moduleName).toContain(`import("./${moduleName}")`);
    }
    expect(app).toContain("<ViewReady view={view}>");
    expect(app).not.toMatch(/setTimeout\([^\n]+dispatchEvent/);
  });
});
