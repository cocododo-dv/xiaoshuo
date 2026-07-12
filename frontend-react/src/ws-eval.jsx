import React from "react";
import { apiGet, apiPost } from "./lib/client.js";

/* global React */
/* ==========================================================
   WsEval — 质量实验室 · 匿名 A/B 人类盲评（Wave 5，结果闭环治理 §6.2/§9.4）
   对接后端实验通道：
     GET  /api/v1/evaluation-experiments/{id}/next-pair   盲化取对（只出左右纯文本）
     POST /api/v1/evaluation-pairs/{id}/vote              投票（left|right|tie）
     GET  /api/v1/evaluation-experiments/{id}/report      可复算报告
   盲化契约：store **只消费** pair_id + 左右纯文本，只回传 choice+耗时——
   映射/策略/token/快照哈希由后端隐藏，前端无从得知哪边是 treatment（防无意识偏倚）。
   ========================================================== */

let evState = {
  experimentId: null,
  reviewerRef: "author",
  current: null,      // { pair_id, left_text, right_text } | null
  shownAt: 0,
  report: null,
  voting: false,
  loading: false,
  done: false,        // next-pair 返回 null（投完）
  error: null,
};

function evSnapshot() { return evState; }
function evEmit() { try { window.dispatchEvent(new CustomEvent("ws:eval-changed")); } catch (e) {} }

/* 只保留盲化视图三键——即便后端多回字段也不带入 store（纵深防泄漏）。 */
function evBlindView(pair) {
  if (!pair) return null;
  return { pair_id: pair.pair_id, left_text: pair.left_text, right_text: pair.right_text };
}

async function evLoadNext() {
  const id = evState.experimentId;
  if (!id) return null;
  evState = { ...evState, loading: true, error: null };
  evEmit();
  try {
    const path = `/api/v1/evaluation-experiments/${encodeURIComponent(id)}/next-pair`
      + `?reviewer_ref=${encodeURIComponent(evState.reviewerRef)}`;
    const data = await apiGet(path);
    const view = evBlindView(data);
    evState = { ...evState, current: view, done: !view, shownAt: Date.now(), loading: false };
    evEmit();
    return view;
  } catch (e) {
    evState = { ...evState, loading: false, error: (e && e.message) || "取对失败。" };
    evEmit();
    return null;
  }
}

async function evStart(experimentId, reviewerRef = "author") {
  evState = { ...evState, experimentId, reviewerRef, current: null, report: null, done: false, error: null };
  evEmit();
  return evLoadNext();
}

async function evVote(choice) {
  const pair = evState.current;
  if (!pair || evState.voting) return null;
  if (!["left", "right", "tie"].includes(choice)) return null;
  const durationMs = Math.max(0, Date.now() - (evState.shownAt || Date.now()));
  // 乐观推进：先清当前对，投票成功后拉下一对；失败回滚。
  evState = { ...evState, voting: true, current: null, error: null };
  evEmit();
  try {
    await apiPost(`/api/v1/evaluation-pairs/${encodeURIComponent(pair.pair_id)}/vote`, {
      choice,
      reviewer_ref: evState.reviewerRef,
      duration_ms: durationMs,
    });
    evState = { ...evState, voting: false };
    evEmit();
    return evLoadNext();
  } catch (e) {
    // 回滚：恢复当前对并告警，不吞掉这一票。
    evState = { ...evState, voting: false, current: pair, error: (e && e.message) || "投票失败。" };
    evEmit();
    try { window.alert("投票失败，请重试。"); } catch (e2) {}
    return null;
  }
}

