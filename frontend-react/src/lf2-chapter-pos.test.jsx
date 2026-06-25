import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { installApiRouter } from "./test-helpers.js";

/* 正确性回归：长篇控制塔的「本章」章号定位（LF2_NEXT / LF2_BOOK.now）此前只在
   tide 演示书里随目录同步，lf2SyncFromCatalog 对非 tide 作品整体早退，导致 LF2_NEXT
   恒为 tide 常量 now+1=9 —— 非 tide 短书的 auditReceipt/adjudicateDraft 静默指向不存在
   的第 9 章；长书则审计/裁定到错误的第 9 章。修复让章号定位对所有作品都取目录真相，
   仅把 beat / 理想张力的演示结构层保留给 tide。 */

vi.mock("./lib/client.js", () => ({
  apiGet: vi.fn(),
  apiPost: vi.fn(),
  apiPatch: vi.fn(),
  apiDelete: vi.fn(),
}));

const T = { timeout: 5000, interval: 25 };

function chap(no, state, current) {
  return { slug: `ch${no}`, chapter_id: `c${no}`, no, title: `第 ${parseInt(no, 10)} 章`, state, current: !!current };
}

async function loadLf2(projects, catalog) {
  const client = await import("./lib/client.js");
  installApiRouter(client, { projects, catalog });
  await import("./lf2-data.jsx");
  const activeId = projects[0].project_id;
  await vi.waitFor(() => expect(window.WsWorks && window.WsWorks.activeId()).toBe(activeId), T);
  await vi.waitFor(() => expect(window.WsCatalog.get().length).toBe(catalog.length), T);
  window.lf2SyncFromCatalog();
  return client;
}

describe("lf2SyncFromCatalog · 章号定位以目录真相为准（非 tide 不再锚死第 9 章）", () => {
  beforeEach(() => { vi.resetModules(); window.localStorage.clear(); });
  afterEach(() => vi.restoreAllMocks());

  it("非 tide 作品：作者在第 3 章 → now=3 / LF2_NEXT=4（修复前整体早退，LF2_NEXT 恒为 9）", async () => {
    await loadLf2(
      [{ project_id: "salt", title: "盐镇旧事", genre: "年代", is_demo: false }],
      [chap("01", "approved"), chap("02", "approved"), chap("03", "writing", true)],
    );
    expect(window.LF2_BOOK.now).toBe(3);
    expect(window.LF2_NEXT).toBe(4);
    expect(window.LF2_NEXT).not.toBe(9); // 可证伪：旧实现非 tide 早退，此处会是 9
  });

  it("长书非 tide：作者在第 15 章 → LF2_NEXT=16（不再误指第 9 章）", async () => {
    const cat = [];
    for (let i = 1; i <= 15; i++) cat.push(chap(String(i).padStart(2, "0"), i === 15 ? "writing" : "approved", i === 15));
    await loadLf2([{ project_id: "salt", title: "盐镇旧事", is_demo: false }], cat);
    expect(window.LF2_NEXT).toBe(16);
  });

  it("tide 作品不受影响：8 章目录（第 8 章在写）→ LF2_NEXT=9（演示结构层照常）", async () => {
    const cat = [];
    for (let i = 1; i <= 8; i++) cat.push(chap(String(i).padStart(2, "0"), i === 8 ? "writing" : "approved", i === 8));
    await loadLf2([{ project_id: "tide", title: "潮汐档案", genre: "悬疑 · 长篇", is_demo: true }], cat);
    expect(window.LF2_NEXT).toBe(9);
  });

  it("全为计划章（无已写）→ now 兜底为 1，LF2_NEXT=2（不崩、不指第 9 章）", async () => {
    await loadLf2(
      [{ project_id: "salt", title: "盐镇旧事", is_demo: false }],
      [chap("01", "planned"), chap("02", "planned")],
    );
    expect(window.LF2_BOOK.now).toBe(1);
    expect(window.LF2_NEXT).toBe(2);
  });

  it("lf2DeriveStructure 先 POST 确定性派生端点、再水合（派生失败不阻塞）", async () => {
    const client = await loadLf2(
      [{ project_id: "salt", title: "盐镇旧事", is_demo: false }],
      [chap("01", "writing", true)],
    );
    client.apiPost.mockClear();
    await window.lf2DeriveStructure();
    expect(client.apiPost).toHaveBeenCalledWith("/api/v2/projects/salt/longform/derive-structure", {});
  });
});
