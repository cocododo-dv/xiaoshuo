import { ref } from "vue";

const activeView = ref("workbench");
const visitedViews = ref(["workbench"]);
const focusTarget = ref({
  target_type: null,
  target_id: null,
  target_ref: null,
  source_type: null,
  source_id: null,
});
const pendingFocusView = ref(null);

const views = [
  {
    id: "author",
    label: "作者工作台",
    cacheMode: "light",
  },
  {
    id: "trash",
    label: "作者回收站",
    cacheMode: "light",
  },
  {
    id: "workbench",
    label: "场景工作台",
    cacheMode: "light",
  },
  {
    id: "review",
    label: "审核收件箱",
    cacheMode: "light",
  },
  {
    id: "index",
    label: "索引控制台",
    cacheMode: "light",
  },
  {
    id: "knowledge",
    label: "知识控制台",
    cacheMode: "light",
  },
  {
    id: "interop",
    label: "互操作中心",
    cacheMode: "light",
  },
  {
    id: "config",
    label: "系统配置",
    cacheMode: "light",
  },
];

const viewMap = Object.fromEntries(views.map((view) => [view.id, view]));

const workbenchTargetTypes = new Set([
  "scene_card",
  "scene_memory",
  "scene_run_state",
  "final_scene",
  "scene_attempt",
]);

function ensureVisited(nextView) {
  if (!viewMap[nextView]) {
    return;
  }
  if (visitedViews.value.includes(nextView)) {
    return;
  }
  visitedViews.value = [...visitedViews.value, nextView];
}

export function useShellRouter() {
  function clearFocus() {
    pendingFocusView.value = null;
    focusTarget.value = {
      target_type: null,
      target_id: null,
      target_ref: null,
      source_type: null,
      source_id: null,
    };
  }

  function navigate(nextView) {
    if (viewMap[nextView]) {
      ensureVisited(nextView);
      if (pendingFocusView.value && pendingFocusView.value !== nextView) {
        pendingFocusView.value = null;
      }
      activeView.value = nextView;
    }
  }

  function targetView(targetType) {
    if (targetType === "chapter_goal") {
      return "author";
    }
    if (workbenchTargetTypes.has(targetType)) {
      return "workbench";
    }
    if (targetType === "review_item" || targetType === "human_review_event") {
      return "review";
    }
    if (targetType === "verify_job" || targetType === "reindex_job") {
      return "index";
    }
    if (targetType === "knowledge_entry") {
      return "knowledge";
    }
    return activeView.value;
  }

  function openTarget(target, options = {}) {
    if (!target?.target_type || !target?.target_id || !target?.target_ref) {
      return;
    }
    const nextView = options.view_id || target.view_id || targetView(target.target_type);
    pendingFocusView.value = nextView !== activeView.value ? nextView : null;
    focusTarget.value = {
      target_type: target.target_type,
      target_id: target.target_id,
      target_ref: target.target_ref,
      source_type: options.source_type ?? target.source_type ?? null,
      source_id: options.source_id ?? target.source_id ?? null,
    };
    navigate(nextView);
  }

  function settleFocusView(viewId) {
    if (pendingFocusView.value === viewId) {
      pendingFocusView.value = null;
    }
  }

  function viewMeta(viewId) {
    return viewMap[viewId] || viewMap.workbench;
  }

  function isViewActive(viewId) {
    return activeView.value === viewId;
  }

  function reset() {
    activeView.value = "workbench";
    visitedViews.value = ["workbench"];
    clearFocus();
  }

  return {
    activeView,
    visitedViews,
    focusTarget,
    pendingFocusView,
    views,
    navigate,
    openTarget,
    clearFocus,
    settleFocusView,
    viewMeta,
    isViewActive,
    reset,
  };
}
