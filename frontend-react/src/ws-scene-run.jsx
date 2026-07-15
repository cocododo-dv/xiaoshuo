import React from "react";
import { I } from "./icons.jsx";
import { wsKey, WsWorks } from "./ws-works.jsx";
import { s2ExportState } from "./ws-snow.jsx";
import { WsCatalog } from "./ws-catalog.jsx";
import { cancelRunJob, getLatestSceneRunJob } from "./lib/client.js";

/* global React, I */
/* ==========================================================
   AI 起草台 — 真实运行引擎（catalog-sourced scenes）
   ----------------------------------------------------------
   把演示流水线的「预检 → 起草 → 质检 → 裁决 → 归档」落到实处：
   · 上下文：雪花构思（一句话 / 道德前提 / 读者定位 / 角色表）+ 章节卡
   · 起草：后端 scenes run 管线（run/jobs 投递 + 轮询，FE-ALIGN F6）
   · 质检：确定性、可解释——短句率 / 句式重复 / 超长句标红，不装神弄鬼
   · 归档：写入写作器正文文档（wr-doc:sid）+ 字数回写 + 场景卡置 done
   · 持久化：每场的运行结果存 scn-run:sid（按作品隔离），刷新不丢
   ========================================================== */

const SCN_RUN_FIELDS = ["state", "draft", "metrics", "alignment", "verdict", "log", "attempts", "attempt", "at", "words", "gate", "budgetBlock"];
const scnRunKey = (sid) => (wsKey ? wsKey("scn-run:" + sid) : "scn-run:" + sid);
const scnQueueKey = () => (wsKey ? wsKey("scn-queue:v1") : "scn-queue:v1");

const RUN_JOB_POLLING_STATUSES = new Set(["queued", "running", "cancel_requested"]);
const RUN_JOB_CANCELABLE_STATUSES = new Set(["queued", "running"]);
const RUN_JOB_TERMINAL_STATUSES = new Set(["cancelled", "completed", "failed", "blocked"]);
const RUN_JOB_STATUS_LABELS = {
  queued: "排队中",
  running: "运行中",
  cancel_requested: "正在取消",
  cancelled: "已取消",
  completed: "已完成",
  failed: "运行失败",
  blocked: "已阻断",
};

function runJobErrorText(error) {
  const code = error && error.code ? String(error.code) : "REQUEST_FAILED";
  const message = error && error.message ? String(error.message) : "请求失败";
  const details = error && error.details && typeof error.details === "object"
    ? Object.entries(error.details)
      .filter(([, value]) => value !== null && value !== undefined && value !== "")
      .map(([key, value]) => `${key}: ${typeof value === "object" ? JSON.stringify(value) : value}`)
      .join(" · ")
    : "";
  return `${code} · ${message}${details ? ` · ${details}` : ""}`;
}

function isRunJobStateRegression(currentJob, nextJob) {
  if (!currentJob || !nextJob || currentJob.job_id !== nextJob.job_id) return false;
  if (RUN_JOB_TERMINAL_STATUSES.has(currentJob.status)) {
    return currentJob.status !== nextJob.status;
  }
  if (currentJob.status === "cancel_requested") {
    return nextJob.status === "queued" || nextJob.status === "running";
  }
  return currentJob.status === "running" && nextJob.status === "queued";
}

