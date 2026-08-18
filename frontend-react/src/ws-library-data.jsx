import { apiGet } from "./lib/client.js";
import { WsWorks } from "./ws-works.jsx";

/* global window */
/* ==========================================================
   Library data — 档案库（后端 /library 聚合的适配层）
   One connected dataset across categories, with cross-links.
   Each entry: { id, cat, name, code, kind, accent, tags,
                 summary, blurb, facts[], links[], appears[],
                 state?, arc?, updated, pinned? }
   ========================================================== */

const LIB_CATS = [
  { id: "people",    label: "人物",   icon: "Users",     accent: "crimson", noun: "位角色" },
  { id: "world",     label: "世界",   icon: "MapPin",    accent: "gold",    noun: "处设定" },
  { id: "events",    label: "大事记", icon: "Clock",     accent: "slate",   noun: "起事件" },
  { id: "refs",      label: "参考",   icon: "BookOpen",  accent: "sage",    noun: "本参考" },
  { id: "profiles",  label: "风格",   icon: "Sparkles",  accent: "rose",    noun: "组画像" },
  { id: "knowledge", label: "知识",   icon: "FileText",  accent: "ink",     noun: "条沉淀" },
];


/* ==========================================================
   FE-ALIGN Phase 6：资料库接真。
   LIB_ENTRIES 退化为可变缓存数组（保持引用——视图随访问重挂载读取
   最新内容）；数据来自 /api/v2/projects/{id}/library（人物/实体/关系/
   时间线聚合），适配为原型条目形状。refs/profiles/knowledge 三类
   由风格/知识子系统供给，P8 接真前留空。
   ========================================================== */

const LIB_ENTRIES = [];
const LIB_BY_ID = {};

const LIB_KIND_LABEL = { location: "地点", item: "物品", faction: "机构", concept: "概念" };
const LIB_CAT_ACCENT = { people: "crimson", world: "gold", events: "slate" };

const libActiveId = () => { try { return WsWorks ? WsWorks.activeId() : null; } catch (e) { return null; } };

/* 关系 id 缓存（编辑层 diff 删边用）：refPair "a|b" → relation_id */
let LIB_RELATIONS = [];
let LIB_REVISION = 0;
const libSubscribers = new Set();

function libNotify() {
  LIB_REVISION += 1;
  libSubscribers.forEach((listener) => {
    try { listener(); } catch (e) {}
  });
  /* 兼容仍通过 window 事件读取资料库的过渡期模块。 */
  try { window.dispatchEvent(new CustomEvent("ws:library-changed")); } catch (e) {}
}

function libSubscribe(listener) {
  libSubscribers.add(listener);
  return () => libSubscribers.delete(listener);
}

function libSnapshot() { return LIB_REVISION; }

function libStripRef(ref) { return String(ref || "").split(":").slice(1).join(":"); }

function libAdaptCharacter(c, linksOf) {
  const d = c.details || {};
  return {
    id: c.character_id, cat: "people", name: c.name,
    code: d.code || "人物", kind: c.role || "角色",
    accent: d.accent || LIB_CAT_ACCENT.people, glyph: d.glyph || Array.from(c.name)[0],
    pinned: !!d.pinned, updated: d.updated || "",
    summary: c.summary || "", tags: d.tags || [],
    arc: d.arc, state: d.state,
    blurb: d.blurb || "",
    facts: d.facts || [],
    links: linksOf(`character:${c.character_id}`),
    appears: d.appears || [],
    ref: c.ref,
  };
}

function libAdaptEntity(e, linksOf) {
  const d = e.details || {};
  return {
    id: e.entity_id, cat: "world", name: e.name,
    code: d.code || "世界", kind: LIB_KIND_LABEL[e.kind] || e.kind,
    accent: d.accent || LIB_CAT_ACCENT.world, glyph: d.glyph || Array.from(e.name)[0],
    pinned: !!d.pinned, updated: d.updated || "",
    summary: e.summary || "", tags: e.tags || [],
    arc: d.arc, state: d.state,
    blurb: d.blurb || "",
    facts: d.facts || [],
    links: linksOf(e.ref),
    appears: d.appears || [],
    ref: e.ref,
  };
}

