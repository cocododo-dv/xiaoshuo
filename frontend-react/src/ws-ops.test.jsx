import React, { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const api = vi.hoisted(() => ({
  get: vi.fn(),
  post: vi.fn(),
}));

vi.mock("./lib/client.js", () => ({
  apiGet: api.get,
  apiPost: api.post,
}));

vi.mock("./ws-catalog.jsx", () => ({
  WsCatalog: {
    get: () => [],
    totals: () => ({ words: 12000, planned: 3 }),
  },
  useCatalogChapters: () => [],
}));

vi.mock("./ws-review.jsx", () => ({
  rvCustomList: () => [],
  rvIsResolved: () => false,
}));

vi.mock("./ws-works.jsx", () => ({
  WsWorks: {
    activeId: () => "project-1",
    active: () => ({ id: "project-1", title: "北岸手记", genre: "悬疑", sub: "长篇" }),
  },
}));

import { WsInterop, ioBuildCacheSnapshot } from "./ws-ops.jsx";

globalThis.IS_REACT_ACT_ENVIRONMENT = true;
const mounted = [];

const envelope = {
  bundle_id: "bundle-1",
  scene_id: "scene-1",
  chapter_id: "chapter-1",
  bundle_snapshot_hash: "sha256:abc",
  execution_mode: "P0_manual",
  created_by_action: "bundle_worksheet_import",
  snapshot: {},
};

function previewPayload() {
  return {
    envelope,
    summary: {
      bundle_id: "bundle-1",
      scene_id: "scene-1",
      chapter_id: "chapter-1",
      comparison_count: 0,
    },
    source_ref_comparisons: [],
  };
}

async function renderInterop(go = vi.fn()) {
  const host = document.createElement("div");
  document.body.appendChild(host);
  const root = createRoot(host);
  mounted.push({ root, host });
  await act(async () => root.render(<WsInterop go={go} />));
  return { host, go };
}

async function setControl(node, value) {
  const prototype = node instanceof HTMLTextAreaElement ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype;
  const setter = Object.getOwnPropertyDescriptor(prototype, "value").set;
  await act(async () => {
    setter.call(node, value);
    node.dispatchEvent(new Event("input", { bubbles: true }));
    node.dispatchEvent(new Event("change", { bubbles: true }));
  });
}

async function click(node) {
  await act(async () => node.click());
  await act(async () => { await Promise.resolve(); await Promise.resolve(); });
}

beforeEach(() => {
  vi.clearAllMocks();
  localStorage.clear();
  api.post.mockImplementation((path) => {
    if (path.endsWith("/preview/bundle-worksheet")) return Promise.resolve(previewPayload());
    if (path.endsWith("/import/bundle-worksheet")) {
      return Promise.resolve({
        envelope,
        bundle: { bundle_id: "bundle-1" },
        artifact_receipt: { artifact_id: "artifact-1", artifact_kind: "bundle_worksheet_import" },
        source_ref_comparisons: [],
      });
    }
    return Promise.reject(new Error("unexpected POST"));
  });
  api.get.mockResolvedValue({
    envelope,
    artifact_receipt: { artifact_id: "artifact-2", artifact_kind: "bundle_worksheet_export" },
    source_ref_comparisons: [],
  });
});

afterEach(async () => {
  while (mounted.length) {
    const { root, host } = mounted.pop();
    await act(async () => root.unmount());
    host.remove();
  }
});

describe("互操作中心真实边界", () => {
  it("缓存快照只收集当前作品后缀键，并显式声明非权威且不可导入", () => {
    localStorage.setItem("wr-doc:scene-1::project-1", "本机缓存");
    localStorage.setItem("wr-doc:scene-2::project-2", "其他作品");
    localStorage.setItem("novel-system-operator-ref", "operator");

    const snapshot = ioBuildCacheSnapshot();

    expect(snapshot.__ws_cache_snapshot).toBe(1);
    expect(snapshot.app).toBe("novel-system-workbench");
    expect(snapshot.boundary).toMatchObject({
      authoritative: false,
      import_supported: false,
      includes_server_database: false,
    });
    expect(snapshot.keys).toEqual({ "wr-doc:scene-1": "本机缓存" });
  });

  it("工作表必须先由后端预览，且文本变化后重新锁住导入", async () => {
    const { host } = await renderInterop();
    const editor = host.querySelector('[data-testid="interop-worksheet-input"]');
    const importButton = host.querySelector('[data-testid="interop-import-button"]');
    expect(importButton.disabled).toBe(true);

    await setControl(editor, "bundle_id: bundle-1");
    await click(host.querySelector('[data-testid="interop-preview-button"]'));
    await vi.waitFor(() => expect(api.post).toHaveBeenCalledWith(
      "/api/v1/interop/preview/bundle-worksheet",
      { worksheet_yaml: "bundle_id: bundle-1" },
    ));
    await vi.waitFor(() => expect(importButton.disabled).toBe(false));

    await setControl(editor, "bundle_id: bundle-changed");
    expect(importButton.disabled).toBe(true);
  });

  it("预览未变化时调用真实导入端点，并渲染服务端回执", async () => {
    const { host } = await renderInterop();
    const editor = host.querySelector('[data-testid="interop-worksheet-input"]');
    await setControl(editor, "bundle_id: bundle-1");
    await click(host.querySelector('[data-testid="interop-preview-button"]'));
    const importButton = host.querySelector('[data-testid="interop-import-button"]');
    await vi.waitFor(() => expect(importButton.disabled).toBe(false));
    await click(importButton);

    await vi.waitFor(() => expect(api.post).toHaveBeenCalledWith(
      "/api/v1/interop/import/bundle-worksheet",
      { worksheet_yaml: "bundle_id: bundle-1" },
    ));
    await vi.waitFor(() => expect(host.querySelector('[data-testid="interop-envelope-panel"]')?.textContent).toContain("artifact-1"));
  });

  it("按服务端 ID 加载 bundle 导出结果，并对路径参数编码", async () => {
    const { host } = await renderInterop();
    const input = host.querySelector('[data-testid="interop-export-bundle-id"]');
    await setControl(input, "bundle/with space");
    await click(host.querySelector('[data-testid="interop-export-button"]'));

    await vi.waitFor(() => expect(api.get).toHaveBeenCalledWith(
      "/api/v1/interop/export/bundle-worksheet/bundle%2Fwith%20space",
    ));
    expect(host.querySelector('[data-testid="interop-envelope-panel"]')).not.toBeNull();
  });

  it("服务端成稿导出不再读本机正文，而是导航到成稿中心", async () => {
    const go = vi.fn();
    const { host } = await renderInterop(go);
    const button = [...host.querySelectorAll("button")].find((node) => node.textContent.includes("前往成稿中心"));
    await click(button);
    expect(go).toHaveBeenCalledWith("manuscripts");
  });
});
