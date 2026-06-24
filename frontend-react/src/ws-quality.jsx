import React from "react";
import { apiGet, apiPost } from "./lib/client.js";
import { WsDemoTag } from "./ws-catalog.jsx";

/* global React, I, WsDemoTag */
/* ==========================================================
   WsQuality — 文学质量巡检 · 案头
   React 主线入口，对接后端 21 维「质量地板」引擎：
     GET  /api/v1/literary-quality/overview      全库巡检
     POST /api/v1/literary-quality/analyze-text  临时文本即时扫描
   引擎为纯规则/词表打分（关键词命中 + 指纹），与是否启用真
   LLM 无关——巡检/扫描随时可用；只有「基准评测 live」才需模型。
   ========================================================== */

/* 21 维中文标签（含蓝图 v2 新增三维：感知过滤 / 自我重复 / 冲突过净） */
const QUALITY_DIMS = {
  model_voice: "模型腔",
  image_homogeneity: "意象同质",
  repetitive_action: "动作重复",
  expository_dialogue: "说明式对白",
  no_choice_scene: "无抉择场景",
  summary_ending: "概述式收尾",
  choice_pressure: "抉择压力",
  ending_drive: "收束驱动",
  template_action_reuse: "模板动作复用",
  image_field_reuse: "意象场复用",
  syntax_monotony: "句式单调",
  false_clarity: "虚假清晰",
  valid_ambiguity: "有效留白",
  painless_scene: "无痛场景",
  decorative_imagery: "装饰性意象",
  dialogue_as_report: "对白即汇报",
  over_explained_motive: "过度解释动机",
  false_poetic_closure: "伪诗意收束",
  perception_filter: "感知过滤",
  self_repetition: "自我重复",
  conflict_too_clean: "冲突过净",
};
const QUALITY_DIM_KEYS = Object.keys(QUALITY_DIMS);
const qDimLabel = (k) => QUALITY_DIMS[k] || k;

/* severity 中文 + 色调（复用既有 pill 色板） */
const QUALITY_SEV = {
  blocking: { label: "阻断", tone: "crimson" },
  revision: { label: "修订", tone: "rose" },
  taste: { label: "审美", tone: "gold" },
  info: { label: "信息", tone: "slate" },
};
const qSevLabel = (s) => (QUALITY_SEV[s] ? QUALITY_SEV[s].label : s || "");
const qSevTone = (s) => (QUALITY_SEV[s] ? QUALITY_SEV[s].tone : "slate");

/* text_layer 下拉（对齐 Vue 视图选用的 4 个；后端另支持 runtime） */
const QUALITY_TEXT_LAYERS = [
  { v: "author_draft_preferred", l: "作者稿优先" },
  { v: "runtime_final_scene", l: "运行末场" },
  { v: "chapter_memory_final", l: "章记忆终稿" },
  { v: "chapter_assembled", l: "整章拼装" },
];
const QUALITY_MIN_SEVERITIES = ["blocking", "revision", "taste", "info"];

/* ==========================================================
   store —— 轻量模块级缓存 + 自定义事件（对齐 ws-review 范式）。
   不依赖 active project（三个端点都不收 project_id），故无
   __loading__ 等待逻辑；视图挂载时拉取，失败设 error 而非崩溃。
   ========================================================== */
let qState = { overview: null, analyze: null, review: null, loading: false, analyzing: false, reviewing: false, error: null };

function qSnapshot() { return qState; }
function qEmit() { try { window.dispatchEvent(new CustomEvent("ws:quality-changed")); } catch (e) {} }

/* 自建查询串：只 import apiGet/apiPost，避免单测 mock 掉 buildQueryPath */
function qBuildPath(base, filters) {
  const p = new URLSearchParams();
  Object.entries(filters || {}).forEach(([k, v]) => {
    if (v === null || v === undefined || v === "") return;
    p.set(k, v);
  });
  const q = p.toString();
  return q ? `${base}?${q}` : base;
}

async function qLoadOverview(filters = {}) {
  qState = { ...qState, loading: true, error: null };
  qEmit();
  try {
    const data = await apiGet(qBuildPath("/api/v1/literary-quality/overview", filters));
    qState = { ...qState, overview: data || null, loading: false };
    qEmit();
    return data;
  } catch (e) {
    qState = { ...qState, loading: false, error: (e && e.message) || "巡检失败。" };
    qEmit();
    return null;
  }
}

