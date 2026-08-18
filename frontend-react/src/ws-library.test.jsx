// WsLibrary store 层单测：libFetch 关系双向索引 + LIB_persist diff→PATCH +
// relations CRUD（含 event 终点跳过）+ 失败 refetch/告警 + LIB_persistAdds 去重。
//
// 「store 实质」不在 ws-library.jsx（那是视图组件），而在：
//   · ws-library-data.jsx —— libFetch / LIB_ENTRIES / LIB_BY_ID / window.LIB_refetch
//   · ws-library-edit.jsx —— LIB_persist / libSyncLinks / LIB_persistAdds / LIB_newEntry
// 这两个模块级纯函数族就是被测契约面。
//
// 断言取向（对齐 ws-catalog.test 范式）：断「可观测结果」+「仅失败路径触发的 alert」。
// 写动词去重不可靠，故失败回滚断 alert + refetch；端点路由断精确 URL+body（可证伪）。
// installApiRouter 不识别 /library，故本 spec 自带 apiGet 路由。
import React, { act } from "react";
import { createRoot } from "react-dom/client";
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";

globalThis.IS_REACT_ACT_ENVIRONMENT = true;

vi.mock("./lib/client.js", () => ({
  apiGet: vi.fn(),
  apiPost: vi.fn(),
  apiPatch: vi.fn(),
  apiDelete: vi.fn(),
}));

vi.mock("./ws-catalog.jsx", () => ({
  WsTrashStore: {
    subscribe: () => () => {},
    list: () => [],
    restore: vi.fn(),
    purge: vi.fn(),
    clear: vi.fn(),
  },
}));

const T = { timeout: 5000, interval: 25 };

// 默认资料库：林岑(people) —r1(conflict)→ 周岚(people)；档案馆(world)；第三潮汐(event)。
function libResponse() {
  return {
    characters: [
      { character_id: "lin", name: "林岑", role: "主角", summary: "修复师", ref: "character:lin", details: {} },
      { character_id: "zhou", name: "周岚", role: "对立", summary: "主任", ref: "character:zhou", details: {} },
    ],
    entities: [
      { entity_id: "arch", name: "档案馆", kind: "location", summary: "主场景", ref: "entity:arch", tags: [], details: {} },
    ],
    timeline: [
      { event_id: "e1", label: "第三潮汐事件", time_label: "2003", entity_refs: ["character:lin"], note: "事故" },
    ],
    relations: [
      { relation_id: "r1", from_ref: "character:lin", to_ref: "character:zhou", kind: "conflict", note: "宿敌" },
    ],
  };
}

function routeApiGet(client, lib) {
  client.apiGet.mockImplementation((url) => {
    if (url === "/api/v2/projects") return Promise.resolve({ items: [{ project_id: "prj-main", title: "北岸手记" }] });
    if (/\/api\/v2\/projects\/prj-main\/library$/.test(url)) return Promise.resolve(lib);
    return Promise.resolve({});
  });
  client.apiPost.mockResolvedValue({});
  client.apiPatch.mockResolvedValue({});
  client.apiDelete.mockResolvedValue({});
}

function deferred() {
  let resolve;
  let reject;
  const promise = new Promise((ok, fail) => { resolve = ok; reject = fail; });
  return { promise, resolve, reject };
}

function namedLibrary(id, name) {
  return {
    characters: [{ character_id: id, name, role: "主角", summary: "", ref: `character:${id}`, details: {} }],
    entities: [], timeline: [], relations: [],
  };
}

async function loadLib(lib = libResponse()) {
  const client = await import("./lib/client.js");
  routeApiGet(client, lib);
  // 先让 WsWorks 落到真实激活作品，再 import 数据层（其 import 期 libFetch 才会真正拉取）
  await import("./ws-works.jsx");
  await vi.waitFor(() => expect(window.WsWorks && window.WsWorks.activeId()).toBe("prj-main"), T);
  const data = await import("./ws-library-data.jsx");
  const edit = await import("./ws-library-edit.jsx");
  await window.LIB_refetch();   // 等内联 IIFE 拉取 settle（resolve 在 LIB_ENTRIES 赋值之后）
  return { client, data, edit };
}

