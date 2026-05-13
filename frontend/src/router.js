import { ref } from "vue";

import { useUiMode } from "./composables/useUiMode";

const activeView = ref("snowflake-workbench");
const visitedViews = ref(["snowflake-workbench"]);
const routeContext = ref({
  step: "",
  panel: "",
  target: "",
  focus: "",
});
const focusTarget = ref({
  target_type: null,
  target_id: null,
  target_ref: null,
  source_type: null,
  source_id: null,
});
const pendingFocusView = ref(null);
let popstateInstalled = false;

function hasWindowLocation() {
  return typeof window !== "undefined" && window.location && window.history;
}

function cleanRouteContext(value = {}) {
  return {
    step: String(value.step || "").trim(),
    panel: String(value.panel || "").trim(),
    target: String(value.target || value.target_id || value.target_ref || "").trim(),
    focus: String(value.focus || value.target_type || "").trim(),
  };
}

function contextHasValue(context) {
  return Object.values(context || {}).some((value) => String(value || "").trim());
}

function applyRouteContext(nextContext = {}) {
  routeContext.value = cleanRouteContext(nextContext);
}

export const workflowGroups = [
  {
    id: "daily",
    label: "日用写作",
    description: "今天写哪章、怎么改、哪些风险会影响下一场",
  },
  {
    id: "production",
    label: "生产工具",
    description: "审核、知识、参考学习和成稿交付",
  },
  {
    id: "advanced",
    label: "高级工具",
    description: "索引、互操作、系统配置和运行证据",
  },
];

