import { computed, ref } from "vue";

function resolveValue(value, payload) {
  return typeof value === "function" ? value(payload) : value;
}

function errorMessage(error, actionLabel) {
  return error?.message || `${actionLabel || "操作"}失败`;
}

function errorTrace(error = {}) {
  return {
    requestId: error.requestId || error.request_id || null,
    clientRequestId: error.clientRequestId || error.client_request_id || null,
    code: error.code || null,
    httpStatus: error.status ?? null,
    details: error.details || {},
    retryable: Boolean(error.retryable || error.details?.retryable),
  };
}

export function useFlowActionFeedback({ emitNotice } = {}) {
  const receipts = ref({});

  function setReceipt(scopeKey, receipt) {
    receipts.value = {
      ...receipts.value,
      [scopeKey]: {
        scopeKey,
        updatedAt: Date.now(),
        ...receipt,
      },
    };
  }

  function receiptFor(scopeKey) {
    return computed(() => receipts.value[scopeKey] || null);
  }

  function receipt(scopeKey) {
    return receipts.value[scopeKey] || null;
  }

  function isRunning(scopeKey) {
    return computed(() => receipts.value[scopeKey]?.status === "running");
  }

  function running(scopeKey) {
    return receipts.value[scopeKey]?.status === "running";
  }

  function clearReceipt(scopeKey) {
    const next = { ...receipts.value };
    delete next[scopeKey];
    receipts.value = next;
  }

  async function runFlowAction(config) {
    const {
      scopeKey,
      actionLabel,
      runningMessage,
      successMessage,
      nextStep,
      failureNextStep = "检查输入后可重试。",
      target,
      phaseLabel = "",
      longRunningMs = 12000,
      longRunningMessage = "仍在处理，可以继续编辑当前内容。",
      onCancelWait,
      onRetry,
      retryable = false,
      action,
      notify = true,
    } = config;
    const startedAt = Date.now();
    let timeoutId = null;
    const runningActions = [];
    if (typeof onCancelWait === "function") {
      runningActions.push({
        label: "停止等待",
        onClick: () => onCancelWait(scopeKey),
      });
    }

    setReceipt(scopeKey, {
      status: "running",
      actionLabel,
      message: runningMessage || `正在执行：${actionLabel}`,
      nextStep: "",
      target: null,
      phaseLabel,
      startedAt,
      elapsedMs: 0,
      longRunning: false,
      retryable: Boolean(retryable),
      actions: runningActions,
    });

    if (Number(longRunningMs) > 0) {
      timeoutId = setTimeout(() => {
        const current = receipts.value[scopeKey];
        if (current?.status !== "running") {
          return;
        }
        setReceipt(scopeKey, {
          ...current,
          status: "running",
          nextStep: longRunningMessage,
          elapsedMs: Date.now() - startedAt,
          longRunning: true,
        });
      }, Number(longRunningMs));
    }

    try {
      const result = await action();
      if (timeoutId) {
        clearTimeout(timeoutId);
      }
      const message = resolveValue(successMessage, result) || `${actionLabel}已完成。`;
      setReceipt(scopeKey, {
        status: "success",
        actionLabel,
        message,
        nextStep: resolveValue(nextStep, result) || "",
        target: resolveValue(target, result) || null,
        phaseLabel,
        startedAt,
        elapsedMs: Date.now() - startedAt,
        longRunning: false,
        retryable: false,
        actions: [],
      });
      if (notify && emitNotice) {
        emitNotice(message);
      }
      return result;
    } catch (error) {
      if (timeoutId) {
        clearTimeout(timeoutId);
      }
      const message = errorMessage(error, actionLabel);
      const trace = errorTrace(error);
      const canRetry = Boolean(retryable || trace.retryable);
      const actions = [];
      if (canRetry && typeof onRetry === "function") {
        actions.push({
          label: "重试",
          onClick: () => onRetry(error),
        });
      }
      setReceipt(scopeKey, {
        status: "error",
        actionLabel,
        message,
        nextStep: resolveValue(failureNextStep, error) || "检查输入后可重试。",
        target: null,
        phaseLabel,
        startedAt,
        elapsedMs: Date.now() - startedAt,
        longRunning: false,
        ...trace,
        retryable: canRetry,
        actions,
      });
      if (notify && emitNotice) {
        emitNotice(message);
      }
      return null;
    }
  }

  return {
    receipts,
    runFlowAction,
    receiptFor,
    receipt,
    isRunning,
    running,
    clearReceipt,
  };
}
