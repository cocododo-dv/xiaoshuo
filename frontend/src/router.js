import { ref } from "vue";

const activeView = ref("workbench");
const focusTarget = ref({
  target_type: null,
  target_id: null,
  target_ref: null,
  source_type: null,
  source_id: null,
});

const views = [
  { id: "workbench", label: "Scene Workbench" },
  { id: "review", label: "Review Inbox" },
  { id: "index", label: "Index Console" },
  { id: "knowledge", label: "Knowledge Console" },
];

const workbenchTargetTypes = new Set([
  "scene_card",
  "scene_memory",
  "scene_run_state",
  "final_scene",
  "scene_attempt",
]);

export function useShellRouter() {
  function clearFocus() {
    focusTarget.value = {
      target_type: null,
      target_id: null,
      target_ref: null,
      source_type: null,
      source_id: null,
    };
  }

  function navigate(nextView) {
    if (views.some((view) => view.id === nextView)) {
      activeView.value = nextView;
    }
  }

  function targetView(targetType) {
    if (workbenchTargetTypes.has(targetType)) {
      return "workbench";
    }
    if (targetType === "review_item" || targetType === "human_review_event") {
      return "review";
    }
    if (targetType === "verify_job" || targetType === "reindex_job") {
      return "index";
    }
    return activeView.value;
  }

  function openTarget(target, options = {}) {
    if (!target?.target_type || !target?.target_id || !target?.target_ref) {
      return;
    }
    focusTarget.value = {
      target_type: target.target_type,
      target_id: target.target_id,
      target_ref: target.target_ref,
      source_type: options.source_type ?? target.source_type ?? null,
      source_id: options.source_id ?? target.source_id ?? null,
    };
    navigate(options.view_id || target.view_id || targetView(target.target_type));
  }

  function reset() {
    activeView.value = "workbench";
    clearFocus();
  }

  return {
    activeView,
    focusTarget,
    views,
    navigate,
    openTarget,
    clearFocus,
    reset,
  };
}
