import { computed, ref } from "vue";

function resolveValue(value, payload) {
  return typeof value === "function" ? value(payload) : value;
}

function errorMessage(error, actionLabel) {
  return error?.message || `${actionLabel || "操作"}失败`;
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
      action,
      notify = true,
    } = config;

    setReceipt(scopeKey, {
      status: "running",
      actionLabel,
      message: runningMessage || `正在执行：${actionLabel}`,
      nextStep: "",
      target: null,
    });

    try {
      const result = await action();
      const message = resolveValue(successMessage, result) || `${actionLabel}已完成。`;
      setReceipt(scopeKey, {
        status: "success",
        actionLabel,
        message,
        nextStep: resolveValue(nextStep, result) || "",
        target: resolveValue(target, result) || null,
      });
      if (notify && emitNotice) {
        emitNotice(message);
      }
      return result;
    } catch (error) {
      const message = errorMessage(error, actionLabel);
      setReceipt(scopeKey, {
        status: "error",
        actionLabel,
        message,
        nextStep: resolveValue(failureNextStep, error) || "检查输入后可重试。",
        target: null,
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
