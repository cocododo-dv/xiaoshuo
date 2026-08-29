import React from "react";
import { apiGet, apiPost } from "./lib/client.js";
import { StatCard } from "./ws-quality-ui.jsx";

/* global React, I */
/* ==========================================================
   WsEval — 质量实验室 · 匿名 A/B 人类盲评（结果闭环治理 §6.2/§9.4）
   对接后端实验通道：
     GET  /api/v1/evaluation-experiments                    实验清单 + 进度摘要
     POST /api/v1/evaluation-experiments                    建实验
     POST /api/v1/evaluation-experiments/{id}/pairs         加对（服务端盲化落库）
     POST /api/v1/evaluation-experiments/{id}/freeze        冻结题包
     GET  /api/v1/evaluation-experiments/{id}/next-pair     盲化取对（pair 三键 + 纯计数进度）
     POST /api/v1/evaluation-pairs/{id}/vote                投票（left|right|tie）
     GET  /api/v1/evaluation-experiments/{id}/report        可复算报告
   盲化契约：store 对取到的 pair **只消费** pair_id + 左右纯文本三键，
   只回传 choice + 耗时——映射/策略/token/快照哈希由后端隐藏，前端无从
   得知哪边是 treatment（防无意识偏倚）。进度/清单只含纯计数与实验元信息。
   ========================================================== */

let evState = {
  view: "hub",          // hub | arena | report
  experiments: null,    // 实验清单（null=未加载）
  listLoading: false,
  experimentId: null,
  reviewerRef: "author",
  current: null,        // 盲化三键 { pair_id, left_text, right_text } | null
  progress: null,       // { total_pairs, voted_pairs, remaining_pairs } | null
  shownAt: 0,
  report: null,
  reportFor: null,
  voting: false,
  loading: false,
  busy: false,          // 建实验/加对/冻结等管理写操作
  done: false,          // next-pair 已投完
  error: null,
  notice: null,
};

function evSnapshot() { return evState; }
function evEmit() { try { window.dispatchEvent(new CustomEvent("ws:eval-changed")); } catch (e) {} }
function evSet(patch) { evState = { ...evState, ...patch }; evEmit(); }

const EV_REVIEWER_KEY = "ws-eval:reviewer";
try {
  const saved = window.localStorage.getItem(EV_REVIEWER_KEY);
  if (saved && saved.trim()) evState.reviewerRef = saved.trim();
} catch (e) {}

/* 只保留盲化视图三键——即便后端多回字段也不带入 store（纵深防泄漏）。 */
function evBlindView(pair) {
  if (!pair) return null;
  return { pair_id: pair.pair_id, left_text: pair.left_text, right_text: pair.right_text };
}

/* 进度只保留纯计数三键。 */
function evProgressView(progress) {
  if (!progress) return null;
  return {
    total_pairs: progress.total_pairs || 0,
    voted_pairs: progress.voted_pairs || 0,
    remaining_pairs: progress.remaining_pairs || 0,
  };
}

/* ---- 清单 / 管理 ---- */

async function evLoadExperiments() {
  evSet({ listLoading: true, error: null });
  try {
    const data = await apiGet("/api/v1/evaluation-experiments");
    evSet({ experiments: Array.isArray(data) ? data : [], listLoading: false });
    return evState.experiments;
  } catch (e) {
    evSet({ listLoading: false, error: (e && e.message) || "实验清单加载失败。" });
    return null;
  }
}

/* 建实验/加对/冻结共用的管理写骨架：busy 置起 → POST → 成功记 notice 后重拉清单；
   失败仍按原样落 state.error（noticeOf(data) 出成功文案，errorFallback 兜无 message 的错）。 */
async function evAdminPost(path, body, noticeOf, errorFallback) {
  evSet({ busy: true, error: null, notice: null });
  try {
    const data = await apiPost(path, body);
    evSet({ busy: false, notice: noticeOf(data) });
    await evLoadExperiments();
    return data;
  } catch (e) {
    evSet({ busy: false, error: (e && e.message) || errorFallback });
    return null;
  }
}

async function evCreateExperiment(fields) {
  return evAdminPost(
    "/api/v1/evaluation-experiments", fields,
    (data) => `实验「${(data && data.name) || fields.name}」已创建。`,
    "建实验失败。"
  );
}

async function evAddPair(experimentId, fields) {
  if (!experimentId) return null;
  return evAdminPost(
    `/api/v1/evaluation-experiments/${encodeURIComponent(experimentId)}/pairs`, fields,
    () => `已加入 1 对（快照 ${fields.scene_snapshot_hash}）。`,
    "加对失败。"
  );
}

async function evFreeze(experimentId) {
  if (!experimentId) return null;
  return evAdminPost(
    `/api/v1/evaluation-experiments/${encodeURIComponent(experimentId)}/freeze`, {},
    () => "题包已冻结——清单哈希封存，此后增删对即篡改。",
    "冻结失败。"
  );
}

/* ---- 盲评（竞技场） ---- */

async function evLoadNext() {
  const id = evState.experimentId;
  if (!id) return null;
  evSet({ loading: true, error: null });
  try {
    const path = `/api/v1/evaluation-experiments/${encodeURIComponent(id)}/next-pair`
      + `?reviewer_ref=${encodeURIComponent(evState.reviewerRef)}`;
    const data = await apiGet(path);
    const view = evBlindView(data && data.pair);
    evSet({
      current: view,
      progress: evProgressView(data && data.progress),
      done: !view,
      shownAt: Date.now(),
      loading: false,
    });
    return view;
  } catch (e) {
    evSet({ loading: false, error: (e && e.message) || "取对失败。" });
    return null;
  }
}