function SceneRunJobControl({
  sceneId,
  observedJob = null,
  onJobChange = null,
  pollIntervalMs = 2000,
  refreshSignal = 0,
}) {
  const [job, setJob] = React.useState(null);
  const [loading, setLoading] = React.useState(Boolean(sceneId));
  const [cancelling, setCancelling] = React.useState(false);
  const [errorText, setErrorText] = React.useState("");
  const jobRef = React.useRef(null);
  const sceneRef = React.useRef(sceneId || "");
  const epochRef = React.useRef(0);
  const requestVersionRef = React.useRef(0);
  const cancelInFlightRef = React.useRef(false);
  const refreshInFlightRef = React.useRef(false);
  const refreshAbortRef = React.useRef(null);
  const cancelAbortRef = React.useRef(null);
  const onJobChangeRef = React.useRef(onJobChange);

  React.useEffect(() => {
    onJobChangeRef.current = onJobChange;
  }, [onJobChange]);

  const publishJob = React.useCallback((nextJob, epoch = epochRef.current) => {
    if (epoch !== epochRef.current) return false;
    const expectedSceneId = sceneRef.current;
    if (
      nextJob
      && nextJob.scene_id
      && expectedSceneId
      && String(nextJob.scene_id) !== String(expectedSceneId)
    ) {
      return false;
    }
    if (isRunJobStateRegression(jobRef.current, nextJob)) return false;
    jobRef.current = nextJob || null;
    setJob(nextJob || null);
    if (onJobChangeRef.current) onJobChangeRef.current(nextJob || null);
    return true;
  }, []);

  const refreshLatest = React.useCallback(async ({ silent = false, epoch = epochRef.current, force = false } = {}) => {
    const targetSceneId = sceneRef.current;
    if (!targetSceneId || epoch !== epochRef.current || (refreshInFlightRef.current && !force)) return null;
    if (force && refreshAbortRef.current) refreshAbortRef.current.abort();
    const requestVersion = requestVersionRef.current + 1;
    requestVersionRef.current = requestVersion;
    const controller = new AbortController();
    refreshAbortRef.current = controller;
    refreshInFlightRef.current = true;
    if (!silent) setLoading(true);
    try {
      const latest = await getLatestSceneRunJob(targetSceneId, { signal: controller.signal });
      if (requestVersion !== requestVersionRef.current) return null;
      if (publishJob(latest, epoch) && !silent) setErrorText("");
      return latest;
    } catch (error) {
      if (epoch !== epochRef.current || requestVersion !== requestVersionRef.current) return null;
      if (error && (error.status === 404 || error.code === "RUN_JOB_NOT_FOUND")) {
        publishJob(null, epoch);
        if (!silent) setErrorText("");
        return null;
      }
      if (!silent) setErrorText(runJobErrorText(error));
      return null;
    } finally {
      if (refreshAbortRef.current === controller) refreshAbortRef.current = null;
      if (epoch === epochRef.current && requestVersion === requestVersionRef.current) {
        refreshInFlightRef.current = false;
        if (!silent) setLoading(false);
      }
    }
  }, [publishJob]);

  React.useEffect(() => {
    const epoch = epochRef.current + 1;
    epochRef.current = epoch;
    requestVersionRef.current += 1;
    if (refreshAbortRef.current) refreshAbortRef.current.abort();
    if (cancelAbortRef.current) cancelAbortRef.current.abort();
    refreshAbortRef.current = null;
    cancelAbortRef.current = null;
    sceneRef.current = sceneId || "";
    refreshInFlightRef.current = false;
    cancelInFlightRef.current = false;
    jobRef.current = null;
    setCancelling(false);
    setErrorText("");
    publishJob(null, epoch);
    if (!sceneId) {
      setLoading(false);
      return () => {
        if (epochRef.current === epoch) epochRef.current += 1;
      };
    }
    void refreshLatest({ epoch });
    return () => {
      if (epochRef.current === epoch) epochRef.current += 1;
      if (refreshAbortRef.current) refreshAbortRef.current.abort();
      if (cancelAbortRef.current) cancelAbortRef.current.abort();
      refreshAbortRef.current = null;
      cancelAbortRef.current = null;
      refreshInFlightRef.current = false;
      cancelInFlightRef.current = false;
    };
  }, [sceneId, publishJob, refreshLatest]);

  React.useEffect(() => {
    if (!observedJob || !sceneId) return;
    // A POST response is newer than any latest request already in flight.
    requestVersionRef.current += 1;
    if (refreshAbortRef.current) refreshAbortRef.current.abort();
    refreshAbortRef.current = null;
    refreshInFlightRef.current = false;
    publishJob(observedJob);
  }, [observedJob, sceneId, publishJob]);

  /* 归档等页面动作后由父组件递增 refreshSignal：终态 job 不轮询，
     不刷新的话横幅会停留在旧暂停点（如 awaiting_candidate_selection）。 */
  React.useEffect(() => {
    if (!sceneId || !refreshSignal) return;
    void refreshLatest({ silent: true, force: true });
  }, [refreshSignal, sceneId, refreshLatest]);

  React.useEffect(() => {
    if (!sceneId || !job || !RUN_JOB_POLLING_STATUSES.has(job.status)) return undefined;
    const timer = window.setInterval(() => {
      void refreshLatest({ silent: true });
    }, Math.max(1, pollIntervalMs));
    return () => window.clearInterval(timer);
  }, [sceneId, job && job.job_id, job && job.status, pollIntervalMs, refreshLatest]);

  const requestCancellation = React.useCallback(async () => {
    const currentJob = job;
    if (
      !currentJob
      || !RUN_JOB_CANCELABLE_STATUSES.has(currentJob.status)
      || cancelInFlightRef.current
    ) {
      return;
    }
    const epoch = epochRef.current;
    requestVersionRef.current += 1;
    if (refreshAbortRef.current) refreshAbortRef.current.abort();
    refreshAbortRef.current = null;
    refreshInFlightRef.current = false;
    cancelInFlightRef.current = true;
    const controller = new AbortController();
    cancelAbortRef.current = controller;
    setCancelling(true);
    setErrorText("");
    try {
      const nextJob = await cancelRunJob(currentJob.job_id, { signal: controller.signal });
      if (epoch !== epochRef.current) return;
      if (
        !jobRef.current
        || jobRef.current.job_id !== currentJob.job_id
      ) {
        await refreshLatest({ silent: true, epoch, force: true });
        return;
      }
      requestVersionRef.current += 1;
      refreshInFlightRef.current = false;
      publishJob(nextJob, epoch);
    } catch (error) {
      if (epoch !== epochRef.current) return;
      if (
        !jobRef.current
        || jobRef.current.job_id !== currentJob.job_id
        || !RUN_JOB_CANCELABLE_STATUSES.has(jobRef.current.status)
      ) {
        await refreshLatest({ silent: true, epoch, force: true });
        return;
      }
      setErrorText(runJobErrorText(error));
      if (error && error.status === 409) {
        await refreshLatest({ silent: true, epoch, force: true });
      }
    } finally {
      if (cancelAbortRef.current === controller) cancelAbortRef.current = null;
      if (epoch === epochRef.current) {
        cancelInFlightRef.current = false;
        setCancelling(false);
      }
    }
  }, [job, publishJob, refreshLatest]);

  if (!sceneId) return null;

  const status = job && job.status ? job.status : "none";
  const statusLabel = loading && !job
    ? "正在恢复运行任务"
    : (RUN_JOB_STATUS_LABELS[status] || (job ? status : "暂无运行任务"));
  const showCancel = Boolean(job && RUN_JOB_CANCELABLE_STATUSES.has(status));
  const showCancelling = Boolean(job && status === "cancel_requested");

  return (
    <div
      className="scn2-decide is-wait"
      data-testid="scene-run-job-control"
      data-status={status}
      data-job-id={(job && job.job_id) || ""}
    >
      <div
        className="scn2-decide-sum"
        role="status"
        aria-live="polite"
        aria-atomic="true"
      >
        {RUN_JOB_POLLING_STATUSES.has(status) && <span className="scn2-spin" aria-hidden="true" />}
        <span>
          运行任务 · {statusLabel}
          {job && job.current_step ? ` · ${job.current_step}` : ""}
        </span>
      </div>
      <div className="scn2-decide-acts">
        {errorText && <span role="alert" data-testid="scene-run-cancel-error">{errorText}</span>}
        {showCancel && (
          <button
            type="button"
            className="btn btn-accent btn-sm"
            data-testid="scene-run-cancel-button"
            disabled={cancelling}
            aria-disabled={cancelling ? "true" : "false"}
            onClick={requestCancellation}
          >
            {cancelling ? "正在提交取消…" : "取消运行"}
          </button>
        )}
        {showCancelling && (
          <button
            type="button"
            className="btn btn-ghost btn-sm"
            data-testid="scene-run-cancel-button"
            disabled
            aria-disabled="true"
          >
            取消处理中
          </button>
        )}
      </div>
    </div>
  );
}

