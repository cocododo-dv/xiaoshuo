import { apiGet, apiPost, apiPut } from "./lib/client.js";
import { WsWorks } from "./ws-works.jsx";
import { WsCatalog } from "./ws-catalog.jsx";

/* ==========================================================
   WsChapterPlan — 章节编排的 LLM 规划 store
   （docs/chapter-arrangement-llm-design-2026-07-16.md §7）

   后端契约（/api/v2/projects/{pid}/catalog/chapters/{chid}/…）：
   · GET/PUT architecture + POST architecture/generate —— 章节蓝图一等公民
   · POST plan/candidates | plan/fill | plan/review —— 咨询通道
     （LLM 未配置时 ok 信封里带 source:"fallback" + author_action，不是错误）
   · POST plan/apply —— 咨询补丁经作者确认后的原子回写；成功后重拉目录收敛

   状态按「后端 chapter_id」分桶；所有键都是后端 id（视图层负责
   backendId 换算）。写失败不做本地猜测：错误原样挂进桶，目录以
   服务端为准（apply 失败不动 WsCatalog 缓存）。
   ========================================================== */

const cpState = {};          // backendChapterId → bucket
const cpSubs = new Set();
let cpVersionCounter = 0;    // useSyncExternalStore 的快照信号（bucket 引用稳定，靠版本号触发重渲）

const CP_EMPTY = Object.freeze({
  arch: Object.freeze({ status: "idle", data: null, error: null, busy: false }),
  action: Object.freeze({ busy: false, kind: null, error: null }),
  candidates: null,          // {items, degraded, llmCallId} | null
  fill: null,                // {patch, notes, gaps, dropped, degraded, llmCallId} | null
  review: null,              // {findings, source, degraded} | null
  authorAction: null,        // 最近一次 fallback 的 author_action
  applied: null,             // 最近一次 apply 的 {scenes, appended, skipped}
});

function cpNotify() { cpVersionCounter += 1; cpSubs.forEach((fn) => { try { fn(); } catch (e) {} }); }

function cpBucket(chapterId) {
  if (!cpState[chapterId]) {
    cpState[chapterId] = {
      arch: { ...CP_EMPTY.arch },
      action: { ...CP_EMPTY.action },
      candidates: null,
      fill: null,
      review: null,
      authorAction: null,
      applied: null,
    };
  }
  return cpState[chapterId];
}

function cpProjectId() {
  try {
    const id = WsWorks ? WsWorks.activeId() : null;
    return id && id !== "__loading__" ? id : null;
  } catch (e) { return null; }
}

const cpBase = (pid, chid) => `/api/v2/projects/${pid}/catalog/chapters/${encodeURIComponent(chid)}`;

function cpError(e) {
  return { code: (e && e.code) || "REQUEST_FAILED", message: (e && e.message) || "请求失败" };
}

/* 后端蓝图行 → 视图形状 */
function cpAdaptArch(row) {
  if (!row) return null;
  const p = row.payload || {};
  return {
    rowId: row.row_id,
    createdBy: row.created_by || "",
    createdAt: row.created_at || "",
    fromLlm: !!row.llm_call_id,
    promise: p.chapter_promise || "",
    escalation: Array.isArray(p.escalation_path) ? p.escalation_path : [],
    reveals: Array.isArray(p.reveal_plan) ? p.reveal_plan : [],
    payoff: p.payoff_target || "",
    shift: p.character_shift || "",
    endingQuestion: p.ending_question || "",
  };
}

function cpArchBody(view) {
  return {
    chapter_promise: view.promise || "",
    escalation_path: (view.escalation || []).filter((s) => String(s || "").trim()),
    reveal_plan: (view.reveals || []).filter((s) => String(s || "").trim()),
    payoff_target: view.payoff || "",
    character_shift: view.shift || "",
    ending_question: view.endingQuestion || "",
  };
}

async function cpRun(chapterId, kind, fn) {
  const bucket = cpBucket(chapterId);
  if (bucket.action.busy) return null;
  bucket.action = { busy: true, kind, error: null };
  cpNotify();
  try {
    const result = await fn();
    bucket.action = { busy: false, kind: null, error: null };
    cpNotify();
    return result;
  } catch (e) {
    bucket.action = { busy: false, kind, error: cpError(e) };
    cpNotify();
    throw e;
  }
}

