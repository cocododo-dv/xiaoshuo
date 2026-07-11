// ws-scene-run store 层单测：队列成员的后端派生（scnBackendQueueSids）。
// 贯通轮遗留 ①：GET /scene-run-states 是队列成员真相源，localStorage 退化为读缓存——
// 这里验证「run-states → 目录 backendId 对位 → sid 列表」的派生契约与其兜底路径。
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { installApiRouter, DEFAULT_CHAP } from "./test-helpers.js";

vi.mock("./lib/client.js", () => ({
  apiGet: vi.fn(),
  apiPost: vi.fn(),
  apiPatch: vi.fn(),
  apiDelete: vi.fn(),
}));

// ws-scene-run 只从 ws-snow.jsx 取 s2ExportState（提示词上下文，与本测试无关）；
// ws-catalog 链上的 ws-snow-sync 只取 S2_BE_STEPS。mock 掉避免拉入整张雪花视图。
vi.mock("./ws-snow.jsx", () => ({ S2_BE_STEPS: [], s2ExportState: () => null }));

const T = { timeout: 5000, interval: 25 };

const RUN_STATES_URL = /^\/api\/v1\/scene-run-states\?/;

async function settleActive() {
  await vi.waitFor(() => expect(window.WsWorks && window.WsWorks.activeId()).toBe("tide"), T);
}

/* 在 installApiRouter 之上叠一层 scene-run-states 路由（贯通轮惯用法：包装现有实现） */
function routeRunStates(client, responder) {
  const base = client.apiGet.getMockImplementation();
  client.apiGet.mockImplementation((url) => {
    if (RUN_STATES_URL.test(url)) return responder(url);
    return base(url);
  });
}

async function loadSceneRun(opts) {
  const client = await import("./lib/client.js");
  installApiRouter(client, opts);
  const mod = await import("./ws-scene-run.jsx");
  await settleActive();
  return { mod, client };
}

describe("scnBackendQueueSids（队列成员的后端派生）", () => {
  beforeEach(() => {
    vi.resetModules();
    window.localStorage.clear();
  });
  afterEach(() => vi.restoreAllMocks());

  it("run-states 按目录 backendId 对位成 sid 列表；无对位的场丢弃", async () => {
    const { mod, client } = await loadSceneRun();
    // 等目录装载（派生依赖 backendId → sid 映射）
    const cat = await import("./ws-catalog.jsx");
    await vi.waitFor(() => expect(cat.WsCatalog.get().length).toBeGreaterThan(0), T);
    routeRunStates(client, () =>
      Promise.resolve({
        items: [
          { scene_id: "s1", scene_status: "human_review_required" },
          { scene_id: "s-ghost", scene_status: "archived" }, // 目录里没有：丢弃
        ],
      })
    );

    const sids = await mod.scnBackendQueueSids();

    expect(sids).toEqual(["ch01s1"]);
    expect(client.apiGet).toHaveBeenCalledWith("/api/v1/scene-run-states?project_id=tide");
  });

  it("目录为空时先 __refresh 再对位（换浏览器冷启动路径）", async () => {
    // 启动装载吃到空目录（installApiRouter 的 catalog: []）；之后经包装路由
    // 返回真实章——模拟「目录还没就绪就进起草台」的竞态，派生应自行补拉
    const { mod, client } = await loadSceneRun({ catalog: [] });
    const cat = await import("./ws-catalog.jsx");
    await vi.waitFor(() => expect(cat.WsCatalog.ready()).toBe(true), T);
    expect(cat.WsCatalog.get().length).toBe(0);
    const base = client.apiGet.getMockImplementation();
    client.apiGet.mockImplementation((url) => {
      if (RUN_STATES_URL.test(url)) {
        return Promise.resolve({ items: [{ scene_id: "s1", scene_status: "soft_qc_patch_required" }] });
      }
      if (/\/api\/v2\/projects\/[^/]+\/catalog(\?|$)/.test(url)) {
        return Promise.resolve({ chapters: [DEFAULT_CHAP] });
      }
      return base(url);
    });

    const sids = await mod.scnBackendQueueSids();

    expect(sids).toEqual(["ch01s1"]);
  });

  it("run-states 端点失败时返回空列表（本地队列照常可用，不炸）", async () => {
    const { mod, client } = await loadSceneRun();
    routeRunStates(client, () => Promise.reject(new Error("boom")));

    const sids = await mod.scnBackendQueueSids();

    expect(sids).toEqual([]);
  });
});