async function evStart(experimentId, reviewerRef) {
  const reviewer = String(reviewerRef || evState.reviewerRef || "author").trim() || "author";
  try { window.localStorage.setItem(EV_REVIEWER_KEY, reviewer); } catch (e) {}
  evSet({
    view: "arena", experimentId, reviewerRef: reviewer,
    current: null, progress: null, report: null, reportFor: null,
    done: false, error: null, notice: null,
  });
  return evLoadNext();
}

async function evVote(choice) {
  const pair = evState.current;
  if (!pair || evState.voting) return null;
  if (!["left", "right", "tie"].includes(choice)) return null;
  const durationMs = Math.max(0, Date.now() - (evState.shownAt || Date.now()));
  // 乐观推进：先清当前对，投票成功后拉下一对；失败回滚恢复，不吞掉这一票。
  evSet({ voting: true, current: null, error: null });
  try {
    await apiPost(`/api/v1/evaluation-pairs/${encodeURIComponent(pair.pair_id)}/vote`, {
      choice,
      reviewer_ref: evState.reviewerRef,
      duration_ms: durationMs,
    });
    evSet({ voting: false });
    return evLoadNext();
  } catch (e) {
    evSet({ voting: false, current: pair, error: `这一票没有提交成功（${(e && e.message) || "网络错误"}），请重试。` });
    return null;
  }
}

/* ---- 报告 ---- */

async function evLoadReport(experimentId) {
  const id = experimentId || evState.experimentId;
  if (!id) return null;
  evSet({ loading: true, error: null });
  try {
    const data = await apiGet(`/api/v1/evaluation-experiments/${encodeURIComponent(id)}/report`);
    evSet({ report: data || null, reportFor: id, loading: false });
    return data;
  } catch (e) {
    evSet({ loading: false, error: (e && e.message) || "报告加载失败。" });
    return null;
  }
}

async function evOpenReport(experimentId) {
  evSet({ view: "report", experimentId: experimentId || evState.experimentId, notice: null, error: null });
  return evLoadReport(experimentId);
}

function evBackToHub() {
  evSet({ view: "hub", current: null, progress: null, done: false, error: null });
  evLoadExperiments();
}

function useEvalState() {
  const [, force] = React.useReducer((x) => x + 1, 0);
  React.useEffect(() => {
    const h = () => force();
    window.addEventListener("ws:eval-changed", h);
    return () => window.removeEventListener("ws:eval-changed", h);
  }, []);
  return evSnapshot();
}

/* ==========================================================
   文案映射
   ========================================================== */

const DECISION_META = {
  upgrade_to_default: { tone: "sage", label: "统计显著 · 值得升级为默认", hint: "升级生产默认前仍须走证据门（真人票 + 复验）。" },
  keep_optional: { tone: "slate", label: "未证增益 · 保持可选", hint: "treatment 没有显著胜出，维持按需手动开启。" },
  disable: { tone: "crimson", label: "显著更差 · 建议关闭", hint: "对照组显著胜出，treatment 不值这份成本。" },
  need_more_samples: { tone: "gold", label: "样本不足 · 继续收集", hint: "非平局票不够，结论还不能下。" },
  not_eligible_for_policy: { tone: "gold", label: "证据不合格 · 仅供诊断", hint: "统计结果不能用于调整生产默认，见下方合格性清单。" },
  replication_required: { tone: "gold", label: "统计门已过 · 须新一批复验", hint: "消融实验升级默认前，必须再取一批 30 组非平局真人票复验。" },
};

const ELIGIBILITY_LABEL = {
  evidence_provenance_not_human: "证据来源不是真人票（synthetic 不得调整生产默认）",
  frozen_manifest_not_verified: "题包未冻结，或冻结清单哈希校验失败",
  hidden_benchmark_manifest_not_verified: "未绑定已冻结的隐藏基准清单",
  hidden_benchmark_pair_bindings_not_verified: "对比对与隐藏基准结果的绑定未通过校验",
  evaluation_isolation_not_verified: "快照隔离未声明（种子项目 / 时间隔离 / 外部保留集）",
  snapshot_pseudo_replication_detected: "检测到伪重复：同一快照出现多对",
  anonymous_vote_provenance_present: "存在匿名票（缺 reviewer_ref）",
  fewer_than_30_non_tie_votes: "非平局票不足 30",
};

const STATUS_META = {
  collecting: { tone: "gold", label: "收集中" },
  frozen: { tone: "slate", label: "已冻结" },
};

const PROVENANCE_META = {
  human: { tone: "sage", label: "真人票" },
};

const ISOLATION_LABEL = {
  seed_project: "种子项目",
  time_isolated: "时间隔离",
  external_holdout: "外部保留集",
};

const SCENE_FUNCTIONS = [
  ["advance", "推进"], ["deepen", "深化"], ["reveal", "揭示"],
  ["breathe", "呼吸"], ["foreshadow", "铺垫"], ["turn", "转折"],
];
const SCENE_FUNCTION_LABEL = Object.fromEntries(SCENE_FUNCTIONS);

function fmtPct(v, digits = 0) {
  if (v === null || v === undefined || Number.isNaN(Number(v))) return "—";
  return `${(Number(v) * 100).toFixed(digits)}%`;
}
function fmtNum(v) { return v === null || v === undefined ? "—" : Number(v).toLocaleString(); }
function fmtDate(iso) { return (iso || "").slice(0, 10) || "—"; }

/* ==========================================================
   小部件
   ========================================================== */

const CARD_STYLE = { padding: "12px 14px", borderRadius: 12, border: "1px solid var(--line, #e5e2dc)" };

