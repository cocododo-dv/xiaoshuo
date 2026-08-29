import React from "react";
import { I } from "./icons.jsx";
import { LIB_BY_ID, LIB_CATS, LIB_ENTRIES } from "./ws-library-data.jsx";
import { LIB_REL_TYPES, LIB_relType } from "./ws-library-derive.jsx";
import { apiDelete, apiPatch, apiPost } from "./lib/client.js";
import { storeAlert } from "./lib/store-utils.js";
import { wsKey, WsWorks } from "./ws-works.jsx";

/* global React, I, LIB_CATS, LIB_REL_TYPES, LIB_relType */
const { useState: useEdSt } = React;

/* ==========================================================
   Library — 档案编辑态 + 本地持久化覆盖层
   · edits      : 对内置条目的字段覆盖   { [id]: patch }
   · additions  : 用户新建的条目          [ entry, ... ]
   ========================================================== */

const LIB_EDIT_KEY = "ws-lib-edits-v1";
const LIB_ADD_KEY  = "ws-lib-additions-v1";
const LIB_K = (k) => (wsKey ? wsKey(k) : k);  // per-work namespace
const LIB_MIGRATED_KEY = "ws-lib-migrated-v1";

const libProjectId = () => { try { return WsWorks ? WsWorks.activeId() : null; } catch (e) { return null; } };
const libApiBase = () => `/api/v2/projects/${libProjectId()}/library`;
const libRefetch = () => { try { if (window.LIB_refetch) window.LIB_refetch(); } catch (e) {} };
const libToast = (e, fallback) => storeAlert(e, fallback);

/* —— FE-ALIGN P6：编辑/新建直接落后端（base 已来自 API），
   localStorage 覆盖层退化为「读空」；旧键一次性上行后保留（P8 清理）。 —— */

function LIB_loadEdits() {
  LIB_migrateLegacy();
  return {};
}

/* 条目 patch → 各对象的 PATCH/关系 CRUD；调用粒度=单次保存的 edits 全量 diff */
const libSentEdits = {};
async function LIB_persist(edits) {
  try {
    for (const id of Object.keys(edits || {})) {
      const patch = edits[id];
      if (!patch || JSON.stringify(libSentEdits[id]) === JSON.stringify(patch)) continue;
      const base = LIB_BY_ID[id];
      if (!base) continue;
      await libPushPatch(base, patch);
      // 只有主对象和关系操作都成功后才去重；部分失败必须允许同载荷重试。
      libSentEdits[id] = patch;
    }
    libRefetch();
    return true;
  } catch (e) {
    libToast(e, "资料卡保存失败。");
    libRefetch();
    return false;
  }
}

async function libPushPatch(base, patch) {
  const body = {};
  if (patch.name != null) body.name = patch.name;
  if (patch.summary != null) body.summary = patch.summary;
  const details = {};
  if (patch.blurb != null) details.blurb = patch.blurb;
  if (patch.facts != null) details.facts = patch.facts;
  if (Object.keys(details).length) body.details = { ...(baseDetails(base)), ...details };
  if (base.cat === "people") {
    if (patch.kind != null) body.role = patch.kind;
    await apiPatch(`${libApiBase()}/characters/${base.id}`, body);
  } else if (base.cat === "events") {
    const eventBody = {};
    if (patch.name != null) eventBody.label = patch.name;
    if (patch.blurb != null || patch.summary != null) eventBody.note = patch.blurb || patch.summary;
    await apiPatch(`${libApiBase()}/timeline/${base.id}`, eventBody);
  } else {
    if (patch.tags != null) body.tags = patch.tags;
    await apiPatch(`${libApiBase()}/entities/${base.id}`, body);
  }
  if (patch.links) await libSyncLinks(base, patch.links);
}

function baseDetails(base) {
  return {
    blurb: base.blurb, facts: base.facts, appears: base.appears,
    arc: base.arc, state: base.state, code: base.code, accent: base.accent,
    glyph: base.glyph, pinned: base.pinned, updated: base.updated,
  };
}