/* ==========================================================
   Wave 1（结果闭环治理 §5.2）：采纳归档必须先打后端单入口。
   旧实现 scnAdoptToDoc 只写 wr-doc 缓存 + 目录置 done——前端「完成」
   与后端归档态可以分裂（G-02）。新契约：
   · 成功路径 = POST /scenes/{id}/adopt-current 成功 → 才写缓存/置 done
   · 后端拒绝（无稿/来源安全）→ 不置 done、不写缓存，faithful 返回失败
   ========================================================== */
describe("scnAdoptToDoc（归档单入口：先后端、后本地）", () => {
  beforeEach(() => {
    vi.resetModules();
    window.localStorage.clear();
    vi.spyOn(window, "confirm").mockReturnValue(true);
  });
  afterEach(() => vi.restoreAllMocks());

  const DRAFT = [{ id: "p1", beat: null, parts: [{ text: "潮水退去，她看清了闸门上的名字。" }] }];

  async function loadWithCatalog(opts) {
    const { mod, client } = await loadSceneRun(opts);
    const cat = await import("./ws-catalog.jsx");
    await vi.waitFor(() => expect(cat.WsCatalog.get().length).toBeGreaterThan(0), T);
    return { mod, client, cat };
  }

  it("成功：POST adopt-current 后才置 done + 写正文缓存", async () => {
    const { mod, client, cat } = await loadWithCatalog();
    client.apiPost.mockImplementation((url) => {
      if (/\/api\/v1\/scenes\/s1\/adopt-current$/.test(url)) {
        return Promise.resolve({ scene_id: "s1", scene_status: "archived", final_scene_row_id: "final_s1_v1" });
      }
      return Promise.resolve({});
    });

    const result = await mod.scnAdoptToDoc("ch01s1", DRAFT);

    expect(result.ok).toBe(true);
    expect(client.apiPost).toHaveBeenCalledWith("/api/v1/scenes/s1/adopt-current", expect.anything());
    // done 只由服务端 archived 响应映射，且写穿到目录 PATCH（mock 后端重拉
    // 会把乐观缓存收敛回 mock 值，故断言写穿动作而非最终缓存态）
    await vi.waitFor(() => expect(client.apiPatch).toHaveBeenCalledWith(
      expect.stringMatching(/\/scenes\/s1$/),
      expect.objectContaining({ state: "done" })
    ), T);
    void cat;
    // 正文写作器缓存同步（写穿主路径或缓存）
    const wrKeys = Object.keys(window.localStorage).filter(k => k.includes("wr-doc:ch01s1"));
    expect(wrKeys.length).toBeGreaterThan(0);
  });

  it("后端拒绝（409 无稿/来源安全）：不置 done、不写缓存、faithful 返回失败", async () => {
    const { mod, client, cat } = await loadWithCatalog();
    const blocked = Object.assign(new Error("blocked"), { code: "SOURCE_SAFETY_BLOCKED" });
    client.apiPost.mockImplementation((url) => {
      if (/\/adopt-current$/.test(url)) return Promise.reject(blocked);
      return Promise.resolve({});
    });

    const result = await mod.scnAdoptToDoc("ch01s1", DRAFT);

    expect(result.ok).toBe(false);
    expect(result.reason).toContain("SOURCE_SAFETY_BLOCKED");
    // 可证伪：先本地置 done 的旧实现会发出 state:"done" 的目录 PATCH，此断言转红
    const donePatches = client.apiPatch.mock.calls.filter(c => c[1] && c[1].state === "done");
    expect(donePatches).toEqual([]);
    const scene = cat.WsCatalog.get()[0].scenes.find(s => s.sid === "ch01s1");
    expect(scene.state).not.toBe("done");
    expect(Object.keys(window.localStorage).filter(k => k.includes("wr-doc:ch01s1"))).toEqual([]);
  });

  it("目录未同步到后端（无 backendId）：不静默装成功", async () => {
    const { mod } = await loadSceneRun({ catalog: [] });
    const cat = await import("./ws-catalog.jsx");
    await vi.waitFor(() => expect(cat.WsCatalog.ready()).toBe(true), T);
    const result = await mod.scnAdoptToDoc("ch99s9", DRAFT);
    expect(result.ok).toBe(false);
  });
});