async function qAnalyzeText(content) {
  const text = (content || "").trim();
  if (!text) return null;
  qState = { ...qState, analyzing: true, error: null };
  qEmit();
  try {
    const data = await apiPost("/api/v1/literary-quality/analyze-text", { content: text });
    qState = { ...qState, analyze: data || null, analyzing: false };
    qEmit();
    return data;
  } catch (e) {
    qState = { ...qState, analyzing: false, error: (e && e.message) || "扫描失败。" };
    qEmit();
    try { window.alert(qState.error); } catch (e2) {}
    return null;
  }
}

async function qChapterSetReview({ chapter_ids, protected_terms, text_layer } = {}) {
  const ids = (chapter_ids || []).filter(Boolean);
  if (!ids.length) return null;
  qState = { ...qState, reviewing: true, error: null };
  qEmit();
  try {
    const data = await apiPost("/api/v1/literary-quality/chapter-set-review", {
      chapter_ids: ids,
      protected_terms: (protected_terms || []).filter(Boolean),
      text_layer: text_layer || "author_draft_preferred",
    });
    qState = { ...qState, review: data || null, reviewing: false };
    qEmit();
    return data;
  } catch (e) {
    qState = { ...qState, reviewing: false, error: (e && e.message) || "章组复审失败。" };
    qEmit();
    try { window.alert(qState.error); } catch (e2) {}
    return null;
  }
}

function useQualityState() {
  const [, force] = React.useState(0);
  React.useEffect(() => {
    const bump = () => force((n) => n + 1);
    window.addEventListener("ws:quality-changed", bump);
    return () => window.removeEventListener("ws:quality-changed", bump);
  }, []);
  return qSnapshot();
}

/* ---- helpers ---- */
const qPct = (v) => (v === null || v === undefined || Number.isNaN(v) ? "—" : Math.round(v * 100));
function qRiskDims(item) {
  const sig = (item && item.signals) || {};
  return Object.keys(sig).filter((k) => sig[k] && sig[k].risk);
}

/* ==========================================================
   view
   ========================================================== */
