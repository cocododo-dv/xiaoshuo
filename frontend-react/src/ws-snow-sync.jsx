import { apiGet, apiPatch, apiPost } from "./lib/client.js";
import { WsWorks } from "./ws-works.jsx";
import { WsCatalog } from "./ws-catalog.jsx";
import { S2_BE_STEPS } from "./ws-snow.jsx";

/* global window */
/* ==========================================================
   SnowSync — 雪花构思 ↔ snowflake-workspace v2（FE-ALIGN F3）
   ----------------------------------------------------------
   ws_snow_state_v2::<work> 退化为后端真相的写穿缓存：
   - 视图保存（ws:snow-saved）→ 按步 diff → PATCH steps/{key}
     （draft 同时带规范字段喂完备性闸门 + fe_* 键无损保存原型形状）；
     fe_state 变为 done 时顺手 POST approve（闸门不满足则静默跳过）。
   - 启动 / 进入 #construct / 切作品 → GET workspace 水合：
     fe_* 键优先（无损还原），无 fe_* 时从规范字段反推原型形状
     （兼容 seed_demo / 真·雪花管线生成的项目）；本地 _t 不旧于
     服务端则本地为准（未上行的编辑不被覆盖）。
   - revs/confirmRevs 经 book_brief 的 fe_meta 随存；history（过程
     快照日志）留本地（体积大、跨会话价值低，账本记录）。
   ========================================================== */

// G5：FE→BE 步骤键映射统一以 ws-snow 的 S2_BE_STEPS 为正源（避免双份漂移）
const SNOW_STEPS = S2_BE_STEPS;
const FE_BY_BE = Object.fromEntries(SNOW_STEPS.map(([fe, be]) => [be, fe]));

const snowCacheKey = (workId) => "ws_snow_state_v2::" + workId;
const activeWork = () => { try { return (WsWorks && WsWorks.activeId()) || ""; } catch (e) { return ""; } };

/* ---------- FE → BE：规范字段（喂完备性闸门 / scene plans 同步） ---------- */
const txt = (v) => (typeof v === "string" ? v.trim() : "");
function canonFromFE(feKey, saved) {
  const sc = ((saved || {}).scaffolds || {})[feKey] || {};
  const draftText = txt(((saved || {}).drafts || {})[feKey]);
  if (feKey === "audience") {
    return {
      category: txt(sc.genre), target_reader: txt(sc.reader), delight_reason: txt(sc.pleasure),
      story_kind: txt(sc.source), genre_promise: txt(sc.exclude),
    };
  }
  if (feKey === "logline") return { summary: draftText.split("\n").filter(Boolean)[0] || "" };
  if (feKey === "paragraph") {
    return {
      sentences: [txt(sc.setup), txt(sc.d1), txt(sc.d2), txt(sc.d3), txt(sc.resolution)],
      moral_premise: txt(sc.premiseT) || txt(sc.premiseF),
    };
  }
  if (feKey === "characters") {
    return { characters: Object.entries(sc.chars || {}).map(([id, c]) => ({
      character_id: id, display_name: txt(c.name), role: txt(c.role), goal: txt(c.goal),
      ambition: txt(c.ambition), values: txt(c.values) ? [txt(c.values)] : [], conflict: txt(c.conflict), epiphany: txt(c.epiphany),
    })) };
  }
  if (feKey === "synopsis") {
    const p = sc.paras || {};
    return { paragraphs: [txt(p.setup), txt(p.d1), txt(p.d2), txt(p.d3), txt(p.resolution)] };
  }
  if (feKey === "backstory") {
    return { characters: Object.entries(sc.chars || {}).map(([id, c]) => ({
      character_id: id, display_name: txt(c.name), role: txt(c.role),
      synopsis: [c.belief && `信念：${txt(c.belief)}`, c.wound && `旧伤：${txt(c.wound)}`, c.desire && `欲望：${txt(c.desire)}`, c.fear && `恐惧：${txt(c.fear)}`, c.relation && `关系：${txt(c.relation)}`].filter(Boolean).join("\n"),
    })) };
  }
  if (feKey === "outline") {
    const byAct = (n) => (sc.chapters || []).filter(c => c.act === n)
      .map(c => `${c.id} ${txt(c.title)}：${txt(c.summary)}${c.spine ? `（${c.spine}）` : ""}`).join("\n");
    return { paragraphs: [byAct(1), byAct(2), byAct(3), ""] };
  }
  if (feKey === "profile") {
    return { characters: Object.entries(sc.chars || {}).map(([id, c]) => ({
      character_id: id, display_name: txt(c.name), role: txt(c.role),
      physical_profile: { appearance: txt(c.physical) },
      personality_profile: { strongest_trait: txt(c.personality) },
      environment_profile: { home: txt(c.environment) },
      psychological_profile: { philosophy: txt(c.views), self_image: txt(c.contradiction), deepest_fear: txt(c.psych) },
    })) };
  }
  if (feKey === "scenes") {
    return { scenes: (sc.list || []).map((s, i) => ({
      row_uid: s.id || `S${String(i + 1).padStart(2, "0")}`, scene_seq: i + 1,
      summary: txt(s.event), primary_form: s.type === "reactive" ? "reactive" : "proactive",
      pov_character_id: txt(s.pov), location: txt(s.place), crucible: txt(s.crucible), chapter_role: txt(s.fn),
    })) };
  }
  if (feKey === "planning") {
    const listScenes = (((saved || {}).scaffolds || {}).scenes || {}).list || [];
    const plans = sc.plans || {};
    return { scenes: listScenes.map((s, i) => {
      const plan = plans[s.id] || {};
      const form = (plan.mode || (s.type === "reactive" ? "reactive" : "proactive"));
      return {
        row_uid: s.id || `S${String(i + 1).padStart(2, "0")}`, title: txt(s.event), summary: txt(s.event),
        primary_form: form, location: txt(s.place), crucible: txt(s.crucible), scene_crucible: txt(s.crucible),
        pov_character_id: txt(plan.pov) || txt(s.pov),
        goal: txt(plan.goal), conflict: txt(plan.conflict), setback: txt(plan.setback),
        reaction: txt(plan.reaction), dilemma: txt(plan.dilemma), decision: txt(plan.decision),
      };
    }) };
  }
  return {};
}