function EvPill({ tone = "slate", title, children }) {
  return (
    <span className={`pill pill-${tone} text-xs`} title={title}>
      <span className="pill-dot" />{children}
    </span>
  );
}

function EvMeter({ value, max, danger, label }) {
  const ratio = max > 0 ? Math.min(1, Math.max(0, value / max)) : 0;
  return (
    <div role="progressbar" aria-label={label} aria-valuemin="0" aria-valuemax={max || 0} aria-valuenow={value || 0}
         style={{ height: 8, borderRadius: 5, background: "var(--line-1, #e7e4dc)", overflow: "hidden" }}>
      <div style={{ width: `${Math.round(ratio * 100)}%`, height: "100%", borderRadius: 5,
                    background: danger ? "var(--crimson, #a64b3c)" : "var(--acc, #667a64)" }} />
    </div>
  );
}

/* 偏好率 + 95% Wilson 区间：单系列水平区间条，50% 为中立参考线。纯 SVG。 */
function PreferenceCiBar({ rate, ci }) {
  if (rate === null || rate === undefined || !ci) return null;
  const W = 640, H = 56, PAD = 8, y = 34;
  const x = (p) => PAD + Math.min(1, Math.max(0, p)) * (W - PAD * 2);
  return (
    <svg viewBox={`0 0 ${W} ${H}`} width="100%" height={H} role="img"
         aria-label={`treatment 偏好率 ${fmtPct(rate, 1)}，95% 置信区间 ${fmtPct(ci.low, 1)} 至 ${fmtPct(ci.high, 1)}`}
         style={{ display: "block" }}>
      <line x1={PAD} y1={y} x2={W - PAD} y2={y} stroke="var(--line-1, #e7e4dc)" strokeWidth="2" />
      <line x1={x(0.5)} y1={y - 14} x2={x(0.5)} y2={y + 10} stroke="var(--ink-3, #8a857c)" strokeWidth="1" strokeDasharray="3 3" />
      <text x={x(0.5)} y={y + 20} textAnchor="middle" fontSize="10" fill="var(--ink-3, #8a857c)">50%（无差异）</text>
      <rect x={x(ci.low)} y={y - 4} width={Math.max(2, x(ci.high) - x(ci.low))} height="8" rx="4"
            fill="var(--acc, #667a64)" opacity="0.35">
        <title>{`95% CI ${fmtPct(ci.low, 1)}–${fmtPct(ci.high, 1)}`}</title>
      </rect>
      <circle cx={x(rate)} cy={y} r="5" fill="var(--acc, #667a64)" stroke="var(--paper, #fff)" strokeWidth="2">
        <title>{`偏好率 ${fmtPct(rate, 1)}`}</title>
      </circle>
      <text x={x(rate)} y={y - 12} textAnchor="middle" fontSize="11" fill="var(--ink-1, #2f2b26)">{fmtPct(rate, 1)}</text>
      <text x={x(ci.low)} y={y + 20} textAnchor="middle" fontSize="10" fill="var(--ink-3, #8a857c)">{fmtPct(ci.low, 1)}</text>
      <text x={x(ci.high)} y={y + 20} textAnchor="middle" fontSize="10" fill="var(--ink-3, #8a857c)">{fmtPct(ci.high, 1)}</text>
    </svg>
  );
}

function EvBanner({ tone, children }) {
  const color = tone === "crimson" ? "var(--crimson, #a64b3c)" : tone === "sage" ? "var(--acc, #667a64)" : "var(--gold-deep, #a67c00)";
  return (
    <div className="card" role="status"
         style={{ ...CARD_STYLE, borderLeft: `3px solid ${color}`, display: "flex", gap: 8, alignItems: "baseline" }}>
      {children}
    </div>
  );
}

/* ==========================================================
   Hub：实验清单 + 建实验 + 手动加对
   ========================================================== */