function WsQuality({ go }) {
  const st = useQualityState();
  const [tab, setTab] = React.useState("overview");
  const [filters, setFilters] = React.useState({ text_layer: "author_draft_preferred", chapter_id: "", risk_type: "", min_severity: "" });
  const [draft, setDraft] = React.useState("");

  // 初次进入巡检一轮
  React.useEffect(() => { qLoadOverview(filters); /* eslint-disable-next-line */ }, []);

  const reload = () => qLoadOverview(filters);
  const setF = (k, v) => setFilters((f) => ({ ...f, [k]: v }));

  const ov = st.overview || {};
  const summary = ov.summary || {};
  const items = ov.items || [];
  const analyze = st.analyze;

  const summaryCards = [
    { k: "object_count", label: "巡检对象", v: summary.object_count ?? 0 },
    { k: "mean_score", label: "平均分", v: summary.mean_score == null ? "—" : qPct(summary.mean_score) },
    { k: "high_risk_count", label: "高风险项", v: summary.high_risk_count ?? 0 },
    { k: "model_voice_count", label: "模型腔", v: summary.model_voice_count ?? 0 },
    { k: "risk_cluster_count", label: "风险簇", v: summary.risk_cluster_count ?? 0 },
    { k: "cross_scene_reuse_count", label: "跨场复用", v: summary.cross_scene_reuse_count ?? 0 },
  ];

  return (
    <div className="ws-page ws-view q-quality" data-screen-label="quality">
      <header className="rv-head">
        <div className="rv-eyebrow" style={{ display: "flex", alignItems: "center", gap: 8 }}>
          {I && I.Microscope && <I.Microscope size={13} />} 案头 · 质量地板
          <WsDemoTag note="基准评测的 live 模式需启用 LLM（系统设置→模型与接入）；巡检 / 临时扫描为纯规则引擎，随时可用。" />
        </div>
        <h1 className="rv-title">文学质量</h1>
        <p className="rv-sub">用 21 维「质量地板」引擎巡检全库稿件，或即时扫描一段临时文本，找出模型腔、意象同质、无抉择场景等反 AI 味风险。</p>
      </header>

      <div className="rv-toolbar" style={{ gap: 6, marginBottom: 4 }}>
        <button className={`btn btn-sm ${tab === "overview" ? "btn-accent" : "btn-ghost"}`} onClick={() => setTab("overview")}>稿件巡检</button>
        <button className={`btn btn-sm ${tab === "review" ? "btn-accent" : "btn-ghost"}`} onClick={() => setTab("review")}>章组复审</button>
      </div>

      {tab === "overview" && (<>
      {/* 过滤器 */}
      <div className="rv-toolbar" style={{ flexWrap: "wrap", gap: 10 }}>
        <label style={{ display: "inline-flex", alignItems: "center", gap: 6 }}>
          <span className="text-xs" style={{ color: "var(--ink-3)" }}>文本层</span>
          <select className="ws-nw-input" style={{ width: "auto", padding: "4px 8px" }}
            value={filters.text_layer} onChange={(e) => setF("text_layer", e.target.value)}>
            {QUALITY_TEXT_LAYERS.map((o) => <option key={o.v} value={o.v}>{o.l}</option>)}
          </select>
        </label>
        <label style={{ display: "inline-flex", alignItems: "center", gap: 6 }}>
          <span className="text-xs" style={{ color: "var(--ink-3)" }}>章</span>
          <input className="ws-nw-input" style={{ width: 120, padding: "4px 8px" }} placeholder="chapter_id"
            value={filters.chapter_id} onChange={(e) => setF("chapter_id", e.target.value)} />
        </label>
        <label style={{ display: "inline-flex", alignItems: "center", gap: 6 }}>
          <span className="text-xs" style={{ color: "var(--ink-3)" }}>风险维度</span>
          <select className="ws-nw-input" style={{ width: "auto", padding: "4px 8px" }}
            value={filters.risk_type} onChange={(e) => setF("risk_type", e.target.value)}>
            <option value="">全部</option>
            {QUALITY_DIM_KEYS.map((k) => <option key={k} value={k}>{qDimLabel(k)}</option>)}
          </select>
        </label>
        <label style={{ display: "inline-flex", alignItems: "center", gap: 6 }}>
          <span className="text-xs" style={{ color: "var(--ink-3)" }}>最低级别</span>
          <select className="ws-nw-input" style={{ width: "auto", padding: "4px 8px" }}
            value={filters.min_severity} onChange={(e) => setF("min_severity", e.target.value)}>
            <option value="">全部</option>
            {QUALITY_MIN_SEVERITIES.map((s) => <option key={s} value={s}>{qSevLabel(s)}</option>)}
          </select>
        </label>
        <button className="btn btn-accent btn-sm" onClick={reload} disabled={st.loading}>
          {I && I.Refresh && <I.Refresh size={13} />} {st.loading ? "巡检中…" : "重新巡检"}
        </button>
      </div>

      {st.error && (
        <div className="rv-none" style={{ color: "var(--crimson, #b00)" }}>巡检/扫描出错：{st.error}</div>
      )}

      {/* summary 卡 */}
      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(120px, 1fr))", gap: 10, margin: "12px 0" }}>
        {summaryCards.map((c) => (
          <div key={c.k} className="card" style={{ padding: "10px 12px", borderRadius: 12, border: "1px solid var(--line, #e5e2dc)" }}>
            <div className="text-xs" style={{ color: "var(--ink-3)" }}>{c.label}</div>
            <div className="text-serif" style={{ fontSize: 22, lineHeight: 1.2 }}>{c.v}</div>
          </div>
        ))}
      </div>

      {/* items */}
      {items.length === 0 ? (
        <div className="rv-none">
          {st.loading ? "正在巡检…" : "暂无可巡检稿件——先到「构思」或「章节编排」生成内容，再回来巡检。"}
        </div>
      ) : (
        <div className="rv-list">
          {items.map((it, i) => <QualityItem key={(it.object_id || "it") + ":" + i} item={it} go={go} />)}
        </div>
      )}

      {/* 临时文本扫描 */}
      <section style={{ marginTop: 22 }}>
        <h2 className="text-serif" style={{ fontSize: 16, margin: "0 0 8px" }}>临时文本扫描</h2>
        <p className="rv-sub" style={{ marginTop: 0 }}>粘贴一段文字即时打分，不写入任何稿件。</p>
        <textarea className="ws-nw-input ws-nw-area" rows={5} style={{ width: "100%" }}
          placeholder="把要体检的段落贴进来…" value={draft} onChange={(e) => setDraft(e.target.value)} />
        <div style={{ marginTop: 8 }}>
          <button className="btn btn-accent btn-sm" disabled={!draft.trim() || st.analyzing}
            onClick={() => qAnalyzeText(draft)}>
            {I && I.Activity && <I.Activity size={13} />} {st.analyzing ? "扫描中…" : "扫描这段文字"}
          </button>
        </div>
        {analyze && <AnalyzeResult data={analyze} />}
      </section>
      </>)}

      {tab === "review" && <QualityChapterSet go={go} />}
    </div>
  );
}

