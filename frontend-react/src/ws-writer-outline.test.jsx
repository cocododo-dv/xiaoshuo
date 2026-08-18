// 写作台「章节大纲」抽屉的删除 / 批量删除契约。
// 目录写穿点是 WsCatalog（单一真相源）——这里断言抽屉里的删除动作最终变成
// 一次带完整 id 集合的软删调用，而不是只改本地渲染；被删章下的场不再单独进场景桶
// （后端会以「章下已有单独回收的场景」挡下整章删除，那正是「删了又冒出来」的来源）。
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

const SECOND_CHAP = {
  ...DEFAULT_CHAP,
  slug: "ch02", chapter_id: "c2", no: "02", title: "第二章", current: false,
  scenes: [
    { ...DEFAULT_CHAP.scenes[0], slug: "ch02s1", scene_id: "s2", title: "夜航" },
    { ...DEFAULT_CHAP.scenes[0], slug: "ch02s2", scene_id: "s3", title: "回港" },
  ],
};

function matchMedia() {
  return { matches: false, media: "", addEventListener: vi.fn(), removeEventListener: vi.fn(), addListener: vi.fn(), removeListener: vi.fn() };
}

async function loadWriter(opts) {
  const client = await import("./lib/client.js");
  installApiRouter(client, opts);
  await import("./ws-catalog.jsx");
  await vi.waitFor(() => expect(window.WsWorks && window.WsWorks.activeId()).toBe("prj-main"), T);
  await vi.waitFor(() => expect(window.WsCatalog && window.WsCatalog.get().length).toBeGreaterThan(0), T);
  const writer = await import("./ws-writer.jsx");
  return { ...writer, client };
}

async function render(node) {
  const host = document.createElement("div");
  document.body.appendChild(host);
  const root = createRoot(host);
  mounted.push({ root, host });
  await act(async () => root.render(node));
  return host;
}

const click = (node) => act(async () => node.dispatchEvent(new MouseEvent("click", { bubbles: true })));

/* 大纲抽屉常驻 DOM（靠 class 控制显隐），所以直接取节点即可，不必先开抽屉 */
const outline = (host) => host.querySelector(".wr-drawer.left");

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