/* ---------- BE → FE：fe_* 缺席时从规范字段反推原型形状 ---------- */
function feFromCanon(feKey, draft) {
  const d = draft || {};
  const pad2 = (n) => String(n).padStart(2, "0");
  if (feKey === "audience") {
    return { scaffold: { genre: d.category || "", reader: d.target_reader || "", pleasure: d.delight_reason || "", source: d.story_kind || "", exclude: d.genre_promise || "" } };
  }
  if (feKey === "logline") return { text: d.summary || "" };
  if (feKey === "paragraph") {
    const s = d.sentences || [];
    return { scaffold: { premiseF: "", premiseT: d.moral_premise || "", setup: s[0] || "", d1: s[1] || "", d2: s[2] || "", d3: s[3] || "", resolution: s[4] || "" } };
  }
  if (feKey === "characters" || feKey === "backstory" || feKey === "profile") {
    const chars = {};
    (d.characters || []).forEach((c, i) => {
      const id = c.character_id || "c" + (i + 1);
      if (feKey === "characters") {
        chars[id] = { name: c.display_name || "", role: c.role || "主角", goal: c.goal || "", ambition: c.ambition || "", values: (c.values || []).join("、"), conflict: c.conflict || "", epiphany: c.epiphany || "" };
      } else if (feKey === "backstory") {
        chars[id] = { name: c.display_name || "", role: c.role || "主角", belief: c.synopsis || "", wound: "", desire: "", fear: "", relation: "" };
      } else {
        chars[id] = {
          name: c.display_name || "", role: c.role || "主角",
          physical: (c.physical_profile || {}).appearance || "", psych: (c.psychological_profile || {}).deepest_fear || "",
          environment: (c.environment_profile || {}).home || "", personality: (c.personality_profile || {}).strongest_trait || "",
          contradiction: (c.psychological_profile || {}).self_image || "", views: (c.psychological_profile || {}).philosophy || "",
        };
      }
    });
    const sel = Object.keys(chars)[0] || "c1";
    return { scaffold: { sel, chars } };
  }
  if (feKey === "synopsis") {
    const p = d.paragraphs || [];
    return { scaffold: { paras: { setup: p[0] || "", d1: p[1] || "", d2: p[2] || "", d3: p[3] || "", resolution: p[4] || "" } } };
  }
  if (feKey === "outline") {
    const chapters = [];
    (d.paragraphs || []).forEach((para, ai) => {
      String(para || "").split("\n").map(x => x.trim()).filter(Boolean).forEach(line => {
        const m = /^(\d+)\s+([^：:]+)[：:]?(.*)$/.exec(line);
        chapters.push({ id: m ? m[1] : pad2(chapters.length + 1), act: Math.min(ai + 1, 3), title: m ? m[2].trim() : line.slice(0, 16), summary: m ? m[3].replace(/（.*?）$/, "").trim() : "", spine: /灾[一二三]/.test(line) ? (line.match(/灾[一二三]/) || [""])[0] : "" });
      });
    });
    return { scaffold: { chapters } };
  }
  if (feKey === "scenes") {
    return { scaffold: { lines: [], list: (d.scenes || []).map((s, i) => ({
      id: s.row_uid || "S" + pad2(i + 1), type: s.primary_form === "reactive" ? "reactive" : "proactive", line: "main",
      pov: s.pov_character_id || "", place: s.location || "", event: s.summary || "", crucible: s.crucible || "", fn: s.chapter_role || "", spine: "",
    })) } };
  }
  if (feKey === "planning") {
    const plans = {};
    (d.scenes || []).forEach((s, i) => {
      plans[s.row_uid || "S" + pad2(i + 1)] = {
        mode: s.primary_form === "reactive" ? "reactive" : "proactive", pov: s.pov_character_id || "",
        goal: s.goal || "", conflict: s.conflict || "", setback: s.setback || "",
        reaction: s.reaction || "", dilemma: s.dilemma || "", decision: s.decision || "",
      };
    });
    return { scaffold: { sel: Object.keys(plans)[0] || "", plans } };
  }
  return {};
}