function QualityItem({ item, go }) {
  const [open, setOpen] = React.useState(false);
  const riskDims = qRiskDims(item);
  const findings = item.findings || [];
  const rna = item.recommended_next_action || {};
  return (
    <article className="rv-item" style={{ padding: "12px 14px" }}>
      <button className="rv-row" onClick={() => setOpen((o) => !o)} aria-expanded={open} style={{ width: "100%" }}>
        <div className="rv-row-main">
          <div className="rv-meta" style={{ gap: 8, flexWrap: "wrap" }}>
            <span className="pill pill-slate text-xs"><span className="pill-dot" />{item.object_type === "chapter" ? "章" : "场"} {item.object_id}</span>
            {riskDims.slice(0, 6).map((k) => (
              <span key={k} className="pill pill-rose text-xs"><span className="pill-dot" />{qDimLabel(k)}</span>
            ))}
            {riskDims.length > 6 && <span className="text-xs" style={{ color: "var(--ink-3)" }}>+{riskDims.length - 6}</span>}
          </div>
          <h3 className="rv-item-title">{item.source_ref || item.object_id} · 第 {qPct(item.score)} 分</h3>
        </div>
        <span className="rv-chev" data-open={open}>{I && I.ChevronDown && <I.ChevronDown size={16} />}</span>
      </button>
      {open && (
        <div className="rv-detail-inner" style={{ paddingTop: 8 }}>
          {findings.length === 0 ? (
            <p className="rv-detail-text">该对象未触发风险维度。</p>
          ) : (
            <ul style={{ listStyle: "none", margin: 0, padding: 0, display: "grid", gap: 8 }}>
              {findings.map((f, i) => (
                <li key={i} style={{ borderLeft: "3px solid var(--line, #e5e2dc)", paddingLeft: 10 }}>
                  <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                    <span className={`pill pill-${qSevTone(f.severity)} text-xs`}><span className="pill-dot" />{qSevLabel(f.severity)}</span>
                    <strong>{qDimLabel(f.dimension)}</strong>
                  </div>
                  {f.issue && <div className="rv-detail-text" style={{ margin: "4px 0" }}>{f.issue}</div>}
                  {f.evidence_excerpt && <div className="text-xs" style={{ color: "var(--ink-3)", fontStyle: "italic" }}>「{f.evidence_excerpt}」</div>}
                  {f.recommendation && <div className="text-xs" style={{ color: "var(--ink-2)" }}>建议：{f.recommendation}</div>}
                </li>
              ))}
            </ul>
          )}
          {rna.action === "open_deepdesk_patch" && (
            <div style={{ marginTop: 10 }}>
              <button className="btn btn-ghost btn-sm" onClick={() => go && go("writer")}>
                {I && I.ArrowRight && <I.ArrowRight size={13} />} 去深改台处理
              </button>
            </div>
          )}
        </div>
      )}
    </article>
  );
}

