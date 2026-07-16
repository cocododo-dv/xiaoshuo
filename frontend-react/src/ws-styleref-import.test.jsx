import React, { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, describe, expect, it, vi } from "vitest";

vi.mock("./ws-catalog.jsx", () => ({ WsDemoTag: () => null }));
vi.mock("./ws-works.jsx", () => ({ WsWorks: { activeId: () => "new-book" } }));
vi.mock("./ws-review.jsx", () => ({ rvPush: vi.fn() }));

import { SrImportDialog, SR_CLOUD_POLICIES, srImportBook } from "./ws-styleref.jsx";

globalThis.IS_REACT_ACT_ENVIRONMENT = true;
const mounted = [];

async function renderDialog(props) {
  const host = document.createElement("div");
  document.body.appendChild(host);
  const root = createRoot(host);
  mounted.push({ root, host });
  await act(async () => root.render(<SrImportDialog {...props} />));
  await act(async () => new Promise((resolve) => setTimeout(resolve, 0)));
  return host;
}

afterEach(async () => {
  while (mounted.length) {
    const { root, host } = mounted.pop();
    await act(async () => root.unmount());
    host.remove();
  }
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

describe("参考书导入的数据出域选择", () => {
  it("展示三档策略并默认仅本机，作者可显式选择按段落送云", async () => {
    const onChoose = vi.fn();
    const host = await renderDialog({ open: true, onClose: vi.fn(), onChoose });

    expect(SR_CLOUD_POLICIES.map((item) => item.id)).toEqual([
      "local_only", "segments_only", "allow_full_cloud",
    ]);
    expect(host.textContent).toContain("仅保存在本机");
    expect(host.textContent).toContain("只发送所需段落");
    expect(host.textContent).toContain("允许全文上云");
    expect(host.querySelector('input[value="local_only"]').checked).toBe(true);

    await act(async () => host.querySelector('input[value="segments_only"]').click());
    await act(async () => host.querySelector('[data-testid="sr-import-choose-file"]').click());

    expect(onChoose).toHaveBeenCalledWith("segments_only");
  });

  it("Escape 关闭并把焦点还给打开它的按钮", async () => {
    const opener = document.createElement("button");
    document.body.appendChild(opener);
    opener.focus();
    const onClose = vi.fn();
    const host = await renderDialog({ open: true, onClose, onChoose: vi.fn() });
    expect(host.querySelector('[role="dialog"]')).toBeTruthy();

    await act(async () => document.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape", bubbles: true })));
    expect(onClose).toHaveBeenCalledTimes(1);

    const { root } = mounted[mounted.length - 1];
    await act(async () => root.render(<SrImportDialog open={false} onClose={onClose} onChoose={vi.fn()} />));
    expect(document.activeElement).toBe(opener);
    opener.remove();
  });

  it("把作者所选策略原样写入上传表单，不再硬编码 segments_only", async () => {
    const originalCreate = document.createElement.bind(document);
    const fileInput = {
      type: "", accept: "", files: [new File(["片段"], "参考.md", { type: "text/markdown" })],
      onchange: null,
      click() { return this.onchange(); },
    };
    vi.spyOn(document, "createElement").mockImplementation((tag, options) => (
      tag === "input" ? fileInput : originalCreate(tag, options)
    ));
    vi.spyOn(window, "prompt").mockReturnValue("参考书");
    vi.spyOn(window, "alert").mockImplementation(() => {});
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      headers: new Headers(),
      json: async () => ({ ok: true, data: { book: { total_chars: 2 } }, books: [] }),
    });
    vi.stubGlobal("fetch", fetchMock);

    srImportBook("allow_full_cloud");
    await vi.waitFor(() => expect(fetchMock).toHaveBeenCalled());
    await vi.waitFor(() => expect(window.alert).toHaveBeenCalledWith(expect.stringContaining("已导入")));

    const request = fetchMock.mock.calls[0][1];
    expect(request.body).toBeInstanceOf(FormData);
    expect(request.body.get("cloud_policy")).toBe("allow_full_cloud");
  });
});