function scnRunLoad(sid) {
  try { return JSON.parse(localStorage.getItem(scnRunKey(sid))) || null; } catch (e) { return null; }
}
function scnRunSave(sid, run) {
  try {
    const slim = {}; SCN_RUN_FIELDS.forEach(f => { if (run[f] !== undefined) slim[f] = run[f]; });
    localStorage.setItem(scnRunKey(sid), JSON.stringify(slim));
  } catch (e) {}
}
function scnQueueLoad() {
  try { return JSON.parse(localStorage.getItem(scnQueueKey())) || []; } catch (e) { return []; }
}
function scnQueueSave(sids) {
  try { localStorage.setItem(scnQueueKey(), JSON.stringify(sids.slice(0, 40))); } catch (e) {}
}

/* ---- 上游上下文：雪花构思折叠成提示词材料 ---- */
function scnSnowContext() {
  try {
    const st = s2ExportState ? s2ExportState() : null;
    if (!st) return "";
    const d = st.drafts || {}, sc = st.scaffolds || {};
    const lines = [];
    const logline = (d.logline || "").trim();
    if (logline) lines.push("一句话概括：" + logline);
    const para = sc.paragraph || {};
    if ((para.premiseF || "").trim() || (para.premiseT || "").trim()) lines.push(`道德前提：「${para.premiseF || "—"}」→ 中点翻转为 →「${para.premiseT || "—"}」`);
    const aud = sc.audience || {};
    if ((aud.pleasure || "").trim()) lines.push("读者核心快感：" + aud.pleasure.trim());
    if ((aud.exclude || "").trim()) lines.push("明确不写：" + aud.exclude.trim());
    const chars = ((sc.characters || {}).chars) || {};
    const cl = Object.values(chars).filter(c => (c.name || "").trim()).slice(0, 5)
      .map(c => `${c.name}（${c.role}）：目标「${c.goal || "—"}」· 没有什么比「${c.values || "—"}」更重要`);
    if (cl.length) lines.push("角色表：\n" + cl.join("\n"));
    return lines.join("\n");
  } catch (e) { return ""; }
}

function scnBuildPrompt(item, note, prevText) {
  const hit = item.sid && WsCatalog ? WsCatalog.sceneById(item.sid) : null;
  const c = hit ? hit.chapter : null;
  const s = hit ? hit.scene : {};
  const reactive = (s.kind || item.kind || "").includes("反应");
  const ctx = scnSnowContext();
  const trio = reactive
    ? `这是「反应场景（RDD）」：\n· 反应（情绪先于理性）：${s.goal || "—"}\n· 两难（没有好选项）：${s.obstacle || "—"}\n· 决定（选一个坏选项，成为下一场目标）：${s.turn || "—"}`
    : `这是「主动场景（GCS）」：\n· 目标（具体可拍摄）：${s.goal || "—"}\n· 冲突（逐级受阻）：${s.obstacle || "—"}\n· 挫败（结尾比开场更糟）：${s.turn || "—"}`;
  return [
    "你是长篇小说的场景起草助手。为下面这一场写正文初稿。",
    ctx ? "【作品上下文 · 与之严格一致】\n" + ctx : "",
    c ? `【本章】第 ${c.n} 章《${c.title}》${(c.promise || "").trim() ? " · 章承诺：" + c.promise.trim() : ""}` : "",
    `【本场】《${s.title || item.title}》${c && (c.pov || "").trim() ? " · POV：" + c.pov : ""}`,
    trio,
    prevText ? "【上一版草稿 · 按指令改写而非重来】\n" + prevText.slice(0, 1200) : "",
    note ? "【作者改写指令 · 最高优先级】\n" + note : "",
    "",
    "要求：限知视角；短句克制、动词驱动、少形容词；700–1100 字，分 5–8 段；",
    "结尾的拍（挫败/决定）必须落在最后一两段，为下一场留钩。",
    "只输出一个 JSON 对象，不要任何其它文字、不要代码围栏：",
    '{"paras":[{"beat":"goal|conflict|setback|exit 或 null","text":"段落正文"}]}',
    reactive ? "（反应场用 beat 标注：reaction→goal、dilemma→conflict、decision→exit 的对应拍）" : "（goal/conflict/setback 各标在落点段，最后一段可标 exit）",
  ].filter(Boolean).join("\n");
}

const SCN_BEAT_MAP = { goal: "goal", conflict: "conflict", setback: "setback", exit: "exit", reaction: "goal", dilemma: "conflict", decision: "exit" };
function scnParseDraft(raw) {
  if (!raw) throw new Error("空响应");
  let t = String(raw).trim().replace(/```json/gi, "").replace(/```/g, "").trim();
  const a = t.indexOf("{"), b = t.lastIndexOf("}");
  let paras = null;
  if (a >= 0 && b > a) {
    const body = t.slice(a, b + 1);
    try { const obj = JSON.parse(body); if (Array.isArray(obj.paras)) paras = obj.paras; } catch (e) {
      // 模型常在字符串里直接换行 → 控制字符让 JSON.parse 报错；拍平后重试
      try { const obj = JSON.parse(body.replace(/[\u0000-\u001f]+/g, " ")); if (Array.isArray(obj.paras)) paras = obj.paras; } catch (e2) {}
    }
  }
  if (!paras) {
    // 宽松抽取：逐对 "beat"/"text" 字段，容忍外层结构坏掉
    const found = [];
    let m;
    const re = /"beat"\s*:\s*(?:null|"([a-z]*)")\s*,\s*"text"\s*:\s*"((?:[^"\\]|\\.)*)"/g;
    while ((m = re.exec(t))) found.push({ beat: m[1] || null, text: m[2] });
    if (!found.length) {
      const re2 = /"text"\s*:\s*"((?:[^"\\]|\\.)*)"/g;
      while ((m = re2.exec(t))) found.push({ beat: null, text: m[1] });
    }
    if (found.length) paras = found;
  }
  if (!paras) {
    if (t.includes('"paras"')) throw new Error("模型输出无法解析，请重试一次");
    paras = t.split(/\n{2,}/).map(x => ({ beat: null, text: x.replace(/\n/g, "") })).filter(p => p.text.trim());
  }
  const unesc = (s) => s.replace(/\\n/g, "\n").replace(/\\"/g, '"').replace(/\\\\/g, "\\");
  const tidy = (s) => s.replace(/\s*\n\s*/g, "").replace(/([\u4e00-\u9fff\u3000-\u303f\uff00-\uffef])\s+(?=[\u4e00-\u9fff\u3000-\u303f\uff00-\uffef])/g, "$1").trim();
  const out = paras
    .map((p, i) => ({ id: "p" + (i + 1), beat: SCN_BEAT_MAP[p.beat] || null, text: tidy(unesc((p.text || "").toString())) }))
    .filter(p => p.text);
  if (!out.length) throw new Error("未能解析出正文段落");
  return out;
}

