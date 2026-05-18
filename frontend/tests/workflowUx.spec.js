// @vitest-environment jsdom

import { existsSync, readFileSync } from "node:fs";
import path from "node:path";

import { createApp, nextTick } from "vue";
import { describe, expect, it, beforeEach, vi } from "vitest";

import { useShellRouter } from "../src/router";

const SOURCE_ROOT = process.cwd();

function readSource(relativePath) {
  return readFileSync(path.join(SOURCE_ROOT, relativePath), "utf8");
}

function mountComponent(component, props = {}) {
  const el = document.createElement("div");
  document.body.appendChild(el);
  const app = createApp(component, props);
  app.mount(el);
  return {
    el,
    unmount() {
      app.unmount();
      el.remove();
    },
  };
}

describe("workflow-driven shell metadata", () => {
  it("keeps the snowflake workbench as the default entry while exposing step navigation metadata", () => {
    const router = useShellRouter();

    router.reset();

    expect(router.activeView.value).toBe("snowflake-workbench");
    expect(router.views.map((view) => view.id)).toEqual([
      "snowflake-workbench",
      "writer-flow",
      "writer-room",
      "config",
      "author",
      "workbench",
      "review",
      "quality",
      "manuscripts",
      "deepdesk",
      "longform",
      "trash",
      "index",
      "knowledge",
      "reference",
      "interop",
    ]);

    expect(router.viewMeta("workbench")).toEqual(
      expect.objectContaining({
        label: "运行场景",
        stepLabel: "运行场景",
        legacyLabel: "场景工作台",
        stage: "toolbox",
        icon: "PlayCircle",
        nextViews: ["review", "manuscripts"],
      }),
    );
    expect(router.viewMeta("config")).toEqual(
      expect.objectContaining({
        label: "配置环境",
        stepLabel: "配置环境",
        legacyLabel: "系统配置",
      }),
    );
  });

  it("documents the snowflake workbench with the reference ten-step names", () => {
    const readme = readFileSync(path.join(SOURCE_ROOT, "..", "README.md"), "utf8");

    expect(readme).toContain(
      "读者定位、一句话概括、一段话概括、角色摘要表、一页梗概、角色背景故事、长篇大纲、角色全档案、场景列表、场景规划",
    );
    expect(readme).not.toContain("读者与类型");
    expect(readme).not.toContain("单场景计划");
  });

  it("ships grouped workflow metadata for every console page", () => {
    const router = useShellRouter();

    expect(router.workflowGroups.map((group) => group.id)).toEqual([
      "shape",
      "draft",
      "polish",
      "inform",
      "decide",
      "toolbox",
    ]);
    expect(router.views.every((view) => view.label && view.legacyLabel && view.stepLabel && view.stage && view.icon)).toBe(true);
    expect(router.views.every((view) => Array.isArray(view.nextViews))).toBe(true);
    expect(router.views
      .filter((view) => view.writerPrimary)
      .sort((left, right) => (left.writerOrder || 99) - (right.writerOrder || 99))
      .map((view) => view.id)).toEqual([
        "snowflake-workbench",
        "writer-flow",
        "writer-room",
        "reference",
        "review",
      ]);
    router.views
      .filter((view) => view.writerPrimary)
      .forEach((view) => {
        expect(view.writerGoal, `${view.id} writerGoal`).toBeTruthy();
        expect(view.writerDoneSignal, `${view.id} writerDoneSignal`).toBeTruthy();
      });
  });

  it("keeps every desktop navigation icon unique for the collapsed rail", () => {
    const router = useShellRouter();
    const icons = router.views.map((view) => view.icon);
    const iconByView = Object.fromEntries(router.views.map((view) => [view.id, view.icon]));

    expect(new Set(icons).size).toBe(icons.length);
    expect(iconByView["writer-room"]).not.toBe(iconByView.author);
    expect(iconByView.review).not.toBe(iconByView.quality);
    expect(iconByView.manuscripts).not.toBe(iconByView.deepdesk);
  });

  it("keeps shell navigation in the URL and restores deep-link context", async () => {
    const { UI_MODE_STORAGE_KEY } = await import("../src/composables/useUiMode.js");
    const router = useShellRouter();

    window.history.replaceState({}, "", "/");
    localStorage.clear();
    router.reset({ replace: true });

    router.navigate("review", {
      target: {
        step: "scene_details",
        panel: "materialization",
        target: "PRJ_WS_CH01_SC01",
      },
    });

    let params = new URL(window.location.href).searchParams;
    expect(params.get("view")).toBe("review");
    expect(params.get("step")).toBe("scene_details");
    expect(params.get("panel")).toBe("materialization");
    expect(params.get("target")).toBe("PRJ_WS_CH01_SC01");
    expect(router.routeContext.value).toMatchObject({
      step: "scene_details",
      panel: "materialization",
      target: "PRJ_WS_CH01_SC01",
    });

    window.history.replaceState({}, "", "/?view=reference&mode=advanced&step=book_brief&panel=assistant");
    router.hydrateFromLocation();

    expect(router.activeView.value).toBe("reference");
    expect(localStorage.getItem(UI_MODE_STORAGE_KEY)).toBe("advanced");
    expect(router.routeContext.value).toMatchObject({
      step: "book_brief",
      panel: "assistant",
    });

    window.history.replaceState({}, "", "/?view=missing-console&mode=writer");
    router.hydrateFromLocation();

    expect(router.activeView.value).toBe("snowflake-workbench");
    params = new URL(window.location.href).searchParams;
    expect(params.get("view")).toBe("snowflake-workbench");
    expect(localStorage.getItem(UI_MODE_STORAGE_KEY)).toBe("writer");
  });
});