describe("WsLibrary 数据层（libFetch 关系双向索引）", () => {
  beforeEach(() => {
    vi.resetModules();
    window.localStorage.clear();
    vi.spyOn(window, "alert").mockImplementation(() => {});
  });
  afterEach(() => vi.restoreAllMocks());

  it("relation 双向挂载：lin 与 zhou 互为对方 links（带 relationId/type）", async () => {
    const { data } = await loadLib();
    const lin = data.LIB_BY_ID["lin"];
    const zhou = data.LIB_BY_ID["zhou"];
    expect(lin.links.find(l => l.id === "zhou")).toMatchObject({ id: "zhou", relationId: "r1", type: "conflict" });
    // 反向 backlink 必须存在（可证伪：libFetch 若只挂 from_ref 单向，则 zhou.links 找不到 lin）
    expect(zhou.links.find(l => l.id === "lin")).toMatchObject({ id: "lin", relationId: "r1" });
  });

  it("空 library 不抛、缓存清空", async () => {
    const { data } = await loadLib({ characters: [], entities: [], timeline: [], relations: [] });
    expect(data.LIB_ENTRIES.length).toBe(0);
    expect(window.LIB_relationsRaw()).toEqual([]);
  });

  it("A→B 快速切换时立即隔离旧快照，且 A 的迟到响应不能覆盖 B", async () => {
    const client = await import("./lib/client.js");
    const projectA = deferred();
    client.apiGet.mockImplementation((url) => {
      if (url === "/api/v2/projects") return Promise.resolve({ items: [
        { project_id: "project-a", title: "甲项目" },
        { project_id: "project-b", title: "乙项目" },
      ] });
      if (url === "/api/v2/projects/project-a/library") return projectA.promise;
      if (url === "/api/v2/projects/project-b/library") return Promise.resolve(namedLibrary("char-b", "乙角色"));
      return Promise.resolve({});
    });
    window.localStorage.setItem("ws_active_work_v1", "project-a");

    const { WsWorks } = await import("./ws-works.jsx");
    await vi.waitFor(() => expect(WsWorks.list().map(w => w.id)).toEqual(["project-a", "project-b"]), T);
    const data = await import("./ws-library-data.jsx");
    expect(data.LIB_ENTRIES).toHaveLength(0);

    WsWorks.setActive("project-b");
    await vi.waitFor(() => expect(data.LIB_ENTRIES.map(e => e.name)).toEqual(["乙角色"]), T);

    projectA.resolve(namedLibrary("char-a", "甲角色"));
    await projectA.promise;
    await Promise.resolve();
    expect(data.LIB_ENTRIES.map(e => e.name)).toEqual(["乙角色"]);
    expect(data.LIB_BY_ID["char-a"]).toBeUndefined();
  });
});

describe("WsLibrary 视图与异步资料快照连通", () => {
  beforeEach(() => {
    vi.resetModules();
    window.localStorage.clear();
    vi.spyOn(window, "alert").mockImplementation(() => {});
  });
  afterEach(() => vi.restoreAllMocks());

  it("组件先挂载、请求后完成时自动重算并显示服务端条目", async () => {
    const client = await import("./lib/client.js");
    const library = deferred();
    client.apiGet.mockImplementation((url) => {
      if (url === "/api/v2/projects") return Promise.resolve({ items: [{ project_id: "prj-main", title: "北岸手记" }] });
      if (url === "/api/v2/projects/prj-main/library") return library.promise;
      return Promise.resolve({});
    });
    window.localStorage.setItem("ws_active_work_v1", "prj-main");

    const { WsWorks } = await import("./ws-works.jsx");
    await vi.waitFor(() => expect(WsWorks.activeId()).toBe("prj-main"), T);
    const { WsLibrary } = await import("./ws-library.jsx");
    const host = document.createElement("div");
    document.body.appendChild(host);
    const root = createRoot(host);
    try {
      await act(async () => root.render(<WsLibrary go={vi.fn()} />));
      expect(host.textContent).toContain("这部作品的档案库还是空的");

      await act(async () => { library.resolve(libResponse()); await library.promise; });
      await vi.waitFor(() => expect(host.textContent).toContain("林岑"), T);
      expect(host.textContent).not.toContain("这部作品的档案库还是空的");
    } finally {
      await act(async () => root.unmount());
      host.remove();
    }
  });
});