function canonHasContent(feKey, draft) {
  const d = draft || {};
  if (feKey === "logline") return !!txt(d.summary);
  if (feKey === "audience") return !!(txt(d.category) || txt(d.target_reader) || txt(d.delight_reason));
  if (feKey === "paragraph") return (d.sentences || []).some(s => txt(s)) || !!txt(d.moral_premise);
  if (feKey === "synopsis" || feKey === "outline") return (d.paragraphs || []).some(s => txt(s));
  if (feKey === "characters" || feKey === "backstory" || feKey === "profile") return (d.characters || []).length > 0;
  return (d.scenes || []).length > 0;
}

const BE_STATE_TO_FE = { approved: "done", skipped: "skip", stale: "warn" };

/* ---------- 水合 ---------- */
const snowHydratedOnce = {};
const snowReadyFlags = {};
const snowUnsupported = {};

async function snowHydrate(workId, opts) {
  const force = !!(opts && opts.force);
  if (!workId || snowUnsupported[workId]) return;
  if (!force && snowHydratedOnce[workId]) return;
  snowHydratedOnce[workId] = true;
  let ws = null;
  try {
    ws = await apiGet(`/api/v2/projects/${workId}/snowflake-workspace`);
  } catch (e) {
    if (e && (e.status === 409 || e.status === 404)) snowUnsupported[workId] = true;
    else delete snowHydratedOnce[workId]; // 网络类失败：下次再试
    return;
  }
  snowReadyFlags[workId] = !!(ws && ws.ready_to_materialize);
  const remote = { drafts: {}, scaffolds: {}, checks: {}, states: {}, _t: 0 };
  let any = false;
  (ws && ws.steps ? ws.steps : []).forEach(step => {
    const feKey = FE_BY_BE[step.step_key];
    if (!feKey) return;
    const draft = step.draft || {};
    if (draft.fe_scaffold || draft.fe_text || draft.fe_state) {
      any = true;
      if (draft.fe_text != null) remote.drafts[feKey] = draft.fe_text;
      if (draft.fe_scaffold) remote.scaffolds[feKey] = draft.fe_scaffold;
      if (Array.isArray(draft.fe_checks)) remote.checks[feKey] = draft.fe_checks;
      if (draft.fe_state) remote.states[feKey] = draft.fe_state;
      if (draft.fe_t && draft.fe_t > remote._t) remote._t = draft.fe_t;
      if (draft.fe_meta) {
        if (draft.fe_meta.revs) remote.revs = draft.fe_meta.revs;
        if (draft.fe_meta.confirmRevs) remote.confirmRevs = draft.fe_meta.confirmRevs;
        // G2：跨会话 journal（去快照、cap 20）——视图只对带 snap 的条目给回滚按钮，
        // 还原条目天然只读，不需要视图改动
        if (Array.isArray(draft.fe_meta.history)) remote.history = draft.fe_meta.history;
      }
    } else if (canonHasContent(feKey, draft)) {
      any = true;
      const fe = feFromCanon(feKey, draft);
      if (fe.text != null) remote.drafts[feKey] = fe.text;
      if (fe.scaffold) remote.scaffolds[feKey] = fe.scaffold;
      const st = BE_STATE_TO_FE[step.status];
      remote.states[feKey] = st || (step.step_key === ws.current_step_key ? "active" : "todo");
      if (remote._t < 1) remote._t = 1; // 规范字段水合：极小时间戳，本地编辑永远赢
    }
  });
  if (!any) return; // 服务端还没有构思数据：保留本地（含种子门控默认）
  const key = snowCacheKey(workId);
  let local = null;
  try { local = JSON.parse(localStorage.getItem(key)); } catch (e) {}
  if (local && (local._t || 0) >= remote._t) return; // 本地不旧于服务端：本地为准
  try { localStorage.setItem(key, JSON.stringify(remote)); } catch (e) {}
  try { window.dispatchEvent(new CustomEvent("ws:snow-hydrated", { detail: workId })); } catch (e) {}
}

