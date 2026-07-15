// WrDocs / WrDocVersions store 层单测：save(ensure+PATCH 带 base_revision_no) +
// words_rollup 回流 + 409 冲突重水合 + 非409只留底 + 跨作品 sid 前缀防污染 + 修订映射 + 句级 diff。
//
// 依赖链：WrDocs 经 window.WsCatalog.__backendSceneId(slug)→scene_id、
//        缓存键经 window.wsKey 加 ::<activeId> 后缀、docMeta 经 metaKeyOf 加作品前缀。
// 故先 import ws-catalog（装 window.WsCatalog + 间接装 ws-works），settle 后再 import wr-doc-store。
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { installApiRouter, DEFAULT_PROJECT } from "./test-helpers.js";

vi.mock("./lib/client.js", () => ({
  apiGet: vi.fn(),
  apiPost: vi.fn(),
  apiPatch: vi.fn(),
  apiDelete: vi.fn(),
}));

const T = { timeout: 5000, interval: 25 };

const SALT_PROJECT = { project_id: "salt", title: "盐镇旧志", genre: "悬疑", is_demo: true, stats: { words_total: 0 } };

// ensure → draft d1/rev1；save PATCH(d1) → rev2 + words_rollup。
function wireDrafts(client) {
  client.apiPost.mockImplementation((url) => {
    if (/\/author-drafts\/scene\/.+\/ensure$/.test(url)) {
      return Promise.resolve({ draft: { draft_id: "d1", revision_no: 1, content: "" } });
    }
    return Promise.resolve({});
  });
  client.apiPatch.mockImplementation((url) => {
    if (/\/author-drafts\/d1$/.test(url)) {
      return Promise.resolve({ draft: { revision_no: 2 }, words_rollup: { chapter_words: 120, scene_words: 120 } });
    }
    return Promise.resolve({});
  });
}

async function settleActive(id = "tide") {
  await vi.waitFor(() => expect(window.WsWorks && window.WsWorks.activeId()).toBe(id), T);
}

async function loadDocs(opts = {}) {
  const client = await import("./lib/client.js");
  installApiRouter(client, opts);   // /api/v2/projects + catalog(DEFAULT_CHAP: ch01s1→s1) + dashboard
  wireDrafts(client);
  await import("./ws-catalog.jsx"); // 装 window.WsCatalog（间接 import ws-works）
  await settleActive("tide");
  await vi.waitFor(() => expect(window.WsCatalog.get().length).toBeGreaterThan(0), T);
  const mod = await import("./wr-doc-store.jsx");
  return { mod, client };
}

describe("WrDocs.save（ensure + PATCH 带 base_revision_no）", () => {
  beforeEach(() => {
    vi.resetModules();
    window.localStorage.clear();
    vi.spyOn(window, "alert").mockImplementation(() => {});
  });
  afterEach(() => vi.restoreAllMocks());

  it("缓存即时落地 + 经 ws-catalog 把 ch01s1→s1 ensure 后 PATCH（带 base_revision_no）", async () => {
    const { mod, client } = await loadDocs();
    await mod.WrDocs.save("ch01s1", "<p>正文</p>");
    // 同步缓存：视图零等待即可读到
    expect(mod.WrDocs.load("ch01s1")).toBe("<p>正文</p>");
    await vi.waitFor(() => expect(client.apiPost).toHaveBeenCalledWith(
      "/api/v1/author-drafts/scene/s1/ensure", {}), T);
    await vi.waitFor(() => expect(client.apiPatch).toHaveBeenCalledWith(
      "/api/v1/author-drafts/d1",
      { content: "<p>正文</p>", base_revision_no: 1 }), T);
  });

  it("save 成功把 words_rollup 经 WsCatalog.__applyWordsRollup 回流", async () => {
    const { mod } = await loadDocs();
    const spy = vi.spyOn(window.WsCatalog, "__applyWordsRollup");
    await mod.WrDocs.save("ch01s1", "<p>x</p>");
    await vi.waitFor(() => expect(spy).toHaveBeenCalledWith(
      "ch01s1", { chapter_words: 120, scene_words: 120 }), T);
  });
});

