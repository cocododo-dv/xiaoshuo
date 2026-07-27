import React, { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const catalog = vi.hoisted(() => ({
  get: vi.fn(() => []),
  adoptOutline: vi.fn(async () => 2),
}));

vi.mock("./ws-catalog.jsx", () => ({ WsCatalog: catalog }));
vi.mock("./ws-works.jsx", () => ({
  wsKey: (base) => `${base}::new-book`,
  WsWorks: {
    activeId: () => "new-book",
    active: () => ({ id: "new-book", title: "真正的新书" }),
  },
}));

import { WsSnowflake } from "./ws-snow.jsx";

globalThis.IS_REACT_ACT_ENVIRONMENT = true;

const mounted = [];

async function renderSnow() {
  const host = document.createElement("div");
  document.body.appendChild(host);
  const root = createRoot(host);
  mounted.push({ root, host });
  await act(async () => root.render(<WsSnowflake initialStep="paragraph" onOverview={vi.fn()} />));
  return host;
}

describe("真实新项目的雪花顶部主操作", () => {
  beforeEach(() => {
    window.localStorage.clear();
    catalog.get.mockReturnValue([]);
    catalog.adoptOutline.mockClear();
    vi.spyOn(window, "confirm").mockReturnValue(true);
    vi.spyOn(window, "alert").mockImplementation(() => {});
    // 分章面板打开即拉后端预览（算法在后端，前端不再持有第二套）
    window.SnowSync = {
      chapterPreview: vi.fn(async () => ({
        strategy: "spine_anchor",
        chapters: [
          { row_uid: "c1", chapter_seq: 1, act: 1, title: "雨夜来信", spine: "灾一", chapter_goal: "信件迫使主角回乡",
            scene_count: 1, scenes: [{ scene_plan_id: "sp1", scene_id: "SC1", scene_seq: 1, title: "第一场", primary_form: "proactive", spine: "灾一", anchored: true, planned: true }] },
          { row_uid: "c2", chapter_seq: 2, act: 1, title: "旧屋回声", spine: "", chapter_goal: "旧证词出现裂缝",
            scene_count: 1, scenes: [{ scene_plan_id: "sp2", scene_id: "SC2", scene_seq: 1, title: "第二场", primary_form: "reactive", spine: "", anchored: false, planned: true }] },
        ],
        unassigned: [],
        removed_scenes: [],
        warnings: [],
        totals: { chapter_count: 2, scene_count: 2, unassigned_count: 0 },
      })),
      materialize: vi.fn(async () => ({ created_chapter_count: 2 })),
    };
    window.localStorage.setItem("ws_snow_state_v2::new-book", JSON.stringify({
      scaffolds: {
        outline: {
          chapters: [
            { id: "01", act: 1, title: "雨夜来信", summary: "信件迫使主角回乡", spine: "灾一" },
            { id: "02", act: 1, title: "旧屋回声", summary: "旧证词出现裂缝", spine: "" },
          ],
        },
      },
    }));
  });

  afterEach(async () => {
    while (mounted.length) {
      const { root, host } = mounted.pop();
      await act(async () => root.unmount());
      host.remove();
    }
    vi.restoreAllMocks();
    try { delete window.SnowSync; } catch (e) {}
  });

  it("点击“整理为章节结构”打开分章预览面板，而不是直接落库", async () => {
    // P2：这个按钮以前是 window.confirm 加三条互不相同的落库路径，选哪条取决于闸门
    // 状态 —— 做得越完整反而掉进最差的那条，而且确认框说「并入 12 章」实际写 1 章。
    // 现在它只做一件事：打开预览，让作者按下确认之前就看得见会得到什么。
    const host = await renderSnow();

    const button = host.querySelector('[data-testid="snow-materialize-top"]');
    expect(button).toBeTruthy();

    await act(async () => button.click());

    expect(host.querySelector('[data-testid="chapter-plan-panel"]')).toBeTruthy();
    expect(window.SnowSync.chapterPreview).toHaveBeenCalledTimes(1);
    // 预览阶段绝不落库
    expect(catalog.adoptOutline).not.toHaveBeenCalled();
    expect(window.SnowSync.materialize).not.toHaveBeenCalled();
  });
});