describe("WsLibrary 编辑层（LIB_persist diff→PATCH + relations CRUD）", () => {
  beforeEach(() => {
    vi.resetModules();
    window.localStorage.clear();
    vi.spyOn(window, "alert").mockImplementation(() => {});
  });
  afterEach(() => vi.restoreAllMocks());

  it("people 字段 patch 打到 characters 端点（kind→role + details.blurb）", async () => {
    const { client, edit } = await loadLib();
    client.apiPatch.mockClear();
    edit.LIB_persist({ lin: { name: "林岑·改", kind: "新角色", blurb: "新简述" } });
    await vi.waitFor(() => expect(client.apiPatch).toHaveBeenCalledWith(
      "/api/v2/projects/prj-main/library/characters/lin",
      expect.objectContaining({
        name: "林岑·改",
        role: "新角色",
        details: expect.objectContaining({ blurb: "新简述" }),
      })), T);
  });

  it("events patch 走 timeline 端点（label/note，而非 name/role）", async () => {
    const { client, edit } = await loadLib();
    client.apiPatch.mockClear();
    edit.LIB_persist({ e1: { name: "事件改名", blurb: "新备注" } });
    await vi.waitFor(() => expect(client.apiPatch).toHaveBeenCalledWith(
      "/api/v2/projects/prj-main/library/timeline/e1",
      { label: "事件改名", note: "新备注" }), T);
  });

  it("links 增边→POST relations；删旧边→DELETE relations/{relationId}", async () => {
    const { client, edit } = await loadLib();
    client.apiPost.mockClear();
    client.apiDelete.mockClear();
    // lin 原有 →zhou(r1)。新 links 仅含 →arch：应删 r1、增 lin→arch。
    edit.LIB_persist({ lin: { links: [{ id: "arch", type: "ally", rel: "工作于" }] } });
    await vi.waitFor(() => expect(client.apiDelete).toHaveBeenCalledWith(
      "/api/v2/projects/prj-main/library/relations/r1"), T);
    await vi.waitFor(() => expect(client.apiPost).toHaveBeenCalledWith(
      "/api/v2/projects/prj-main/library/relations",
      { from_ref: "character:lin", to_ref: "entity:arch", kind: "ally", note: "工作于" }), T);
  });

  it("event 作为 relation 终点被跳过（不产生 to_ref=event: 的 POST）", async () => {
    const { client, edit } = await loadLib();
    client.apiPost.mockClear();
    const refetch = vi.spyOn(window, "LIB_refetch");
    // 保留 →zhou(避免删边)，新增 →e1(事件终点应被守卫跳过)
    edit.LIB_persist({ lin: { links: [
      { id: "zhou", type: "conflict", rel: "宿敌", relationId: "r1" },
      { id: "e1", type: "related", rel: "卷入" },
    ] } });
    await vi.waitFor(() => expect(refetch).toHaveBeenCalled(), T); // persist 全程跑完
    const postedTo = client.apiPost.mock.calls.map(c => c[1] && c[1].to_ref);
    // 可证伪：删掉 startsWith("event:") 守卫 → 出现 to_ref="event:e1" 的 POST
    expect(postedTo).not.toContain("event:e1");
  });

  it("PATCH 失败→alert 告警且 refetch 以服务端为准回滚", async () => {
    const { client, edit } = await loadLib();
    const refetch = vi.spyOn(window, "LIB_refetch");
    client.apiPatch.mockRejectedValueOnce(new Error("boom"));
    edit.LIB_persist({ lin: { name: "会失败" } });
    await vi.waitFor(() => expect(window.alert).toHaveBeenCalled(), T); // 仅失败路径调 alert
    await vi.waitFor(() => expect(refetch).toHaveBeenCalled(), T);      // 回滚 = 重拉服务端
  });

  it("LIB_persistAdds 新建 people→POST characters，且同 id 不重复发", async () => {
    const { client, edit } = await loadLib();
    client.apiPost.mockClear();
    const ne = edit.LIB_newEntry("people", "新人物");
    edit.LIB_persistAdds([ne]);
    edit.LIB_persistAdds([ne]); // 第二次应被 libSentAdds 去重
    await vi.waitFor(() => expect(client.apiPost).toHaveBeenCalledWith(
      "/api/v2/projects/prj-main/library/characters",
      expect.objectContaining({ name: "新人物" })), T);
    const charPosts = client.apiPost.mock.calls.filter(c => /\/library\/characters$/.test(c[0]));
    expect(charPosts.length).toBe(1); // 去重可证伪
  });

  it("新建请求失败不会污染去重集合；同一条目可重试", async () => {
    const { client, edit } = await loadLib();
    client.apiPost.mockClear();
    client.apiPost.mockRejectedValueOnce(new Error("network down"));
    const ne = edit.LIB_newEntry("people", "可重试人物");

    expect(await edit.LIB_persistAdds([ne])).toBe(false);
    expect(window.alert).toHaveBeenCalled();
    client.apiPost.mockResolvedValueOnce({});
    expect(await edit.LIB_persistAdds([ne])).toBe(true);

    const posts = client.apiPost.mock.calls.filter(c => /\/library\/characters$/.test(c[0]));
    expect(posts).toHaveLength(2);
  });

  it("关系写入失败不会把整次编辑误标成功；相同 patch 可重试", async () => {
    const { client, edit } = await loadLib();
    client.apiPost.mockClear();
    client.apiPatch.mockClear();
    client.apiPost.mockRejectedValueOnce(new Error("relation unavailable"));
    const patch = { links: [
      { id: "zhou", type: "conflict", rel: "宿敌", relationId: "r1" },
      { id: "arch", type: "ally", rel: "工作于" },
    ] };

    expect(await edit.LIB_persist({ lin: patch })).toBe(false);
    expect(window.alert).toHaveBeenCalled();
    client.apiPost.mockResolvedValueOnce({});
    expect(await edit.LIB_persist({ lin: patch })).toBe(true);

    const relationPosts = client.apiPost.mock.calls.filter(c => /\/library\/relations$/.test(c[0]));
    expect(relationPosts).toHaveLength(2);
  });
});