async function evLoadReport() {
  const id = evState.experimentId;
  if (!id) return null;
  try {
    const data = await apiGet(`/api/v1/evaluation-experiments/${encodeURIComponent(id)}/report`);
    evState = { ...evState, report: data || null };
    evEmit();
    return data;
  } catch (e) {
    evState = { ...evState, error: (e && e.message) || "报告加载失败。" };
    evEmit();
    return null;
  }
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

const DECISION_LABEL = {
  upgrade_to_default: "值得升级为默认（需复验）",
  keep_optional: "未证增益 · 保持可选",
  disable: "显著更差 · 建议关闭",
  need_more_samples: "样本不足",
};

function WsEval() {
  const st = useEvalState();
  const [expId, setExpId] = React.useState(st.experimentId || "");
  const pair = st.current;

  return (
    <div className="ws-eval" style={{ padding: 16, maxWidth: 960, margin: "0 auto" }}>
      <h2>质量实验室 · 匿名盲评</h2>
      <p style={{ opacity: 0.7 }}>
        左右两稿匿名随机；你不知道哪边是 Best-of-N 终选、哪边是单发基线。凭直觉选更好的一稿，或选“无明显差异”。
      </p>
      <div style={{ display: "flex", gap: 8, marginBottom: 12 }}>
        <input
          value={expId}
          onChange={(e) => setExpId(e.target.value)}
          placeholder="实验 ID"
          style={{ flex: 1, padding: 6 }}
        />
        <button onClick={() => evStart(expId.trim())} disabled={!expId.trim()}>开始/继续</button>
        <button onClick={() => evLoadReport()}>看报告</button>
      </div>

      {st.error && <div style={{ color: "crimson" }}>{st.error}</div>}

      {pair ? (
        <div>
          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12 }}>
            <article style={{ border: "1px solid #ccc", padding: 12, whiteSpace: "pre-wrap" }}>
              <h4>稿 A（左）</h4>{pair.left_text}
            </article>
            <article style={{ border: "1px solid #ccc", padding: 12, whiteSpace: "pre-wrap" }}>
              <h4>稿 B（右）</h4>{pair.right_text}
            </article>
          </div>
          <div style={{ display: "flex", gap: 8, marginTop: 12 }}>
            <button onClick={() => evVote("left")} disabled={st.voting}>选左（A）更好</button>
            <button onClick={() => evVote("right")} disabled={st.voting}>选右（B）更好</button>
            <button onClick={() => evVote("tie")} disabled={st.voting}>无明显差异</button>
          </div>
        </div>
      ) : st.done ? (
        <div style={{ padding: 12, opacity: 0.8 }}>本轮已投完。点“看报告”查看可复算结论。</div>
      ) : (
        <div style={{ padding: 12, opacity: 0.6 }}>输入实验 ID 并开始。</div>
      )}

      {st.report && (
        <section style={{ marginTop: 20, borderTop: "1px solid #ddd", paddingTop: 12 }}>
          <h3>报告（§6.2/§9.4，可复算）</h3>
          <ul>
            <li>偏好率：{Math.round((st.report.preference_rate || 0) * 100)}%
              （treatment {st.report.treatment_wins}/{st.report.non_tie_n}，平局 {st.report.ties}）</li>
            <li>双侧精确二项 p：{st.report.p_value}（最小胜场阈值 {st.report.min_wins_threshold}）</li>
            <li>token 倍率：{st.report.token_cost ? st.report.token_cost.token_multiplier : "—"}</li>
            <li>互异快照：{st.report.distinct_snapshot_count}
              （伪重复守卫 {st.report.pseudo_replication_ok ? "OK" : "⚠"}）</li>
            <li><b>决定：{DECISION_LABEL[st.report.decision] || st.report.decision}</b>
              {st.report.requires_fresh_replication ? "（消融升级前须再取一批 30 组复验）" : ""}</li>
          </ul>
          <p style={{ opacity: 0.7 }}>{st.report.rationale}</p>
        </section>
      )}
    </div>
  );
}

Object.assign(window, { WsEval, evStart, evVote, evLoadNext, evLoadReport, evSnapshot });
export { WsEval, evStart, evVote, evLoadNext, evLoadReport, evSnapshot, useEvalState };