function EvExperimentCard({ exp, busy }) {
  const status = STATUS_META[exp.status] || { tone: "slate", label: exp.status };
  const prov = PROVENANCE_META[exp.evidence_provenance] || { tone: "slate", label: exp.evidence_provenance };
  const humanLocked = exp.evidence_provenance === "human" && exp.status !== "frozen";
  const canVote = exp.remaining_pairs > 0 && !humanLocked;
  const needMore = Math.max(0, (exp.freeze_required_contrastive || 30) - (exp.contrastive_pairs || 0));
  return (
    <div className="card" style={{ ...CARD_STYLE, display: "grid", gap: 8, alignContent: "start" }}>
      <div style={{ display: "flex", gap: 8, alignItems: "baseline", flexWrap: "wrap" }}>
        <h3 className="text-serif" style={{ margin: 0, fontSize: 16, flex: 1, minWidth: 0 }}>{exp.name || exp.experiment_id}</h3>
        <EvPill tone={status.tone}>{status.label}</EvPill>
        <EvPill tone={prov.tone} title="human=真人票（human-only 契约；可进策略门，须冻结+隔离）">{prov.label}</EvPill>
        {exp.isolation_mode && <EvPill tone="slate" title={exp.snapshot_source_ref || ""}>{ISOLATION_LABEL[exp.isolation_mode] || exp.isolation_mode}</EvPill>}
      </div>
      {exp.hypothesis && (
        <div className="text-xs" style={{ color: "var(--ink-2)" }}>{exp.hypothesis}</div>
      )}
      <div>
        <div className="text-xs" style={{ display: "flex", justifyContent: "space-between", gap: 8, marginBottom: 2 }}>
          <span>已判 {fmtNum(exp.voted_pairs)} / {fmtNum(exp.total_pairs)} 对</span>
          <span style={{ color: "var(--ink-3)" }}>
            {exp.remaining_pairs > 0 ? `还剩 ${fmtNum(exp.remaining_pairs)} 对` : exp.total_pairs > 0 ? "已投完" : "尚无对比对"}
          </span>
        </div>
        <EvMeter value={exp.voted_pairs} max={exp.total_pairs} label={`${exp.name || exp.experiment_id} 盲评进度`} />
      </div>
      <div className="text-xs" style={{ color: "var(--ink-3)", display: "flex", gap: 10, flexWrap: "wrap" }}>
        <span>对比对 {fmtNum(exp.contrastive_pairs)} / {exp.freeze_required_contrastive || 30}</span>
        <span>建于 {fmtDate(exp.created_at)}</span>
        {exp.frozen_at && <span>冻结于 {fmtDate(exp.frozen_at)}</span>}
        <code style={{ opacity: 0.6 }} title={exp.experiment_id}>{exp.experiment_id}</code>
      </div>
      <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
        <button className={`btn btn-sm ${canVote ? "btn-accent" : "btn-ghost"}`} disabled={!canVote || busy}
                title={humanLocked ? "真人票实验须先冻结题包（≥30 组对比对）才开放盲评" : undefined}
                onClick={() => evStart(exp.experiment_id)}>
          {I && I.Eye && <I.Eye size={13} />} {exp.voted_pairs > 0 ? "继续盲评" : "开始盲评"}
        </button>
        <button className="btn btn-ghost btn-sm" disabled={busy} onClick={() => evOpenReport(exp.experiment_id)}>
          看报告
        </button>
        {exp.can_freeze && (
          <button className="btn btn-ghost btn-sm" disabled={busy}
                  onClick={() => { if (window.confirm(`冻结「${exp.name}」的题包？冻结后不能再增删对比对。`)) evFreeze(exp.experiment_id); }}>
            冻结题包
          </button>
        )}
        {!exp.can_freeze && exp.status === "collecting" && needMore > 0 && (
          <span className="text-xs" style={{ color: "var(--ink-3)", alignSelf: "center" }}>
            再收 {needMore} 组对比对可冻结
          </span>
        )}
        {humanLocked && exp.remaining_pairs > 0 && (
          <span className="text-xs" style={{ color: "var(--gold-deep, #a67c00)", alignSelf: "center" }}>
            真人票需先冻结题包
          </span>
        )}
      </div>
    </div>
  );
}

function EvCreateForm({ busy }) {
  const [name, setName] = React.useState("");
  const [hypothesis, setHypothesis] = React.useState("");
  const [isolation, setIsolation] = React.useState("");
  const [sourceRef, setSourceRef] = React.useState("");
  const submit = async () => {
    const body = {
      name: name.trim(),
      hypothesis: hypothesis.trim(),
      // 迁移 0075 起后端为 human-only 契约，synthetic 会被 422 拒绝
      evidence_provenance: "human",
      isolation_mode: isolation || null,
      snapshot_source_ref: sourceRef.trim() || null,
    };
    const created = await evCreateExperiment(body);
    if (created) { setName(""); setHypothesis(""); }
  };
  const field = { display: "grid", gap: 4 };
  const input = { padding: "6px 8px", borderRadius: 8, border: "1px solid var(--line, #d8d4cb)", background: "var(--paper, #fff)", font: "inherit" };
  return (
    <details className="card" style={CARD_STYLE}>
      <summary className="text-xs" style={{ cursor: "pointer", color: "var(--ink-2)" }}>新建实验</summary>
      <div style={{ display: "grid", gap: 10, marginTop: 10, gridTemplateColumns: "repeat(auto-fit, minmax(220px, 1fr))" }}>
        <label className="text-xs" style={field}>实验名 *
          <input style={input} value={name} onChange={(e) => setName(e.target.value)} placeholder="如：Best-of-N vs 单发（悬疑卷二）" />
        </label>
        <label className="text-xs" style={field}>假设
          <input style={input} value={hypothesis} onChange={(e) => setHypothesis(e.target.value)} placeholder="如：Best-of-N 终选在揭示场显著更好" />
        </label>
        <label className="text-xs" style={field}>证据来源
          <div style={{ ...input, color: "var(--ink-2)" }}>human · 真人票（human-only 契约；进策略门须冻结+隔离）</div>
        </label>
        <label className="text-xs" style={field}>快照隔离
          <select style={input} value={isolation} onChange={(e) => setIsolation(e.target.value)}>
            <option value="">未声明</option>
            <option value="seed_project">seed_project · 种子项目</option>
            <option value="time_isolated">time_isolated · 时间隔离</option>
            <option value="external_holdout">external_holdout · 外部保留集</option>
          </select>
        </label>
        <label className="text-xs" style={field}>快照来源标注
          <input style={input} value={sourceRef} onChange={(e) => setSourceRef(e.target.value)} placeholder="如：project:blind-eval-seed-v1" />
        </label>
      </div>
      <div style={{ marginTop: 10 }}>
        <button className="btn btn-accent btn-sm" disabled={busy || !name.trim()} onClick={submit}>创建</button>
        <span className="text-xs" style={{ color: "var(--ink-3)", marginLeft: 10 }}>
          真人票实验冻结时会校验隔离声明；两臂生成策略由评测工具在加对时绑定。
        </span>
      </div>
    </details>
  );
}

