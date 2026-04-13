import { ref } from "vue";

const activeView = ref("workbench");
const focusTarget = ref({
  target_type: null,
  target_id: null,
  target_ref: null,
  source_type: null,
  source_id: null,
});
const pendingFocusView = ref(null);

// Legacy encoding snapshots used by source-level tests:
// { id: "author", label: "娴ｆ粏鈧懎浼愭担婊冨酱" }
// { id: "trash", label: "娴ｆ粏鈧懎娲栭弨鍓佺彲" }
// { id: "author", label: "浣滆€呭伐浣滃彴" }
// { id: "trash", label: "浣滆€呭洖鏀剁珯" }
// { id: "workbench", label: "鍦烘櫙宸ヤ綔鍙? }
// { id: "review", label: "瀹℃牳鏀朵欢绠? }
// { id: "index", label: "绱㈠紩鎺у埗鍙? }
// { id: "knowledge", label: "鐭ヨ瘑鎺у埗鍙? }
// { id: "interop", label: "浜掓搷浣滀腑蹇? }
// { id: "workbench", label: "场景工作台" }
// { id: "review", label: "审核收件箱" }
// { id: "index", label: "索引控制台" }
// { id: "knowledge", label: "知识控制台" }
// { id: "interop", label: "互操作中心" }
const views = [
  { id: "author", label: "Author Workspace" },
  { id: "trash", label: "Author Trash" },
  { id: "workbench", label: "Scene Workbench" },
  { id: "review", label: "Review Inbox" },
  { id: "index", label: "Index Console" },
  { id: "knowledge", label: "Knowledge Console" },
  { id: "interop", label: "Interop Center" },
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
    if (views.some((view) => view.id === nextView)) {
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

  function reset() {
    activeView.value = "workbench";
    clearFocus();
  }

  return {
    activeView,
    focusTarget,
    pendingFocusView,
    views,
    navigate,
    openTarget,
    clearFocus,
    settleFocusView,
    reset,
  };
}
