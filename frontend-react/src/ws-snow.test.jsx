import React, { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const catalog = vi.hoisted(() => ({
  get: vi.fn(() => []),
  adoptOutline: vi.fn(async () => 2),
}));

vi.mock("./ws-catalog.jsx", () => ({ WsCatalog: catalog }));
vi.mock("./ct-app.jsx", () => ({ ControlTower: () => <div data-testid="demo-control-tower" /> }));
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
  });

  it("直接点击“整理为章节结构”会调用真实采用链路，不跳演示控制塔", async () => {
    const host = await renderSnow();

    expect(host.textContent).not.toContain("控制塔总览 · 演示");
    const button = host.querySelector('[data-testid="snow-materialize-top"]');
    expect(button).toBeTruthy();

    await act(async () => button.click());

    expect(catalog.adoptOutline).toHaveBeenCalledTimes(1);
    expect(catalog.adoptOutline).toHaveBeenCalledWith(
      [
        expect.objectContaining({ title: "雨夜来信" }),
        expect.objectContaining({ title: "旧屋回声" }),
      ],
      expect.objectContaining({ outline: expect.any(Object) }),
    );
    expect(host.textContent).toContain("已整理并写入 2 章");
  });
});
