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

export const workflowGroups = [
  {
    id: "setup",
    label: "起步",
    description: "先确认环境和模型可用",
  },
  {
    id: "authoring",
    label: "创作输入",
    description: "把章节和场景输入整理清楚",
  },
  {
    id: "runtime",
    label: "运行与审核",
    description: "运行场景、处理候选、检查成稿",
  },
  {
    id: "knowledge",
    label: "知识沉淀",
    description: "发布长期知识并学习参考书",
  },
  {
    id: "operations",
    label: "运维工具",
    description: "索引、回收、导入导出",
  },
];

const views = [
  {
    id: "config",
    label: "1 配置环境",
    stepLabel: "配置环境",
    legacyLabel: "系统配置",
    description: "连接后端、接入模型、配置节点路由，并验证发布前快照。",
    group: "起步",
    groupId: "setup",
    icon: "Settings2",
    nextViews: ["author", "workbench", "reference"],
    cacheMode: "light",
  },
  {
    id: "author",
    label: "2 编排章节",
    stepLabel: "编排章节",
    legacyLabel: "作者工作台",
    description: "选择章节，维护章节目标和场景卡，再把场景送去运行。",
    group: "创作输入",
    groupId: "authoring",
    icon: "PenLine",
    nextViews: ["workbench", "trash"],
    cacheMode: "light",
  },
  {
    id: "workbench",
    label: "3 运行场景",
    stepLabel: "运行场景",
    legacyLabel: "场景工作台",
    description: "先预检，再运行单场景，最后验收证据和归档结果。",
    group: "运行与审核",
    groupId: "runtime",
    icon: "PlayCircle",
    nextViews: ["review", "manuscripts"],
    cacheMode: "light",
  },
  {
    id: "review",
    label: "4 处理审核",
    stepLabel: "处理审核",
    legacyLabel: "审核收件箱",
    description: "处理候选、人工事件和后续动作，让运行链路继续前进。",
    group: "运行与审核",
    groupId: "runtime",
    icon: "ClipboardCheck",
    nextViews: ["index", "knowledge", "workbench"],
    cacheMode: "light",
  },
  {
    id: "manuscripts",
    label: "5 查看成稿",
    stepLabel: "查看成稿",
    legacyLabel: "章节成稿中心",
    description: "阅读实时拼接和最终聚合正文，确认章节是否可交付。",
    group: "运行与审核",
    groupId: "runtime",
    icon: "BookOpenCheck",
    nextViews: ["longform", "author", "trash", "workbench"],
    cacheMode: "light",
  },
  {
    id: "longform",
    label: "6 长篇控制",
    stepLabel: "长篇控制",
    legacyLabel: "长篇控制塔",
    description: "汇总章节节奏、人物弧线、悬念债务和连续性风险，帮助作者看见全书压力点。",
    group: "运行与审核",
    groupId: "runtime",
    icon: "Radar",
    nextViews: ["manuscripts", "knowledge", "review"],
    cacheMode: "light",
  },
  {
    id: "trash",
    label: "7 回收内容",
    stepLabel: "回收内容",
    legacyLabel: "作者回收站",
    description: "恢复误删内容，或在确认安全后永久清除作者层对象。",
    group: "运维工具",
    groupId: "operations",
    icon: "Trash2",
    nextViews: ["author", "manuscripts"],
    cacheMode: "light",
  },
  {
    id: "index",
    label: "8 发布索引",
    stepLabel: "发布索引",
    legacyLabel: "索引控制台",
    description: "查看待发布、失败校验和恢复事件，确认候选真正进入运行时。",
    group: "运维工具",
    groupId: "operations",
    icon: "UploadCloud",
    nextViews: ["review", "knowledge", "workbench"],
    cacheMode: "light",
  },
  {
    id: "knowledge",
    label: "9 沉淀知识",
    stepLabel: "沉淀知识",
    legacyLabel: "知识控制台",
    description: "创建长期知识候选，并追踪批准、校验、发布和生效过程。",
    group: "知识沉淀",
    groupId: "knowledge",
    icon: "Library",
    nextViews: ["review", "index", "workbench"],
    cacheMode: "light",
  },
  {
    id: "reference",
    label: "10 学习参考",
    stepLabel: "学习参考",
    legacyLabel: "参考书学习",
    description: "导入参考书，抽样学习，生成画像候选，再选择应用范围。",
    group: "知识沉淀",
    groupId: "knowledge",
    icon: "GraduationCap",
    nextViews: ["review", "knowledge"],
    cacheMode: "light",
  },
  {
    id: "interop",
    label: "11 导入导出",
    stepLabel: "导入导出",
    legacyLabel: "互操作中心",
    description: "预览工作表、导入外部包、导出 bundle，并回放运行结果。",
    group: "运维工具",
    groupId: "operations",
    icon: "Files",
    nextViews: ["workbench", "author"],
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
    if (targetType === "chapter_manuscript") {
      return "manuscripts";
    }
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
    workflowGroups,
    navigate,
    openTarget,
    clearFocus,
    settleFocusView,
    viewMeta,
    isViewActive,
    reset,
  };
}