function libAdaptEvent(ev, byRef) {
  const facts = [];
  if (ev.time_label) facts.push({ k: "时间", v: ev.time_label });
  if (ev.chapter_ref) facts.push({ k: "章", v: ev.chapter_ref });
  return {
    id: ev.event_id, cat: "events", name: ev.label,
    code: "事记", kind: "事件",
    accent: LIB_CAT_ACCENT.events, glyph: Array.from(ev.label)[0],
    updated: "",
    summary: ev.time_label || "", tags: [],
    blurb: ev.note || "",
    facts,
    links: (ev.entity_refs || []).map(ref => ({ id: libStripRef(ref), rel: "相关" })).filter(l => l.id),
    appears: ev.chapter_ref ? [ev.chapter_ref] : ["贯穿"],
    ref: `event:${ev.event_id}`,
  };
}

let libFetching = null;
let libFetchingProjectId = null;
let libVisibleProjectId = null;
let libRequestSerial = 0;

function libClearForProject(projectId) {
  libVisibleProjectId = projectId || null;
  LIB_RELATIONS = [];
  LIB_ENTRIES.length = 0;
  Object.keys(LIB_BY_ID).forEach(k => { delete LIB_BY_ID[k]; });
  libNotify();
}

function libFetch() {
  const pid = libActiveId();
  if (!pid || pid === "__loading__") {
    if (libVisibleProjectId !== null || LIB_ENTRIES.length || LIB_RELATIONS.length) {
      libRequestSerial += 1; // 让尚未返回的旧作品请求失效
      libFetching = null;
      libFetchingProjectId = null;
      libClearForProject(null);
    }
    return Promise.resolve();
  }

  /* 切换作品时立即清空旧快照；新请求完成前绝不展示上一部作品的数据。 */
  if (libVisibleProjectId !== pid) {
    libRequestSerial += 1;
    libFetching = null;
    libFetchingProjectId = null;
    libClearForProject(pid);
  }
  if (libFetching && libFetchingProjectId === pid) return libFetching;

  const requestSerial = ++libRequestSerial;
  libFetchingProjectId = pid;
  const pending = (async () => {
    try {
      const data = await apiGet(`/api/v2/projects/${pid}/library`);
      /* A→B 快速切换时，A 的迟到响应不得覆盖 B 的资料库。 */
      if (requestSerial !== libRequestSerial || libActiveId() !== pid || libVisibleProjectId !== pid) return;
      LIB_RELATIONS = (data && data.relations) || [];
      const linkIndex = {};
      for (const rel of LIB_RELATIONS) {
        (linkIndex[rel.from_ref] = linkIndex[rel.from_ref] || []).push({ id: libStripRef(rel.to_ref), rel: rel.note || rel.kind, type: rel.kind, relationId: rel.relation_id });
        (linkIndex[rel.to_ref] = linkIndex[rel.to_ref] || []).push({ id: libStripRef(rel.from_ref), rel: rel.note || rel.kind, type: rel.kind, relationId: rel.relation_id });
      }
      const linksOf = (ref) => linkIndex[ref] || [];
      const byRef = {};
      const next = [
        ...((data && data.characters) || []).map(c => libAdaptCharacter(c, linksOf)),
        ...((data && data.entities) || []).map(e => libAdaptEntity(e, linksOf)),
        ...((data && data.timeline) || []).map(ev => libAdaptEvent(ev, byRef)),
      ];
      LIB_ENTRIES.length = 0;
      LIB_ENTRIES.push(...next);
      Object.keys(LIB_BY_ID).forEach(k => { delete LIB_BY_ID[k]; });
      next.forEach(e => { LIB_BY_ID[e.id] = e; });
      libNotify();
    } catch (e) {
      console.warn("[WsLibrary] 拉取资料库失败:", e);
    } finally {
      if (requestSerial === libRequestSerial) {
        libFetching = null;
        libFetchingProjectId = null;
      }
    }
  })();
  libFetching = pending;
  return pending;
}

try { libFetch(); } catch (e) {}
if (window.__wsLibraryDataWorkChanged) {
  window.removeEventListener("ws:work-changed", window.__wsLibraryDataWorkChanged);
}
const libOnWorkChanged = () => { try { libFetch(); } catch (e) {} };
window.addEventListener("ws:work-changed", libOnWorkChanged);
window.__wsLibraryDataWorkChanged = libOnWorkChanged;
Object.assign(window, {
  LIB_relationsRaw: () => LIB_RELATIONS,
  LIB_refetch: libFetch,
  LIB_subscribe: libSubscribe,
  LIB_snapshot: libSnapshot,
});

Object.assign(window, { LIB_CATS, LIB_ENTRIES, LIB_BY_ID });

/* ESM 导出（Phase 1 机械追加；window.* 赋值过渡期保留） */
export { LIB_CATS, LIB_ENTRIES, LIB_BY_ID, libSubscribe, libSnapshot };
