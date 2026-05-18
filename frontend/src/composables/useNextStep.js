import { computed } from "vue";

import { useShellRouter, workflowGroups } from "../router";
import { useWriterPathProgress } from "./useWriterPathProgress";

const STAGE_LABELS = Object.fromEntries(workflowGroups.map((group) => [group.id, group.label]));
const OPTIONAL_WRITER_VIEW_IDS = new Set(["reference", "review"]);

function isOptionalWriterItem(item) {
  return OPTIONAL_WRITER_VIEW_IDS.has(item?.viewId);
}

function isActionableOptionalItem(item) {
  return isOptionalWriterItem(item) && ["active", "running"].includes(item?.status);
}

// Single source of truth for the path-level "what should I do right now".
//
// It derives entirely from useWriterPathProgress (which already folds every
// store's actionId/state into a status + summary + nextAction). When a flow
// action is running, that composable already reports status === "running" with
// a "wait for it to finish" message, so the guidance card naturally yields to
// the in-view FlowActionReceipt instead of competing with a second next step.
export function useNextStep() {
  const router = useShellRouter();
  const { items, activeItem, journeyPhase, navigateToItem } = useWriterPathProgress();

  // When the step you're on is already done and routing to it would be a
  // no-op (no handoff target), advance the whole guidance card to the next
  // open work: any blocked item first, else the earliest still-unfinished
  // step in path order. If nothing is left, the path is complete.
  const effectiveItem = computed(() => {
    const current = activeItem.value;
    if (!current) {
      return null;
    }
    const noOpDone = current.isActive
      && current.status === "done"
      && (current.primaryTarget || current.viewId) === current.viewId;
    if (!noOpDone) {
      return current;
    }
    const list = items.value;
    const next = list.find((entry) => entry.status === "blocked")
      || list.find((entry) => entry.viewId !== current.viewId && !isOptionalWriterItem(entry) && entry.status !== "done")
      || list.find((entry) => entry.viewId !== current.viewId && isActionableOptionalItem(entry));
    return next || current;
  });

  const pathComplete = computed(() => {
    const current = activeItem.value;
    return Boolean(current
      && effectiveItem.value === current
      && current.isActive
      && current.status === "done"
      && (current.primaryTarget || current.viewId) === current.viewId);
  });

  const status = computed(() => effectiveItem.value?.status || "todo");

  const stageLabel = computed(() => {
    const item = effectiveItem.value;
    if (!item) {
      return "";
    }
    const meta = router.viewMeta(item.viewId);
    return STAGE_LABELS[meta?.stage] || "";
  });

  const headline = computed(() => effectiveItem.value?.label || "创作之旅");

  const writerMotivation = computed(() => {
    const item = effectiveItem.value;
    if (!item) return "";
    const meta = router.viewMeta(item.viewId);
    return meta?.writerMotivation || "";
  });
  const summaryText = computed(() => effectiveItem.value?.summary || "");
  const nextActionText = computed(() => effectiveItem.value?.nextAction || "");

  const primaryTarget = computed(() => {
    const item = effectiveItem.value;
    return item?.primaryTarget || item?.viewId || "snowflake-workbench";
  });

  // A handoff means the recommended next destination differs from the step the
  // effective item represents (e.g. snowflake "done" hands off to writer-flow).
  const isHandoff = computed(() => {
    const item = effectiveItem.value;
    return Boolean(item && primaryTarget.value && primaryTarget.value !== item.viewId);
  });

  const onTarget = computed(() => router.activeView.value === primaryTarget.value);
  const ctaDisabled = computed(() => status.value === "running" || pathComplete.value);

  const ctaLabel = computed(() => {
    if (pathComplete.value) {
      return "全部完成";
    }
    switch (status.value) {
      case "running":
        return "正在处理…";
      case "blocked":
        return isHandoff.value ? "去处理" : "去处理这一步";
      case "todo":
        return isHandoff.value ? "进入下一步" : "开始这一步";
      case "done":
        return isHandoff.value ? "进入下一步" : "已完成，继续";
      default:
        return onTarget.value ? "继续这一步" : "去这一步";
    }
  });

  function go() {
    const item = effectiveItem.value;
    if (!item || ctaDisabled.value) {
      return;
    }
    navigateToItem(item);
  }

  return {
    items,
    activeItem,
    status,
    stageLabel,
    headline,
    writerMotivation,
    journeyPhase,
    summaryText,
    nextActionText,
    primaryTarget,
    isHandoff,
    onTarget,
    ctaLabel,
    ctaDisabled,
    go,
    navigateToItem,
  };
}
