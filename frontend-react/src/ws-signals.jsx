// §0 编排信号面板 — surface orchestration-layer decisions at the right resolution.
// Reads /api/v1/scenes/{id}/orchestration-signals and renders a compact, read-only
// panel: Best-of-N dispersion (§6), scene criticality (§6), foreshadow debt (§5),
// theme expression budget (§12), active style-drift correction (§9).
//
// Fully defensive: renders nothing when there is no scene, the fetch fails, or the
// backend reports the scene has no run state yet (available:false). This keeps the
// prototype views and smoke tests unaffected when no real backend data exists.
import React from "react";
import { I } from "./icons.jsx";
import { apiGet } from "./lib/client.js";

const CRITICALITY_TONE = { critical: "crimson", standard: "gold", transition: "slate" };
const CRITICALITY_LABEL = { critical: "关键场景", standard: "标准场景", transition: "过渡场景" };

export function OrchestrationSignals({ sceneId }) {
  const [data, setData] = React.useState(null);

  React.useEffect(() => {
    let alive = true;
    if (!sceneId) { setData(null); return undefined; }
    apiGet(`/api/v1/scenes/${encodeURIComponent(sceneId)}/orchestration-signals`)
      .then((d) => { if (alive) setData(d && d.available ? d : null); })
      .catch(() => { if (alive) setData(null); });
    return () => { alive = false; };
  }, [sceneId]);

  if (!data) return null;

  const disp = data.dispersion || {};
  const crit = data.criticality;
  const fs = data.foreshadow_health;
  const budget = Array.isArray(data.theme_budget) ? data.theme_budget : [];
  const drift = data.style_drift;
  /* Wave 3（治理 §5.5/§5.8）：场景 token 预算——5× 上限使用率 */
  const tok = data.token_budget && data.token_budget.budget != null ? data.token_budget : null;
  const tokRatio = tok ? Math.min(1, (tok.used || 0) / Math.max(1, tok.budget)) : 0;
  /* Wave 6（治理 §5.8/§5.7）：场景成本 + 裁判独立性 */
  const cost = data.cost && data.cost.total_cost != null ? data.cost : null;
  const ji = data.judge_independence || null;
  const degraded = Array.isArray(data.degraded_signals) ? data.degraded_signals : [];

  const hasAny = (
    disp.score != null || crit ||
    (fs && fs.total_open > 0) || budget.length > 0 ||
    (drift && drift.active) || tok || cost || ji || degraded.length > 0
  );
  if (!hasAny) return null;

  return (
    <div className="ws-sig">
      <div className="ws-sig-head"><I.Activity size={13} /> 编排信号</div>
      <div className="ws-sig-row">
        {crit && (
          <span className={`ws-sig-chip tone-${CRITICALITY_TONE[crit.level] || "slate"}`}
                title={(crit.reasons || []).join(" · ")}>
            {CRITICALITY_LABEL[crit.level] || crit.level}
          </span>
        )}
        {disp.score != null && (
          <span className={`ws-sig-chip ${disp.signal === "low" ? "tone-rose" : "tone-sage"}`}
                title="Best-of-N 候选分散度：过低说明采样没探到分布尾巴，再选也难有惊喜">
            候选分散度 {Number(disp.score).toFixed(2)}
            {disp.signal === "low" ? " · 偏低" : " · 正常"}
          </span>
        )}
        {tok && (
          <span className={`ws-sig-chip ${tokRatio >= 1 ? "tone-crimson" : tokRatio >= 0.8 ? "tone-rose" : "tone-slate"}`}
                title={`场景 token 预算（5× 单发基线）：已用 ${tok.used} / ${tok.budget}${tok.run_policy ? ` · 策略 ${tok.run_policy}` : ""}——耗尽后停止新调用，返回已有最佳稿`}>
            预算 {Math.round(tokRatio * 100)}%
            {tokRatio >= 1 ? " · 已耗尽" : ""}
          </span>
        )}
        {cost && (
          <span className={`ws-sig-chip ${cost.over_budget ? "tone-crimson" : "tone-slate"}`}
                title={`本场累计成本（${cost.is_estimate ? "估算" : "计费"}${cost.cross_provider ? " · 跨 provider 以费用汇总" : ""}）——${
                  Object.entries(cost.phase_breakdown || {})
                    .filter(([, v]) => (v.share || 0) > 0)
                    .map(([k, v]) => `${k} ${Math.round((v.share || 0) * 100)}%`).join(" · ")}`}>
            成本 {Number(cost.total_cost).toFixed(3)} {cost.currency || "USD"}
            {cost.over_budget ? " · 超预算" : ""}
          </span>
        )}
        {ji && (
          <span className={`ws-sig-chip ${ji.correlated_judge ? "tone-rose" : "tone-sage"}`}
                title={ji.reason || (ji.correlated_judge ? "评审与写作同源——咨询意见降权" : "评审与写作异源——独立")}>
            {ji.correlated_judge ? "裁判同源" : "裁判独立"}
          </span>
        )}
      </div>

      {fs && fs.total_open > 0 && (
        <div className="ws-sig-line">
          <I.Link size={12} />
          <span>伏笔欠债 {fs.total_open} 条</span>
          {fs.overdue_count > 0 && <span className="ws-sig-warn">· {fs.overdue_count} 条逾期未回收</span>}
          {fs.without_planned_reinforcement > 0 && (
            <span className="ws-sig-muted">· {fs.without_planned_reinforcement} 条无强化计划</span>
          )}
        </div>
      )}

      {budget.length > 0 && (
        <div className="ws-sig-line">
          <I.Layers size={12} />
          <span>主题表达预算</span>
          {budget.map((b) => (
            <span key={b.level} className={`ws-sig-budget ${b.status === "exhausted" ? "is-out" : "is-near"}`}
                  title={b.message}>
              {b.label} {b.count}/{b.cap}
            </span>
          ))}
        </div>
      )}

      {drift && drift.active && (
        <div className="ws-sig-line">
          <I.Radar size={12} />
          <span>风格漂移修正中</span>
          {(drift.drifted_dimensions || []).slice(0, 4).map((d) => (
            <span key={d} className="ws-sig-dim">{d}</span>
          ))}
        </div>
      )}

      {degraded.length > 0 && (
        <div className="ws-sig-line ws-sig-warn"
             title={degraded.map((item) => `${item.signal}: ${item.error_code}`).join(" · ")}>
          <I.AlertTriangle size={12} />
          <span>部分编排信号暂不可用：{degraded.map((item) => item.signal).join("、")}</span>
        </div>
      )}
    </div>
  );
}
