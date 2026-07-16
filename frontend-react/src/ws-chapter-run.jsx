import React from "react";
import { I } from "./icons.jsx";
import { apiGet, apiPost } from "./lib/client.js";
import { WsCatalog } from "./ws-catalog.jsx";
import { WsWorks } from "./ws-works.jsx";

const { useEffect, useRef, useState } = React;

const ACTIVE_STATUSES = new Set(["submitting", "pending", "running"]);
const TERMINAL_STATUSES = new Set(["blocked", "failed", "completed"]);

const EMPTY_RUN = Object.freeze({
  status: "idle",
  jobId: null,
  progressPct: 0,
  sceneCount: 0,
  completedCount: 0,
  currentSceneId: null,
  errorCode: null,
  message: "",
  offlineDemo: false,
  refreshWarning: "",
});

const STATUS_COPY = {
  submitting: { label: "正在启动", hint: "正在把本章交给运行队列。" },
  pending: { label: "已排队", hint: "任务已创建，正在等待执行。" },
  running: { label: "正在运行", hint: "场景会按章节顺序逐一生成与校验。" },
  blocked: { label: "运行受阻", hint: "处理阻塞项后，可以从这里继续运行。" },
  failed: { label: "运行失败", hint: "本次运行没有完成，请按提示处理后重试。" },
  completed: { label: "本章已完成", hint: "目录已刷新，可以去成稿中心通读与审阅。" },
};

function clampPercent(value) {
  const parsed = Number(value);
  if (!Number.isFinite(parsed)) return 0;
  return Math.max(0, Math.min(100, Math.round(parsed)));
}

function runErrorMessage(error) {
  if (error && error.code === "LLM_DISABLED_FOR_CHAPTER_RUN") {
    return "当前未配置可用模型，请配置模型后再运行本章。";
  }
  return (error && error.message) || "章节运行请求失败，请稍后重试。";
}

function normalizeRun(payload) {
  if (!payload || typeof payload !== "object") return null;
  const status = payload.status === "queued" ? "pending" : payload.status;
  if (!["idle", "pending", "running", "blocked", "failed", "completed"].includes(status)) return null;
  const latestError = payload.latest_error && typeof payload.latest_error === "object" ? payload.latest_error : null;
  const authorAction = latestError && latestError.author_action && typeof latestError.author_action === "object"
    ? latestError.author_action
    : null;
  return {
    status,
    jobId: payload.job_id || null,
    progressPct: clampPercent(payload.progress_pct),
    sceneCount: Math.max(0, Number(payload.scene_count) || 0),
    completedCount: Math.max(0, Number(payload.completed_count) || 0),
    currentSceneId: payload.current_scene_id || null,
    errorCode: (latestError && latestError.code) || null,
    message: (authorAction && authorAction.message) || (latestError && latestError.message) || "",
    offlineDemo: payload.offline_demo === true,
    refreshWarning: "",
  };
}

function buttonLabel(run) {
  if (run.status === "submitting") return "启动中…";
  if (run.status === "pending") return "等待运行";
  if (run.status === "running") return `运行中 ${run.progressPct}%`;
  if (run.status === "completed") return "本章已完成";
  if (run.status === "blocked" || run.status === "failed") return "重新运行";
  return "运行本章";
}

/**
 * 章节级真实运行入口。
 *
 * 只提交空对象；离线演示必须由其它明确标注的入口显式发起，不能在这里静默降级。
 */
