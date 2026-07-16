import React, { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { DEFAULT_CHAP, DEFAULT_PROJECT, installApiRouter } from "./test-helpers.js";

vi.mock("./lib/client.js", () => ({
  apiGet: vi.fn(), apiPost: vi.fn(), apiPatch: vi.fn(), apiDelete: vi.fn(),
}));

globalThis.IS_REACT_ACT_ENVIRONMENT = true;
const T = { timeout: 5000, interval: 25 };
const mounted = [];
const innerTextDescriptor = Object.getOwnPropertyDescriptor(HTMLElement.prototype, "innerText");

function matchMedia() {
  return {
    matches: false,
    media: "",
    addEventListener: vi.fn(),
    removeEventListener: vi.fn(),
    addListener: vi.fn(),
    removeListener: vi.fn(),
  };
}

async function loadWriter(opts) {
  const client = await import("./lib/client.js");
  installApiRouter(client, opts);
  await import("./ws-catalog.jsx");
  await vi.waitFor(() => expect(window.WsWorks && window.WsWorks.activeId()).toBe("tide"), T);
  await vi.waitFor(() => expect(window.WsCatalog && window.WsCatalog.get().length).toBeGreaterThan(0), T);
  const store = await import("./wr-doc-store.jsx");
  const writer = await import("./ws-writer.jsx");
  return { ...writer, ...store };
}

async function render(node) {
  const host = document.createElement("div");
  document.body.appendChild(host);
  const root = createRoot(host);
  mounted.push({ root, host });
  await act(async () => root.render(node));
  return host;
}

async function click(node) {
  await act(async () => node.dispatchEvent(new MouseEvent("click", { bubbles: true })));
}

beforeEach(() => {
  vi.resetModules();
  window.localStorage.clear();
  Object.defineProperty(window, "matchMedia", { configurable: true, value: matchMedia });
  if (!innerTextDescriptor) {
    Object.defineProperty(HTMLElement.prototype, "innerText", {
      configurable: true,
      get() { return this.textContent || ""; },
      set(value) { this.textContent = value; },
    });
  }
  vi.spyOn(window, "confirm").mockReturnValue(true);
  vi.spyOn(window, "alert").mockImplementation(() => {});
});

afterEach(async () => {
  while (mounted.length) {
    const { root, host } = mounted.pop();
    await act(async () => root.unmount());
    host.remove();
  }
  if (!innerTextDescriptor) delete HTMLElement.prototype.innerText;
  vi.restoreAllMocks();
});

describe("WriterRoom canonical 内容风险复核接缝", () => {
  it("首次 409 打开逐项确认；作者勾选后仅携 exact code 重试", async () => {
    const { WriterRoom, WrDocs } = await loadWriter();
    vi.spyOn(WrDocs, "state").mockReturnValue({ canonicalDirty: true });
    vi.spyOn(WrDocs, "load").mockReturnValue("<p>作者正文</p>");
    vi.spyOn(WrDocs, "save").mockResolvedValue({});
    const reviewError = Object.assign(new Error("review required"), {
      code: "CONTENT_SAFETY_REVIEW_REQUIRED",
      status: 409,
      details: {
        final_text_gate: {
          content_safety: {
            findings: [{
              code: "sexual_content_with_minor_indicators",
              review_required: true,
              acknowledged: false,
              severity: "high",
              confidence: "heuristic",
              message: "核对人物年龄与叙事目的。",
              evidence_terms: ["age:16", "性行为"],
            }],
            limitations: ["启发式不能判断完整语境。"],
          },
        },
      },
    });
    const promote = vi.spyOn(WrDocs, "promote")
      .mockRejectedValueOnce(reviewError)
      .mockResolvedValueOnce({ canonical_dirty: false });

    const host = await render(<WriterRoom t={{}} setTweak={() => {}} />);
    await vi.waitFor(() => expect(host.querySelector(".wr-canonical-promote")?.disabled).toBe(false), T);
    await click(host.querySelector(".wr-canonical-promote"));

    await vi.waitFor(() => expect(document.querySelector(".wr-safety-dialog")).toBeTruthy(), T);
    expect(document.querySelector(".wr-safety-dialog").textContent).toContain("age:16");
    expect(promote).toHaveBeenNthCalledWith(1, "ch01s1", { narrativeEffect: "facts_unchanged" });
    const checkbox = document.querySelector('.wr-safety-dialog input[type="checkbox"]');
    const confirm = document.querySelector('[data-testid="content-safety-confirm"]');
    expect(confirm.disabled).toBe(true);

    await click(checkbox);
    expect(confirm.disabled).toBe(false);
    await click(confirm);

    await vi.waitFor(() => expect(promote).toHaveBeenCalledTimes(2), T);
    expect(promote).toHaveBeenNthCalledWith(2, "ch01s1", {
      narrativeEffect: "facts_unchanged",
      acceptedWarningCodes: ["sexual_content_with_minor_indicators"],
    });
    await vi.waitFor(() => expect(document.querySelector(".wr-safety-dialog")).toBeNull(), T);
    expect(host.querySelector('[data-testid="canonical-status"]').textContent).toBe("权威正文已更新");
  });

  it("已批准章节的正文、权威提升、深改与 AI 续写全部只读", async () => {
    const approvedChapter = {
      ...DEFAULT_CHAP,
      state: "approved",
      scenes: DEFAULT_CHAP.scenes.map((scene) => ({ ...scene, state: "done" })),
    };
    const { WriterRoom, WrDocs } = await loadWriter({ catalog: [approvedChapter] });
    vi.spyOn(WrDocs, "load").mockReturnValue("<p>已经批准的正文</p>");
    const save = vi.spyOn(WrDocs, "save").mockResolvedValue({});

    const host = await render(<WriterRoom t={{}} setTweak={() => {}} />);
    await vi.waitFor(() => expect(host.querySelector(".wr-editor")).toBeTruthy(), T);

    const editor = host.querySelector(".wr-editor");
    expect(editor.getAttribute("contenteditable")).toBe("false");
    expect(editor.getAttribute("aria-readonly")).toBe("true");
    expect(host.textContent).toContain("已批准终稿只读");
    expect(host.querySelector(".wr-canonical-promote").disabled).toBe(true);
    expect([...host.querySelectorAll("button")].find((button) => button.textContent.includes("AI 续写")).disabled).toBe(true);
    expect([...host.querySelectorAll(".wr-sc-actbtn, .wr-sc-addbtn")].every((button) => button.disabled)).toBe(true);

    await act(async () => editor.dispatchEvent(new InputEvent("input", { bubbles: true, inputType: "insertText", data: "越权修改" })));
    expect(save).not.toHaveBeenCalled();
  });

  it("切换作品时立即清除旧场景，目录装载完成前不允许在旧稿上继续写", async () => {
    const secondProject = { ...DEFAULT_PROJECT, project_id: "project-2", title: "第二部作品", is_demo: false };
    const { WriterRoom, WrDocs } = await loadWriter({ projects: [DEFAULT_PROJECT, secondProject] });
    vi.spyOn(WrDocs, "load").mockImplementation((sid) => `<p>${sid} 的正文</p>`);
    const host = await render(<WriterRoom t={{}} setTweak={() => {}} />);
    await vi.waitFor(() => expect(host.textContent).toContain("ch01s1 的正文"), T);

    const client = await import("./lib/client.js");
    const route = client.apiGet.getMockImplementation();
    let resolveSecondCatalog;
    const pending = new Promise((resolve) => { resolveSecondCatalog = resolve; });
    client.apiGet.mockImplementation((url) => (
      url === "/api/v2/projects/project-2/catalog" ? pending : route(url)
    ));

    await act(async () => {
      window.WsWorks.setActive("project-2");
      await new Promise((resolve) => setTimeout(resolve, 0));
    });
    expect(host.textContent).toContain("正在从服务端加载章节与正文");
    expect(host.textContent).not.toContain("ch01s1 的正文");
    expect([...host.querySelectorAll("button")].some((button) => button.textContent.includes("创建第一章"))).toBe(false);

    await act(async () => {
      resolveSecondCatalog({ chapters: [{
        ...DEFAULT_CHAP,
        slug: "p2ch01",
        chapter_id: "p2-c1",
        title: "第二部第一章",
        scenes: [{ ...DEFAULT_CHAP.scenes[0], slug: "p2ch01s1", scene_id: "p2-s1" }],
      }] });
      await pending;
      await new Promise((resolve) => setTimeout(resolve, 0));
    });
    await vi.waitFor(() => expect(host.textContent).toContain("p2ch01s1 的正文"), T);
  });
});