describe("WrDocs 409 冲突重水合（历史 bug 回归）", () => {
  beforeEach(() => {
    vi.resetModules();
    window.localStorage.clear();
    vi.spyOn(window, "alert").mockImplementation(() => {});
  });
  afterEach(() => vi.restoreAllMocks());

  it("PATCH 抛 AUTHOR_DRAFT_CONFLICT → 重新 ensure 重水合 + alert 提示", async () => {
    const { mod, client } = await loadDocs();
    const conflict = Object.assign(new Error("conflict"), { code: "AUTHOR_DRAFT_CONFLICT" });
    client.apiPatch.mockRejectedValueOnce(conflict); // 仅首次保存冲突
    client.apiPost.mockClear();

    await expect(mod.WrDocs.save("ch01s1", "<p>本地改动</p>")).rejects.toBe(conflict);

    // 409 → alert（强可证伪：非 409 路径只 console.warn）
    await vi.waitFor(() => expect(window.alert).toHaveBeenCalled(), T);
    // 重水合：draftId 被清后 hydrate 再次 ensure（共 2 次 ensure）
    await vi.waitFor(() => {
      const ensures = client.apiPost.mock.calls.filter(c => /\/scene\/s1\/ensure$/.test(c[0]));
      expect(ensures.length).toBe(2);
    }, T);
  });

  it("非 409 失败只留底不 alert（缓存仍在，下次重试）", async () => {
    const { mod, client } = await loadDocs();
    const failure = new Error("network");
    client.apiPatch.mockRejectedValueOnce(failure); // 无 .code
    await expect(mod.WrDocs.save("ch01s1", "<p>x</p>")).rejects.toBe(failure);
    expect(window.alert).not.toHaveBeenCalled();          // 可证伪：若把非 409 也 alert 则红
    expect(mod.WrDocs.load("ch01s1")).toBe("<p>x</p>");   // 缓存留底
  });
});

describe("WrDocs 跨作品 sid 前缀防污染（历史 bug 回归）", () => {
  beforeEach(() => {
    vi.resetModules();
    window.localStorage.clear();
    vi.spyOn(window, "alert").mockImplementation(() => {});
  });
  afterEach(() => vi.restoreAllMocks());

  it("同名 sid 在不同作品下：缓存键(wsKey)与 docMeta(metaKeyOf)双隔离", async () => {
    const { mod, client } = await loadDocs({ projects: [DEFAULT_PROJECT, SALT_PROJECT] });
    // ensure 按当前激活作品返回不同 draft_id，以验证 docMeta 隔离（裸 sid 会复用上一部的 draftId）
    client.apiPost.mockImplementation((url) => {
      if (/\/author-drafts\/scene\/.+\/ensure$/.test(url)) {
        const w = window.WsWorks.activeId();
        return Promise.resolve({ draft: { draft_id: w === "salt" ? "d-salt" : "d-tide", revision_no: 1, content: "" } });
      }
      return Promise.resolve({});
    });

    // —— 作品 tide：保存 ch01s1 ——
    await mod.WrDocs.save("ch01s1", "<p>潮汐的正文</p>");
    expect(mod.WrDocs.load("ch01s1")).toBe("<p>潮汐的正文</p>");
    await vi.waitFor(() => expect(client.apiPatch).toHaveBeenCalledWith(
      "/api/v1/author-drafts/d-tide",
      { content: "<p>潮汐的正文</p>", base_revision_no: 1 }), T);

    // —— 切到作品 salt（真实 setActive，使 WS_ACTIVE_ID 切换，wsKey/metaKeyOf 同步）——
    window.WsWorks.setActive("salt");
    await settleActive("salt");
    await vi.waitFor(() => expect(window.WsCatalog.get().length).toBeGreaterThan(0), T);

    // 缓存键隔离（wsKey）：salt 下读不到 tide 的正文
    expect(mod.WrDocs.load("ch01s1")).toBeNull();

    // —— 作品 salt：保存同名 ch01s1 ——
    await mod.WrDocs.save("ch01s1", "<p>盐镇的正文</p>");
    expect(mod.WrDocs.load("ch01s1")).toBe("<p>盐镇的正文</p>");
    // docMeta 隔离（metaKeyOf）：salt 走自己的 d-salt，而非复用 tide 的 d-tide
    // 可证伪：metaKeyOf 改裸 sid → 复用 d-tide，此断言转红
    await vi.waitFor(() => expect(client.apiPatch).toHaveBeenCalledWith(
      "/api/v1/author-drafts/d-salt",
      { content: "<p>盐镇的正文</p>", base_revision_no: 1 }), T);

    // —— 切回 tide：正文互不覆盖 ——
    window.WsWorks.setActive("tide");
    await settleActive("tide");
    expect(mod.WrDocs.load("ch01s1")).toBe("<p>潮汐的正文</p>");
  });
});

/* ==========================================================
   Wave 1（结果闭环治理 · 设计项 5）：跨会话「本地较新」冲突检测。
   旧缺口：pushSave 失败后 dirty 只在内存 docMeta——重启浏览器丢失，
   下次 hydrate 用服务端旧版静默覆盖 localStorage 里较新的本地稿。
   新契约：保存失败 → 持久化 pending 标记；重启后 hydrate 发现标记且
   本地 ≠ 服务端 → 本地稿备份为冲突副本 + alert 让作者选择；保存成功清标记。
   ========================================================== */