function EvAddPairForm({ experiments, busy }) {
  const collecting = (experiments || []).filter((e) => e.status === "collecting");
  const [expId, setExpId] = React.useState("");
  const [snap, setSnap] = React.useState("");
  const [genre, setGenre] = React.useState("");
  const [fn, setFn] = React.useState("");
  const [treatment, setTreatment] = React.useState("");
  const [control, setControl] = React.useState("");
  const [tokT, setTokT] = React.useState("");
  const [tokC, setTokC] = React.useState("");
  const targetId = expId || (collecting[0] && collecting[0].experiment_id) || "";
  const randomSnap = () => setSnap(`manual_${Date.now().toString(36)}_${Math.random().toString(36).slice(2, 8)}`);
  const submit = async () => {
    const tokenCost = {};
    if (tokT !== "" && Number.isFinite(Number(tokT))) tokenCost.treatment = Number(tokT);
    if (tokC !== "" && Number.isFinite(Number(tokC))) tokenCost.control = Number(tokC);
    const added = await evAddPair(targetId, {
      scene_snapshot_hash: snap.trim(),
      treatment_text: treatment,
      control_text: control,
      genre: genre.trim() || null,
      scene_function: fn || null,
      token_cost: tokenCost,
    });
    if (added) { setSnap(""); setTreatment(""); setControl(""); setTokT(""); setTokC(""); }
  };
  const input = { padding: "6px 8px", borderRadius: 8, border: "1px solid var(--line, #d8d4cb)", background: "var(--paper, #fff)", font: "inherit" };
  const area = { ...input, minHeight: 90, resize: "vertical", whiteSpace: "pre-wrap" };
  return (
    <details className="card" style={CARD_STYLE}>
      <summary className="text-xs" style={{ cursor: "pointer", color: "var(--ink-2)" }}>
        手动加对（管理）——正式实验请用评测工具批量入库
      </summary>
      {collecting.length === 0 ? (
        <div className="text-xs" style={{ color: "var(--ink-3)", marginTop: 8 }}>没有处于「收集中」的实验——先新建一个。</div>
      ) : (
        <div style={{ display: "grid", gap: 10, marginTop: 10 }}>
          <div style={{ display: "grid", gap: 10, gridTemplateColumns: "repeat(auto-fit, minmax(200px, 1fr))" }}>
            <label className="text-xs" style={{ display: "grid", gap: 4 }}>目标实验
              <select style={input} value={targetId} onChange={(e) => setExpId(e.target.value)}>
                {collecting.map((e) => <option key={e.experiment_id} value={e.experiment_id}>{e.name || e.experiment_id}</option>)}
              </select>
            </label>
            <label className="text-xs" style={{ display: "grid", gap: 4 }}>场景快照标识 *（同实验内唯一）
              <span style={{ display: "flex", gap: 6 }}>
                <input style={{ ...input, flex: 1 }} value={snap} onChange={(e) => setSnap(e.target.value)} placeholder="scene 快照哈希 / 唯一标识" />
                <button className="btn btn-ghost btn-sm" type="button" onClick={randomSnap}>随机</button>
              </span>
            </label>
            <label className="text-xs" style={{ display: "grid", gap: 4 }}>题材
              <input style={input} value={genre} onChange={(e) => setGenre(e.target.value)} placeholder="如：悬疑" />
            </label>
            <label className="text-xs" style={{ display: "grid", gap: 4 }}>场景功能
              <select style={input} value={fn} onChange={(e) => setFn(e.target.value)}>
                <option value="">未标注</option>
                {SCENE_FUNCTIONS.map(([k, label]) => <option key={k} value={k}>{label}（{k}）</option>)}
              </select>
            </label>
          </div>
          <div style={{ display: "grid", gap: 10, gridTemplateColumns: "repeat(auto-fit, minmax(260px, 1fr))" }}>
            <label className="text-xs" style={{ display: "grid", gap: 4 }}>treatment 文本 *（如 Best-of-N 终选稿）
              <textarea style={area} value={treatment} onChange={(e) => setTreatment(e.target.value)} />
            </label>
            <label className="text-xs" style={{ display: "grid", gap: 4 }}>control 文本 *（如单发基线稿）
              <textarea style={area} value={control} onChange={(e) => setControl(e.target.value)} />
            </label>
          </div>
          <div style={{ display: "flex", gap: 10, alignItems: "end", flexWrap: "wrap" }}>
            <label className="text-xs" style={{ display: "grid", gap: 4 }}>treatment tokens
              <input style={{ ...input, width: 120 }} inputMode="numeric" value={tokT} onChange={(e) => setTokT(e.target.value)} />
            </label>
            <label className="text-xs" style={{ display: "grid", gap: 4 }}>control tokens
              <input style={{ ...input, width: 120 }} inputMode="numeric" value={tokC} onChange={(e) => setTokC(e.target.value)} />
            </label>
            <button className="btn btn-accent btn-sm" disabled={busy || !targetId || !snap.trim() || !treatment || !control} onClick={submit}>
              盲化入库
            </button>
            <span className="text-xs" style={{ color: "var(--ink-3)" }}>
              左右位置由服务端随机分配并隐藏——入库后连你也看不到映射。
            </span>
          </div>
        </div>
      )}
    </details>
  );
}