/* ---- 确定性质检：可解释、可复算 ---- */
function scnSentencesOf(text) {
  return text.split(/(?<=[。！？；…])/).map(s => s.trim()).filter(s => s.length > 1);
}
/* ---- 质检阈值：从 Tweaks 面板读，改动对已生成稿实时重算 ---- */
function scnQcTh() {
  const t = window.__scnQcTh || {};
  return { short: t.short || 55, repeat: t.repeat || 30, long: t.long || 64 };
}

function scnQC(paras, reactive) {
  const th = scnQcTh();
  const all = paras.map(p => p.text).join("");
  const sents = paras.flatMap(p => scnSentencesOf(p.text));
  const n = sents.length || 1;
  const shortRate = Math.round(100 * sents.filter(s => s.length <= 20).length / n);
  const openers = {};
  sents.forEach(s => { const k = s.slice(0, 2); openers[k] = (openers[k] || 0) + 1; });
  /* 句式重复：同一起手出现 ≥ 3 次才计（限知视角里「她」起句是正常的） */
  const repeated = Object.values(openers).filter(c => c >= 3).reduce((a, c) => a + c, 0);
  const repeatRate = Math.round(100 * repeated / n);
  const longs = sents.filter(s => s.length > th.long);

  // 把风险句标进段落 parts（写作台同款高亮）
  const risks = [];
  const draft = paras.map(p => {
    const parts = [];
    let rest = p.text;
    scnSentencesOf(p.text).forEach(s => {
      const at = rest.indexOf(s);
      if (at < 0) return;
      const isLong = s.length > th.long;
      const isRep = openers[s.slice(0, 2)] > 2;
      if (isLong || isRep) {
        if (at > 0) parts.push({ text: rest.slice(0, at) });
        const tip = isLong ? `超长句（${s.length} 字 > 阈值 ${th.long}）：考虑拆成两到三句` : `句首「${s.slice(0, 2)}」重复 ${openers[s.slice(0, 2)]} 次：换个起手`;
        parts.push({ risk: isLong ? "pace" : "repeat", sev: isLong ? "mid" : "low", text: s, tip });
        risks.push({ sev: isLong ? "mid" : "low" });
        rest = rest.slice(at + s.length);
      }
    });
    if (rest) parts.push({ text: rest });
    return { id: p.id, beat: p.beat, parts: parts.length ? parts : [{ text: p.text }] };
  });

  const metrics = [
    { label: "短句率",   pct: shortRate,  target: th.short,  val: shortRate + "%", tone: shortRate >= th.short ? "ok" : "warn" },
    { label: "句式重复", pct: repeatRate, target: th.repeat, val: repeatRate + "%", tone: repeatRate <= th.repeat ? "ok" : "warn" },
    { label: "超长句",   pct: Math.min(100, longs.length * 20), target: 20, val: longs.length + " 句", tone: longs.length <= 1 ? "ok" : "warn" },
  ];
  const beats = reactive ? ["goal", "conflict", "exit"] : ["goal", "conflict", "setback", "exit"];
  const noteOf = reactive
    ? { goal: "反应拍", conflict: "两难拍", exit: "决定拍" }
    : { goal: "目标拍", conflict: "冲突拍", setback: "挫败拍", exit: "出口拍" };
  const alignment = beats.map(b => {
    const p = paras.find(x => x.beat === b);
    return { beat: b, para: p ? p.id : null, status: p ? "ok" : "pend", note: p ? `${noteOf[b]}落在 ${p.id}` : `模型未标注${noteOf[b]}` };
  });
  const alignOk = alignment.filter(a => a.status === "ok").length;
  const warns = metrics.filter(m => m.tone === "warn").length + (risks.length ? 1 : 0);
  const words = all.replace(/\s/g, "").length;
  return {
    draft, metrics, alignment, words,
    verdict: {
      qc: warns ? "通过 · 有风险" : "通过",
      risks: risks.length ? `${risks.length} 处风险句` : "无风险句",
      align: `戏剧卡 ${alignOk}/${beats.length} 对齐`,
      words,
    },
  };
}

/* ---- 作者可见状态门（Wave 2 · 治理 §5.3/§5.4）----
   从 workbench/status 的 author_state 投影提取「无法继续 vs 有稿建议修改」：
   · hard_blocked（verified Q0/Q1）→ 不可归档，正文保留可接管
   · quality_warning（Q2/Q3）→ 有稿可归档，警告随行
   gate 随运行记录持久化，裁决条据此分开展示、归档前先拦。 ---- */
function scnGateFrom(src) {
  const a = src && src.author_state;
  if (!a || typeof a !== "object") return null;
  return {
    authorState: a.author_state || null,
    blocking: Array.isArray(a.blocking_findings) ? a.blocking_findings : [],
    warnings: Array.isArray(a.quality_warnings) ? a.quality_warnings : [],
    recommended: Array.isArray(a.recommended_actions) ? a.recommended_actions : [],
    canArchive: a.can_archive !== false,
  };
}

function scnGateLog(gate, tm) {
  if (!gate) return null;
  if (gate.authorState === "hard_blocked") {
    const keys = gate.blocking.map(f => f.issue_key || f.kind).filter(Boolean).join("、");
    return { t: tm, who: "pipeline", text: `无法继续：存在已证实的硬问题（Q0/Q1${keys ? "：" + keys : ""}）——正文已保留，处理后可续跑；此稿暂不可归档` };
  }
  if (gate.authorState === "quality_warning") {
    return { t: tm, who: "pipeline", text: `已有稿，建议修改：${gate.warnings.length} 条质量建议（Q2/Q3）随稿附上——可直接采纳归档，也可按建议改后重跑` };
  }
  return null;
}