describe("writer and advanced UI modes", () => {
  beforeEach(() => {
    localStorage.clear();
  });

  it("defaults to writer mode and persists advanced mode", async () => {
    const { UI_MODE_STORAGE_KEY, useUiMode } = await import("../src/composables/useUiMode.js");
    const mode = useUiMode();

    expect(mode.uiMode.value).toBe("writer");
    expect(mode.isAdvancedMode.value).toBe(false);

    mode.setUiMode("advanced");

    expect(mode.uiMode.value).toBe("advanced");
    expect(mode.isAdvancedMode.value).toBe(true);
    expect(localStorage.getItem(UI_MODE_STORAGE_KEY)).toBe("advanced");

    mode.toggleUiMode();
    expect(mode.uiMode.value).toBe("writer");
  });

  it("provides shared workflow and evidence components", () => {
    const expectedFiles = [
      "src/components/WorkflowNav.vue",
      "src/components/WriterPathProgress.vue",
      "src/components/WorkflowPageHeader.vue",
      "src/components/UiModeSwitch.vue",
      "src/components/EvidenceDisclosure.vue",
      "src/components/DangerConfirm.vue",
      "src/components/base/BaseEmptyState.vue",
      "src/components/base/BaseTooltip.vue",
      "src/components/base/BaseButton.vue",
      "src/components/base/BaseBadge.vue",
    ];

    expectedFiles.forEach((file) => {
      expect(existsSync(path.join(SOURCE_ROOT, file))).toBe(true);
    });
  });

  it("makes writer navigation daily-use only and advanced navigation visibly technical", async () => {
    const { useUiMode } = await import("../src/composables/useUiMode.js");
    const { default: WorkflowNav } = await import("../src/components/WorkflowNav.vue");
    const router = useShellRouter();
    const mode = useUiMode();

    router.reset();
    mode.setUiMode("guided");

    const wrapper = mountComponent(WorkflowNav, {
      views: router.views,
      groups: router.workflowGroups,
      activeView: router.activeView.value,
    });

    try {
      expect(wrapper.el.textContent).toContain("想清楚故事");
      expect(wrapper.el.textContent).toContain("写出这一章");
      expect(wrapper.el.textContent).toContain("打磨正文");
      expect(wrapper.el.textContent).toContain("学参考书");
      expect(wrapper.el.textContent).toContain("等你确认");
      expect(wrapper.el.textContent).not.toContain("编排章节");
      expect(wrapper.el.textContent).not.toContain("文学质检");
      expect(wrapper.el.textContent).not.toContain("场景工作台");
      expect(wrapper.el.querySelector('[data-testid="nav-workbench-route"]')).toBeNull();

      mode.setUiMode("advanced");
      await nextTick();

      expect(wrapper.el.textContent).toContain("场景工作台");
      expect(wrapper.el.querySelector('[data-testid="nav-workbench-route"]')?.textContent).toContain("view: workbench");
    } finally {
      wrapper.unmount();
    }
  });

  it("offers a compact mobile workflow selector without changing desktop nav events", async () => {
    const { useUiMode } = await import("../src/composables/useUiMode.js");
    const { default: WorkflowNav } = await import("../src/components/WorkflowNav.vue");
    const router = useShellRouter();
    const mode = useUiMode();
    const onNavigate = vi.fn();

    router.reset();
    mode.setUiMode("writer");

    const wrapper = mountComponent(WorkflowNav, {
      views: router.views,
      groups: router.workflowGroups,
      activeView: router.activeView.value,
      onNavigate,
    });

    try {
      const selector = wrapper.el.querySelector('[data-testid="workflow-nav-mobile-select"]');

      expect(selector).not.toBeNull();
      expect(selector.value).toBe("snowflake-workbench");
      expect([...selector.options].map((option) => option.value)).toEqual([
        "snowflake-workbench",
        "writer-flow",
        "writer-room",
        "reference",
        "review",
      ]);

      selector.value = "review";
      selector.dispatchEvent(new Event("change"));

      expect(onNavigate).toHaveBeenCalledWith("review");
      expect(wrapper.el.querySelector('[data-testid="workflow-nav-desktop-list"]')).not.toBeNull();
    } finally {
      wrapper.unmount();
    }
  });

  it("keeps desktop navigation usable as an icon rail when collapsed", async () => {
    const { useUiMode } = await import("../src/composables/useUiMode.js");
    const { default: WorkflowNav } = await import("../src/components/WorkflowNav.vue");
    const router = useShellRouter();
    const mode = useUiMode();
    const onNavigate = vi.fn();

    router.reset();
    mode.setUiMode("advanced");

    const wrapper = mountComponent(WorkflowNav, {
      views: router.views,
      groups: router.workflowGroups,
      activeView: router.activeView.value,
      collapsed: true,
      onNavigate,
    });

    try {
      const desktopList = wrapper.el.querySelector('[data-testid="workflow-nav-desktop-list"]');
      const workbenchButton = wrapper.el.querySelector('[data-testid="nav-workbench"]');
      const workbenchTitle = router.views.find((view) => view.id === "workbench").label;

      expect(desktopList).not.toBeNull();
      expect(workbenchButton).not.toBeNull();
      expect(workbenchButton.getAttribute("title")).toBe(workbenchTitle);
      expect(workbenchButton.getAttribute("aria-label")).toBe(workbenchTitle);
      expect(desktopList.textContent).not.toContain(workbenchTitle);
      expect(desktopList.textContent).not.toContain("view: workbench");
      expect(wrapper.el.querySelector('[data-testid="nav-workbench-route"]')).toBeNull();

      workbenchButton.dispatchEvent(new MouseEvent("click"));

      expect(onNavigate).toHaveBeenCalledWith("workbench");
    } finally {
      wrapper.unmount();
    }
  });

  it("collapses the writer rail to an icon-only column without step numbers", async () => {
    const { useUiMode } = await import("../src/composables/useUiMode.js");
    const { default: WorkflowNav } = await import("../src/components/WorkflowNav.vue");
    const router = useShellRouter();
    const mode = useUiMode();

    router.reset();
    mode.setUiMode("writer");

    const wrapper = mountComponent(WorkflowNav, {
      views: router.views,
      groups: router.workflowGroups,
      activeView: router.activeView.value,
      collapsed: true,
    });

    try {
      const snowflakeButton = wrapper.el.querySelector('[data-testid="nav-snowflake-workbench"]');

      expect(snowflakeButton).not.toBeNull();
      // The writer step number must not render in the collapsed icon rail.
      expect(wrapper.el.querySelector(".workflow-nav-number")).toBeNull();
      expect(snowflakeButton.querySelector(".workflow-nav-copy")).toBeNull();

      const styleSource = readSource("src/styles/app.css");
      // The collapsed single-column grid must out-specify the writer 3-column grid.
      expect(styleSource).toMatch(
        /\.ui-mode-writer \.workflow-nav\.collapsed \.workflow-nav-btn[\s\S]*?grid-template-columns:\s*1fr/,
      );
    } finally {
      wrapper.unmount();
    }
  });

  it("declares persisted shell rail collapse state and responsive styles", () => {
    const appSource = readSource("src/App.vue");
    const styleSource = readSource("src/styles/app.css");

    expect(appSource).toContain("railCollapsed");
    expect(appSource).toContain("novel-system:rail-collapsed");
    expect(appSource).toContain("PanelLeftClose");
    expect(appSource).toContain("PanelLeftOpen");
    expect(appSource).toContain('data-testid="rail-toggle"');
    expect(styleSource).toContain(".shell.rail-collapsed");
    expect(styleSource).toContain(".rail-toggle");
    expect(styleSource).toMatch(/@media \(max-width:\s*980px\)[\s\S]*\.shell\.rail-collapsed/);
  });

  it("mounts the writer path task bar only in writer mode", () => {
    const appSource = readSource("src/App.vue");
    const componentSource = readSource("src/components/WriterPathProgress.vue");
    const styleSource = readSource("src/styles/app.css");

    expect(appSource).toContain("WriterPathProgress");
    expect(appSource).toContain('v-if="uiMode === \'writer\'"');
    expect(componentSource).toContain('data-testid="writer-path-progress"');
    expect(componentSource).toContain('data-testid="writer-path-active-summary"');
    expect(styleSource).toContain(".writer-path-progress");
    expect(componentSource).toMatch(/@media \(max-width:\s*768px\)[\s\S]*\.journey-breadcrumb/);
  });

  it("keeps page headers outcome-first in guided mode and metadata-rich in advanced mode", async () => {
    const { useUiMode } = await import("../src/composables/useUiMode.js");
    const { default: WorkflowPageHeader } = await import("../src/components/WorkflowPageHeader.vue");
    const router = useShellRouter();
    const mode = useUiMode();

    router.reset();
    mode.setUiMode("guided");

    const wrapper = mountComponent(WorkflowPageHeader, { viewId: "workbench" });

    try {
      expect(wrapper.el.querySelector('[data-testid="workflow-advanced-meta-workbench"]')).toBeNull();
      expect(wrapper.el.textContent).toContain(router.viewMeta("workbench").description);

      mode.setUiMode("advanced");
      await nextTick();

      const advancedMeta = wrapper.el.querySelector('[data-testid="workflow-advanced-meta-workbench"]');
      expect(advancedMeta?.textContent).toContain("view: workbench");
      expect(advancedMeta?.textContent).toContain("cache: light");
    } finally {
      wrapper.unmount();
    }
  });

  it("renders writer path goal and done signal in writer mode headers, leaving next action to the guidance card", async () => {
    const { useUiMode } = await import("../src/composables/useUiMode.js");
    const { default: WorkflowPageHeader } = await import("../src/components/WorkflowPageHeader.vue");
    const router = useShellRouter();
    const mode = useUiMode();

    router.reset();
    mode.setUiMode("writer");

    const wrapper = mountComponent(WorkflowPageHeader, { viewId: "snowflake-workbench" });

    try {
      // Writer mode shows description plus a compact 目标/完成信号 line; next
      // action stays in the guidance card. Advanced metadata stays hidden.
      const meta = router.viewMeta("snowflake-workbench");
      expect(wrapper.el.textContent).toContain(meta.description);
      const aim = wrapper.el.querySelector('[data-testid="workflow-writer-aim-snowflake-workbench"]');
      expect(aim).not.toBeNull();
      expect(aim.textContent).toContain(meta.writerGoal);
      expect(aim.textContent).toContain(meta.writerDoneSignal);
      expect(wrapper.el.querySelector('[data-testid="workflow-advanced-meta-snowflake-workbench"]')).toBeNull();
      expect(meta.writerNextAction).toBeUndefined();

      mode.setUiMode("advanced");
      await nextTick();

      expect(wrapper.el.querySelector('[data-testid="workflow-writer-aim-snowflake-workbench"]')).toBeNull();
      expect(wrapper.el.querySelector('[data-testid="workflow-advanced-meta-snowflake-workbench"]')).not.toBeNull();
    } finally {
      wrapper.unmount();
    }
  });

  it("adds accessible expanded state to shared disclosure controls", async () => {
    const { useUiMode } = await import("../src/composables/useUiMode.js");
    const { default: LazySection } = await import("../src/components/LazySection.vue");
    const { default: EvidenceDisclosure } = await import("../src/components/EvidenceDisclosure.vue");

    useUiMode().setUiMode("writer");

    const lazy = mountComponent(LazySection, {
      title: "关联证据",
      toggleTestId: "lazy-a11y-toggle",
    });

    try {
      const toggle = lazy.el.querySelector('[data-testid="lazy-a11y-toggle"]');
      expect(toggle.getAttribute("aria-expanded")).toBe("false");
      expect(toggle.getAttribute("aria-controls")).toBeTruthy();

      toggle.click();
      await nextTick();
      expect(toggle.getAttribute("aria-expanded")).toBe("true");
      expect(lazy.el.querySelector(`#${toggle.getAttribute("aria-controls")}`)).not.toBeNull();
    } finally {
      lazy.unmount();
    }

    const evidence = mountComponent(EvidenceDisclosure, {
      title: "运行证据",
      testId: "evidence-a11y",
    });

    try {
      const toggle = evidence.el.querySelector('[data-testid="evidence-a11y-toggle"]');
      expect(toggle.getAttribute("aria-expanded")).toBe("false");
      expect(toggle.getAttribute("aria-controls")).toBeTruthy();
    } finally {
      evidence.unmount();
    }
  });
});