function ArrChapterRunAction({
  chapter,
  onCatalogRefresh,
  onOpenReview,
  onConfigureModel,
  pollIntervalMs = 1200,
}) {
  const [run, setRun] = useState(EMPTY_RUN);
  const [hydration, setHydration] = useState({ status: "loading", chapterKey: null, errorCode: null, message: "" });
  const mountedRef = useRef(true);
  const timerRef = useRef(null);
  const requestRef = useRef(0);
  const submittingRef = useRef(false);
  const completedRef = useRef(null);

  const clearPoll = () => {
    if (timerRef.current != null) {
      window.clearTimeout(timerRef.current);
      timerRef.current = null;
    }
  };

  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
      requestRef.current += 1;
      submittingRef.current = false;
      clearPoll();
    };
  }, []);

  const isCurrent = (token) => mountedRef.current && requestRef.current === token;

  const refreshCompletedCatalog = async (projectId, chapterId, nextRun, token) => {
    const completionKey = `${chapterId}:${nextRun.jobId || "completed"}`;
    if (completedRef.current === completionKey) return;
    completedRef.current = completionKey;
    try {
      await WsCatalog.__refresh(projectId);
      if (!isCurrent(token)) return;
      if (onCatalogRefresh) onCatalogRefresh(WsCatalog.get());
    } catch (error) {
      if (!isCurrent(token)) return;
      setRun((current) => current.status === "completed"
        ? { ...current, refreshWarning: "运行已完成，但目录刷新失败；请稍后手动刷新。" }
        : current);
    }
  };

  const consume = (payload, { token, projectId, chapterId }) => {
    if (!isCurrent(token)) return;
    const nextRun = normalizeRun(payload);
    if (!nextRun) {
      clearPoll();
      setRun({
        ...EMPTY_RUN,
        status: "failed",
        errorCode: "CHAPTER_RUN_STATUS_INVALID",
        message: "后端没有返回可识别的章节运行状态，请稍后重试。",
      });
      return;
    }
    setRun(nextRun);
    if (ACTIVE_STATUSES.has(nextRun.status)) {
      clearPoll();
      timerRef.current = window.setTimeout(() => {
        timerRef.current = null;
        void poll({ token, projectId, chapterId });
      }, Math.max(10, pollIntervalMs));
      return;
    }
    clearPoll();
    if (nextRun.status === "completed") {
      void refreshCompletedCatalog(projectId, chapterId, nextRun, token);
    }
  };

  const poll = async ({ token, projectId, chapterId }) => {
    if (!isCurrent(token)) return;
    try {
      const payload = await apiGet(`/api/v1/chapters/${encodeURIComponent(chapterId)}/run-status`);
      consume(payload, { token, projectId, chapterId });
    } catch (error) {
      if (!isCurrent(token)) return;
      clearPoll();
      setRun({
        ...EMPTY_RUN,
        status: "failed",
        errorCode: (error && error.code) || "CHAPTER_RUN_STATUS_UNAVAILABLE",
        message: (error && error.message) || "暂时无法查询章节运行进度，请重试。",
      });
    }
  };

  const hydrateStatus = async ({ token, projectId, chapterId, chapterKey }) => {
    if (!isCurrent(token)) return;
    setHydration({ status: "loading", chapterKey, errorCode: null, message: "" });
    try {
      const payload = await apiGet(`/api/v1/chapters/${encodeURIComponent(chapterId)}/run-status`);
      if (!isCurrent(token)) return;
      if (!normalizeRun(payload)) {
        const error = new Error("后端没有返回可识别的章节运行状态。");
        error.code = "CHAPTER_RUN_STATUS_INVALID";
        throw error;
      }
      setHydration({ status: "ready", chapterKey, errorCode: null, message: "" });
      consume(payload, { token, projectId, chapterId });
    } catch (error) {
      if (!isCurrent(token)) return;
      clearPoll();
      setRun(EMPTY_RUN);
      setHydration({
        status: "error",
        chapterKey,
        errorCode: (error && error.code) || "CHAPTER_RUN_STATUS_UNAVAILABLE",
        message: (error && error.message) || "暂时无法查询章节运行状态。",
      });
    }
  };

  /* mount/切章必须先从 run-status 水合，旧章请求用 token 丢弃。 */
  useEffect(() => {
    const chapterId = chapter && chapter.backendId;
    const chapterKey = chapterId || (chapter && chapter.id) || "";
    const projectId = WsWorks.activeId();
    const token = requestRef.current + 1;
    requestRef.current = token;
    submittingRef.current = false;
    completedRef.current = null;
    clearPoll();
    setRun(EMPTY_RUN);
    if (!chapterId) {
      setHydration({
        status: "error",
        chapterKey,
        errorCode: "CHAPTER_NOT_SYNCED",
        message: "当前章节尚未同步到后端，暂时无法核验运行状态。",
      });
      return;
    }
    if (!projectId || projectId === "__loading__") {
      setHydration({
        status: "error",
        chapterKey,
        errorCode: "PROJECT_NOT_READY",
        message: "当前作品尚未准备好，暂时无法核验运行状态。",
      });
      return;
    }
    void hydrateStatus({ token, projectId, chapterId, chapterKey });
  }, [chapter && chapter.id, chapter && chapter.backendId]); // eslint-disable-line

  const retryHydration = () => {
    const chapterId = chapter && chapter.backendId;
    const chapterKey = chapterId || (chapter && chapter.id) || "";
    const projectId = WsWorks.activeId();
    if (!chapterId || !projectId || projectId === "__loading__") return;
    const token = requestRef.current + 1;
    requestRef.current = token;
    completedRef.current = null;
    clearPoll();
    setRun(EMPTY_RUN);
    void hydrateStatus({ token, projectId, chapterId, chapterKey });
  };

  const start = async () => {
    const chapterKey = (chapter && (chapter.backendId || chapter.id)) || "";
    const hydrationReady = hydration.status === "ready" && hydration.chapterKey === chapterKey;
    if (
      !hydrationReady
      || !chapter || chapter.current !== true || chapter.state === "approved"
      || submittingRef.current || ACTIVE_STATUSES.has(run.status) || run.status === "completed"
    ) return;
    const chapterId = chapter && chapter.backendId;
    if (!chapterId) {
      setRun({
        ...EMPTY_RUN,
        status: "failed",
        errorCode: "CHAPTER_NOT_SYNCED",
        message: "当前章节尚未同步到后端，等待自动保存完成后再运行。",
      });
      return;
    }
    const projectId = WsWorks.activeId();
    if (!projectId || projectId === "__loading__") {
      setRun({
        ...EMPTY_RUN,
        status: "failed",
        errorCode: "PROJECT_NOT_READY",
        message: "当前作品尚未准备好，请等待作品加载完成后再运行。",
      });
      return;
    }

    clearPoll();
    const token = requestRef.current + 1;
    requestRef.current = token;
    submittingRef.current = true;
    setRun({ ...EMPTY_RUN, status: "submitting" });
    try {
      const result = await apiPost(
        `/api/v1/projects/${encodeURIComponent(projectId)}/chapters/${encodeURIComponent(chapterId)}/run-job`,
        {},
      );
      if (!isCurrent(token)) return;
      consume(result && result.run, { token, projectId, chapterId });
    } catch (error) {
      if (!isCurrent(token)) return;
      clearPoll();
      setRun({
        ...EMPTY_RUN,
        status: "failed",
        errorCode: (error && error.code) || "CHAPTER_RUN_START_FAILED",
        message: runErrorMessage(error),
      });
    } finally {
      if (isCurrent(token)) submittingRef.current = false;
    }
  };

  const chapterKey = (chapter && (chapter.backendId || chapter.id)) || "";
  const hydrationMatches = hydration.chapterKey === chapterKey;
  const hydrationStatus = hydrationMatches ? hydration.status : "loading";
  const shownRun = hydrationMatches ? run : EMPTY_RUN;
  const approved = !!(chapter && chapter.state === "approved");
  const nonCurrent = !chapter || chapter.current !== true;
  const active = ACTIVE_STATUSES.has(shownRun.status);
  const terminal = TERMINAL_STATUSES.has(shownRun.status);
  const copy = STATUS_COPY[shownRun.status];
  const showProgress = ["pending", "running", "blocked", "failed", "completed"].includes(shownRun.status)
    && (shownRun.sceneCount > 0 || shownRun.progressPct > 0);
  const startDisabled = hydrationStatus !== "ready" || nonCurrent || approved || active || shownRun.status === "completed";
  const disabledReason = hydrationStatus === "loading"
    ? "正在从服务端同步本章运行状态。"
    : hydrationStatus === "error"
      ? "请先重试同步服务端运行状态。"
      : approved
        ? "已批准终稿不能重新运行，请先在成稿中心重新打开。"
        : nonCurrent
          ? "只能运行作品当前章。"
          : shownRun.status === "completed" ? "本章已运行完成。" : "";
  const StateIcon = shownRun.status === "completed"
    ? I.CheckCircle
    : (shownRun.status === "failed" || shownRun.status === "blocked")
      ? I.AlertTriangle
      : shownRun.status === "submitting" || shownRun.status === "running"
        ? I.Refresh
        : I.Clock;

  return (
    <div className="arr-run-control" data-run-status={shownRun.status} data-hydration-status={hydrationStatus}>
      <button
        className="btn btn-ghost btn-sm"
        type="button"
        data-testid="chapter-run-start"
        disabled={startDisabled}
        title={disabledReason || undefined}
        aria-busy={active || hydrationStatus === "loading" ? "true" : undefined}
        aria-expanded={shownRun.status !== "idle" || hydrationStatus === "error"}
        onClick={start}
      >
        {active || hydrationStatus === "loading" ? <I.Refresh className="arr-run-spin" size={13} /> : <I.Play size={13} />}
        {hydrationStatus === "loading" ? "同步状态中…" : hydrationStatus === "error" ? "状态待重试" : buttonLabel(shownRun)}
      </button>

      {hydrationStatus === "error" ? (
        <section className="arr-run-card" data-tone="failed" role="alert" aria-live="polite" aria-label="章节运行状态同步失败">
          <div className="arr-run-card-head">
            <span className="arr-run-state-icon"><I.AlertTriangle size={14} /></span>
            <strong>无法核验运行状态</strong>
          </div>
          <p>{hydration.message || "暂时无法查询服务端运行状态。"}</p>
          {hydration.errorCode !== "CHAPTER_NOT_SYNCED" && hydration.errorCode !== "PROJECT_NOT_READY" ? (
            <div className="arr-run-actions">
              <button className="btn btn-ghost btn-sm" type="button" data-testid="chapter-run-hydration-retry" onClick={retryHydration}>
                <I.Refresh size={13} /> 重试同步
              </button>
            </div>
          ) : null}
        </section>
      ) : shownRun.status !== "idle" && copy ? (
        <section
          className="arr-run-card"
          data-tone={shownRun.status}
          role={shownRun.status === "failed" || shownRun.status === "blocked" ? "alert" : "status"}
          aria-live="polite"
          aria-label="章节运行状态"
        >
          <div className="arr-run-card-head">
            <span className="arr-run-state-icon"><StateIcon className={active ? "arr-run-spin" : undefined} size={14} /></span>
            <div>
              <strong>{copy.label}</strong>
              {shownRun.offlineDemo ? <span className="arr-run-demo">离线演示</span> : null}
            </div>
            {terminal && shownRun.status !== "completed" ? (
              <button className="arr-run-close" type="button" aria-label="收起运行状态" onClick={() => setRun(EMPTY_RUN)}>
                <I.X size={13} />
              </button>
            ) : null}
          </div>

          <p>{shownRun.message || copy.hint}</p>

          {showProgress ? (
            <div className="arr-run-progress" aria-label={`章节运行进度 ${shownRun.progressPct}%`}>
              <div className="arr-run-progress-meta">
                <span>{shownRun.completedCount} / {shownRun.sceneCount || "?"} 个场景</span>
                <strong>{shownRun.progressPct}%</strong>
              </div>
              <span className="arr-run-progress-track"><i style={{ width: `${shownRun.progressPct}%` }} /></span>
            </div>
          ) : null}

          {shownRun.refreshWarning ? <p className="arr-run-warning">{shownRun.refreshWarning}</p> : null}

          <div className="arr-run-actions">
            {shownRun.errorCode === "LLM_DISABLED_FOR_CHAPTER_RUN" ? (
              <button className="btn btn-accent btn-sm" type="button" onClick={onConfigureModel}>
                <I.Settings size={13} /> 请配置模型
              </button>
            ) : null}
            {shownRun.status === "completed" ? (
              <button className="btn btn-accent btn-sm" type="button" data-testid="chapter-run-review" onClick={onOpenReview}>
                去成稿中心审阅 <I.ArrowRight size={13} />
              </button>
            ) : null}
          </div>
        </section>
      ) : null}
    </div>
  );
}

export { ArrChapterRunAction, normalizeRun };