async function libSyncLinks(base, nextLinks) {
  const prev = base.links || [];
  const nextIds = new Set((nextLinks || []).map(l => l.id));
  for (const link of prev) {
    if (!nextIds.has(link.id) && link.relationId) {
      await apiDelete(`${libApiBase()}/relations/${link.relationId}`);
    }
  }
  const prevIds = new Set(prev.map(l => l.id));
  for (const link of nextLinks || []) {
    if (prevIds.has(link.id)) continue;
    const target = LIB_BY_ID[link.id];
    if (!target || !target.ref || !base.ref || String(target.ref).startsWith("event:")) continue;
    await apiPost(`${libApiBase()}/relations`, {
      from_ref: base.ref, to_ref: target.ref,
      kind: link.type || "related", note: link.rel || "",
    });
  }
}

/* Q2 修复：真删后端（characters/entities/timeline）。此前 deleteEntry 仅清本地
   adds，refetch 后被删条目复活；后端 characters/entities 也无 DELETE 端点（405）。 */
async function LIB_deleteEntry(base) {
  if (!base || !base.id) return;
  try {
    if (base.cat === "people") {
      await apiDelete(`${libApiBase()}/characters/${base.id}`);
    } else if (base.cat === "events") {
      await apiDelete(`${libApiBase()}/timeline/${base.id}`);
    } else {
      await apiDelete(`${libApiBase()}/entities/${base.id}`);
    }
    libRefetch();
  } catch (e) {
    libToast(e, "删除资料失败。");
    libRefetch();
  }
}

/* merge a stored patch over a base entry */
function LIB_applyEdit(entry, edits) {
  const p = entry && edits ? edits[entry.id] : null;
  return p ? { ...entry, ...p } : entry;
}

/* ---- additions (用户新建条目) ---- */
function LIB_loadAdds() { return []; }

const libSentAdds = new Set();
const libSendingAdds = new Set();
async function LIB_persistAdds(adds) {
  let firstError = null;
  for (const add of adds || []) {
    if (!add || libSentAdds.has(add.id) || libSendingAdds.has(add.id)) continue;
    libSendingAdds.add(add.id);
    try {
      if (add.cat === "people") {
        await apiPost(`${libApiBase()}/characters`, {
          name: add.name, role: add.kind, summary: add.summary || "",
          details: { blurb: add.blurb, facts: add.facts, glyph: add.glyph },
        });
      } else if (add.cat === "events") {
        await apiPost(`${libApiBase()}/timeline`, {
          label: add.name, note: add.blurb || add.summary || "",
        });
      } else {
        await apiPost(`${libApiBase()}/entities`, {
          name: add.name, kind: "concept", summary: add.summary || "",
          tags: add.tags || [], details: { blurb: add.blurb, facts: add.facts, glyph: add.glyph, code: add.code },
        });
      }
      libSentAdds.add(add.id);
    } catch (e) {
      if (!firstError) firstError = e;
    } finally {
      libSendingAdds.delete(add.id);
    }
  }
  if (firstError) {
    libToast(firstError, "新建资料失败，可在网络恢复后重试。");
    libRefetch();
    return false;
  }
  libRefetch();
  return true;
}

/* 旧 localStorage 覆盖层（edits/additions）一次性上行；失败不写完成标记，下次重试。 */
let libMigrationPromise = null;
function LIB_migrateLegacy() {
  if (libMigrationPromise) return libMigrationPromise;
  libMigrationPromise = (async () => {
    try {
      const pid = libProjectId();
      if (!pid || pid === "__loading__") return false;
      const flag = LIB_K(LIB_MIGRATED_KEY);
      if (localStorage.getItem(flag)) return true;
      const edits = JSON.parse(localStorage.getItem(LIB_K(LIB_EDIT_KEY)) || "{}");
      const adds = JSON.parse(localStorage.getItem(LIB_K(LIB_ADD_KEY)) || "[]");
      const editsOk = !Object.keys(edits).length || await LIB_persist(edits);
      const addsOk = !Array.isArray(adds) || !adds.length || await LIB_persistAdds(adds);
      if (editsOk && addsOk) localStorage.setItem(flag, new Date().toISOString());
      return editsOk && addsOk;
    } catch (e) {
      libToast(e, "旧资料迁移失败，已保留本地数据供下次重试。");
      return false;
    }
  })().finally(() => { libMigrationPromise = null; });
  return libMigrationPromise;
}
/* 构造一个新档案的种子，cat = 类别 id，name = 名称 */
function LIB_newEntry(cat, name) {
  const meta = LIB_CATS.find(c => c.id === cat) || LIB_CATS[0];
  const glyph = (name || "新").trim().charAt(0) || "新";
  const id = "u-" + Date.now().toString(36) + "-" + Math.random().toString(36).slice(2, 6);
  return {
    id, cat, name: name || "未命名档案", code: meta.label + "·新",
    kind: meta.kind ? meta.kind.replace(/^./, "") : "条目",
    accent: meta.accent, glyph, updated: "现在", user: true,
    summary: "", blurb: "", tags: [], facts: [], links: [], appears: [],
    state: { tone: "crimson", label: "草稿" },
  };
}