describe("WrDocs 跨会话 pending 冲突（Wave 1）", () => {
  beforeEach(() => {
    vi.resetModules();
    window.localStorage.clear();
    vi.spyOn(window, "alert").mockImplementation(() => {});
  });
  afterEach(() => vi.restoreAllMocks());

  it("保存失败留持久化 pending 标记；保存成功清除", async () => {
    const { mod, client } = await loadDocs();
    const failure = new Error("network");
    client.apiPatch.mockRejectedValueOnce(failure);
    await expect(mod.WrDocs.save("ch01s1", "<p>没保上的本地稿</p>")).rejects.toBe(failure);
    const pendingKeys = () => Object.keys(window.localStorage).filter(k => k.includes("wr-doc-pending:ch01s1"));
    expect(pendingKeys().length).toBe(1);

    // 下一次保存成功 → 标记清除
    await mod.WrDocs.save("ch01s1", "<p>这次保上了</p>");
    await vi.waitFor(() => expect(pendingKeys().length).toBe(0), T);
  });

  it("重启会话后：pending 标记 + 本地≠服务端 → 冲突副本 + alert，服务端版本上屏", async () => {
    // —— 会话 1：保存失败留底 ——
    const first = await loadDocs();
    const failure = new Error("network");
    first.client.apiPatch.mockRejectedValue(failure);
    await expect(first.mod.WrDocs.save("ch01s1", "<p>重启前较新的本地稿</p>")).rejects.toBe(failure);
    expect(Object.keys(window.localStorage).some(k => k.includes("wr-doc-pending:ch01s1"))).toBe(true);

    // —— 会话 2：重启（resetModules 清 docMeta 内存态），服务端有旧版内容 ——
    vi.resetModules();
    const second = await (async () => {
      const client = await import("./lib/client.js");
      installApiRouter(client);
      client.apiPost.mockImplementation((url) => {
        if (/\/author-drafts\/scene\/.+\/ensure$/.test(url)) {
          return Promise.resolve({ draft: { draft_id: "d1", revision_no: 5, content: "服务端的旧版正文" } });
        }
        return Promise.resolve({});
      });
      await import("./ws-catalog.jsx");
      await settleActive("tide");
      await vi.waitFor(() => expect(window.WsCatalog.get().length).toBeGreaterThan(0), T);
      const mod = await import("./wr-doc-store.jsx");
      return { mod, client };
    })();

    second.mod.WrDocs.load("ch01s1"); // 触发 hydrate
    // 本地较新稿备份为冲突副本，作者可找回
    await vi.waitFor(() => {
      const conflictKeys = Object.keys(window.localStorage).filter(k => k.includes("wr-doc:ch01s1") && k.includes("conflict"));
      expect(conflictKeys.length).toBe(1);
      expect(window.localStorage.getItem(conflictKeys[0])).toBe("<p>重启前较新的本地稿</p>");
    }, T);
    // alert 让作者知道有副本可选（可证伪：静默覆盖则红）
    await vi.waitFor(() => expect(window.alert).toHaveBeenCalled(), T);
    // 服务端版本上屏（服务端优先）
    await vi.waitFor(() => expect(second.mod.WrDocs.load("ch01s1")).toContain("服务端的旧版正文"), T);
    // pending 标记已消费
    expect(Object.keys(window.localStorage).some(k => k.includes("wr-doc-pending:ch01s1"))).toBe(false);
  });

  it("pending 标记 + 本地==服务端（上次实际保上了）→ 静默清标记，无副本无 alert", async () => {
    const first = await loadDocs();
    const failure = new Error("network");
    first.client.apiPatch.mockRejectedValue(failure);
    await expect(first.mod.WrDocs.save("ch01s1", "<p>同一份内容</p>")).rejects.toBe(failure);

    vi.resetModules();
    const client = await import("./lib/client.js");
    installApiRouter(client);
    client.apiPost.mockImplementation((url) => {
      if (/\/author-drafts\/scene\/.+\/ensure$/.test(url)) {
        return Promise.resolve({ draft: { draft_id: "d1", revision_no: 5, content: "<p>同一份内容</p>" } });
      }
      return Promise.resolve({});
    });
    await import("./ws-catalog.jsx");
    await settleActive("tide");
    const mod = (await import("./wr-doc-store.jsx"));

    mod.WrDocs.load("ch01s1");
    await vi.waitFor(() => {
      expect(Object.keys(window.localStorage).some(k => k.includes("wr-doc-pending:ch01s1"))).toBe(false);
    }, T);
    expect(Object.keys(window.localStorage).filter(k => k.includes("conflict"))).toEqual([]);
    expect(window.alert).not.toHaveBeenCalled();
  });
});

