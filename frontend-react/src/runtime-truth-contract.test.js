import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";

const srcRoot = path.dirname(fileURLToPath(import.meta.url));

describe("正式运行时文案与行为一致", () => {
  it("设置页不会把仅清理浏览器缓存冒充为重置服务端作品", () => {
    const source = fs.readFileSync(path.join(srcRoot, "ws-settings.jsx"), "utf8");
    expect(source).toContain("不会删除服务端作品、章节或正文");
    expect(source).toContain('label="清除本机缓存"');
    expect(source).not.toContain("重置本作品");
    expect(source).not.toContain("回到示例种子状态");
  });

  it("主页待办没有退役演示种子的回退入口", () => {
    const source = fs.readFileSync(path.join(srcRoot, "ws-home.jsx"), "utf8");
    expect(source).not.toContain("window.RV_SEED");
  });

  it("互操作页不把浏览器缓存冒充完整项目备份或恢复入口", () => {
    const source = fs.readFileSync(path.join(srcRoot, "ws-ops.jsx"), "utf8");
    expect(source).toContain("__ws_cache_snapshot");
    expect(source).toContain("includes_server_database: false");
    expect(source).toContain("/api/v1/interop/preview/bundle-worksheet");
    expect(source).toContain("/api/v1/interop/import/bundle-worksheet");
    expect(source).not.toContain("__ws_backup");
    expect(source).not.toContain("tide-workbench");
    expect(source).not.toContain("ioImportBundle");
    expect(source).not.toContain("已恢复为新作品");
    expect(source).not.toContain("当前作品的全部状态，可备份可迁移");
  });
});
