import React from "react";
import { apiGet } from "./lib/client.js";

/* global React */
/* ==========================================================
   WsCost — 成本看板（Wave 6，结果闭环治理 §5.8/§10）
   数据源：GET /api/v2/projects/{id}/cost-summary（?scene_id / ?chapter_id 下钻）
   只读：把 LlmCall token 经价格快照折算成费用，解释——
     · 总成本 + 币种（跨 provider 以费用为准）
     · 各阶段占比（候选生成 / QC / 修订 / 评审）
     · 是否超预算（5× 单发基线使用率）
     · 评审是否独立（correlated_judge）
   ========================================================== */

let csState = {
  projectId: null,
  level: "project",   // project | chapter | scene
  summary: null,
  loading: false,
  error: null,
};

function csSnapshot() { return csState; }
function csEmit() { try { window.dispatchEvent(new CustomEvent("ws:cost-changed")); } catch (e) {} }

const PHASE_LABEL = {
  candidate_generation: "候选生成",
  quality_check: "质检 QC",
  revision: "修订",
  review: "评审",
  other: "其他",
};

async function costLoad(projectId, opts = {}) {
  if (!projectId) return null;
  const level = opts.sceneId ? "scene" : opts.chapterId ? "chapter" : "project";
  csState = { ...csState, projectId, level, loading: true, error: null };
  csEmit();
  try {
    let path = `/api/v2/projects/${encodeURIComponent(projectId)}/cost-summary`;
    if (opts.sceneId) path += `?scene_id=${encodeURIComponent(opts.sceneId)}`;
    else if (opts.chapterId) path += `?chapter_id=${encodeURIComponent(opts.chapterId)}`;
    const data = await apiGet(path);
    csState = {
      ...csState,
      level: (data && data.level) || level,
      summary: (data && data.summary) || null,
      loading: false,
    };
    csEmit();
    return data;
  } catch (e) {
    csState = { ...csState, loading: false, error: (e && e.message) || "成本加载失败。" };
    csEmit();
    return null;
  }
}

function useCostState() {
  const [, force] = React.useReducer((x) => x + 1, 0);
  React.useEffect(() => {
    const h = () => force();
    window.addEventListener("ws:cost-changed", h);
    return () => window.removeEventListener("ws:cost-changed", h);
  }, []);
  return csSnapshot();
}

function fmtCost(v, cur) {
  if (v == null) return "—";
  return `${Number(v).toFixed(4)} ${cur || "USD"}`;
}

function PhaseBar({ breakdown }) {
  if (!breakdown) return null;
  const rows = Object.keys(PHASE_LABEL)
    .map((k) => ({ k, ...(breakdown[k] || { cost: 0, share: 0 }) }))
    .filter((r) => (r.share || 0) > 0);
  if (!rows.length) return <div style={{ opacity: 0.6 }}>暂无阶段成本。</div>;
  return (
    <div>
      {rows.map((r) => (
        <div key={r.k} style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 4 }}>
          <span style={{ width: 88 }}>{PHASE_LABEL[r.k]}</span>
          <div style={{ flex: 1, background: "#eee", height: 10, borderRadius: 4 }}>
            <div style={{ width: `${Math.round((r.share || 0) * 100)}%`, height: 10, background: "#7a8", borderRadius: 4 }} />
          </div>
          <span style={{ width: 48, textAlign: "right" }}>{Math.round((r.share || 0) * 100)}%</span>
        </div>
      ))}
    </div>
  );
}

function WsCost() {
  const st = useCostState();
  const [pid, setPid] = React.useState(st.projectId || "");
  const s = st.summary;
  const ji = s && s.judge_independence;
  const budget = s && s.budget;

  return (
    <div className="ws-cost" style={{ padding: 16, maxWidth: 960, margin: "0 auto" }}>
      <h2>成本看板 · token 与费用</h2>
      <p style={{ opacity: 0.7 }}>
        每一次候选、重试、批判、补丁与 QC 都计入同一场景预算。价格为占位估算（is_estimate），
        运维接入真实计费后可替换 <code>config/pricing.yaml</code> 单价。
      </p>
      <div style={{ display: "flex", gap: 8, marginBottom: 12 }}>
        <input value={pid} onChange={(e) => setPid(e.target.value)} placeholder="项目 ID"
               style={{ flex: 1, padding: 6 }} />
        <button onClick={() => costLoad(pid.trim())} disabled={!pid.trim()}>查项目成本</button>
      </div>

      {st.error && <div style={{ color: "crimson" }}>{st.error}</div>}
      {st.loading && <div style={{ opacity: 0.6 }}>加载中…</div>}

      {s && (
        <section style={{ borderTop: "1px solid #ddd", paddingTop: 12 }}>
          <h3>{st.level === "scene" ? "场景" : st.level === "chapter" ? "章节" : "全书"}成本
            {s.is_estimate && <span style={{ fontSize: 12, opacity: 0.6 }}> · 估算</span>}</h3>
          <div style={{ display: "flex", gap: 24, flexWrap: "wrap", marginBottom: 12 }}>
            <div><b>总成本</b>：{fmtCost(s.total_cost, s.currency)}</div>
            <div><b>调用数</b>：{s.call_count != null ? s.call_count : "—"}</div>
            {s.cross_provider && <div style={{ color: "#a60" }}>跨 provider · token 不可直接相加（以费用汇总）</div>}
          </div>

          <h4>各阶段占比</h4>
          <PhaseBar breakdown={s.phase_breakdown} />

          {budget && budget.budget != null && (
            <p style={{ marginTop: 12 }}>
              <b>预算</b>：已用 {budget.used} / {budget.budget}（5× 单发基线）·
              使用率 {budget.usage_ratio != null ? Math.round(budget.usage_ratio * 100) : "—"}%
              {budget.over_budget && <span style={{ color: "crimson" }}> · 已超预算</span>}
            </p>
          )}

          {s.extra_cost && (
            <p style={{ opacity: 0.85 }}>
              额外成本：失败重试 {fmtCost(s.extra_cost.failed_call_cost, s.currency)} ·
              重复 QC {fmtCost(s.extra_cost.repeat_qc_cost, s.currency)} ·
              低分散补候选 {fmtCost(s.extra_cost.low_dispersion_topup_cost, s.currency)}
              （占比 {Math.round((s.extra_cost.retry_cost_ratio || 0) * 100)}%）
            </p>
          )}

          {ji && (
            <p style={{ marginTop: 8 }}>
              <b>评审独立性</b>：
              {ji.correlated_judge
                ? <span style={{ color: "#a60" }}> 同源（correlated_judge）· 咨询意见降权</span>
                : <span style={{ color: "#360" }}> 独立</span>}
              {ji.reason ? ` — ${ji.reason}` : ""}
            </p>
          )}
        </section>
      )}
    </div>
  );
}

Object.assign(window, { WsCost, costLoad, csSnapshot });
export { WsCost, costLoad, csSnapshot, useCostState };