describe("WrDocs 提升权威正文", () => {
  beforeEach(() => {
    vi.resetModules();
    window.localStorage.clear();
    vi.spyOn(window, "alert").mockImplementation(() => {});
  });
  afterEach(() => vi.restoreAllMocks());

  it("只提升已保存修订，并携带草稿与当前权威正文双基线", async () => {
    const { mod, client } = await loadDocs();
    client.apiPost.mockImplementation((url) => {
      if (/\/author-drafts\/scene\/.+\/ensure$/.test(url)) {
        return Promise.resolve({
          draft: {
            draft_id: "d1",
            revision_no: 1,
            content: "",
            last_promoted_revision_no: 1,
            last_promoted_final_scene_row_id: "final-old",
            canonical_dirty: false,
          },
          runtime_final_ref: "final_scene:final-old",
        });
      }
      if (url === "/api/v1/author-drafts/d1/promote-canonical") {
        return Promise.resolve({
          draft_id: "d1",
          draft_revision_no: 2,
          final_scene_row_id: "final-new",
          canonical_dirty: false,
          narrative_sync_status: "synced",
        });
      }
      return Promise.resolve({});
    });
    client.apiPatch.mockResolvedValue({
      draft: {
        draft_id: "d1",
        revision_no: 2,
        canonical_dirty: true,
        last_promoted_revision_no: 1,
        last_promoted_final_scene_row_id: "final-old",
      },
    });

    await mod.WrDocs.save("ch01s1", "<p>作者定稿</p>");
    expect(mod.WrDocs.state("ch01s1").canonicalDirty).toBe(true);
    const result = await mod.WrDocs.promote("ch01s1");

    expect(client.apiPost).toHaveBeenCalledWith(
      "/api/v1/author-drafts/d1/promote-canonical",
      {
        base_revision_no: 2,
        expected_current_final_scene_row_id: "final-old",
        narrative_effect: "facts_unchanged",
        accepted_warning_codes: [],
      },
    );
    expect(result.narrative_sync_status).toBe("synced");
    expect(mod.WrDocs.state("ch01s1")).toMatchObject({
      revision: 2,
      canonicalDirty: false,
      currentFinalSceneRowId: "final-new",
      lastPromotedRevisionNo: 2,
      lastPromotedFinalSceneRowId: "final-new",
      lastSaveError: null,
    });
  });

  it("最近一次草稿保存失败时拒绝提升，且不会调用提升接口", async () => {
    const { mod, client } = await loadDocs();
    const failure = new Error("network");
    client.apiPatch.mockRejectedValueOnce(failure);
    await expect(mod.WrDocs.save("ch01s1", "<p>未保存稿</p>")).rejects.toBe(failure);
    client.apiPost.mockClear();

    await expect(mod.WrDocs.promote("ch01s1")).rejects.toBe(failure);
    expect(client.apiPost.mock.calls.some(([url]) => url.includes("promote-canonical"))).toBe(false);
  });
});

describe("WrDocVersions（修订列表映射 + 句级 diff 纯函数）", () => {
  beforeEach(() => {
    vi.resetModules();
    window.localStorage.clear();
    vi.spyOn(window, "alert").mockImplementation(() => {});
  });
  afterEach(() => vi.restoreAllMocks());

  it("list 把 revision_no/created_at 映射为 revisionNo/at", async () => {
    const { mod, client } = await loadDocs();
    client.apiGet.mockImplementation((url) => {
      if (url === "/api/v2/projects") return Promise.resolve({ items: [DEFAULT_PROJECT] });
      if (/\/author-drafts\/d1\/revisions$/.test(url)) {
        return Promise.resolve({ items: [{ revision_no: 2, words: 10, origin: "edited", created_at: "2026-06-01" }] });
      }
      return Promise.resolve({});
    });
    const list = await mod.WrDocVersions.list("ch01s1");
    expect(list).toEqual([{ revisionNo: 2, words: 10, origin: "edited", at: "2026-06-01" }]);
  });

  it("diff 句级：新增句被标 add（纯函数，无需 mock）", async () => {
    const { mod } = await loadDocs();
    const r = mod.WrDocVersions.diff(["他走了。"], ["他走了。", "她留下。"]);
    expect(r.adds).toBe(1);
    expect(r.dels).toBe(0);
    expect(r.paras.flatMap(p => p.segs).some(s => s.t === "add" && s.text === "她留下。")).toBe(true);
  });
});