/* ---- 完整一跑：后端 scenes run 管线（FE-ALIGN F6）----
   投递 run job（POST run/jobs）→ 轮询 run-jobs/{id} → workbench 取产出
   → 本地确定性复检。失败/阻塞给明确引导（执行契约缺字段 / LLM 未启用 /
   预检不过），不装假进度。scnBuildPrompt 保留作提示词参考（管线内由
   后端 config/prompts.yaml 组装）。 */
function scnFriendly(e) {
  const code = (e && e.code) || "";
  const msg = (e && e.message) || String(e || "");
  if (code === "SCENE_EXECUTION_CONTRACT_BLOCKED") {
    const miss = (((e && e.details) || {}).missing_fields || []).join("、");
    return new Error(`这一场的执行契约还缺关键字段${miss ? `（${miss}）` : ""}——先在章节编排把场景卡补全，或走「构思 → 物化」主路径生成完整场景卡。`);
  }
  if (code === "VOICE_PROFILE_MISSING" || code === "RELATION_PROFILE_MISSING") {
    // Fix C：缺声线/关系卡现可一键补齐最小卡解阻（scnCreateCards → /preflight/create-cards）
    const what = code === "VOICE_PROFILE_MISSING" ? "POV 声线卡" : "同场角色关系卡";
    const err = new Error(`这一场缺少可用的${what}，暂不能起草——可点「补齐声线卡并重试」一键生成后自动续跑，或在声线/关系工作台细化。`);
    err.code = code;
    err.canCreateCards = true; // 起草台据此在阻断态显示「补齐声线卡并重试」按钮
    return err;
  }
  if (/LLM/i.test(code) || /llm|provider|api.?key/i.test(msg)) {
    return new Error("AI 起草需要可用的 LLM：请到「系统设置 → 模型与接入」配置并启用后重试。原始信息：" + msg);
  }
  return new Error("起草失败：" + msg);
}

/* Fix C：一键补齐当前场景缺失的最小 voice/relation 卡(active)，解阻 run 预检。
   返回 { created, run_preflight }。这是 create_minimal_voice_card 预检动作的真实执行入口。 */
async function scnCreateCards(sid) { // eslint-disable-line no-unused-vars
  const { apiPost } = await import("./lib/client.js");
  const sceneId = WsCatalog && WsCatalog.__backendSceneId ? await WsCatalog.__backendSceneId(sid) : null;
  if (!sceneId) throw new Error("这一场还没同步到后端目录——稍候片刻或刷新后重试。");
  return apiPost(`/api/v1/scenes/${sceneId}/preflight/create-cards`, {});
}

function scnRewriteBriefFrom(src) {
  const reports = [src && src.hard_qc, src && src.soft_qc, src && src.latest_qc].filter(Boolean);
  for (const report of reports) {
    const brief = Array.isArray(report.rewrite_brief) ? report.rewrite_brief.filter(Boolean) : [];
    if (brief.length) return brief.join("；");
  }
  const projection = scnGateFrom(src);
  return ((projection && projection.blocking) || [])
    .map(f => f.human_readable_reason || f.message || f.issue_key || f.kind)
    .filter(Boolean)
    .join("；");
}

const SCN_LIFECYCLE_BUDGET_CODES = new Set([
  "LLM_SCENE_TOKEN_BUDGET_EXHAUSTED",
  "LLM_BUSINESS_ATTEMPT_BUDGET_EXHAUSTED",
  "LLM_PROVIDER_ATTEMPT_BUDGET_EXHAUSTED",
]);

function scnBudgetBlock(job, workbench) {
  const code = String((job && job.error_code) || "");
  if (!SCN_LIFECYCLE_BUDGET_CODES.has(code)) return null;
  const lifecycle = (workbench && workbench.scene_run_state && workbench.scene_run_state.lifecycle_budget) || {};
  let topup;
  let label;
  if (code === "LLM_SCENE_TOKEN_BUDGET_EXHAUSTED") {
    const suggested = Number(lifecycle.recommended_topup_tokens || lifecycle.baseline_tokens || 6400);
    topup = { extra_tokens: Math.max(1, Math.trunc(suggested)) };
    label = "本场 token 生命周期预算已到派发边界";
  } else if (code === "LLM_BUSINESS_ATTEMPT_BUDGET_EXHAUSTED") {
    topup = { extra_attempts: 1 };
    label = "本场业务尝试预算已用完";
  } else {
    topup = { extra_provider_attempts: 1 };
    label = "本场 provider 尝试预算已用完";
  }
  return {
    code,
    label,
    message: String((job && job.error_text) || "生命周期预算耗尽；已有正文已保留"),
    currentStep: String((job && job.current_step) || "blocked"),
    lifecycle,
    topup,
  };
}

async function scnTopupBudget(sid, budgetBlock) { // eslint-disable-line no-unused-vars
  const { apiPost } = await import("./lib/client.js");
  const sceneId = WsCatalog && WsCatalog.__backendSceneId ? await WsCatalog.__backendSceneId(sid) : null;
  if (!sceneId) throw new Error("这一场还没同步到后端目录——稍候片刻或刷新后重试。");
  const raw = budgetBlock && budgetBlock.topup && typeof budgetBlock.topup === "object"
    ? budgetBlock.topup
    : {};
  const topup = Object.fromEntries(Object.entries(raw).filter(([, value]) => Number.isInteger(value) && value > 0));
  if (!Object.keys(topup).length) throw new Error("没有可执行的生命周期预算追加量。");
  return apiPost(`/api/v1/scenes/${sceneId}/budget/topup`, {
    ...topup,
    reason: "作者在起草台确认追加生命周期预算并从持久化检查点继续",
  });
}

function scnRunUiAbortError() {
  const error = new Error("scene run UI tracking stopped");
  error.code = "SCENE_RUN_UI_ABORTED";
  return error;
}

function scnThrowIfAborted(signal) {
  if (signal && signal.aborted) throw scnRunUiAbortError();
}

function scnPollDelay(delayMs, signal) {
  scnThrowIfAborted(signal);
  if (!signal) return new Promise(resolve => setTimeout(resolve, delayMs));
  return new Promise((resolve, reject) => {
    const finish = () => {
      signal.removeEventListener("abort", abort);
      resolve();
    };
    const abort = () => {
      clearTimeout(timer);
      reject(scnRunUiAbortError());
    };
    const timer = setTimeout(finish, delayMs);
    signal.addEventListener("abort", abort, { once: true });
  });
}