function EvHub({ st }) {
  const [reviewer, setReviewer] = React.useState(st.reviewerRef || "author");
  const apply = () => {
    const v = reviewer.trim() || "author";
    try { window.localStorage.setItem(EV_REVIEWER_KEY, v); } catch (e) {}
    evSet({ reviewerRef: v });
  };
  const input = { padding: "6px 8px", borderRadius: 8, border: "1px solid var(--line, #d8d4cb)", background: "var(--paper, #fff)", font: "inherit" };
  return (
    <div style={{ display: "grid", gap: 12 }}>
      <div className="rv-toolbar" style={{ flexWrap: "wrap", gap: 8 }}>
        <label className="text-xs" style={{ display: "flex", gap: 6, alignItems: "center" }}>
          评审人
          <input style={{ ...input, width: 140 }} value={reviewer} onChange={(e) => setReviewer(e.target.value)} onBlur={apply}
                 title="真人票实验要求非自动化评审人标识（不能以 model:/llm:/ai:/bot: 等开头）" />
        </label>
        <span style={{ flex: 1 }} />
        <button className="btn btn-ghost btn-sm" disabled={st.listLoading} onClick={() => evLoadExperiments()}>
          {I && I.Refresh && <I.Refresh size={13} />} {st.listLoading ? "加载中…" : "刷新"}
        </button>
      </div>

      {st.experiments && st.experiments.length > 0 ? (
        <div style={{ display: "grid", gap: 12, gridTemplateColumns: "repeat(auto-fill, minmax(320px, 1fr))" }}>
          {st.experiments.map((exp) => <EvExperimentCard key={exp.experiment_id} exp={exp} busy={st.busy} />)}
        </div>
      ) : st.experiments ? (
        <div className="rv-none">
          还没有盲评实验。流程：新建实验 → 加入 ≥30 组来自互异快照的对比对（正式实验由评测工具
          在隐藏基准上双臂生成并绑定入库）→ 冻结题包 → 逐对盲评 → 看可复算报告。
        </div>
      ) : (
        <div className="rv-none">正在加载实验清单…</div>
      )}

      <EvCreateForm busy={st.busy} />
      <EvAddPairForm experiments={st.experiments} busy={st.busy} />
    </div>
  );
}

/* ==========================================================
   Arena：逐对盲评
   ========================================================== */

function EvArena({ st }) {
  const pair = st.current;
  const progress = st.progress;
  const expMeta = (st.experiments || []).find((e) => e.experiment_id === st.experimentId) || null;

  React.useEffect(() => {
    if (!pair || st.voting) return undefined;
    const h = (e) => {
      const tag = e.target && e.target.tagName;
      if (tag && /^(INPUT|TEXTAREA|SELECT)$/.test(tag)) return;
      if (e.key === "ArrowLeft") { e.preventDefault(); evVote("left"); }
      else if (e.key === "ArrowRight") { e.preventDefault(); evVote("right"); }
      else if (e.key === "0" || e.key === "=") { e.preventDefault(); evVote("tie"); }
    };
    window.addEventListener("keydown", h);
    return () => window.removeEventListener("keydown", h);
  }, [pair, st.voting]);

  const articleStyle = {
    border: "1px solid var(--line, #e5e2dc)", borderRadius: 12, padding: "14px 16px",
    background: "var(--paper, #fff)", whiteSpace: "pre-wrap", overflowY: "auto",
    maxHeight: "56vh", fontSize: 15, lineHeight: 1.9,
  };
  const position = progress ? Math.min(progress.voted_pairs + 1, progress.total_pairs) : null;

  return (
    <div style={{ display: "grid", gap: 12 }}>
      <div className="rv-toolbar" style={{ gap: 8, flexWrap: "wrap" }}>
        <button className="btn btn-ghost btn-sm" onClick={evBackToHub}>
          {I && I.ChevronLeft && <I.ChevronLeft size={13} />} 返回实验清单
        </button>
        <h2 className="text-serif" style={{ margin: 0, fontSize: 17, flex: 1, minWidth: 0 }}>
          {(expMeta && expMeta.name) || st.experimentId}
        </h2>
        {progress && !st.done && (
          <span className="text-xs" style={{ color: "var(--ink-3)" }}>
            第 {fmtNum(position)} / {fmtNum(progress.total_pairs)} 对 · 还剩 {fmtNum(progress.remaining_pairs)} 对
          </span>
        )}
      </div>
      {progress && <EvMeter value={progress.voted_pairs} max={progress.total_pairs} label="盲评进度" />}

      {pair ? (
        <>
          <div className="text-xs" style={{ color: "var(--ink-3)" }}>
            两稿匿名随机放置，你不知道哪边是 Best-of-N 终选、哪边是单发基线。凭阅读直觉选更好的一稿；确实难分再选平。
          </div>
          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(300px, 1fr))", gap: 12 }}>
            <article style={articleStyle} aria-label="甲稿">
              <div className="text-xs" style={{ color: "var(--ink-3)", marginBottom: 8 }}>甲</div>
              <div className="text-serif">{pair.left_text}</div>
            </article>
            <article style={articleStyle} aria-label="乙稿">
              <div className="text-xs" style={{ color: "var(--ink-3)", marginBottom: 8 }}>乙</div>
              <div className="text-serif">{pair.right_text}</div>
            </article>
          </div>
          <div style={{ display: "flex", gap: 10, flexWrap: "wrap", justifyContent: "center" }}>
            <button className="btn btn-accent" disabled={st.voting} onClick={() => evVote("left")}>甲更好 ←</button>
            <button className="btn btn-ghost" disabled={st.voting} onClick={() => evVote("tie")}>难分高下（0）</button>
            <button className="btn btn-accent" disabled={st.voting} onClick={() => evVote("right")}>→ 乙更好</button>
          </div>
          <div className="text-xs" style={{ color: "var(--ink-3)", textAlign: "center" }}>
            键盘：← 选甲 · → 选乙 · 0 平。每对只记一票，投出后不可改。
          </div>
        </>
      ) : st.done ? (
        <div className="card" style={{ ...CARD_STYLE, textAlign: "center", padding: "28px 16px" }}>
          <div className="text-serif" style={{ fontSize: 18, marginBottom: 6 }}>
            {I && I.CheckCircle && <I.CheckCircle size={16} />} 本轮盲评已完成
          </div>
          <div className="text-xs" style={{ color: "var(--ink-3)", marginBottom: 12 }}>
            {progress ? `共 ${fmtNum(progress.total_pairs)} 对已全部投完。` : "所有对比对都已投完。"}结论以可复算报告为准。
          </div>
          <button className="btn btn-accent btn-sm" onClick={() => evOpenReport(st.experimentId)}>查看报告</button>
        </div>
      ) : (
        <div className="rv-none">{st.loading ? "正在取对…" : "暂无待评的对比对。"}</div>
      )}
    </div>
  );
}