/* ---- editable dossier form ---- */
function DossierEdit({ entry: e, allEntries, byId, onSave, onCancel, onReset, dirty }) {
  const [name, setName] = useEdSt(e.name);
  const [kind, setKind] = useEdSt(e.kind);
  const [summary, setSummary] = useEdSt(e.summary || "");
  const [blurb, setBlurb] = useEdSt(e.blurb || "");
  const [facts, setFacts] = useEdSt((e.facts || []).map(f => ({ ...f })));
  const [tags, setTags] = useEdSt([...(e.tags || [])]);
  const [tagInput, setTagInput] = useEdSt("");
  const [links, setLinks] = useEdSt((e.links || []).map(l => ({ ...l })));
  const [addId, setAddId] = useEdSt("");
  const [addType, setAddType] = useEdSt("kin");
  const ents = allEntries || [];
  const bid = byId || {};

  const setLinkRel = (i, rel) => setLinks(prev => prev.map((l, j) => j === i ? { ...l, rel } : l));
  const setLinkType = (i, type) => setLinks(prev => prev.map((l, j) => j === i ? { ...l, type } : l));
  const delLink = (i) => setLinks(prev => prev.filter((_, j) => j !== i));
  const addLink = () => {
    if (!addId || links.some(l => l.id === addId)) { setAddId(""); return; }
    const tDef = (LIB_REL_TYPES.find(t => t.id === addType)) || LIB_REL_TYPES[0];
    setLinks(prev => [...prev, { id: addId, rel: tDef.label, type: addType }]);
    setAddId("");
  };
  /* 可选关联：排除自身与已关联 */
  const linkOptions = ents.filter(x => x.id !== e.id && !links.some(l => l.id === x.id));
  const setFactK = (i, k) => setFacts(prev => prev.map((f, j) => j === i ? { ...f, k } : f));
  const setFactV = (i, v) => setFacts(prev => prev.map((f, j) => j === i ? { ...f, v } : f));
  const addFact = () => setFacts(prev => [...prev, { k: "字段", v: "" }]);
  const delFact = (i) => setFacts(prev => prev.filter((_, j) => j !== i));
  const addTag = () => {
    const t = tagInput.trim();
    if (t && !tags.includes(t)) setTags([...tags, t]);
    setTagInput("");
  };
  const save = () => onSave({ name, kind, summary, blurb, facts, tags, links });

  return (
    <div className={`acc-${e.accent} dform`}>
      <header className="dossier-head">
        <div className="dossier-glyph">{e.glyph}</div>
        <div className="dossier-head-main" style={{ display: "flex", flexDirection: "column", gap: 6 }}>
          <div className="dossier-code">{e.code} · 编辑中</div>
          <input className="dform-name" value={name} onChange={ev => setName(ev.target.value)} placeholder="名称" />
          <input className="dform-kind" value={kind} onChange={ev => setKind(ev.target.value)} placeholder="类型 / 角色" />
        </div>
      </header>

      <div className="dossier-body">
        <section className="dossier-section">
          <div className="dossier-h"><I.Quote size={13} /> 一句话摘要</div>
          <input className="dform-input" value={summary} onChange={ev => setSummary(ev.target.value)} placeholder="列表里显示的副标题" />
        </section>

        <section className="dossier-section">
          <div className="dossier-h"><I.FileText size={13} /> 简述</div>
          <textarea className="dform-area" value={blurb} onChange={ev => setBlurb(ev.target.value)} rows={4} placeholder="这份档案的描述…" />
        </section>

        <section className="dossier-section">
          <div className="dossier-h"><I.Info size={13} /> 关键信息</div>
          <div className="dform-facts">
            {facts.map((f, i) => (
              <div key={i} className="dform-fact dform-fact-edit">
                <input className="dform-fact-key" value={f.k} onChange={ev => setFactK(i, ev.target.value)} placeholder="字段名" />
                <div className="dform-fact-row">
                  <input value={f.v} onChange={ev => setFactV(i, ev.target.value)} placeholder="内容" />
                  <button className="dform-fact-del" onClick={() => delFact(i)} title="删除该项"><I.X size={12} /></button>
                </div>
              </div>
            ))}
          </div>
          <button className="dform-add" onClick={addFact}><I.Plus size={13} /> 添加一项</button>
        </section>

        <section className="dossier-section">
          <div className="dossier-h"><I.Tag size={13} /> 标签</div>
          <div className="dform-tags">
            {tags.map(t => (
              <span key={t} className="dform-tag">
                {t}
                <button onClick={() => setTags(tags.filter(x => x !== t))} title="移除"><I.X size={11} /></button>
              </span>
            ))}
            <input
              className="dform-tag-input"
              value={tagInput}
              onChange={ev => setTagInput(ev.target.value)}
              onKeyDown={ev => { if (ev.key === "Enter") { ev.preventDefault(); addTag(); } }}
              placeholder="加标签 ⏎"
            />
          </div>
        </section>

        <section className="dossier-section">
          <div className="dossier-h"><I.Compass size={13} /> 关联关系</div>
          <div className="dform-links">
            {links.map((l, i) => {
              const t = bid[l.id];
              const curType = l.type || LIB_relType(l).id;
              const tDef = LIB_REL_TYPES.find(x => x.id === curType) || LIB_REL_TYPES[0];
              return (
                <div key={l.id} className={`dform-link acc-${t ? t.accent : "ink"}`}>
                  <span className="dform-link-glyph">{t ? t.glyph : "?"}</span>
                  <span className="dform-link-name">{t ? t.name : l.id}</span>
                  <span className={`dform-link-typewrap acc-${tDef.accent}`}>
                    <span className="dform-link-typedot" />
                    <select
                      className="dform-link-type"
                      value={curType}
                      onChange={ev => setLinkType(i, ev.target.value)}
                      title="关系类型"
                    >
                      {LIB_REL_TYPES.map(rt => <option key={rt.id} value={rt.id}>{rt.label}</option>)}
                    </select>
                  </span>
                  <input
                    className="dform-link-rel"
                    value={l.rel}
                    onChange={ev => setLinkRel(i, ev.target.value)}
                    placeholder="关系标签，如「对立 · 主任」"
                  />
                  <button className="dform-link-del" onClick={() => delLink(i)} title="移除关联"><I.X size={12} /></button>
                </div>
              );
            })}
            {links.length === 0 && <div className="dform-link-empty">还没有关联。从下方添加，让它融入故事网络。</div>}
          </div>
          <div className="dform-link-add">
            <select className="dform-link-type-add" value={addType} onChange={ev => setAddType(ev.target.value)} title="关系类型">
              {LIB_REL_TYPES.map(rt => <option key={rt.id} value={rt.id}>{rt.label}</option>)}
            </select>
            <select className="dform-link-select" value={addId} onChange={ev => setAddId(ev.target.value)}>
              <option value="">选择要关联的档案…</option>
              {LIB_CATS.map(c => {
                const opts = linkOptions.filter(x => x.cat === c.id);
                if (!opts.length) return null;
                return (
                  <optgroup key={c.id} label={c.label}>
                    {opts.map(x => <option key={x.id} value={x.id}>{x.name}</option>)}
                  </optgroup>
                );
              })}
            </select>
            <button className="btn btn-ghost btn-sm" disabled={!addId} onClick={addLink}><I.Plus size={13} /> 添加关联</button>
          </div>
        </section>
      </div>

      <footer className="dossier-foot">
        <button className="btn btn-accent btn-sm" onClick={save}><I.Save size={13} /> 保存</button>
        <button className="btn btn-ghost btn-sm" onClick={onCancel}>取消</button>
        <span className="spacer" />
        {dirty && <button className="btn btn-quiet btn-sm" onClick={onReset}><I.Refresh size={13} /> 还原为初始</button>}
      </footer>
    </div>
  );
}