async function scnRun(item, note, prevText, lifecycle = {}) { // eslint-disable-line no-unused-vars
  const { apiGet, apiPost } = await import("./lib/client.js");
  const signal = lifecycle && lifecycle.signal;
  const trackedGet = (path) => signal ? apiGet(path, { signal }) : apiGet(path);
  const trackedPost = (path, body) => signal ? apiPost(path, body, { signal }) : apiPost(path, body);
  scnThrowIfAborted(signal);
  const sceneId = WsCatalog && WsCatalog.__backendSceneId
    ? await WsCatalog.__backendSceneId(item.sid)
    : null;
  scnThrowIfAborted(signal);
  if (!sceneId) throw new Error("这一场还没同步到后端目录——稍候片刻或刷新后重试。");
  const t0 = Date.now();
  let job;
  // G3：作者改写指令随任务下发（后端注入风格生成阶段的提示词）
  // 起草台是作者在场的交互式工作流：严格模式把 Q2 建议停在可采纳态，
  // 由“采纳并归档”留下明确接受记录；无 Q2 时后端仍可按契约自动完成。
  const body = { run_policy: (lifecycle && lifecycle.runPolicy) || "strict" };
  if (note && String(note).trim()) body.author_note = String(note).trim().slice(0, 500);
  if (lifecycle && lifecycle.resumeBudget === true) body.resume_budget = true;
  try {
    job = await trackedPost(`/api/v1/scenes/${sceneId}/run/jobs`, body);
  } catch (e) {
    scnThrowIfAborted(signal);
    throw scnFriendly(e);
  }
  scnThrowIfAborted(signal);
  try {
    if (lifecycle && typeof lifecycle.onJobCreated === "function") {
      lifecycle.onJobCreated(job, sceneId);
    }
  } catch (e) {}
  const TERMINAL = ["completed", "blocked", "failed", "cancelled"];
  let last = job;
  const deadline = Date.now() + 5 * 60 * 1000;
  while (!TERMINAL.includes(last.status)) {
    if (Date.now() > deadline) throw new Error("起草超时（5 分钟）——后台任务可能仍在运行，稍后可在质检台查看产出。");
    await scnPollDelay(2000, signal);
    scnThrowIfAborted(signal);
    try {
      last = await trackedGet(`/api/v1/run-jobs/${job.job_id}`);
    } catch (e) {
      scnThrowIfAborted(signal);
    }
  }
  scnThrowIfAborted(signal);
  /* 终态后先看产出：需人工审阅的 blocked 也可能已有草稿，照实呈现 */
  let wb = null;
  try { wb = await trackedGet(`/api/v1/scenes/${sceneId}/workbench`); } catch (e) {}
  scnThrowIfAborted(signal);
  const content = (wb && ((wb.final_scene && wb.final_scene.content)
    || (wb.style_draft && wb.style_draft.content)
    || (wb.neutral_draft && wb.neutral_draft.content))) || "";
  const budgetBlock = scnBudgetBlock(last, wb);
  if (!content.trim()) {
    if (budgetBlock) {
      const error = new Error(`${budgetBlock.label}——可显式追加后从持久化检查点继续。`);
      error.code = budgetBlock.code;
      error.budgetBlock = budgetBlock;
      throw error;
    }
    // Fix A：异步任务现透出结构化 missing_fields（与同步 run/full 同源）→ 引导能点名缺哪些字段
    throw scnFriendly({ code: last.error_code || "", message: last.error_text || `任务以「${last.status}」结束且没有产出正文（${last.current_step || "—"}）`, details: { missing_fields: last.missing_fields || [] } });
  }
  const paras = content.split(/\n{2,}|\n/).map((x, i) => ({ id: "p" + (i + 1), beat: null, text: x.trim() })).filter(p => p.text);
  const hit = item.sid && WsCatalog ? WsCatalog.sceneById(item.sid) : null;
  const reactive = ((hit && hit.scene.kind) || item.kind || "").includes("反应");
  const qc = scnQC(paras, reactive);
  const secs = Math.round((Date.now() - t0) / 1000);
  const tm = (off) => new Date(t0 + off * 1000).toTimeString().slice(0, 8);
  const pipeState = wb && wb.scene_run_state ? wb.scene_run_state.scene_status : last.status;
  // Wave 2：提取作者可见状态门（无法继续 vs 有稿建议修改），随运行记录持久化
  qc.gate = scnGateFrom(wb);
  qc.rewriteBrief = scnRewriteBriefFrom(wb);
  // reliable/无警告路径可能已经由后端原子归档。不能把 author_state=archived
  // 的 can_archive=false 误渲染成 Q0/Q1 阻断，也不能再展示待裁决按钮。
  qc.state = pipeState === "archived" ? "archived" : "ready";
  qc.budgetBlock = budgetBlock;
  if (budgetBlock) {
    qc.gate = {
      ...(qc.gate || { authorState: null, blocking: [], warnings: [], recommended: [] }),
      canArchive: false,
      blockReason: "lifecycle_budget",
    };
  }
  qc.log = [
    { t: tm(0), who: "system", text: "已投递后端起草任务（scenes run 管线：预检 → 蓝图 → 起草 → 硬/软双层质检）" },
    note ? { t: tm(0), who: "system", text: "改写指令已随任务下发（注入风格生成阶段，优先级最高）" } : null,
    { t: tm(secs), who: "pipeline", text: `管线结束 · 任务 ${last.status} · 场景状态 ${pipeState} · ${qc.words} 字 · 用时 ${secs}s` },
    budgetBlock
      ? { t: tm(secs), who: "pipeline", text: `${budgetBlock.label}；已有正文与恢复点均已保留，需作者显式追加预算后续跑` }
      : scnGateLog(qc.gate, tm(secs)),
    { t: tm(secs + 1), who: "qc", text: `本地复检：短句率 ${qc.metrics[0].val} · 句式重复 ${qc.metrics[1].val} · ${qc.verdict.risks}` },
  ].filter(Boolean);
  qc.cost = [
    { k: "起草", v: `后端管线 · ${secs}s` },
    { k: "质检", v: "硬/软双层 + 本地复检" },
    { k: "字数", v: String(qc.words), mono: true },
  ];
  return qc;
}