const views = [
  {
    id: "snowflake-workbench",
    label: "雪花工作台",
    stepLabel: "雪花工作台",
    legacyLabel: "雪花主导写作工作台",
    description: "把十步雪花、场景急救和章节结构草案放在同一个创作工作台里。",
    group: "日用写作",
    groupId: "daily",
    icon: "Snowflake",
    nextViews: ["writer-flow", "reference", "review", "writer-room"],
    cacheMode: "light",
    writerPrimary: true,
    writerOrder: 1,
    writerLabel: "雪花工作台",
    writerGoal: "把故事从十步雪花推进到可继续写作的章节结构草案。",
    writerDoneSignal: "关键雪花步骤已确认，场景急救和准备度检查没有硬阻断。",
    writerNextAction: "继续打磨当前构思，或进入场景急救补齐薄弱场景。",
  },
  {
    id: "writer-flow",
    label: "写作总控",
    stepLabel: "写作总控",
    legacyLabel: "项目写作总控",
    description: "沿着当前项目的下一步，推进章节起草、进度查看、终稿审阅和批准。",
    group: "日用写作",
    groupId: "daily",
    icon: "Route",
    nextViews: ["writer-room", "review", "snowflake-workbench"],
    cacheMode: "light",
    writerPrimary: true,
    writerOrder: 2,
    writerLabel: "写作总控",
    writerGoal: "把已确认的雪花结构推进到当前章节起草、审阅和批准。",
    writerDoneSignal: "当前章已起草、审阅或批准，项目状态能明确指向下一章或完成。",
    writerNextAction: "按主按钮继续当前章节；需要小修时再进入写作房间。",
  },
  {
    id: "writer-room",
    label: "写作房间",
    stepLabel: "写作房间",
    legacyLabel: "文本优先工作台",
    description: "先回到正文，再比较诊断、改法和长篇压力。",
    group: "日用写作",
    groupId: "daily",
    icon: "Feather",
    nextViews: ["snowflake-workbench", "deepdesk", "manuscripts"],
    cacheMode: "light",
    writerPrimary: true,
    writerOrder: 3,
    writerLabel: "小修写作",
    writerGoal: "在当前章节或场景里直接打磨作者正文。",
    writerDoneSignal: "草稿已保存，候选改法已明确采纳或放弃。",
    writerNextAction: "先保存当前正文，再比较候选改法或回到雪花工作台校准结构。",
  },
  {
    id: "config",
    label: "1 配置环境",
    stepLabel: "配置环境",
    legacyLabel: "系统配置",
    description: "连接后端、接入模型、配置节点路由，并验证发布前快照。",
    group: "起步",
    groupId: "advanced",
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
    groupId: "daily",
    icon: "ScrollText",
    nextViews: ["deepdesk", "workbench", "trash"],
    cacheMode: "light",
    writerPrimary: false,
    writerOrder: 12,
  },
  {
    id: "workbench",
    label: "3 运行场景",
    stepLabel: "运行场景",
    legacyLabel: "场景工作台",
    description: "先预检，再运行单场景，最后验收证据和归档结果。",
    group: "运行与审核",
    groupId: "production",
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
    groupId: "production",
    icon: "ClipboardCheck",
    nextViews: ["index", "knowledge", "workbench"],
    cacheMode: "light",
    writerPrimary: true,
    writerOrder: 5,
    writerLabel: "待处理建议",
    writerGoal: "清掉会阻断创作链路的候选、风险和人工事件。",
    writerDoneSignal: "优先审核项已处理，剩余内容不会阻塞下一场写作。",
    writerNextAction: "先处理待作者决策的建议，再回到写作房间或参考书学习。",
  },
  {
    id: "quality",
    label: "5 文学质检",
    stepLabel: "文学质检",
    legacyLabel: "文学质量引擎",
    description: "巡检作者稿优先的章节/场景文本，并运行文学基准评测；只提示风险，不阻断发布。",
    group: "运行与审核",
    groupId: "daily",
    icon: "ShieldCheck",
    nextViews: ["deepdesk", "review", "workbench"],
    cacheMode: "light",
    writerPrimary: false,
    writerOrder: 13,
  },
  {
    id: "manuscripts",
    label: "5 查看成稿",
    stepLabel: "查看成稿",
    legacyLabel: "章节成稿中心",
    description: "阅读实时拼接和最终聚合正文，确认章节是否可交付。",
    group: "运行与审核",
    groupId: "production",
    icon: "BookOpenText",
    nextViews: ["deepdesk", "longform", "author", "trash", "workbench"],
    cacheMode: "light",
  },
  {
    id: "deepdesk",
    label: "6 写作深改",
    stepLabel: "写作深改",
    legacyLabel: "写作与深改台",
    description: "先写作者稿，再反向提取戏剧卡、运行深改诊断、生成局部候选并记录作者决定。",
    group: "运行与审核",
    groupId: "daily",
    icon: "Microscope",
    nextViews: ["author", "manuscripts", "longform", "workbench"],
    cacheMode: "light",
    writerPrimary: false,
    writerOrder: 14,
  },
  {
    id: "longform",
    label: "6 长篇控制",
    stepLabel: "长篇控制",
    legacyLabel: "长篇控制塔",
    description: "汇总章节节奏、人物弧线、悬念债务和连续性风险，帮助作者看见全书压力点。",
    group: "运行与审核",
    groupId: "daily",
    icon: "Radar",
    nextViews: ["manuscripts", "knowledge", "review"],
    cacheMode: "light",
    writerPrimary: false,
    writerOrder: 15,
  },
  {
    id: "trash",
    label: "7 回收内容",
    stepLabel: "回收内容",
    legacyLabel: "作者回收站",
    description: "恢复误删内容，或在确认安全后永久清除作者层对象。",
    group: "运维工具",
    groupId: "advanced",
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
    groupId: "advanced",
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
    groupId: "production",
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
    groupId: "production",
    icon: "GraduationCap",
    nextViews: ["review", "knowledge"],
    cacheMode: "light",
    writerPrimary: true,
    writerOrder: 4,
    writerLabel: "参考书学习",
    writerGoal: "把参考书抽象成安全可用的风格画像和审核卡。",
    writerDoneSignal: "画像已生成并创建应用审核项，没有直接复制源文风险。",
    writerNextAction: "导入或继续分析参考书，然后去待处理建议确认应用。",
  },
  {
    id: "interop",
    label: "11 导入导出",
    stepLabel: "导入导出",
    legacyLabel: "互操作中心",
    description: "预览工作表、导入外部包、导出 bundle，并回放运行结果。",
    group: "运维工具",
    groupId: "advanced",
    icon: "FileInput",
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
const writerRoomTargetTypes = new Set([
  "author_draft",
  "author_draft_proposal",
  "author_draft_scene",
  "author_draft_chapter",
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
  function serializeLocation(viewId = activeView.value, context = routeContext.value) {
    const params = new URLSearchParams();
    const normalizedView = viewMap[viewId] ? viewId : "snowflake-workbench";
    params.set("view", normalizedView);
    const { uiMode } = useUiMode();
    if (uiMode.value) {
      params.set("mode", uiMode.value);
    }
    const cleanedContext = cleanRouteContext(context);
    Object.entries(cleanedContext).forEach(([key, value]) => {
      if (value) {
        params.set(key, value);
      }
    });
    return `?${params.toString()}`;
  }

  function writeLocation(viewId = activeView.value, { replace = false, target = routeContext.value } = {}) {
    if (!hasWindowLocation()) {
      return;
    }
    const nextSearch = serializeLocation(viewId, target);
    const nextUrl = `${window.location.pathname}${nextSearch}${window.location.hash || ""}`;
    if (replace) {
      window.history.replaceState({}, "", nextUrl);
      return;
    }
    window.history.pushState({}, "", nextUrl);
  }

  function hydrateFromLocation({ replaceInvalid = true } = {}) {
    if (!hasWindowLocation()) {
      return activeView.value;
    }
    const params = new URLSearchParams(window.location.search || "");
    const requestedView = params.get("view") || "snowflake-workbench";
    const nextView = viewMap[requestedView] ? requestedView : "snowflake-workbench";
    const requestedMode = params.get("mode") || "";
    if (requestedMode) {
      useUiMode().setUiMode(requestedMode);
    }
    applyRouteContext({
      step: params.get("step") || "",
      panel: params.get("panel") || "",
      target: params.get("target") || "",
      focus: params.get("focus") || "",
    });
    ensureVisited(nextView);
    activeView.value = nextView;
    if (requestedView !== nextView && replaceInvalid) {
      writeLocation(nextView, { replace: true });
    }
    return nextView;
  }

  function installLocationSync() {
    if (!hasWindowLocation() || popstateInstalled) {
      return;
    }
    window.addEventListener("popstate", () => hydrateFromLocation({ replaceInvalid: true }));
    popstateInstalled = true;
  }

  function clearFocus() {
    pendingFocusView.value = null;
    applyRouteContext();
    focusTarget.value = {
      target_type: null,
      target_id: null,
      target_ref: null,
      source_type: null,
      source_id: null,
    };
  }

  function navigate(nextView, options = {}) {
    if (viewMap[nextView]) {
      ensureVisited(nextView);
      if (pendingFocusView.value && pendingFocusView.value !== nextView) {
        pendingFocusView.value = null;
      }
      applyRouteContext(options.target || options.context || {});
      activeView.value = nextView;
      if (options.syncUrl !== false) {
        writeLocation(nextView, { replace: Boolean(options.replace), target: routeContext.value });
      }
    }
  }

  function targetView(targetType) {
    if (writerRoomTargetTypes.has(targetType)) {
      return "writer-room";
    }
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
    navigate(nextView, {
      replace: options.replace,
      target: {
        focus: target.target_type,
        target: target.target_ref || target.target_id,
      },
    });
  }

  function settleFocusView(viewId) {
    if (pendingFocusView.value === viewId) {
      pendingFocusView.value = null;
    }
  }

  function viewMeta(viewId) {
    return viewMap[viewId] || viewMap["snowflake-workbench"];
  }

  function isViewActive(viewId) {
    return activeView.value === viewId;
  }

  function reset(options = {}) {
    activeView.value = "snowflake-workbench";
    visitedViews.value = ["snowflake-workbench"];
    clearFocus();
    if (options.replace) {
      writeLocation(activeView.value, { replace: true, target: routeContext.value });
    }
  }

  return {
    activeView,
    visitedViews,
    routeContext,
    focusTarget,
    pendingFocusView,
    views,
    workflowGroups,
    navigate,
    openTarget,
    hydrateFromLocation,
    installLocationSync,
    serializeLocation,
    clearFocus,
    settleFocusView,
    viewMeta,
    isViewActive,
    reset,
  };
}
