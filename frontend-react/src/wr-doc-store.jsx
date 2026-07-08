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

// 作品id::sid → { draftId, revision, hydrated, dirty, chain }
// 必须带作品前缀：同名 slug（ch01s1）在每部作品都存在，裸 sid 会把
// PATCH 打到上一部作品的 draft（跨作品数据污染）。
const docMeta = {};

function metaKeyOf(sid) {
  let work = "";
  try { work = (window.WsWorks && window.WsWorks.activeId()) || ""; } catch (e) {}
  return work + "::" + sid;
}

function meta(sid) {
  const key = metaKeyOf(sid);
  return docMeta[key] || (docMeta[key] = { draftId: null, revision: 0, hydrated: false, dirty: false, chain: Promise.resolve() });
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
      // 服务端已被改（另一端保存）：以服务端为准重新水合。
      // 审计 P-12：覆盖前把本地未保存稿留一份副本，避免较新的本地编辑无痕丢失。
      let backupKey = null;
      try {
        backupKey = `${wrKeyOf(sid)}:conflict-${Date.now()}`;
        localStorage.setItem(backupKey, html);
      } catch (e3) { backupKey = null; }
      m.draftId = null;
      m.hydrated = false;
      m.dirty = false;
      await hydrate(sid);
      try {
        window.alert(
          "这份正文在别处被修改过，已加载服务端最新版本。" +
          (backupKey ? `\n你本地未保存的内容已备份到浏览器缓存（键：${backupKey}），可从中找回。` : "")
        );
      } catch (e2) {}
    } else {
      console.warn("[WrDocs] 正文保存失败（缓存已留底，下次保存重试）:", e);
    }
  }
}

/* ==========================================================
   WrDocVersions — 正文修订历史（FE-ALIGN F2）
   ----------------------------------------------------------
   成稿中心「对比」的数据源：后端每次保存都会落一行修订快照
   （author_draft_revisions），这里按 sid 取版本列表与任一版正文，
   并提供句级 diff（LCS）。draftId 复用 WrDocs 的 ensure 链路。
   ========================================================== */

function htmlToParas(raw) {
  if (!raw) return [];
  if (!/<\w+[^>]*>/.test(raw)) return String(raw).split(/\n+/).map(x => x.trim()).filter(Boolean);
  const div = document.createElement("div");
  div.innerHTML = raw;
  let paras = Array.from(div.querySelectorAll("p, li")).map(p => (p.textContent || "").trim()).filter(Boolean);
  if (!paras.length) {
    const t = (div.textContent || "").trim();
    paras = t ? t.split(/\n+/).map(x => x.trim()).filter(Boolean) : [];
  }
  return paras;
}

/* 句级 diff：A=旧版段落、B=新版段落 → 按 B 版式分段的 same/del/add 片段 */
function diffSentences(aParas, bParas) {
  const split = (paras) => {
    const out = [];
    (paras || []).forEach((p, pi) => {
      const parts = String(p).split(/(?<=[。！？!?；;…])/).map(s => s.trim()).filter(Boolean);
      (parts.length ? parts : [String(p)]).forEach(s => out.push({ p: pi, s }));
    });
    return out;
  };
  const A = split(aParas), B = split(bParas);
  const n = A.length, m = B.length;
  const dp = Array.from({ length: n + 1 }, () => new Array(m + 1).fill(0));
  for (let i = n - 1; i >= 0; i--) {
    for (let j = m - 1; j >= 0; j--) {
      dp[i][j] = A[i].s === B[j].s ? dp[i + 1][j + 1] + 1 : Math.max(dp[i + 1][j], dp[i][j + 1]);
    }
  }
  const segs = [];
  let i = 0, j = 0, adds = 0, dels = 0;
  const delPara = () => (j < m ? B[j].p : (m ? B[m - 1].p : 0));
  while (i < n && j < m) {
    if (A[i].s === B[j].s) { segs.push({ t: "same", text: B[j].s, p: B[j].p }); i++; j++; }
    else if (dp[i + 1][j] >= dp[i][j + 1]) { segs.push({ t: "del", text: A[i].s, p: delPara() }); dels++; i++; }
    else { segs.push({ t: "add", text: B[j].s, p: B[j].p }); adds++; j++; }
  }
  while (i < n) { segs.push({ t: "del", text: A[i].s, p: delPara() }); dels++; i++; }
  while (j < m) { segs.push({ t: "add", text: B[j].s, p: B[j].p }); adds++; j++; }
  const paras = [];
  segs.forEach(seg => {
    if (!paras.length || paras[paras.length - 1].p !== seg.p) paras.push({ p: seg.p, segs: [] });
    paras[paras.length - 1].segs.push(seg);
  });
  return { paras, adds, dels };
}

const WrDocVersions = {
  /* 版本列表（新→旧）：[{revisionNo, words, origin, at}]；无后端目录映射时返回 [] */
  async list(sid) {
    const m = await ensureDraft(sid);
    if (!m.draftId) return [];
    const data = await apiGet(`/api/v1/author-drafts/${m.draftId}/revisions`);
    return ((data && data.items) || []).map(r => ({
      revisionNo: r.revision_no,
      words: r.words || 0,
      origin: r.origin || "edited",
      at: r.created_at || "",
    }));
  },
  /* 某一版正文 → 段落数组（剥 HTML） */
  async paras(sid, revisionNo) {
    const m = await ensureDraft(sid);
    if (!m.draftId) return [];
    const data = await apiGet(`/api/v1/author-drafts/${m.draftId}/revisions/${revisionNo}`);
    return htmlToParas((data && data.revision && data.revision.content) || "");
  },
  diff: diffSentences,
};

const WrDocs = {
  /* 解析 sid → 后端 author-draft draft_id（不存在则 ensure 建一份空稿）；
     供"AI 续写"等需要真实 draft_id 发起 LLM 调用的功能复用同一份映射缓存。 */
  async draftId(sid) {
    if (!sid) return null;
    const m = await ensureDraft(sid);
    return m.draftId || null;
  },
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

Object.assign(window, { WrDocs, WrDocVersions });

export { WrDocs, WrDocVersions };