/* ---- 后端水合：本地没有运行记录（换浏览器 / 页面关闭前没取回）时，
   从 scenes workbench 恢复这一场的最新产出为一条可裁决的运行。
   队列/运行记录此前只活在 localStorage，后端 SceneRunState 才是管线真相——
   这是「起草台各自为战」的补缝。目录场景卡已 done 的按已归档呈现。 ---- */
async function scnHydrateFromBackend(sid, { signal, terminalJob } = {}) {
  const { apiGet } = await import("./lib/client.js");
  scnThrowIfAborted(signal);
  const sceneId = WsCatalog && WsCatalog.__backendSceneId ? await WsCatalog.__backendSceneId(sid) : null;
  scnThrowIfAborted(signal);
  if (!sceneId) return null;
  let wb = null;
  try {
    wb = signal
      ? await apiGet(`/api/v1/scenes/${sceneId}/workbench`, { signal })
      : await apiGet(`/api/v1/scenes/${sceneId}/workbench`);
  } catch (e) {
    scnThrowIfAborted(signal);
    return null;
  }
  const content = (wb && ((wb.final_scene && wb.final_scene.content)
    || (wb.style_draft && wb.style_draft.content)
    || (wb.neutral_draft && wb.neutral_draft.content))) || "";
  if (!content.trim()) return null;
  const paras = content.split(/\n{2,}|\n/).map((x, i) => ({ id: "p" + (i + 1), beat: null, text: x.trim() })).filter(p => p.text);
  if (!paras.length) return null;
  const hit = WsCatalog ? WsCatalog.sceneById(sid) : null;
  const reactive = ((hit && hit.scene && hit.scene.kind) || "").includes("反应");
  const qc = scnQC(paras, reactive);
  const pipeState = (wb && wb.scene_run_state && wb.scene_run_state.scene_status) || "";
  const done = !!(hit && hit.scene && hit.scene.state === "done") || pipeState === "archived";
  const now = new Date().toTimeString().slice(0, 8);
  qc.state = done ? "archived" : "ready";
  qc.attempt = 1;
  qc.at = Date.now();
  qc.gate = scnGateFrom(wb);
  qc.rewriteBrief = scnRewriteBriefFrom(wb);
  qc.budgetBlock = scnBudgetBlock(terminalJob, wb);
  if (qc.budgetBlock) {
    qc.gate = {
      ...(qc.gate || { authorState: null, blocking: [], warnings: [], recommended: [] }),
      canArchive: false,
      blockReason: "lifecycle_budget",
    };
  }
  qc.attempts = [{ n: 1, time: "后端恢复", result: done ? "已归档" : "待裁决", tone: done ? "sage" : "gold", note: "从后端管线取回的最新产出" }];
  qc.log = [
    { t: now, who: "system", text: `已从后端恢复这一场的最新产出（场景状态 ${pipeState || "—"}）——运行在别处完成或页面关闭前未取回` },
    scnGateLog(qc.gate, now),
    { t: now, who: "qc", text: `本地复检：短句率 ${qc.metrics[0].val} · 句式重复 ${qc.metrics[1].val} · ${qc.verdict.risks}` },
  ].filter(Boolean);
  qc.cost = [
    { k: "起草", v: "后端管线 · 已恢复" },
    { k: "质检", v: "硬/软双层 + 本地复检" },
    { k: "字数", v: String(qc.words), mono: true },
  ];
  return qc;
}

/* ---- 队列成员的后端派生（贯通轮遗留 ①）：项目内进过管线的场
   （GET /scene-run-states，scene_status 已离开 ready）→ sid 列表。
   队列的 localStorage 从此退化为这份管线真相的读缓存——换浏览器时
   队列成员可恢复，各场产出再经 scnHydrateFromBackend 逐场取回。 ---- */
async function scnBackendQueueSids() {
  const { apiGet } = await import("./lib/client.js");
  const workId = WsWorks ? WsWorks.activeId() : null;
  if (!workId || workId === "__loading__") return [];
  let data = null;
  try { data = await apiGet(`/api/v1/scene-run-states?project_id=${encodeURIComponent(workId)}`); } catch (e) { return []; }
  const items = (data && data.items) || [];
  if (!items.length) return [];
  try {
    if (WsCatalog && !WsCatalog.get().length && WsCatalog.__refresh) await WsCatalog.__refresh(workId);
  } catch (e) {}
  const bySceneId = {};
  try {
    (WsCatalog ? WsCatalog.get() : []).forEach(c => (c.scenes || []).forEach(s => { if (s.backendId) bySceneId[s.backendId] = s.sid; }));
  } catch (e) {}
  // 端点按 updated_at 倒序返回：最近有动静的场排前面
  return items.map(it => bySceneId[it.scene_id]).filter(Boolean);
}

/* ---- 候选终选（Wave 3 · 治理 §5.5）----
   关键场景管线暂停在 awaiting_author_choice：盲化候选（后端 blinded_order
   随机序、默认无分数）→ 作者整稿选择 → resume 从批判修订/QC 续跑到归档。
   终选一次写入：改选须显式 reopen（后端锁定，SELECTION_LOCKED 上抛）。 ---- */
async function scnBackendIdOf(sid) {
  const sceneId = WsCatalog && WsCatalog.__backendSceneId ? await WsCatalog.__backendSceneId(sid) : null;
  if (!sceneId) throw new Error("这一场还没同步到后端目录——稍候片刻或刷新后重试。");
  return sceneId;
}
async function scnCandidates(sid) {
  const { apiGet } = await import("./lib/client.js");
  const sceneId = await scnBackendIdOf(sid);
  return apiGet(`/api/v1/scenes/${sceneId}/style-candidates`);
}
async function scnSelectCandidate(sid, rowId, opts) {
  const { apiPost } = await import("./lib/client.js");
  const sceneId = await scnBackendIdOf(sid);
  return apiPost(`/api/v1/scenes/${sceneId}/style-candidates/${encodeURIComponent(rowId)}/select`, opts || {});
}
async function scnResumeAfterSelection(sid) {
  const { apiPost } = await import("./lib/client.js");
  const sceneId = await scnBackendIdOf(sid);
  return apiPost(`/api/v1/scenes/${sceneId}/resume-after-selection`, {});
}