describe("写作台 · 章节大纲的删除与批量删除", () => {
  it("章行删除按钮把整章（含章下场景）软删，只发一次 chapters/trash", async () => {
    const { WriterRoom, client } = await loadWriter({ catalog: [DEFAULT_CHAP, SECOND_CHAP] });
    const host = await render(<WriterRoom t={{}} setTweak={() => {}} />);
    client.apiPost.mockClear();

    const delButtons = [...outline(host).querySelectorAll(".wr-ch-del")];
    expect(delButtons).toHaveLength(2);
    await click(delButtons[1]);

    expect(window.confirm).toHaveBeenCalled();
    await vi.waitFor(() => expect(client.apiPost).toHaveBeenCalledWith(
      "/api/v1/chapters/trash", { chapter_ids: ["c2"] },
    ), T);
    expect(client.apiPost.mock.calls.some(([url]) => url === "/api/v1/scenes/trash")).toBe(false);
    expect(client.apiPost.mock.calls.filter(([url]) => url === "/api/v1/chapters/trash")).toHaveLength(1);
  });

  it("多选批量删除：章 + 场一次提交，被删章下的场不再单独进场景桶", async () => {
    const { WriterRoom, client } = await loadWriter({ catalog: [DEFAULT_CHAP, SECOND_CHAP] });
    const host = await render(<WriterRoom t={{}} setTweak={() => {}} />);
    client.apiPost.mockClear();

    await click(outline(host).querySelector('[data-testid="writer-outline-select-mode"]'));
    // 勾第二章整章 + 第一章的那一场
    const chBoxes = [...outline(host).querySelectorAll(".wr-ch-check input")];
    expect(chBoxes).toHaveLength(2);
    await act(async () => { chBoxes[1].click(); });
    const scBoxes = [...outline(host).querySelectorAll(".wr-sc-check input")];
    await act(async () => { scBoxes[0].click(); });

    await click(outline(host).querySelector('[data-testid="writer-outline-batch-delete"]'));

    await vi.waitFor(() => expect(client.apiPost).toHaveBeenCalledWith(
      "/api/v1/chapters/trash", { chapter_ids: ["c2"] },
    ), T);
    // 只有第一章那一场单独进场景桶；第二章下的 s2/s3 随章一起走
    await vi.waitFor(() => expect(client.apiPost).toHaveBeenCalledWith(
      "/api/v1/scenes/trash", { scene_ids: ["s1"] },
    ), T);
  });

  it("勾选整章后章下场景显示为随章带走，不再当成一次独立选择计数", async () => {
    const { WriterRoom } = await loadWriter({ catalog: [DEFAULT_CHAP, SECOND_CHAP] });
    const host = await render(<WriterRoom t={{}} setTweak={() => {}} />);
    const panel = outline(host);

    await click(panel.querySelector('[data-testid="writer-outline-select-mode"]'));
    const chBoxes = [...panel.querySelectorAll(".wr-ch-check input")];
    await act(async () => { chBoxes[1].click(); });      // 勾第二章（章下两场）

    const scBoxes = [...panel.querySelectorAll(".wr-sc-check input")];
    const followers = scBoxes.filter((box) => box.disabled);
    expect(followers).toHaveLength(2);                    // 第二章的两场
    expect(followers.every((box) => box.checked)).toBe(true);
    // 计数只报作者真正做过的选择，随章带走的场单独说明
    expect(panel.querySelector(".wr-outline-batch-n").textContent).toContain("1");
    expect(panel.querySelector(".wr-outline-batch-n").textContent).toContain("随章带走 2 场");
  });

  it("删除后给出回执并指向回收站，不让作者对着消失的章发呆", async () => {
    const go = vi.fn();
    const { WriterRoom } = await loadWriter({ catalog: [DEFAULT_CHAP, SECOND_CHAP] });
    const host = await render(<WriterRoom t={{}} setTweak={() => {}} go={go} />);

    await click([...outline(host).querySelectorAll(".wr-ch-del")][1]);

    const toast = host.querySelector('[data-testid="undo-toast"]');
    expect(toast.textContent).toContain("移入回收站");
    await click(toast.querySelector('[data-testid="undo-toast-action"]'));
    expect(go).toHaveBeenCalledWith("trash");
  });

  it("已批准章节在大纲里既删不掉也勾不动（要先去成稿中心重新打开）", async () => {
    const approved = { ...DEFAULT_CHAP, state: "approved" };
    const { WriterRoom, client } = await loadWriter({ catalog: [approved] });
    const host = await render(<WriterRoom t={{}} setTweak={() => {}} />);
    client.apiPost.mockClear();

    const del = outline(host).querySelector(".wr-ch-del");
    expect(del).toHaveProperty("disabled", true);
    await click(del);
    expect(client.apiPost).not.toHaveBeenCalled();

    await click(outline(host).querySelector('[data-testid="writer-outline-select-mode"]'));
    expect(outline(host).querySelector(".wr-ch-check input")).toHaveProperty("disabled", true);
    expect(outline(host).querySelector(".wr-sc-check input")).toHaveProperty("disabled", true);
  });
});

describe("写作台 · AI 续写三候选", () => {
  it("用一次 generate-set 请求取得三份独立续写，不再并发三个同签名 mutation", async () => {
    const { wrContinueMulti, client } = await loadWriter();
    vi.spyOn(window.WrDocs, "draftId").mockResolvedValue("draft-s1");
    client.apiPost.mockResolvedValue({
      mode: "continuation_variants",
      proposals: [
        { proposal_id: "p-action", proposal_type: "continuation", content: "她推门追了出去。", rationale: "动作推进" },
        { proposal_id: "p-relation", proposal_type: "continuation", content: "他没有回头，却放慢了脚步。", rationale: "关系压力" },
        { proposal_id: "p-suspense", proposal_type: "continuation", content: "门外只剩一枚还在发热的钥匙。", rationale: "悬念信息" },
      ],
    });
    client.apiPost.mockClear();

    const candidates = await wrContinueMulti("自然承接下一拍");

    expect(client.apiPost).toHaveBeenCalledTimes(1);
    expect(client.apiPost).toHaveBeenCalledWith(
      "/api/v1/author-drafts/draft-s1/proposals/generate-set",
      {
        mode: "continuation_variants",
        instruction: "自然承接下一拍",
      },
    );
    expect(candidates.map((item) => item.id)).toEqual(["p-action", "p-relation", "p-suspense"]);
    expect(candidates.map((item) => item.html)).toEqual([
      "她推门追了出去。",
      "他没有回头，却放慢了脚步。",
      "门外只剩一枚还在发热的钥匙。",
    ]);
  });
});