/* ---------- 上行 ---------- */
let pushTimer = null;
let pendingKeys = new Set();
let pushChain = Promise.resolve();
const lastPushed = {}; // workId -> feKey -> { sig, state }

async function snowPushKey(cacheKey) {
  const workId = cacheKey.split("::")[1];
  if (!workId || snowUnsupported[workId]) return;
  let saved = null;
  try { saved = JSON.parse(localStorage.getItem(cacheKey)); } catch (e) {}
  if (!saved) return;
  const mine = lastPushed[workId] || (lastPushed[workId] = {});
  for (const [feKey, beKey] of SNOW_STEPS) {
    const fragment = {
      ...canonFromFE(feKey, saved),
      fe_text: ((saved.drafts || {})[feKey]) || "",
      fe_scaffold: ((saved.scaffolds || {})[feKey]) || null,
      fe_checks: ((saved.checks || {})[feKey]) || [],
      fe_state: ((saved.states || {})[feKey]) || "todo",
      fe_t: saved._t || Date.now(),
    };
    if (feKey === "audience") {
      fragment.fe_meta = {
        revs: saved.revs || {},
        confirmRevs: saved.confirmRevs || {},
        // G2：journal 随存——去掉 snap 内容快照（体积大），只留时间线行
        history: (saved.history || []).slice(0, 20).map(h => ({ t: h.t, who: h.who, action: h.action, note: h.note, key: h.key })),
      };
    }
    const { fe_t, ...sigPart } = fragment;
    const sig = JSON.stringify(sigPart);
    const prev = mine[feKey] || {};
    if (prev.sig === sig) continue;
    try {
      await apiPatch(`/api/v2/projects/${workId}/snowflake-workspace/steps/${beKey}`, { draft: fragment, force: true });
      mine[feKey] = { sig, state: fragment.fe_state };
      if (fragment.fe_state === "done" && prev.state !== "done") {
        // 确认步骤：尝试后端 approve（前序闸门不满足时静默跳过，不打断写作流）
        try { await apiPost(`/api/v2/projects/${workId}/snowflake-workspace/steps/${beKey}/approve`, {}); } catch (e2) {}
      }
    } catch (e) {
      if (e && e.status === 409 && e.code === "PROJECT_NOT_SNOWFLAKE") { snowUnsupported[workId] = true; return; }
      // 网络/校验失败：sig 不记账，下次保存重试
    }
  }
}

function schedulePush(cacheKey) {
  pendingKeys.add(cacheKey);
  clearTimeout(pushTimer);
  pushTimer = setTimeout(() => {
    const keys = [...pendingKeys];
    pendingKeys = new Set();
    keys.forEach(k => { pushChain = pushChain.then(() => snowPushKey(k)).catch(() => {}); });
  }, 700);
}

window.addEventListener("ws:snow-saved", (e) => {
  const key = (e && e.detail) || (activeWork() ? snowCacheKey(activeWork()) : null);
  if (key) schedulePush(key);
});

/* ---------- 触发面 ---------- */
window.addEventListener("hashchange", () => {
  const h = location.hash || "";
  if (h.indexOf("snowflake") >= 0 || h.indexOf("home") >= 0) snowHydrate(activeWork());
});
window.addEventListener("ws:work-changed", (e) => { if (e && e.detail) snowHydrate(e.detail); });
setTimeout(() => snowHydrate(activeWork()), 600); // 启动水合（等 WsWorks 就绪）

const SnowSync = {
  refetch(workId) { return snowHydrate(workId || activeWork(), { force: true }); },
  readyToMaterialize(workId) { return !!snowReadyFlags[workId || activeWork()]; },
  /* 物化主路径：approved scene plans → ChapterGoal/SceneCard（成功后目录重拉） */
  async materialize(workId) {
    const id = workId || activeWork();
    const data = await apiPost(`/api/v2/projects/${id}/snowflake-workspace/materialize`, {});
    try { if (WsCatalog && WsCatalog.reset) WsCatalog.reset(); } catch (e) {}
    return data;
  },
};

Object.assign(window, { SnowSync });

export { SnowSync };