/* ---- 归档（Wave 1 · 治理 §5.2 归档单入口）----
   「完成」的真值在后端：先 POST adopt-current（服务端归档事务建/提升
   FinalScene 并置权威 archived 态），成功响应后才写写作器缓存、回写字数、
   目录卡置 done——done 只由服务端 archived 响应映射，不再先本地置位。
   后端拒绝（无稿 NO_VALID_DRAFT / 来源安全 SOURCE_SAFETY_BLOCKED）时
   不动本地任何状态，faithful 返回失败原因。 ---- */
function scnEscape(s) { return s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;"); }
async function scnAdoptToDoc(sid, draft, gate) {
  if (!sid || !WsCatalog) return { ok: false, reason: "没有场景卡" };
  // Wave 2（治理 §5.4）：只有真实 Q0/Q1 阻断归档——gate 前置拦截给即时反馈，
  // 后端 adopt-current 的 HARD_BLOCKED 409 仍是权威裁决（绕过前端也拦得住）。
  if (gate && gate.canArchive === false) {
    const keys = (gate.blocking || []).map(f => f.issue_key || f.kind).filter(Boolean).join("、");
    return { ok: false, reason: `存在已证实的硬问题（Q0/Q1${keys ? "：" + keys : ""}），暂不能归档——正文已保留，处理或重跑后再采纳` };
  }
  const html = (draft || []).map(p => "<p>" + scnEscape(p.parts.map(x => x.text).join("")) + "</p>").join("");
  const text = (draft || []).map(p => p.parts.map(x => x.text).join("")).join("");
  const key = wsKey ? wsKey("wr-doc:" + sid) : "wr-doc:" + sid;
  let existing = "";
  try { existing = localStorage.getItem(key) || ""; } catch (e) {}
  const hasReal = existing && existing.replace(/<[^>]+>/g, "").replace(/\s/g, "").length > 0 && !existing.includes("在这里开始写这一场");
  if (hasReal && !window.confirm("这一场在写作器里已有正文。归档会覆盖现有正文（写作器的版本会丢失），确定继续？")) {
    return { ok: false, reason: "已取消" };
  }
  // 1) 后端归档单入口（先于一切本地写入）
  let sceneId = null;
  try { sceneId = WsCatalog.__backendSceneId ? await WsCatalog.__backendSceneId(sid) : null; } catch (e) {}
  if (!sceneId) return { ok: false, reason: "这一场还没同步到后端目录——稍候片刻或刷新后重试" };
  try {
    const { apiPost } = await import("./lib/client.js");
    await apiPost(`/api/v1/scenes/${sceneId}/adopt-current`, {});
  } catch (e) {
    const code = (e && e.code) || "";
    const msg = (e && e.message) || String(e || "");
    return { ok: false, reason: `后端归档未通过（${code || "网络错误"}）：${msg}` };
  }
  // 2) 归档成功 → 正文写穿 author-drafts 主路径（WrDocs 缓存+PATCH）
  try {
    if (window.WrDocs) await window.WrDocs.save(sid, html);
    else localStorage.setItem(key, html);
  } catch (e) { return { ok: false, reason: "写入失败" }; }
  const hit = WsCatalog.sceneById(sid);
  const prev = hit && typeof hit.scene.words === "number" ? hit.scene.words : 0;
  const count = text.replace(/\s/g, "").length;
  try { WsCatalog.recordSceneWords(sid, count, prev); } catch (e) {}
  try {
    WsCatalog.set(WsCatalog.get().map(c => ({
      ...c, scenes: (c.scenes || []).map(s => s.sid === sid ? { ...s, state: "done" } : s),
    })));
  } catch (e) {}
  // 3) 治理设计项 4：归档后重新拉服务端状态（起草台运行记录与管线真相收敛）
  try {
    const { apiGet } = await import("./lib/client.js");
    const status = await apiGet(`/api/v1/scenes/${sceneId}/status`);
    return { ok: true, words: count, serverStatus: (status && status.scene_status) || "archived", authorState: status && status.author_state };
  } catch (e) {
    return { ok: true, words: count, serverStatus: "archived" };
  }
}

/* 已生成稿件的实时重算：阈值改动后，风险标记 / 指标 / 判词跟着变 */
function scnReQC(draft, kind) {
  try {
    const paras = (draft || []).map(p => ({ id: p.id, beat: p.beat, text: p.parts.map(x => x.text).join("") }));
    if (!paras.length) return null;
    return scnQC(paras, (kind || "").includes("反应"));
  } catch (e) { return null; }
}

/* ---- 选场器数据：目录里可入列的场 ---- */
function scnPickList(queuedSids) {
  const q = new Set(queuedSids || []);
  try {
    return (WsCatalog ? WsCatalog.get() : []).map(c => ({
      id: c.id, n: c.n, title: c.title,
      scenes: (c.scenes || []).map(s => ({
        sid: s.sid, title: s.title, kind: s.kind, state: s.state,
        ready: !!((s.goal || "").trim() && !(s.goal || "").includes("待规划")),
        queued: q.has(s.sid),
        hasDraft: !!scnRunLoad(s.sid),
      })),
    })).filter(c => c.scenes.length);
  } catch (e) { return []; }
}

Object.assign(window, { scnRun, scnCreateCards, scnTopupBudget, scnAdoptToDoc, scnPickList, scnRunLoad, scnRunSave, scnQueueLoad, scnQueueSave, scnQC, scnReQC, scnBuildPrompt, scnParseDraft, scnHydrateFromBackend, scnBackendQueueSids, scnGateFrom, scnRewriteBriefFrom, scnCandidates, scnSelectCandidate, scnResumeAfterSelection });

/* ESM 导出（Phase 1 机械追加；window.* 赋值过渡期保留） */
export { SceneRunJobControl, scnRun, scnCreateCards, scnTopupBudget, scnAdoptToDoc, scnPickList, scnRunLoad, scnRunSave, scnQueueLoad, scnQueueSave, scnQC, scnReQC, scnBuildPrompt, scnParseDraft, scnHydrateFromBackend, scnBackendQueueSids, scnGateFrom, scnRewriteBriefFrom, scnCandidates, scnSelectCandidate, scnResumeAfterSelection };
