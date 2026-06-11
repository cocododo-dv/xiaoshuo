/* 侧栏信息架构 — 来自设计稿 ws-app 的四组导航。
   item.label 是导航显示名(设计稿文案);router 里的 view.label
   保持原值供面包屑等场景使用。 */
export const RAIL_GROUPS = [
  {
    id: "daily",
    label: "日常写作",
    advanced: false,
    items: [
      { id: "home", label: "主页" },
      { id: "flowmap", label: "流程" },
      { id: "snowflake-workbench", label: "构思" },
      { id: "writer-room", label: "写作" },
      { id: "reference", label: "风格" },
      { id: "review", label: "待办" },
      { id: "library", label: "资料" },
    ],
  },
  {
    id: "production",
    label: "生产与质控",
    advanced: true,
    items: [
      { id: "writer-flow", label: "写作总控" },
      { id: "author", label: "章节编排" },
      { id: "workbench", label: "AI 起草台" },
      { id: "manuscripts", label: "成稿中心" },
      { id: "deepdesk", label: "写作深改" },
      { id: "longform", label: "长篇控制塔" },
      { id: "quality", label: "文学质检" },
    ],
  },
  {
    id: "ops",
    label: "运维工具",
    advanced: true,
    items: [
      { id: "index", label: "发布索引" },
      { id: "knowledge", label: "沉淀知识" },
      { id: "interop", label: "导入导出" },
    ],
  },
  {
    id: "system",
    label: "系统",
    advanced: false,
    items: [
      { id: "config", label: "设置" },
      { id: "trash", label: "回收站" },
    ],
  },
];

const ADVANCED_ONLY_VIEW_IDS = new Set(
  RAIL_GROUPS.filter((group) => group.advanced).flatMap((group) => group.items.map((item) => item.id)),
);

const RAIL_LABELS = Object.fromEntries(
  RAIL_GROUPS.flatMap((group) => group.items.map((item) => [item.id, item.label])),
);

export function isAdvancedOnlyView(viewId) {
  return ADVANCED_ONLY_VIEW_IDS.has(viewId);
}

export function railLabel(viewId) {
  return RAIL_LABELS[viewId] || "";
}