export const WsChapterPlan = {
  subscribe(fn) { cpSubs.add(fn); return () => cpSubs.delete(fn); },
  version() { return cpVersionCounter; },
  snapshot(chapterId) { return chapterId && cpState[chapterId] ? cpState[chapterId] : CP_EMPTY; },
  reset(chapterId) { delete cpState[chapterId]; cpNotify(); },

  /* ---- 章节蓝图 ---- */
  async loadArchitecture(chapterId) {
    const pid = cpProjectId();
    if (!pid || !chapterId) return null;
    const bucket = cpBucket(chapterId);
    bucket.arch = { ...bucket.arch, status: "loading", error: null };
    cpNotify();
    try {
      const data = await apiGet(`${cpBase(pid, chapterId)}/architecture`);
      bucket.arch = { status: "ready", data: cpAdaptArch(data && data.architecture), error: null, busy: false };
      cpNotify();
      return bucket.arch.data;
    } catch (e) {
      bucket.arch = { status: "error", data: null, error: cpError(e), busy: false };
      cpNotify();
      throw e;
    }
  },

  async saveArchitecture(chapterId, view) {
    const pid = cpProjectId();
    if (!pid || !chapterId) return null;
    return cpRun(chapterId, "arch-save", async () => {
      const data = await apiPut(`${cpBase(pid, chapterId)}/architecture`, cpArchBody(view));
      const bucket = cpBucket(chapterId);
      bucket.arch = { status: "ready", data: cpAdaptArch(data && data.architecture), error: null, busy: false };
      return bucket.arch.data;
    });
  },

  async generateArchitecture(chapterId) {
    const pid = cpProjectId();
    if (!pid || !chapterId) return null;
    return cpRun(chapterId, "arch-generate", async () => {
      const data = await apiPost(`${cpBase(pid, chapterId)}/architecture/generate`, {});
      const bucket = cpBucket(chapterId);
      if (data && data.source === "fallback") {
        bucket.authorAction = data.author_action || null;
        return null;
      }
      bucket.authorAction = null;
      bucket.arch = { status: "ready", data: cpAdaptArch(data && data.architecture), error: null, busy: false };
      return bucket.arch.data;
    });
  },

  /* ---- 三通道 ---- */
  async requestCandidates(chapterId, directionHint) {
    const pid = cpProjectId();
    if (!pid || !chapterId) return null;
    return cpRun(chapterId, "candidates", async () => {
      const body = directionHint ? { direction_hint: directionHint } : {};
      const data = await apiPost(`${cpBase(pid, chapterId)}/plan/candidates`, body);
      const bucket = cpBucket(chapterId);
      if (data && data.source === "fallback") {
        bucket.authorAction = data.author_action || null;
        bucket.candidates = null;
        return null;
      }
      bucket.authorAction = null;
      bucket.candidates = {
        items: (data && data.candidates) || [],
        degraded: (data && data.degraded_slots) || [],
        llmCallId: (data && data.llm_call_id) || null,
      };
      return bucket.candidates;
    });
  },

  async requestFill(chapterId, opts) {
    const pid = cpProjectId();
    if (!pid || !chapterId) return null;
    const mode = opts && opts.candidate ? "adopt" : "fill";
    return cpRun(chapterId, "fill", async () => {
      const body = mode === "adopt" ? { mode, candidate: opts.candidate } : { mode };
      const data = await apiPost(`${cpBase(pid, chapterId)}/plan/fill`, body);
      const bucket = cpBucket(chapterId);
      if (data && data.source === "fallback") {
        bucket.authorAction = data.author_action || null;
        bucket.fill = { patch: { drama: {}, scenes: [], append_scenes: [] }, notes: [], gaps: (data && data.gaps) || [], dropped: [], degraded: (data && data.degraded_slots) || [], llmCallId: null, offline: true };
        return bucket.fill;
      }
      bucket.authorAction = null;
      bucket.fill = {
        patch: (data && data.patch) || { drama: {}, scenes: [], append_scenes: [] },
        notes: (data && data.notes) || [],
        gaps: (data && data.gaps) || [],
        dropped: (data && data.dropped) || [],
        degraded: (data && data.degraded_slots) || [],
        llmCallId: (data && data.llm_call_id) || null,
        offline: false,
      };
      return bucket.fill;
    });
  },

  async requestReview(chapterId) {
    const pid = cpProjectId();
    if (!pid || !chapterId) return null;
    return cpRun(chapterId, "review", async () => {
      const data = await apiPost(`${cpBase(pid, chapterId)}/plan/review`, {});
      const bucket = cpBucket(chapterId);
      if (data && data.source === "fallback") bucket.authorAction = data.author_action || null;
      else bucket.authorAction = null;
      bucket.review = {
        findings: (data && data.findings) || [],
        source: (data && data.source) || "llm",
        degraded: (data && data.degraded_slots) || [],
      };
      return bucket.review;
    });
  },

  /* ---- 原子回写：成功后目录以服务端为准（重拉收敛） ---- */
  async applyPatch(chapterId, patch) {
    const pid = cpProjectId();
    if (!pid || !chapterId) return null;
    return cpRun(chapterId, "apply", async () => {
      const data = await apiPost(`${cpBase(pid, chapterId)}/plan/apply`, { patch });
      const bucket = cpBucket(chapterId);
      bucket.applied = {
        drama: (data && data.applied && data.applied.drama) || 0,
        scenes: (data && data.applied && data.applied.scenes) || 0,
        appended: (data && data.applied && data.applied.appended) || 0,
        skipped: (data && data.skipped) || [],
      };
      bucket.fill = null;        // 已消费的补丁不再展示
      bucket.candidates = null;
      try { if (WsCatalog && WsCatalog.__refresh) await WsCatalog.__refresh(); } catch (e) {}
      return bucket.applied;
    });
  },
};

Object.assign(window, { WsChapterPlan });

/* ESM 导出（与 window.* 赋值过渡期并存） */
export default WsChapterPlan;