/* ==========================================================
   Report：可复算报告
   ========================================================== */

function EvGenreTable({ byGenre }) {
  const entries = Object.entries(byGenre || {});
  if (!entries.length) return null;
  return (
    <div style={{ overflowX: "auto" }}>
      <table className="lib-table" aria-label="分题材盲评结果">
        <thead><tr><th>题材</th><th>非平局</th><th>偏好率</th><th>treatment 胜</th><th>control 胜</th><th>平局</th></tr></thead>
        <tbody>
          {entries.map(([genre, t]) => (
            <tr key={genre}>
              <td>{genre === "unlabeled" ? "未标注" : genre}</td>
              <td>{fmtNum(t.non_tie_n)}</td>
              <td>{fmtPct(t.preference_rate)}</td>
              <td>{fmtNum(t.treatment_wins)}</td>
              <td>{fmtNum(t.control_wins)}</td>
              <td>{fmtNum(t.ties)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function EvCellsTable({ cells }) {
  if (!cells || !cells.length) return null;
  return (
    <div style={{ overflowX: "auto" }}>
      <table className="lib-table" aria-label="题材×场景功能策略格">
        <thead><tr><th>题材</th><th>场景功能</th><th>非平局</th><th>偏好率</th><th>p 值</th><th>显著</th><th>token 倍率</th></tr></thead>
        <tbody>
          {cells.map((c) => (
            <tr key={`${c.genre}|${c.scene_function}`}>
              <td>{c.genre === "unlabeled" ? "未标注" : c.genre}</td>
              <td>{c.scene_function === "unlabeled" ? "未标注" : (SCENE_FUNCTION_LABEL[c.scene_function] || c.scene_function)}</td>
              <td>{fmtNum(c.non_tie_n)}</td>
              <td>{fmtPct(c.preference_rate)}</td>
              <td>{c.p_value === null || c.p_value === undefined ? "—" : c.p_value}</td>
              <td>{c.significant ? <EvPill tone="sage">显著</EvPill> : <EvPill tone="slate">不显著</EvPill>}</td>
              <td>{c.token_multiplier === null || c.token_multiplier === undefined ? "—" : `${c.token_multiplier}×`}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function EvEligibility({ report }) {
  const reasons = report.policy_eligibility_reasons || [];
  return (
    <section className="card" style={CARD_STYLE}>
      <h3 className="text-serif" style={{ margin: "0 0 10px", fontSize: 15 }}>
        {I && I.ShieldCheck && <I.ShieldCheck size={14} />} 策略门合格性（fail-closed）
      </h3>
      {reasons.length === 0 ? (
        <div className="text-xs" style={{ color: "var(--acc, #667a64)" }}>
          ✓ 全部通过——本报告可作为调整生产默认的证据（仍须走 apply_evaluation_report 策略门）。
        </div>
      ) : (
        <ul className="text-xs" style={{ margin: 0, paddingLeft: 18, display: "grid", gap: 4 }}>
          {reasons.map((r) => (
            <li key={r} style={{ color: "var(--gold-deep, #a67c00)" }}>
              ✗ {ELIGIBILITY_LABEL[r] || r}
            </li>
          ))}
        </ul>
      )}
      <div className="text-xs" style={{ color: "var(--ink-3)", marginTop: 8 }}>
        证据 {report.evidence_provenance === "human" ? "真人票" : "合成票"} ·
        隔离 {ISOLATION_LABEL[(report.isolation || {}).mode] || "未声明"}
        {(report.isolation || {}).source_ref ? `（${report.isolation.source_ref}）` : ""} ·
        冻结清单 {report.frozen_manifest_verified ? "已核验" : "未核验"} ·
        互异快照 {fmtNum(report.distinct_snapshot_count)}/{fmtNum(report.total_pairs)}
        {report.pseudo_replication_ok ? "" : "（⚠ 伪重复）"}
      </div>
    </section>
  );
}

function EvReport({ st }) {
  const report = st.report;
  return (
    <div style={{ display: "grid", gap: 12 }}>
      <div className="rv-toolbar" style={{ gap: 8, flexWrap: "wrap" }}>
        <button className="btn btn-ghost btn-sm" onClick={evBackToHub}>
          {I && I.ChevronLeft && <I.ChevronLeft size={13} />} 返回实验清单
        </button>
        <h2 className="text-serif" style={{ margin: 0, fontSize: 17, flex: 1, minWidth: 0 }}>
          {(report && report.name) || st.experimentId} · 可复算报告
        </h2>
        <button className="btn btn-ghost btn-sm" disabled={st.loading} onClick={() => evLoadReport(st.reportFor || st.experimentId)}>
          {I && I.Refresh && <I.Refresh size={13} />} 刷新
        </button>
      </div>

      {!report ? (
        <div className="rv-none">{st.loading ? "正在汇算…" : "报告尚未加载。"}</div>
      ) : (
        <>
          {(() => {
            const meta = DECISION_META[report.decision] || { tone: "slate", label: report.decision, hint: "" };
            return (
              <EvBanner tone={meta.tone}>
                <div style={{ display: "grid", gap: 4 }}>
                  <b className="text-serif" style={{ fontSize: 16 }}>{meta.label}</b>
                  <span className="text-xs" style={{ color: "var(--ink-2)" }}>{report.rationale || meta.hint}</span>
                </div>
              </EvBanner>
            );
          })()}

          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(150px, 1fr))", gap: 10 }}>
            <StatCard label="treatment 偏好率" value={fmtPct(report.preference_rate, 1)}
                    hint={`非平局 ${fmtNum(report.non_tie_n)} 票中胜 ${fmtNum(report.treatment_wins)}`} />
            <StatCard label="双侧精确二项 p" value={report.p_value === null || report.p_value === undefined ? "—" : report.p_value}
                    hint={`显著门 α=0.05 · 最小胜场 ${fmtNum(report.min_wins_threshold)}`} />
            <StatCard label="统计判定" value={report.significant ? "显著" : "不显著"}
                    hint={report.statistical_decision} />
            <StatCard label="平局 / 未投 / 无对比" value={`${fmtNum(report.ties)} / ${fmtNum(report.unvoted)} / ${fmtNum(report.no_contrast)}`}
                    hint={`共 ${fmtNum(report.total_pairs)} 对 · 平局率 ${fmtPct(report.tie_rate)}`} />
            <StatCard label="token 代价倍率"
                    value={report.token_cost && report.token_cost.token_multiplier !== null && report.token_cost.token_multiplier !== undefined
                      ? `${report.token_cost.token_multiplier}×` : "—"}
                    hint={report.token_cost && (report.token_cost.treatment_missing_n || report.token_cost.control_missing_n)
                      ? `成本记录不全（缺 ${fmtNum(report.token_cost.treatment_missing_n)}/${fmtNum(report.token_cost.control_missing_n)} 对）` : "treatment ÷ control"} />
            <StatCard label="平均投票用时"
                    value={report.vote_duration && report.vote_duration.avg_ms !== null && report.vote_duration.avg_ms !== undefined
                      ? `${Math.round(report.vote_duration.avg_ms / 100) / 10}s` : "—"}
                    hint={report.vote_duration ? `${fmtNum(report.vote_duration.count)} 票计时` : null} />
          </div>

          {report.preference_ci95 && (
            <section className="card" style={CARD_STYLE}>
              <h3 className="text-serif" style={{ margin: "0 0 6px", fontSize: 15 }}>偏好率与 95% 置信区间（Wilson）</h3>
              <PreferenceCiBar rate={report.preference_rate} ci={report.preference_ci95} />
              <div className="text-xs" style={{ color: "var(--ink-3)" }}>
                区间含 50% 即不能排除「无差异」；{fmtPct(report.preference_ci95.low, 1)}–{fmtPct(report.preference_ci95.high, 1)}。
              </div>
            </section>
          )}

          <EvEligibility report={report} />

          {report.by_genre && Object.keys(report.by_genre).length > 0 && (
            <section className="card" style={CARD_STYLE}>
              <h3 className="text-serif" style={{ margin: "0 0 10px", fontSize: 15 }}>分题材</h3>
              <EvGenreTable byGenre={report.by_genre} />
            </section>
          )}

          {report.strategy_cells && report.strategy_cells.length > 0 && (
            <details className="card" style={CARD_STYLE}>
              <summary className="text-xs" style={{ cursor: "pointer", color: "var(--ink-2)" }}>
                题材 × 场景功能策略格（Best-of-N 逐格启用的证据单元）
              </summary>
              <div style={{ marginTop: 10 }}>
                <EvCellsTable cells={report.strategy_cells} />
              </div>
            </details>
          )}

          <div className="text-xs" style={{ color: "var(--ink-3)" }}>
            统计口径：{report.statistical_rationale || "—"}
            {report.requires_fresh_replication ? " 消融实验升级默认前须再取一批 30 组非平局票复验。" : ""}
          </div>
        </>
      )}
    </div>
  );
}

/* ==========================================================
   主视图
   ========================================================== */

function WsEval() {
  const st = useEvalState();

  React.useEffect(() => {
    if (st.experiments === null && !st.listLoading) evLoadExperiments();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return (
    <div className="ws-page ws-view q-eval" data-screen-label="eval">
      <header className="rv-head">
        <div className="rv-eyebrow" style={{ display: "flex", alignItems: "center", gap: 8 }}>
          {I && I.Flask && <I.Flask size={13} />} 质量实验室 · 结果闭环
        </div>
        <h1 className="rv-title">盲评实验</h1>
        <p className="rv-sub">
          匿名 A/B 盲评回答一个问题：贵一档的生成策略（如 Best-of-N）到底值不值。左右两稿随机放置、
          映射对你隐藏；投满 30 组非平局票后，报告给出可复算的统计结论与策略建议——生产默认只认真人票证据。
        </p>
      </header>

      {st.error && <div className="rv-none" role="alert" style={{ color: "var(--crimson, #b00)" }}>{st.error}</div>}
      {st.notice && !st.error && <div className="rv-none" role="status" style={{ color: "var(--acc, #667a64)" }}>{st.notice}</div>}

      {st.view === "arena" ? <EvArena st={st} />
        : st.view === "report" ? <EvReport st={st} />
        : <EvHub st={st} />}
    </div>
  );
}

export {
  WsEval, evStart, evVote, evLoadNext, evLoadReport, evLoadExperiments,
  evCreateExperiment, evAddPair, evFreeze, evOpenReport, evBackToHub, evSnapshot, useEvalState,
};
