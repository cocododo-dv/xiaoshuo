import { apiGet, apiPatch, apiPost } from "./lib/client.js";

/* global window */
/* ==========================================================
   WrDocs — 写作器正文文档 store（FE-ALIGN Phase 3）
   ----------------------------------------------------------
   正文真相源 = author-drafts 主路径（POST ensure + PATCH /{draft_id}），
   字数统计与目录 rollup 由保存响应回流（words_rollup）。
   localStorage 的 wr-doc:<sid> 键退化为「同步读缓存」：写作器在
   render/effect 里同步取文档，API 负责水合与持久化；跨浏览器以
   服务端为准（水合覆盖缓存，本地未保存改动优先）。
   sid = 目录 slug（ch08s3）；后端 scene_id 经 WsCatalog 映射。
   冲突（409 AUTHOR_DRAFT_CONFLICT）：以服务端为准重新水合。
   ========================================================== */

const wrKeyOf = (sid) => (window.wsKey ? window.wsKey("wr-doc:" + sid) : "wr-doc:" + sid);

// sid → { draftId, revision, hydrated, dirty, chain }
const docMeta = {};

function meta(sid) {
  return docMeta[sid] || (docMeta[sid] = { draftId: null, revision: 0, hydrated: false, dirty: false, chain: Promise.resolve() });
}

function cacheRead(sid) {
  try { return localStorage.getItem(wrKeyOf(sid)); } catch (e) { return null; }
}
function cacheWrite(sid, html) {
  try { localStorage.setItem(wrKeyOf(sid), html); } catch (e) {}
}

function notifyLoaded(sid) {
  try { window.dispatchEvent(new CustomEvent("ws:wr-doc-loaded", { detail: sid })); } catch (e) {}
}

async function backendSceneId(sid) {
  const cat = window.WsCatalog;
  if (!cat || !cat.__backendSceneId) return null;
  try { return await cat.__backendSceneId(sid); } catch (e) { return null; }
}

/* 文本 → 文档 HTML（服务端草稿以 \n 分段；写作器编辑器吃 <p> 段落） */
function toDocHTML(content) {
  if (!content) return "";
  if (/<\w+[^>]*>/.test(content)) return content; // 已是 HTML
  return content
    .split(/\n+/)
    .map(line => line.trim())
    .filter(Boolean)
    .map(line => `<p>${line}</p>`)
    .join("");
}

/* HTML → 存库内容：原样存 HTML（count_words 服务端会剥标签） */

async function ensureDraft(sid) {
  const m = meta(sid);
  if (m.draftId) return m;
  const sceneId = await backendSceneId(sid);
  if (!sceneId) return m;
  const data = await apiPost(`/api/v1/author-drafts/scene/${sceneId}/ensure`, {});
  const draft = data && data.draft;
  if (draft) {
    m.draftId = draft.draft_id;
    m.revision = draft.revision_no;
    m.serverContent = draft.content || "";
  }
  return m;
}

async function hydrate(sid) {
  const m = meta(sid);
  if (m.hydrated || m.hydrating) return;
  m.hydrating = true;
  try {
    await ensureDraft(sid);
    if (m.draftId != null && !m.dirty) {
      const html = toDocHTML(m.serverContent || "");
      const cached = cacheRead(sid);
      if (html && html !== cached) {
        cacheWrite(sid, html);
        notifyLoaded(sid);
      } else if (!html && cached == null) {
        // 服务端空白草稿：保持缓存为空（视图显示开场占位）
      }
      m.hydrated = true;
    } else if (m.draftId != null) {
      m.hydrated = true; // 本地有未保存改动：本地优先，保存时带 revision 上行
    }
  } catch (e) {
    console.warn("[WrDocs] 文档水合失败:", sid, e);
  } finally {
    m.hydrating = false;
  }
}

async function pushSave(sid, html) {
  const m = meta(sid);
  await ensureDraft(sid);
  if (!m.draftId) return; // 目录尚未就绪（如乐观新场景）：缓存已写，稍后重试
  try {
    const data = await apiPatch(`/api/v1/author-drafts/${m.draftId}`, {
      content: html,
      base_revision_no: m.revision,
    });
    const draft = data && data.draft;
    if (draft) m.revision = draft.revision_no;
    m.dirty = false;
    if (data && data.words_rollup && window.WsCatalog && window.WsCatalog.__applyWordsRollup) {
      window.WsCatalog.__applyWordsRollup(sid, data.words_rollup);
    }
  } catch (e) {
    if (e && e.code === "AUTHOR_DRAFT_CONFLICT") {
      // 服务端已被改（另一端保存）：以服务端为准重新水合
      m.draftId = null;
      m.hydrated = false;
      m.dirty = false;
      await hydrate(sid);
      try { window.alert("这份正文在别处被修改过，已加载服务端最新版本。"); } catch (e2) {}
    } else {
      console.warn("[WrDocs] 正文保存失败（缓存已留底，下次保存重试）:", e);
    }
  }
}

const WrDocs = {
  /* 同步读：返回缓存（可能为 null = 从未写过）；后台触发水合 */
  load(sid) {
    if (!sid) return null;
    hydrate(sid);
    return cacheRead(sid);
  },
  /* 是否仍在等首次水合（视图可据此决定是否回填） */
  pending(sid) {
    const m = meta(sid);
    return !m.hydrated;
  },
  /* 写：缓存即时落地，API 串行保存（按 sid 链式，避免乱序覆盖） */
  save(sid, html) {
    if (!sid) return;
    cacheWrite(sid, html);
    const m = meta(sid);
    m.dirty = true;
    m.chain = m.chain.then(() => pushSave(sid, html)).catch(() => {});
    return m.chain;
  },
  /* 当前在写场景预热（目录装载后调用） */
  hydrateActive() {
    try {
      const w = window.WsCatalog && window.WsCatalog.writingScene();
      if (w && w.scene && w.scene.sid) hydrate(w.scene.sid);
    } catch (e) {}
  },
};

Object.assign(window, { WrDocs });

export { WrDocs };
