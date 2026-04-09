import { ref } from "vue";

const activeView = ref("workbench");

const views = [
  { id: "workbench", label: "Scene Workbench" },
  { id: "review", label: "Review Inbox" },
  { id: "index", label: "Index Console" },
];

export function useShellRouter() {
  function navigate(nextView) {
    if (views.some((view) => view.id === nextView)) {
      activeView.value = nextView;
    }
  }

  return {
    activeView,
    views,
    navigate,
  };
}