function AnalyzeResult({ data }) {
  const spans = data.span_findings || [];
  const riskDims = qRiskDims(data);
  return (
    <div className="card" style={{ marginTop: 12, padding: "12px 14px", borderRadius: 12, border: "1px solid var(--line, #e5e2dc)" }}>
      <div style={{ display: "flex", alignItems: "center", gap: 10, flexWrap: "wrap" }}>
        <span className="pill pill-slate text-xs"><span className="pill-dot" />总分 {qPct(data.score)}</span>
        {riskDims.map((k) => <span key={k} className="pill pill-rose text-xs"><span className="pill-dot" />{qDimLabel(k)}</span>)}
        {riskDims.length === 0 && <span className="text-xs" style={{ color: "var(--ink-3)" }}>未触发风险维度。</span>}
      </div>
      {spans.length > 0 && (
        <ul style={{ listStyle: "none", margin: "10px 0 0", padding: 0, display: "grid", gap: 8 }}>
          {spans.map((s, i) => (
            <li key={i} style={{ borderLeft: "3px solid var(--line, #e5e2dc)", paddingLeft: 10 }}>
              <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                <span className={`pill pill-${qSevTone(s.severity)} text-xs`}><span className="pill-dot" />{qSevLabel(s.severity)}</span>
                <strong>{qDimLabel(s.dimension)}</strong>
              </div>
              {s.evidence && <div className="text-xs" style={{ color: "var(--ink-3)", fontStyle: "italic" }}>「{s.evidence}」</div>}
              {s.issue && <div className="text-xs" style={{ color: "var(--ink-2)" }}>{s.issue}</div>}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

function QualityChapterSet({ go }) {
  const st = useQualityState();
  const [sel, setSel] = React.useState(() => new Set());
  const [terms, setTerms] = React.useState("");
  const [layer, setLayer] = React.useState("author_draft_preferred");

  // 章 id 取自已加载的全库巡检（后端已返回的合法 ChapterGoal id，零额外耦合）
  const chapterIds = React.useMemo(() => {
    const ov = st.overview || {};
    const ids = [];
    (ov.items || []).forEach((it) => { if (it.chapter_id && !ids.includes(it.chapter_id)) ids.push(it.chapter_id); });
    return ids;
  }, [st.overview]);

  const toggle = (id) => setSel((s) => { const n = new Set(s); if (n.has(id)) n.delete(id); else n.add(id); return n; });
  const run = () => qChapterSetReview({
    chapter_ids: [...sel],
    protected_terms: terms.split(/[,，\s]+/).map((t) => t.trim()).filter(Boolean),
    text_layer: layer,
  });

  const rv = st.review;
  const sm = (rv && rv.summary) || {};
  const scores = (rv && rv.scores) || {};
  const chapters = (rv && rv.chapters) || [];
  const scenes = (rv && rv.scenes) || [];
  const repeated = (rv && rv.repeated_patterns) || [];
  const safety = (rv && rv.reference_safety_findings) || [];

  return (
    <div>
      <p className="rv-sub">跨章复审：选若干章一起体检，捕捉跨章重复模式、回收/铺垫缺口与受保护词命中。章 id 取自「稿件巡检」结果——若为空，先去巡检一轮。</p>
      {chapterIds.length === 0 ? (
        <div className="rv-none">还没有可选章节——先到「稿件巡检」tab 跑一轮巡检以载入章节，或先生成内容。</div>
      ) : (
        <div className="card" style={{ padding: "10px 12px", borderRadius: 12, border: "1px solid var(--line, #e5e2dc)", display: "grid", gap: 10 }}>
          <div style={{ display: "flex", flexWrap: "wrap", gap: 8 }}>
            {chapterIds.map((id) => (
              <label key={id} className={`pill text-xs ${sel.has(id) ? "pill-rose" : "pill-slate"}`} style={{ cursor: "pointer" }}>
                <input type="checkbox" checked={sel.has(id)} onChange={() => toggle(id)} style={{ marginRight: 4 }} />{id}
              </label>
            ))}
          </div>
          <div style={{ display: "flex", flexWrap: "wrap", gap: 8, alignItems: "center" }}>
            <input className="ws-nw-input" style={{ width: 220, padding: "4px 8px" }} placeholder="受保护词（逗号分隔，可空）"
              value={terms} onChange={(e) => setTerms(e.target.value)} />
            <select className="ws-nw-input" style={{ width: "auto", padding: "4px 8px" }} value={layer} onChange={(e) => setLayer(e.target.value)}>
              {QUALITY_TEXT_LAYERS.map((o) => <option key={o.v} value={o.v}>{o.l}</option>)}
            </select>
            <button className="btn btn-accent btn-sm" disabled={sel.size === 0 || st.reviewing} onClick={run}>
              {I && I.ShieldCheck && <I.ShieldCheck size={13} />} {st.reviewing ? "复审中…" : `复审选中的 ${sel.size} 章`}
            </button>
          </div>
        </div>
      )}

      {rv && (
        <div style={{ marginTop: 14 }}>
          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(120px, 1fr))", gap: 10 }}>
            {[
              { label: "复审章数", v: sm.chapter_count ?? 0 },
              { label: "场景数", v: sm.scene_count ?? 0 },
              { label: "平均分", v: sm.mean_score == null ? "—" : qPct(sm.mean_score) },
              { label: "高风险项", v: sm.high_risk_count ?? 0 },
              { label: "重复模式", v: sm.repeated_pattern_count ?? 0 },
              { label: "受保护词命中", v: sm.reference_safety_finding_count ?? 0 },
            ].map((c, i) => (
              <div key={i} className="card" style={{ padding: "10px 12px", borderRadius: 12, border: "1px solid var(--line, #e5e2dc)" }}>
                <div className="text-xs" style={{ color: "var(--ink-3)" }}>{c.label}</div>
                <div className="text-serif" style={{ fontSize: 22, lineHeight: 1.2 }}>{c.v}</div>
              </div>
            ))}
          </div>
          <div className="rv-meta" style={{ gap: 8, flexWrap: "wrap", margin: "10px 0" }}>
            <span className="pill pill-slate text-xs"><span className="pill-dot" />文学质量 {qPct(scores.literary_quality)}</span>
            <span className="pill pill-slate text-xs"><span className="pill-dot" />跨章弧光 {qPct(scores.cross_chapter_arc)}</span>
            <span className="pill pill-slate text-xs"><span className="pill-dot" />参考安全 {qPct(scores.reference_safety)}</span>
          </div>
          {repeated.length > 0 && (
            <div style={{ margin: "8px 0" }}>
              <h3 className="text-serif" style={{ fontSize: 15, margin: "0 0 6px" }}>跨章重复模式（{repeated.length}）</h3>
              <ul style={{ listStyle: "none", margin: 0, padding: 0, display: "grid", gap: 6 }}>
                {repeated.slice(0, 12).map((r, i) => (
                  <li key={i} className="text-xs" style={{ color: "var(--ink-2)", borderLeft: "3px solid var(--line, #e5e2dc)", paddingLeft: 10 }}>
                    {(r.cluster_type || "重复")} · 「{r.token}」× {r.count}（{(r.chapter_ids || []).join("/")}）
                  </li>
                ))}
              </ul>
            </div>
          )}
          {safety.length > 0 && (
            <div style={{ margin: "8px 0" }}>
              <h3 className="text-serif" style={{ fontSize: 15, margin: "0 0 6px", color: "var(--crimson, #b00)" }}>受保护词命中（{safety.length}）</h3>
              <ul style={{ listStyle: "none", margin: 0, padding: 0, display: "grid", gap: 6 }}>
                {safety.slice(0, 12).map((f, i) => (
                  <li key={i} className="text-xs" style={{ color: "var(--ink-2)", borderLeft: "3px solid var(--crimson, #b00)", paddingLeft: 10 }}>
                    {f.term ? `「${f.term}」` : ""}{f.evidence_excerpt || f.issue || ""}
                  </li>
                ))}
              </ul>
            </div>
          )}
          {(chapters.length > 0 || scenes.length > 0) && (
            <div className="rv-list" style={{ marginTop: 8 }}>
              {[...chapters, ...scenes].map((it, i) => <QualityItem key={(it.object_id || "it") + ":" + i} item={it} go={go} />)}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

Object.assign(window, { WsQuality, qLoadOverview, qAnalyzeText, qChapterSetReview, qSnapshot, QUALITY_DIMS, QUALITY_SEV });

/* ESM 导出（与既有视图一致：window.* 赋值过渡期保留） */
export { WsQuality, qLoadOverview, qAnalyzeText, qChapterSetReview, qSnapshot, useQualityState, QUALITY_DIMS, QUALITY_DIM_KEYS, QUALITY_SEV, QUALITY_TEXT_LAYERS };