/* ==========================================================
   Wave 2（结果闭环治理 §5.3/§5.4）：作者可见状态门。
   「无法继续」（hard_blocked = verified Q0/Q1，不可归档）与
   「已有稿但建议修改」（quality_warning = Q2/Q3，可归档）必须分开：
   · scnGateFrom 从 workbench/status 的 author_state 投影提取 gate
   · scnAdoptToDoc 对 canArchive=false 前置拦截（不发 adopt POST）
   · quality_warning 不拦归档
   ========================================================== */
describe("作者状态门（Wave 2：无法继续 vs 有稿建议修改）", () => {
  beforeEach(() => {
    vi.resetModules();
    window.localStorage.clear();
    vi.spyOn(window, "confirm").mockReturnValue(true);
  });
  afterEach(() => vi.restoreAllMocks());

  const DRAFT = [{ id: "p1", beat: null, parts: [{ text: "潮水退去，她看清了闸门上的名字。" }] }];

  const HARD_BLOCKED_PROJECTION = {
    author_state: "hard_blocked",
    blocking_findings: [{ issue_key: "missing_required_text", quality_level: "Q1", verified_by: "scene_card_required_text" }],
    quality_warnings: [],
    recommended_actions: ["review_pipeline_gate"],
    can_archive: false,
  };
  const QUALITY_WARNING_PROJECTION = {
    author_state: "quality_warning",
    blocking_findings: [],
    quality_warnings: [{ issue_key: "pacing_flat", quality_level: "Q2" }],
    recommended_actions: ["adopt_or_patch"],
    can_archive: true,
  };

  it("scnGateFrom：hard_blocked 投影 → canArchive=false + 阻断条目", async () => {
    const { mod } = await loadSceneRun();
    const gate = mod.scnGateFrom({ author_state: HARD_BLOCKED_PROJECTION });
    expect(gate.authorState).toBe("hard_blocked");
    expect(gate.canArchive).toBe(false);
    expect(gate.blocking[0].issue_key).toBe("missing_required_text");
  });

  it("scnGateFrom：quality_warning 投影 → 可归档 + 警告随行；无投影 → null", async () => {
    const { mod } = await loadSceneRun();
    const gate = mod.scnGateFrom({ author_state: QUALITY_WARNING_PROJECTION });
    expect(gate.authorState).toBe("quality_warning");
    expect(gate.canArchive).toBe(true);
    expect(gate.warnings.length).toBe(1);
    expect(mod.scnGateFrom({})).toBeNull();
  });

  it("scnAdoptToDoc：gate 不可归档 → 前置拦截，不发 adopt-current POST", async () => {
    const { mod, client } = await loadSceneRun();
    const cat = await import("./ws-catalog.jsx");
    await vi.waitFor(() => expect(cat.WsCatalog.get().length).toBeGreaterThan(0), T);
    const gate = mod.scnGateFrom({ author_state: HARD_BLOCKED_PROJECTION });

    const result = await mod.scnAdoptToDoc("ch01s1", DRAFT, gate);

    expect(result.ok).toBe(false);
    expect(result.reason).toContain("Q0/Q1");
    const adoptCalls = client.apiPost.mock.calls.filter(c => /adopt-current/.test(c[0]));
    expect(adoptCalls).toEqual([]);
    // 正文保留、不置 done、不写缓存
    expect(Object.keys(window.localStorage).filter(k => k.includes("wr-doc:ch01s1"))).toEqual([]);
  });

  it("Wave 3 终选三函数：盲化取数 / 选择提交 / 续跑（sid→后端 id 对位）", async () => {
    const { mod, client } = await loadSceneRun();
    const cat = await import("./ws-catalog.jsx");
    await vi.waitFor(() => expect(cat.WsCatalog.get().length).toBeGreaterThan(0), T);
    const base = client.apiGet.getMockImplementation();
    client.apiGet.mockImplementation((url) => {
      if (/\/api\/v1\/scenes\/s1\/style-candidates$/.test(url)) {
        return Promise.resolve({
          blinded: true,
          candidates: [
            { row_id: "cand_b", content: "候选乙全文" },
            { row_id: "cand_a", content: "候选甲全文" },
          ],
          selection: { decision_status: "awaiting", selected_row_id: null },
        });
      }
      return base(url);
    });
    client.apiPost.mockImplementation((url) => Promise.resolve({ ok: true, url }));

    const list = await mod.scnCandidates("ch01s1");
    // 盲化契约：按后端 blinded_order 原样呈现，不重排、无分数字段
    expect(list.blinded).toBe(true);
    expect(list.candidates.map(c => c.row_id)).toEqual(["cand_b", "cand_a"]);
    expect(list.candidates.every(c => !("adversarial_score" in c))).toBe(true);

    await mod.scnSelectCandidate("ch01s1", "cand_b", { no_clear_difference: true });
    expect(client.apiPost).toHaveBeenCalledWith(
      "/api/v1/scenes/s1/style-candidates/cand_b/select",
      expect.objectContaining({ no_clear_difference: true })
    );

    await mod.scnResumeAfterSelection("ch01s1");
    expect(client.apiPost).toHaveBeenCalledWith("/api/v1/scenes/s1/resume-after-selection", expect.anything());
  });

  it("Wave 3 终选锁定：SELECTION_LOCKED 拒绝原样上抛（不静默吞掉）", async () => {
    const { mod, client } = await loadSceneRun();
    const cat = await import("./ws-catalog.jsx");
    await vi.waitFor(() => expect(cat.WsCatalog.get().length).toBeGreaterThan(0), T);
    const locked = Object.assign(new Error("selection locked"), { code: "SELECTION_LOCKED" });
    client.apiPost.mockImplementation((url) => {
      if (/\/select$/.test(url)) return Promise.reject(locked);
      return Promise.resolve({});
    });

    await expect(mod.scnSelectCandidate("ch01s1", "cand_x", {})).rejects.toMatchObject({ code: "SELECTION_LOCKED" });
  });

  it("scnAdoptToDoc：quality_warning 的 gate 不拦归档（Q2/Q3 照常交付）", async () => {
    const { mod, client } = await loadSceneRun();
    const cat = await import("./ws-catalog.jsx");
    await vi.waitFor(() => expect(cat.WsCatalog.get().length).toBeGreaterThan(0), T);
    client.apiPost.mockImplementation((url) => {
      if (/adopt-current$/.test(url)) {
        return Promise.resolve({ scene_id: "s1", scene_status: "archived", final_scene_row_id: "final_s1_v1" });
      }
      return Promise.resolve({});
    });
    const gate = mod.scnGateFrom({ author_state: QUALITY_WARNING_PROJECTION });

    const result = await mod.scnAdoptToDoc("ch01s1", DRAFT, gate);

    expect(result.ok).toBe(true);
    expect(client.apiPost).toHaveBeenCalledWith("/api/v1/scenes/s1/adopt-current", expect.anything());
  });
});