describe("workflow page adoption", () => {
  it("uses the shared workflow page header on all console pages", () => {
    const pages = [
      "SnowflakeWorkbenchView.vue",
      "WriterRoomView.vue",
      "AuthorWorkspaceView.vue",
      "ChapterManuscriptView.vue",
      "WriterDeepDeskView.vue",
      "LongformControlView.vue",
      "AuthorTrashView.vue",
      "SceneWorkbenchView.vue",
      "ReviewInboxView.vue",
      "IndexConsoleView.vue",
      "KnowledgeConsoleView.vue",
      "ReferenceLearningView.vue",
      "InteropCenterView.vue",
      "SystemConfigView.vue",
    ];

    pages.forEach((page) => {
      const source = readSource(`src/views/${page}`);
      expect(source).toContain("WorkflowPageHeader");
    });
  });

  it("moves heavy implementation evidence behind explicit disclosure controls", () => {
    const sceneSource = readSource("src/views/SceneWorkbenchView.vue");
    const indexSource = readSource("src/views/IndexConsoleView.vue");
    const configSource = readSource("src/views/SystemConfigView.vue");

    expect(sceneSource).toContain("EvidenceDisclosure");
    expect(sceneSource).toContain('test-id="scene-workbench-evidence-disclosure"');
    expect(indexSource).toContain("EvidenceDisclosure");
    expect(indexSource).toContain('test-id="index-advanced-evidence"');
    expect(configSource).toContain("EvidenceDisclosure");
    expect(configSource).toContain('test-id="config-advanced-evidence"');
  });

  it("keeps noisy technical fields out of guided copy on the densest consoles", () => {
    const configSource = readSource("src/views/SystemConfigView.vue");
    const knowledgeSource = readSource("src/views/KnowledgeConsoleView.vue");
    const interopSource = readSource("src/views/InteropCenterView.vue");
    const sceneSource = readSource("src/views/SceneWorkbenchView.vue");

    expect(configSource).toContain("useUiMode");
    expect(configSource).toContain('isAdvancedMode ? "接入 ID" : "接入名称"');
    expect(configSource).toContain('id="config-dashboard-tab-advanced"');
    expect(configSource).toContain('v-if="isAdvancedMode"');

    expect(knowledgeSource).toContain("useUiMode");
    expect(knowledgeSource).toContain('isAdvancedMode ? "审核 ID" : "来源审核"');
    expect(knowledgeSource).toContain('data-testid="knowledge-extra-payload-field"');
    expect(knowledgeSource).toContain('v-if="isAdvancedMode"');

    expect(interopSource).toContain("useUiMode");
    expect(interopSource).toContain('isAdvancedMode ? "工作表 YAML" : "粘贴工作表"');
    expect(interopSource).toContain('data-testid="interop-envelope-technical"');

    expect(sceneSource).toContain("useUiMode");
    expect(sceneSource).toContain('data-testid="scene-bundle-technical-stats"');
    expect(sceneSource).toContain('运行快照');
  });

  it("keeps review and index internal references mode-aware", () => {
    const reviewSource = readSource("src/components/ReviewCard.vue");
    const humanReviewSource = readSource("src/components/HumanReviewDrawer.vue");
    const indexSource = readSource("src/views/IndexConsoleView.vue");
    const targetActivitySource = readSource("src/components/TargetActivityGroupCard.vue");

    expect(reviewSource).toContain("useUiMode");
    expect(reviewSource).toContain('isAdvancedMode ? "审核 ID" : "审核线索"');
    expect(reviewSource).toContain('data-testid="review-technical-ref"');

    expect(humanReviewSource).toContain("useUiMode");
    expect(humanReviewSource).toContain('data-testid="human-review-technical-ref"');
    expect(humanReviewSource).toContain("formatGuidedTargetRef");

    expect(indexSource).toContain("useUiMode");
    expect(indexSource).toContain('isAdvancedMode ? "审核 ID" : "审核线索"');
    expect(indexSource).toContain('data-testid="index-job-technical-ref"');
    expect(indexSource).toContain('data-testid="index-target-filter-technical-ref"');

    expect(targetActivitySource).toContain("useUiMode");
    expect(targetActivitySource).toContain('data-testid="index-target-technical-ref"');
    expect(targetActivitySource).toContain("formatGuidedTargetRef");
  });
});
