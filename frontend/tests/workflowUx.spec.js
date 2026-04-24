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
  it("keeps the scene workbench as the default entry while exposing step navigation metadata", () => {
    const router = useShellRouter();

    router.reset();

    expect(router.activeView.value).toBe("workbench");
    expect(router.views.map((view) => view.id)).toEqual([
      "config",
      "author",
      "workbench",
      "review",
      "manuscripts",
      "trash",
      "index",
      "knowledge",
      "reference",
      "interop",
    ]);

    expect(router.viewMeta("workbench")).toEqual(
      expect.objectContaining({
        label: "3 运行场景",
        stepLabel: "运行场景",
        legacyLabel: "场景工作台",
        group: "运行与审核",
        icon: "PlayCircle",
        nextViews: ["review", "manuscripts"],
      }),
    );
    expect(router.viewMeta("config")).toEqual(
      expect.objectContaining({
        label: "1 配置环境",
        stepLabel: "配置环境",
        legacyLabel: "系统配置",
      }),
    );
  });

  it("ships grouped workflow metadata for every console page", () => {
    const router = useShellRouter();

    expect(router.workflowGroups.map((group) => group.id)).toEqual([
      "setup",
      "authoring",
      "runtime",
      "knowledge",
      "operations",
    ]);
    expect(router.views.every((view) => view.label && view.legacyLabel && view.stepLabel && view.group && view.icon)).toBe(true);
    expect(router.views.every((view) => Array.isArray(view.nextViews))).toBe(true);
  });
});

describe("guided and advanced UI modes", () => {
  beforeEach(() => {
    localStorage.clear();
  });

  it("defaults to guided mode and persists advanced mode", async () => {
    const { UI_MODE_STORAGE_KEY, useUiMode } = await import("../src/composables/useUiMode.js");
    const mode = useUiMode();

    expect(mode.uiMode.value).toBe("guided");
    expect(mode.isAdvancedMode.value).toBe(false);

    mode.setUiMode("advanced");

    expect(mode.uiMode.value).toBe("advanced");
    expect(mode.isAdvancedMode.value).toBe(true);
    expect(localStorage.getItem(UI_MODE_STORAGE_KEY)).toBe("advanced");

    mode.toggleUiMode();
    expect(mode.uiMode.value).toBe("guided");
  });

  it("provides shared workflow and evidence components", () => {
    const expectedFiles = [
      "src/components/WorkflowNav.vue",
      "src/components/WorkflowPageHeader.vue",
      "src/components/UiModeSwitch.vue",
      "src/components/EvidenceDisclosure.vue",
      "src/components/DangerConfirm.vue",
    ];

    expectedFiles.forEach((file) => {
      expect(existsSync(path.join(SOURCE_ROOT, file))).toBe(true);
    });
  });

  it("makes guided navigation simpler and advanced navigation visibly technical", async () => {
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
      expect(wrapper.el.textContent).toContain("3 运行场景");
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
    const { default: WorkflowNav } = await import("../src/components/WorkflowNav.vue");
    const router = useShellRouter();
    const onNavigate = vi.fn();

    router.reset();

    const wrapper = mountComponent(WorkflowNav, {
      views: router.views,
      groups: router.workflowGroups,
      activeView: router.activeView.value,
      onNavigate,
    });

    try {
      const selector = wrapper.el.querySelector('[data-testid="workflow-nav-mobile-select"]');

      expect(selector).not.toBeNull();
      expect(selector.value).toBe("workbench");
      expect([...selector.options].map((option) => option.value)).toEqual(router.views.map((view) => view.id));

      selector.value = "review";
      selector.dispatchEvent(new Event("change"));

      expect(onNavigate).toHaveBeenCalledWith("review");
      expect(wrapper.el.querySelector('[data-testid="workflow-nav-desktop-list"]')).not.toBeNull();
    } finally {
      wrapper.unmount();
    }
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
      expect(wrapper.el.querySelector('[data-testid="workflow-guided-brief-workbench"]')).not.toBeNull();
      expect(wrapper.el.querySelector('[data-testid="workflow-advanced-meta-workbench"]')).toBeNull();

      mode.setUiMode("advanced");
      await nextTick();

      const advancedMeta = wrapper.el.querySelector('[data-testid="workflow-advanced-meta-workbench"]');
      expect(advancedMeta?.textContent).toContain("view: workbench");
      expect(advancedMeta?.textContent).toContain("cache: light");
      expect(wrapper.el.querySelector('[data-testid="workflow-guided-brief-workbench"]')).toBeNull();
    } finally {
      wrapper.unmount();
    }
  });
});

describe("workflow page adoption", () => {
  it("uses the shared workflow page header on all ten console pages", () => {
    const pages = [
      "AuthorWorkspaceView.vue",
      "ChapterManuscriptView.vue",
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