/* ---- 新建档案 · 轻量创建面板 ---- */
function DossierCreate({ onCreate, onCancel }) {
  const [cat, setCat] = useEdSt(LIB_CATS[0].id);
  const [name, setName] = useEdSt("");
  const meta = LIB_CATS.find(c => c.id === cat) || LIB_CATS[0];
  const ok = name.trim().length > 0;
  const submit = () => { if (ok) onCreate(cat, name.trim()); };

  return (
    <div className={`acc-${meta.accent} dcreate`}>
      <div className="dcreate-head">
        <div className="dcreate-icon"><I.Plus size={20} /></div>
        <div>
          <h2 className="dcreate-title">新建一份档案</h2>
          <p className="dcreate-sub">先选类别、起个名，建好后再补充细节。新建的档案会保存在本地。</p>
        </div>
      </div>

      <div className="dcreate-field">
        <div className="dcreate-label">归入类别</div>
        <div className="dcreate-cats">
          {LIB_CATS.map(c => (
            <button
              key={c.id}
              className={`dcreate-cat acc-${c.accent} ${cat === c.id ? "is-active" : ""}`}
              onClick={() => setCat(c.id)}
            >
              <span className="dcreate-cat-dot" />{c.label}
            </button>
          ))}
        </div>
      </div>

      <div className="dcreate-field">
        <div className="dcreate-label">名称</div>
        <input
          className="dform-input dcreate-name-input"
          value={name}
          autoFocus
          onChange={ev => setName(ev.target.value)}
          onKeyDown={ev => { if (ev.key === "Enter") submit(); }}
          placeholder={`例如「${meta.label === "人物" ? "新角色" : meta.label + "条目"}」…`}
        />
      </div>

      <div className="dcreate-preview">
        <span className={`dcreate-prev-glyph acc-${meta.accent}`}>{(name.trim().charAt(0)) || meta.label.charAt(0)}</span>
        <div className="dcreate-prev-main">
          <div className="dcreate-prev-name">{name.trim() || "未命名档案"}</div>
          <div className="dcreate-prev-kind">{meta.label} · 草稿</div>
        </div>
      </div>

      <div className="dcreate-foot">
        <button className="btn btn-accent btn-sm" disabled={!ok} onClick={submit}><I.Check size={13} /> 创建并编辑</button>
        <button className="btn btn-ghost btn-sm" onClick={onCancel}>取消</button>
      </div>
    </div>
  );
}

/* ---- 实时合并视图（写作器等模块共用） ----
   FE-ALIGN P6：LIB_ENTRIES 已按当前作品从后端装载，门控恒开
   （per-work 隔离由 API 保证）；LIB_live() 直接返回当前缓存，
   供正文实体高亮 / @提及等运行时消费，保证与资料库页面同源。 */
const LIB_seedOn = () => true;
function LIB_live() {
  const entries = (LIB_ENTRIES || []).slice();
  const byId = entries.reduce((m, e) => { m[e.id] = e; return m; }, {});
  return { entries, byId };
}

Object.assign(window, { LIB_loadEdits, LIB_persist, LIB_applyEdit, DossierEdit, DossierCreate, LIB_loadAdds, LIB_persistAdds, LIB_newEntry, LIB_seedOn, LIB_live });

/* ESM 导出（Phase 1 机械追加；window.* 赋值过渡期保留） */
export { LIB_loadEdits, LIB_persist, LIB_applyEdit, DossierEdit, DossierCreate, LIB_loadAdds, LIB_persistAdds, LIB_newEntry, LIB_seedOn, LIB_live, LIB_deleteEntry };
