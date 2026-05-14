// @vitest-environment jsdom

import { readFileSync } from "node:fs";
import path from "node:path";

import { createPinia, setActivePinia } from "pinia";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { createApp, nextTick } from "vue";

import * as api from "../src/lib/api";

const SOURCE_ROOT = process.cwd();

function readSource(relativePath) {
  return readFileSync(path.join(SOURCE_ROOT, relativePath), "utf8");
}

function resolveVueImport(importerPath, specifier) {
  if (!specifier.startsWith(".") || !specifier.endsWith(".vue")) {
    return null;
  }
  return path.normalize(path.join(path.dirname(importerPath), specifier)).replace(/\\/g, "/");
}

function readVueImportGraphSource(entryPath) {
  const seen = new Set();
  const chunks = [];

  function visit(relativePath) {
    if (seen.has(relativePath)) {
      return;
    }
    seen.add(relativePath);

    const source = readSource(relativePath);
    chunks.push(source);

    for (const match of source.matchAll(/import\s+[^;]+?\s+from\s+["']([^"']+\.vue)["']/g)) {
      const resolved = resolveVueImport(relativePath, match[1]);
      if (resolved) {
        visit(resolved);
      }
    }
  }

  visit(entryPath);
  return chunks.join("\n");
}

function readSnowflakeViewSource() {
  return readVueImportGraphSource("src/views/SnowflakeWorkbenchView.vue");
}

function okEnvelope(data) {
  return {
    ok: true,
    json: async () => ({ ok: true, data }),
  };
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

const project = {
  project_id: "PRJ_WS",
  title: "Rain City Signal",
  status: "outline_draft",
  planning_mode: "snowflake",
  outline_text: "A cold case drags the heroine back home.",
  current_chapter_id: null,
};

const workspace = {
  project,
  current_step_key: "book_brief",
  ready_to_materialize: false,
  latest_plan: null,
  scene_board: { chapters: [], scenes: [] },
  triage_items: [],
  materialization_gate: { status: "blocked", blockers: ["Approve all snowflake steps."], warnings: [] },
  steps: [
    {
      step_key: "book_brief",
      label: "Reader Promise",
      phase: "\u95b8\u255f\u68e3\u9862\u546c\u5d19\u9361\u696a\u69f5",
      description: "Clarify who this story is for.",
      guidance: {
        instruction: "Define the reader promise before expanding the story.",
        checklist: ["Name the genre promise.", "Name the target reader."],
        timebox_minutes: 60,
        source: "snowflake_method_summary",
      },
      completeness: { filled_count: 0, total_count: 2, missing_fields: ["category", "target_reader"] },
      gate_satisfied: false,
      artifact: null,
      last_generation_source: null,
      last_llm_call_id: null,
      draft: {
        category: "",
        target_reader: "",
      },
      editor: {
        kind: "form",
        fields: [
          { key: "category", kind: "text", label: "Category" },
          {
            key: "target_reader",
            kind: "textarea",
            label: "Target Reader",
            hint: "Who will feel delighted by this promise?",
            placeholder: "Readers who want...",
          },
        ],
      },
    },
    {
      step_key: "one_sentence_summary",
      label: "One Sentence Summary",
      phase: "\u95c2\u55e9\u4ea3\u6fee\u5d07\u7cad?1 \u6fee?",
      description: "Summarize the book in one sentence.",
      guidance: {
        instruction: "Capture protagonist, desire, obstacle, and cost.",
        checklist: ["Keep it short.", "Name the pressure."],
        timebox_minutes: 60,
        source: "snowflake_method_summary",
      },
      completeness: { filled_count: 0, total_count: 1, missing_fields: ["summary"] },
      gate_satisfied: false,
      artifact: null,
      last_generation_source: null,
      last_llm_call_id: null,
      draft: { summary: "" },
      editor: {
        kind: "form",
        fields: [{ key: "summary", kind: "textarea", label: "Summary" }],
      },
    },
  ],
};

describe("snowflake workspace v2 api helpers", () => {
  beforeEach(() => {
    localStorage.clear();
    vi.restoreAllMocks();
  });

  it("calls the v2 snowflake workspace endpoints", async () => {
    globalThis.fetch = vi.fn(async () => okEnvelope({}));

    await api.fetchSnowflakeWorkspaceProjects();
    await api.createSnowflakeWorkspaceProject({ title: "Rain City Signal", outline_text: "Cold case outline" });
    await api.fetchSnowflakeWorkspace("PRJ_WS");
    await api.generateSnowflakeWorkspaceStep("PRJ_WS", "book_brief");
    await api.updateSnowflakeWorkspaceStep("PRJ_WS", "book_brief", { draft: { category: "Urban Mystery" } });
    await api.approveSnowflakeWorkspaceStep("PRJ_WS", "book_brief");
    await api.fetchSnowflakeStepHistory("PRJ_WS", "book_brief");
    await api.restoreSnowflakeWorkspaceStep("PRJ_WS", "book_brief", { step_run_id: "RUN_OLD" });
    await api.requestSnowflakeWorkspaceAssistant("PRJ_WS", { step_key: "book_brief", message: "Narrow the reader." });
    await api.requestSnowflakeSceneTriageSuggestions("PRJ_WS", { draft_override: { scenes: [] } });
    await api.saveSnowflakeSceneTriage("PRJ_WS", { items: [] });
    await api.updateSnowflakeWorkspaceScene("PRJ_WS", "SCENE_PLAN_1", { setback: "Cost rises." });
    await api.applySnowflakeSceneTriageRepair("PRJ_WS", "TRIAGE_1");
    await api.materializeSnowflakeWorkspace("PRJ_WS");
    await api.approveSnowflakeWorkspaceOutline("PRJ_WS");

    const calls = globalThis.fetch.mock.calls.map(([url, options = {}]) => [url, options.method || "GET"]);
    expect(calls).toContainEqual(["http://127.0.0.1:8000/api/v2/projects", "GET"]);
    expect(calls).toContainEqual(["http://127.0.0.1:8000/api/v2/projects", "POST"]);
    expect(calls).toContainEqual(["http://127.0.0.1:8000/api/v2/projects/PRJ_WS/snowflake-workspace", "GET"]);
    expect(calls).toContainEqual(["http://127.0.0.1:8000/api/v2/projects/PRJ_WS/snowflake-workspace/steps/book_brief/generate", "POST"]);
    expect(calls).toContainEqual(["http://127.0.0.1:8000/api/v2/projects/PRJ_WS/snowflake-workspace/steps/book_brief", "PATCH"]);
    expect(calls).toContainEqual(["http://127.0.0.1:8000/api/v2/projects/PRJ_WS/snowflake-workspace/steps/book_brief/approve", "POST"]);
    expect(calls).toContainEqual(["http://127.0.0.1:8000/api/v2/projects/PRJ_WS/snowflake-workspace/steps/book_brief/history", "GET"]);
    expect(calls).toContainEqual(["http://127.0.0.1:8000/api/v2/projects/PRJ_WS/snowflake-workspace/steps/book_brief/restore", "POST"]);
    expect(calls).toContainEqual(["http://127.0.0.1:8000/api/v2/projects/PRJ_WS/snowflake-workspace/assistant", "POST"]);
    expect(calls).toContainEqual(["http://127.0.0.1:8000/api/v2/projects/PRJ_WS/snowflake-workspace/scene-triage/suggest", "POST"]);
    expect(calls).toContainEqual(["http://127.0.0.1:8000/api/v2/projects/PRJ_WS/snowflake-workspace/scene-triage", "POST"]);
    expect(calls).toContainEqual(["http://127.0.0.1:8000/api/v2/projects/PRJ_WS/snowflake-workspace/scenes/SCENE_PLAN_1", "PATCH"]);
    expect(calls).toContainEqual(["http://127.0.0.1:8000/api/v2/projects/PRJ_WS/snowflake-workspace/scene-triage/TRIAGE_1/apply", "POST"]);
    expect(calls).toContainEqual(["http://127.0.0.1:8000/api/v2/projects/PRJ_WS/snowflake-workspace/materialize", "POST"]);
    expect(calls).toContainEqual(["http://127.0.0.1:8000/api/v2/projects/PRJ_WS/snowflake-workspace/outline/approve", "POST"]);
  });
});

describe("snowflake display labels", () => {
  it("maps stable machine keys into Chinese coaching labels", async () => {
    const {
      diagnosticLabel,
      fieldLabel,
      patchKeyListLabel,
      sceneFormLabel,
      sourceLabel,
      stepKeyLabel,
    } = await import("../src/lib/snowflakeDisplay");

    expect(fieldLabel("setback")).toBe("挫折");
    expect(fieldLabel("target_reader")).toBe("目标读者");
    expect(diagnosticLabel("missing_setback")).toBe("缺少挫折");
    expect(diagnosticLabel("weak_conflict_escalation")).toBe("冲突升级不足");
    expect(sourceLabel("fallback")).toBe("本地建议");
    expect(sourceLabel("llm")).toBe("模型建议");
    expect(sceneFormLabel("reactive")).toBe("反应场景");
    expect(stepKeyLabel("scene_details")).toBe("场景规划");
    expect(patchKeyListLabel({ setback: "证人开口，但代价升级。" })).toBe("挫折");
  });
});

describe("snowflake workspace store", () => {
  beforeEach(() => {
    localStorage.clear();
    setActivePinia(createPinia());
    vi.restoreAllMocks();
  });

  it("collapses stale step warnings in persistent local state without changing the workspace gate", async () => {
    const { useSnowflakeWorkbenchStore } = await import("../src/stores/snowflakeWorkbench");
    const store = useSnowflakeWorkbenchStore();
    const staleWorkspace = {
      ...workspace,
      project,
      materialization_gate: { status: "blocked", blockers: ["still blocked"], warnings: [], items: [] },
      steps: [
        {
          ...workspace.steps[0],
          artifact: {
            artifact_id: "ART_STALE",
            status: "stale",
            stale_reason: "upstream step changed",
            updated_at: "2026-05-13T00:00:00Z",
          },
        },
      ],
    };

    store.applyWorkspace(staleWorkspace);
    expect(store.isStaleStepDismissed(store.steps[0])).toBe(false);

    store.dismissStaleStep(store.steps[0]);

    expect(store.isStaleStepDismissed(store.steps[0])).toBe(true);
    expect(localStorage.getItem("snowflake-stale-dismissed:PRJ_WS::book_brief::ART_STALE::2026-05-13T00:00:00Z::upstream step changed")).toBe("1");
    expect(sessionStorage.getItem("snowflake-stale-dismissed:PRJ_WS::book_brief::ART_STALE::2026-05-13T00:00:00Z::upstream step changed")).toBeNull();
    expect(store.materializationGate.status).toBe("blocked");
    expect(store.materializationGate.blockers).toEqual(["still blocked"]);
  });

  it("loads snowflake step history, restores an old draft as pending review, and keeps discovery context as assistant input", async () => {
    const history = {
      step_key: "book_brief",
      items: [
        {
          step_run_id: "RUN_OLD",
          version: 1,
          status: "approved",
          draft_summary: "Readers who want family cost.",
          generation_source: "author",
        },
      ],
    };
    const restoredWorkspace = {
      ...workspace,
      steps: [
        {
          ...workspace.steps[0],
          artifact: { step_run_id: "RUN_RESTORED", status: "pending_review", version: 2 },
          draft: {
            category: "Urban Mystery",
            target_reader: "Readers who want family cost.",
          },
        },
        workspace.steps[1],
      ],
    };

    globalThis.fetch = vi.fn(async (url, options = {}) => {
      const method = options.method || "GET";
      if (url.endsWith("/api/v2/projects/PRJ_WS/snowflake-workspace/steps/book_brief/history") && method === "GET") {
        return okEnvelope(history);
      }
      if (url.endsWith("/api/v2/projects/PRJ_WS/snowflake-workspace/steps/book_brief/restore") && method === "POST") {
        expect(JSON.parse(options.body)).toEqual({ step_run_id: "RUN_OLD" });
        return okEnvelope({ step: restoredWorkspace.steps[0], workspace: restoredWorkspace });
      }
      if (url.endsWith("/api/v2/projects/PRJ_WS/snowflake-workspace/assistant") && method === "POST") {
        const body = JSON.parse(options.body);
        expect(body.discovery_draft_excerpt).toContain("sealed map in the station wall");
        expect(body.message).toContain("自由草稿");
        expect(body.draft_override).toEqual(restoredWorkspace.steps[0].draft);
        return okEnvelope({
          step_key: "book_brief",
          reply: "Use the discovery draft as emotional pressure.",
          suggestions: [],
          source: "fallback",
          llm_call_id: null,
          assistant_history: [],
        });
      }
      throw new Error(`Unexpected fetch ${method} ${url}`);
    });

    const { useSnowflakeWorkbenchStore } = await import("../src/stores/snowflakeWorkbench");
    const store = useSnowflakeWorkbenchStore();
    store.applyWorkspace(workspace);
    store.discoveryDraftContent = "She finds a sealed map in the station wall, then bargains for a witness.";

    await store.loadCurrentStepHistory();
    await store.restoreStepFromHistory("RUN_OLD");
    await store.requestAssistantFromDiscoveryDraft();

    expect(store.stepHistory.items[0].step_run_id).toBe("RUN_OLD");
    expect(store.currentStep.artifact.step_run_id).toBe("RUN_RESTORED");
    expect(store.currentStep.artifact.status).toBe("pending_review");
  });

  it("exposes project discovery draft api helpers and snowflake workbench controls", async () => {
    globalThis.fetch = vi.fn(async () => okEnvelope({}));

    await api.ensureProjectDiscoveryDraft("PRJ_WS");
    await api.fetchProjectDiscoveryDraft("PRJ_WS");
    await api.applyAuthorStructureCandidateToSnowflake("author_structure_project_PRJ_WS");

    const urls = globalThis.fetch.mock.calls.map(([url]) => String(url));
    expect(urls).toContain("http://127.0.0.1:8000/api/v1/projects/PRJ_WS/discovery-draft/ensure");
    expect(urls).toContain("http://127.0.0.1:8000/api/v1/projects/PRJ_WS/discovery-draft/current");
    expect(urls).toContain("http://127.0.0.1:8000/api/v1/author-structure-candidates/author_structure_project_PRJ_WS/apply-to-snowflake");

    const source = readSnowflakeViewSource();
    expect(source).toContain('data-testid="snowflake-discovery-draft"');
    expect(source).toContain("ensureDiscoveryDraft");
    expect(source).toContain("applyDiscoveryStructure");
    expect(source).toContain('data-testid="snowflake-discovery-context"');
    expect(source).toContain('data-testid="snowflake-discovery-assistant"');
    expect(source).toContain('data-testid="snowflake-step-history"');
    expect(source).toContain("loadCurrentStepHistory");
    expect(source).toContain("restoreStepFromHistory");
  });

  it("creates a workspace project and drives step save and approval through structured drafts", async () => {
    const savedWorkspace = {
      ...workspace,
      steps: [
        {
          ...workspace.steps[0],
          artifact: { artifact_id: "ART_BOOK", status: "pending_review", llm_call_id: null },
          draft: {
            category: "Urban Mystery",
            target_reader: "Readers who want cold cases and family cost.",
          },
        },
        workspace.steps[1],
      ],
    };
    const approvedWorkspace = {
      ...savedWorkspace,
      current_step_key: "one_sentence_summary",
      steps: [
        {
          ...savedWorkspace.steps[0],
          gate_satisfied: true,
          artifact: { artifact_id: "ART_BOOK", status: "approved", llm_call_id: null },
        },
        savedWorkspace.steps[1],
      ],
    };

    globalThis.fetch = vi.fn(async (url, options = {}) => {
      const method = options.method || "GET";
      if (url.endsWith("/api/v2/projects") && method === "GET") {
        return okEnvelope({ items: [] });
      }
      if (url.endsWith("/api/v2/projects") && method === "POST") {
        return okEnvelope({ project, workspace });
      }
      if (url.endsWith("/api/v2/projects/PRJ_WS/snowflake-workspace") && method === "GET") {
        return okEnvelope(workspace);
      }
      if (url.endsWith("/api/v2/projects/PRJ_WS/snowflake-workspace/steps/book_brief") && method === "PATCH") {
        return okEnvelope({ step: savedWorkspace.steps[0], workspace: savedWorkspace });
      }
      if (url.endsWith("/api/v2/projects/PRJ_WS/snowflake-workspace/steps/book_brief/approve")) {
        return okEnvelope({ step: approvedWorkspace.steps[0], workspace: approvedWorkspace });
      }
      throw new Error(`Unexpected fetch ${method} ${url}`);
    });

    const { useSnowflakeWorkbenchStore } = await import("../src/stores/snowflakeWorkbench");
    const store = useSnowflakeWorkbenchStore();

    await store.createProject({ title: "Rain City Signal", outline_text: "Cold case outline" });
    store.updateDraftField("target_reader", "Readers who want cold cases and family cost.");
    await store.saveCurrentStep();
    await store.approveCurrentStep();

    expect(store.project.project_id).toBe("PRJ_WS");
    expect(store.currentStep.step_key).toBe("one_sentence_summary");
    expect(store.workspace.steps[0].gate_satisfied).toBe(true);
    expect(store.lastActionMessage).toBe("雪花步骤已确认，可以进入下一层。");
  });

  it("autosaves the current draft before approving a dirty step", async () => {
    const savedWorkspace = {
      ...workspace,
      steps: [
        {
          ...workspace.steps[0],
          artifact: { artifact_id: "ART_BOOK", status: "pending_review", llm_call_id: null },
          draft: {
            category: "Urban Mystery",
            target_reader: "Unsaved local draft reader",
          },
        },
        workspace.steps[1],
      ],
    };
    const approvedWorkspace = {
      ...savedWorkspace,
      current_step_key: "one_sentence_summary",
      steps: [
        {
          ...savedWorkspace.steps[0],
          gate_satisfied: true,
          artifact: { artifact_id: "ART_BOOK", status: "approved", llm_call_id: null },
        },
        workspace.steps[1],
      ],
    };

    globalThis.fetch = vi.fn(async (url, options = {}) => {
      const method = options.method || "GET";
      if (url.endsWith("/api/v2/projects/PRJ_WS/snowflake-workspace/steps/book_brief") && method === "PATCH") {
        return okEnvelope({ step: savedWorkspace.steps[0], workspace: savedWorkspace });
      }
      if (url.endsWith("/api/v2/projects/PRJ_WS/snowflake-workspace/steps/book_brief/approve")) {
        return okEnvelope({ step: approvedWorkspace.steps[0], workspace: approvedWorkspace });
      }
      throw new Error(`Unexpected fetch ${method} ${url}`);
    });

    const { useSnowflakeWorkbenchStore } = await import("../src/stores/snowflakeWorkbench");
    const store = useSnowflakeWorkbenchStore();
    store.workspace = JSON.parse(JSON.stringify(workspace));
    store.project = project;
    store.selectedProjectId = project.project_id;

    store.updateDraftField("target_reader", "Unsaved local draft reader");
    expect(store.currentStepDirty).toBe(true);
    await store.approveCurrentStep();

    const calls = globalThis.fetch.mock.calls.map(([url, options = {}]) => [url, options.method || "GET"]);
    expect(calls).toEqual([
      ["http://127.0.0.1:8000/api/v2/projects/PRJ_WS/snowflake-workspace/steps/book_brief", "PATCH"],
      ["http://127.0.0.1:8000/api/v2/projects/PRJ_WS/snowflake-workspace/steps/book_brief/approve", "POST"],
    ]);
    const saveBody = JSON.parse(globalThis.fetch.mock.calls[0][1].body);
    expect(saveBody.draft.target_reader).toBe("Unsaved local draft reader");
    expect(store.currentStep.step_key).toBe("one_sentence_summary");
    expect(store.currentStepDirty).toBe(false);
  });

  it("skips the current step with an explicit reason through the flexible flow", async () => {
    const skippedWorkspace = {
      ...workspace,
      current_step_key: "one_sentence_summary",
      materialization_gate: {
        status: "warning",
        blockers: [],
        warnings: ["book_brief was skipped for this pass."],
      },
      steps: [
        {
          ...workspace.steps[0],
          gate_satisfied: true,
          can_skip: true,
          artifact: { artifact_id: "RUN_SKIP", status: "skipped", llm_call_id: null },
          health: {
            score: 100,
            status: "pass",
            gaps: [],
            next_actions: [],
            hard_blockers: [],
          },
          draft: { skipped: true, skip_reason: "Reader promise already lives in the outline." },
        },
        workspace.steps[1],
      ],
    };

    globalThis.fetch = vi.fn(async (url, options = {}) => {
      const method = options.method || "GET";
      if (url.endsWith("/api/v2/projects/PRJ_WS/snowflake-workspace/steps/book_brief/generate") && method === "POST") {
        return okEnvelope({ step: skippedWorkspace.steps[0], workspace: skippedWorkspace });
      }
      throw new Error(`Unexpected fetch ${method} ${url}`);
    });

    const { useSnowflakeWorkbenchStore } = await import("../src/stores/snowflakeWorkbench");
    const store = useSnowflakeWorkbenchStore();
    store.workspace = JSON.parse(JSON.stringify(workspace));
    store.project = project;
    store.selectedProjectId = project.project_id;

    await store.skipCurrentStep("Reader promise already lives in the outline.");

    const [, requestOptions] = globalThis.fetch.mock.calls[0];
    expect(JSON.parse(requestOptions.body)).toEqual({
      skip: true,
      skip_reason: "Reader promise already lives in the outline.",
    });
    expect(store.workspace.steps[0].artifact.status).toBe("skipped");
    expect(store.materializationGate.status).toBe("warning");
  });

  it("sends draft_override to the assistant and applies candidate patches without auto-saving", async () => {
    const persistedHistory = [
      {
        turn_id: "TURN_OLD",
        step_key: "book_brief",
        message: "Earlier question",
        reply: "Earlier reply",
        suggestions: [],
        source: "fallback",
        llm_call_id: null,
      },
    ];
    const assistantResult = {
      step_key: "book_brief",
      turn_id: "TURN_NEW",
      message: "Please narrow the reader.",
      reply: "Tighten the reader promise around family cost.",
      suggestions: ["Lead with cost before genre comfort."],
      source: "llm",
      llm_call_id: "LLM_ASSISTANT_1",
      candidate_label: "Narrow target reader",
      candidate_patch: {
        target_reader: "Readers who want cold cases and unresolved family cost.",
      },
      assistant_history: [
        ...persistedHistory,
        {
          turn_id: "TURN_NEW",
          step_key: "book_brief",
          message: "Please narrow the reader.",
          reply: "Tighten the reader promise around family cost.",
          suggestions: ["Lead with cost before genre comfort."],
          source: "llm",
          llm_call_id: "LLM_ASSISTANT_1",
          candidate_label: "Narrow target reader",
          candidate_patch: {
            target_reader: "Readers who want cold cases and unresolved family cost.",
          },
        },
      ],
    };

    globalThis.fetch = vi.fn(async (url, options = {}) => {
      const method = options.method || "GET";
      if (url.endsWith("/api/v2/projects/PRJ_WS/snowflake-workspace/assistant") && method === "POST") {
        return okEnvelope(assistantResult);
      }
      throw new Error(`Unexpected fetch ${method} ${url}`);
    });

    const { useSnowflakeWorkbenchStore } = await import("../src/stores/snowflakeWorkbench");
    const store = useSnowflakeWorkbenchStore();
    store.applyWorkspace({ ...workspace, assistant_history: persistedHistory });
    expect(store.assistantReplies).toEqual(persistedHistory);
    store.updateDraftField("target_reader", "Unsaved local draft reader");
    expect(store.currentStepDirty).toBe(true);

    await store.requestAssistant("Please narrow the reader.");

    const [, requestOptions] = globalThis.fetch.mock.calls[0];
    const requestBody = JSON.parse(requestOptions.body);
    expect(requestBody.draft_override.target_reader).toBe("Unsaved local draft reader");
    expect(store.assistantReplies).toEqual(assistantResult.assistant_history);

    store.applyAssistantCandidate(assistantResult);

    expect(store.currentStep.draft.target_reader).toBe("Readers who want cold cases and unresolved family cost.");
    expect(store.currentStepDirty).toBe(true);
    expect(globalThis.fetch).toHaveBeenCalledTimes(1);
    expect(store.actionId).toBe("");
  });

  it("merges collection candidate patches by stable ids and stages triage suggestions before save", async () => {
    const sceneWorkspace = {
      ...workspace,
      current_step_key: "scene_details",
      scene_board: {
        chapters: [{ chapter_id: "PRJ_WS_CH01", title: "Chapter 01", scene_count: 1 }],
        scenes: [
          {
            scene_plan_id: "SCENE_PLAN_1",
            scene_id: "PRJ_WS_CH01_SC01",
            chapter_id: "PRJ_WS_CH01",
            title: "Scene 01",
            scene_type: "proactive",
            goal: "Get the old letter source",
            conflict: "A relative blocks access",
            setback: "The clue points back home",
          },
        ],
      },
      triage_items: [{ scene_id: "PRJ_WS_CH01_SC01", title: "Scene 01", status: "", notes: "" }],
      steps: [
        workspace.steps[0],
        {
          step_key: "scene_details",
          label: "Scene Details",
          phase: "Scene / Sequel",
          description: "Break each scene into concrete pressure beats.",
          gate_satisfied: false,
          artifact: { artifact_id: "ART_SCENES", status: "pending_review", llm_call_id: null },
          last_generation_source: null,
          last_llm_call_id: null,
          draft: {
            scenes: [
              {
                scene_plan_id: "SCENE_PLAN_1",
                scene_id: "PRJ_WS_CH01_SC01",
                title: "Scene 01",
                scene_type: "proactive",
                goal: "Get the old letter source",
                conflict: "A relative blocks access",
                setback: "The clue points back home",
              },
            ],
          },
          editor: { kind: "form", fields: [] },
        },
      ],
    };
    const triageSuggestion = {
      items: [
        {
          scene_id: "PRJ_WS_CH01_SC01",
          title: "Scene 01",
          scene_type: "proactive",
          status: "maybe",
          notes: "Raise the conflict cost inside the scene.",
          missing_fields: ["setback"],
          fix_steps: ["Make the ending leave the protagonist worse off."],
        },
      ],
      source: "llm",
      llm_call_id: "LLM_TRIAGE_1",
    };

    globalThis.fetch = vi.fn(async (url, options = {}) => {
      const method = options.method || "GET";
      if (url.endsWith("/api/v2/projects/PRJ_WS/snowflake-workspace/scene-triage/suggest") && method === "POST") {
        return okEnvelope(triageSuggestion);
      }
      if (url.endsWith("/api/v2/projects/PRJ_WS/snowflake-workspace/scene-triage") && method === "POST") {
        return okEnvelope({
          items: triageSuggestion.items,
          workspace: { ...sceneWorkspace, triage_items: triageSuggestion.items },
        });
      }
      throw new Error(`Unexpected fetch ${method} ${url}`);
    });

    const { useSnowflakeWorkbenchStore } = await import("../src/stores/snowflakeWorkbench");
    const store = useSnowflakeWorkbenchStore();
    store.workspace = JSON.parse(JSON.stringify(sceneWorkspace));
    store.project = project;
    store.selectedProjectId = project.project_id;

    store.applyAssistantCandidate({
      candidate_patch: {
        scenes: [
          {
            scene_id: "PRJ_WS_CH01_SC01",
            conflict: "The new conflict pushes her directly against family loyalty.",
          },
        ],
      },
    });
    expect(store.currentStep.draft.scenes[0].goal).toBe("Get the old letter source");
    expect(store.currentStep.draft.scenes[0].conflict).toBe(
      "The new conflict pushes her directly against family loyalty.",
    );

    await store.requestSceneTriageSuggestions();
    expect(store.triageDrafts[0].status).toBe("maybe");
    expect(store.triageDrafts[0].missing_fields).toEqual(["setback"]);

    await store.saveSceneTriage();
    expect(store.triageItems[0].status).toBe("maybe");
  });

  it("updates structured scene plans and applies triage repair patches", async () => {
    const sceneWorkspace = {
      ...workspace,
      current_step_key: "scene_details",
      scene_board: {
        chapters: [{ chapter_id: "PRJ_WS_CH01", title: "Chapter 01", scene_count: 1 }],
        scenes: [
          {
            scene_plan_id: "SCENE_PLAN_1",
            scene_id: "PRJ_WS_CH01_SC01",
            chapter_id: "PRJ_WS_CH01",
            title: "Scene 01",
            scene_type: "proactive",
            goal: "Get the old letter source",
            conflict: "A relative blocks access",
            setback: "",
          },
        ],
      },
      triage_items: [
        {
          triage_id: "TRIAGE_1",
          scene_plan_id: "SCENE_PLAN_1",
          scene_id: "PRJ_WS_CH01_SC01",
          title: "Scene 01",
          status: "maybe",
          effective_status: "maybe",
          recommended_status: "maybe",
          missing_fields: ["setback"],
          fix_steps: ["End worse."],
          repair_patch: { setback: "The clue helps but exposes a family debt." },
        },
      ],
      steps: [
        workspace.steps[0],
        {
          step_key: "scene_details",
          label: "Scene Details",
          phase: "Scene / Sequel",
          description: "Break each scene into concrete pressure beats.",
          gate_satisfied: false,
          artifact: { artifact_id: "ART_SCENES", status: "pending_review", llm_call_id: null },
          last_generation_source: null,
          last_llm_call_id: null,
          draft: {
            scenes: [
              {
                scene_plan_id: "SCENE_PLAN_1",
                scene_id: "PRJ_WS_CH01_SC01",
                title: "Scene 01",
                scene_type: "proactive",
                goal: "Get the old letter source",
                conflict: "A relative blocks access",
                setback: "",
              },
            ],
          },
          editor: { kind: "form", fields: [] },
        },
      ],
    };
    const updatedWorkspace = {
      ...sceneWorkspace,
      scene_board: {
        ...sceneWorkspace.scene_board,
        scenes: [{ ...sceneWorkspace.scene_board.scenes[0], setback: "The first repair adds cost." }],
      },
    };
    const appliedWorkspace = {
      ...sceneWorkspace,
      scene_board: {
        ...sceneWorkspace.scene_board,
        scenes: [{ ...sceneWorkspace.scene_board.scenes[0], setback: "The clue helps but exposes a family debt." }],
      },
    };

    globalThis.fetch = vi.fn(async (url, options = {}) => {
      const method = options.method || "GET";
      if (url.endsWith("/api/v2/projects/PRJ_WS/snowflake-workspace/scenes/SCENE_PLAN_1") && method === "PATCH") {
        return okEnvelope({ scene: updatedWorkspace.scene_board.scenes[0], workspace: updatedWorkspace });
      }
      if (url.endsWith("/api/v2/projects/PRJ_WS/snowflake-workspace/scene-triage/TRIAGE_1/apply") && method === "POST") {
        return okEnvelope({
          triage: sceneWorkspace.triage_items[0],
          scene: appliedWorkspace.scene_board.scenes[0],
          workspace: appliedWorkspace,
        });
      }
      throw new Error(`Unexpected fetch ${method} ${url}`);
    });

    const { useSnowflakeWorkbenchStore } = await import("../src/stores/snowflakeWorkbench");
    const store = useSnowflakeWorkbenchStore();
    store.workspace = JSON.parse(JSON.stringify(sceneWorkspace));
    store.project = project;
    store.selectedProjectId = project.project_id;

    await store.updateScenePlan("SCENE_PLAN_1", { setback: "The first repair adds cost." });
    expect(store.sceneBoard.scenes[0].setback).toBe("The first repair adds cost.");

    await store.applyTriageRepair("TRIAGE_1");
    expect(store.sceneBoard.scenes[0].setback).toBe("The clue helps but exposes a family debt.");
  });

  it("persists scene triage items and materialized outline state", async () => {
    const sceneWorkspace = {
      ...workspace,
      current_step_key: null,
      ready_to_materialize: true,
      materialization_gate: {
        status: "warning",
        blockers: [],
        warnings: ["Scene 01 still needs revision."],
      },
      latest_plan: {
        plan_id: "PLAN_WS",
        status: "pending_review",
        plan_json: { source: "snowflake_method", chapters: [{ chapter_id: "PRJ_WS_CH01", scenes: [] }] },
      },
      triage_items: [{ scene_id: "PRJ_WS_CH01_SC01", title: "Scene 01", status: "", notes: "" }],
      steps: [
        {
          ...workspace.steps[0],
          gate_satisfied: true,
          artifact: { artifact_id: "ART_BOOK", status: "approved", llm_call_id: null },
        },
        {
          step_key: "scene_details",
          label: "Scene Details",
          phase: "Scene / Sequel",
          description: "Break each scene into concrete pressure beats.",
          gate_satisfied: true,
          artifact: { artifact_id: "ART_SCENES", status: "approved", llm_call_id: null },
          draft: {
            scenes: [
              {
                scene_id: "PRJ_WS_CH01_SC01",
                title: "Scene 01",
                scene_type: "proactive",
                goal: "Get the old letter source",
                conflict: "A relative blocks access",
                setback: "The clue points back home",
              },
            ],
          },
          editor: { kind: "form", fields: [] },
        },
      ],
    };
    const triagedWorkspace = {
      ...sceneWorkspace,
      triage_items: [{ scene_id: "PRJ_WS_CH01_SC01", title: "Scene 01", status: "maybe", notes: "Raise the cost." }],
    };

    globalThis.fetch = vi.fn(async (url, options = {}) => {
      const method = options.method || "GET";
      if (url.endsWith("/api/v2/projects/PRJ_WS/snowflake-workspace/materialize") && method === "POST") {
        return okEnvelope({ plan: sceneWorkspace.latest_plan, workspace: sceneWorkspace });
      }
      if (url.endsWith("/api/v2/projects/PRJ_WS/snowflake-workspace/scene-triage") && method === "POST") {
        return okEnvelope({ items: triagedWorkspace.triage_items, workspace: triagedWorkspace });
      }
      throw new Error(`Unexpected fetch ${method} ${url}`);
    });

    const { useSnowflakeWorkbenchStore } = await import("../src/stores/snowflakeWorkbench");
    const store = useSnowflakeWorkbenchStore();
    store.workspace = sceneWorkspace;
    store.project = project;
    store.selectedProjectId = project.project_id;
    store.triageDrafts = [{ scene_id: "PRJ_WS_CH01_SC01", status: "maybe", notes: "Raise the cost." }];
    await store.saveSceneTriage();
    const plan = await store.materializeOutline();

    expect(store.triageItems[0].status).toBe("maybe");
    expect(plan.plan_id).toBe("PLAN_WS");
    expect(store.latestPlan.plan_json.source).toBe("snowflake_method");
  });

  it("sends focus_scene_id to the assistant when triage mode has a selected scene", async () => {
    const sceneWorkspace = {
      ...workspace,
      current_step_key: "scene_details",
      triage_items: [
        {
          scene_id: "PRJ_WS_CH01_SC01",
          title: "Scene 01",
          status: "",
          recommended_status: "maybe",
          effective_status: "maybe",
          score: 68,
          missing_fields: ["setback"],
          pressure_flags: ["missing_setback"],
          fix_steps: ["Make the ending leave the protagonist worse off."],
          blocking: false,
        },
      ],
      steps: [
        workspace.steps[0],
        {
          step_key: "scene_details",
          label: "Scene Details",
          phase: "Scene / Sequel",
          description: "Break each scene into concrete pressure beats.",
          gate_satisfied: false,
          artifact: { artifact_id: "ART_SCENES", status: "pending_review", llm_call_id: null },
          last_generation_source: null,
          last_llm_call_id: null,
          draft: {
            scenes: [
              {
                scene_id: "PRJ_WS_CH01_SC01",
                title: "Scene 01",
                scene_type: "proactive",
                goal: "Get the old letter source",
                conflict: "A relative blocks access",
                setback: "",
              },
            ],
          },
          editor: { kind: "form", fields: [] },
        },
      ],
    };
    const assistantResult = {
      step_key: "scene_details",
      reply: "Focus the selected scene on its missing setback.",
      suggestions: ["End worse than the opening."],
      source: "fallback",
      llm_call_id: null,
      candidate_label: null,
      candidate_patch: null,
    };

    globalThis.fetch = vi.fn(async (url, options = {}) => {
      const method = options.method || "GET";
      if (url.endsWith("/api/v2/projects/PRJ_WS/snowflake-workspace/assistant") && method === "POST") {
        return okEnvelope(assistantResult);
      }
      throw new Error(`Unexpected fetch ${method} ${url}`);
    });

    const { useSnowflakeWorkbenchStore } = await import("../src/stores/snowflakeWorkbench");
    const store = useSnowflakeWorkbenchStore();
    store.workspace = JSON.parse(JSON.stringify(sceneWorkspace));
    store.project = project;
    store.selectedProjectId = project.project_id;

    store.setWorkbenchMode("triage");
    store.selectTriageScene("PRJ_WS_CH01_SC01");
    await store.requestAssistant("Help me repair the selected scene.");

    const [, requestOptions] = globalThis.fetch.mock.calls[0];
    const requestBody = JSON.parse(requestOptions.body);
    expect(requestBody.step_key).toBe("scene_details");
    expect(requestBody.focus_scene_id).toBe("PRJ_WS_CH01_SC01");
    expect(requestBody.draft_override.scenes[0].scene_id).toBe("PRJ_WS_CH01_SC01");
  });
});

describe("snowflake workbench UI source", () => {
  it("ships a dedicated workbench view with structured steps, assistant, triage, and outline approval", () => {
    const source = readSnowflakeViewSource();

    expect(source).toContain("snowflake-workbench-view");
    expect(source).toContain("snowflake-workbench-step-list");
    expect(source).toContain("snowflake-scene-triage");
    expect(source).toContain("snowflake-assistant-panel");
    expect(source).toContain("snowflake-outline-approve");
    expect(source).toContain("snowflake-guidance-card");
    expect(source).toContain("materialization-gate");
    expect(source).toContain("currentStepDirty");
    expect(source).toContain("quickAssistant");
    expect(source).toContain("applyAssistantCandidate");
    expect(source).toContain("requestSceneTriageSuggestions");
  });

  it("keeps the snowflake author path oriented with receipts, dirty status, and focus-safe project drawer controls", () => {
    const source = readSnowflakeViewSource();

    expect(source).toContain("useFlowActionFeedback");
    expect(source).toContain("FlowActionReceipt");
    expect(source).toContain("SNOWFLAKE_STEP_SCOPE");
    expect(source).toContain("SNOWFLAKE_PROJECT_SCOPE");
    expect(source).toContain('data-testid="snowflake-step-state-strip"');
    expect(source).toContain('data-testid="snowflake-stale-dismiss"');
    expect(source).toContain('data-testid="snowflake-stale-collapsed"');
    expect(source).toContain("未保存");
    expect(source).toContain("下一步：继续确认下一层雪花");
    expect(source).toContain("panelTrigger");
    expect(source).toContain("aria-expanded");
    expect(source).toContain("requestAnimationFrame");
  });

  it("ships dual planning and triage modes with a queue-detail repair surface", () => {
    const source = readSnowflakeViewSource();

    expect(source).toContain("workbenchMode");
    expect(source).toContain('data-testid="snowflake-mode-planning"');
    expect(source).toContain('data-testid="snowflake-mode-triage"');
    expect(source).toContain('data-testid="snowflake-triage-queue"');
    expect(source).toContain('data-testid="snowflake-triage-detail"');
    expect(source).toContain("selectedTriageItem");
    expect(source).toContain("triageFilter");
    expect(source).toContain("effective_status");
    expect(source).toContain("recommended_status");
    expect(source).toContain("score");
    expect(source).toContain("pressure_flags");
    expect(source).toContain("sceneBoard");
    expect(source).toContain("updateScenePlan");
    expect(source).toContain("applyTriageRepair");
    expect(source).toContain('data-testid="snowflake-scene-board"');
    expect(source).toContain('data-testid="snowflake-scene-board-drawer"');
  });

  it("does not expose technical English headings in the snowflake workbench chrome", () => {
    const source = readSnowflakeViewSource();

    expect(source).not.toContain(">Scene Board<");
    expect(source).not.toContain(">Scene Triage<");
    expect(source).not.toContain(">Materialization Gate<");
    expect(source).not.toContain(">Assistant<");
    expect(source).not.toContain("source:");
    expect(source).not.toContain("call:");
    expect(source).not.toContain(">Repair Patch<");
    expect(source).toContain("场景板");
    expect(source).toContain("场景急救");
    expect(source).toContain("准备度检查");
    expect(source).toContain("常驻助手");
  });

  it("uses an in-app skip dialog instead of a browser prompt for snowflake skips", () => {
    const source = readSnowflakeViewSource();

    expect(source).toContain("SnowflakeSkipStepDialog");
    expect(source).toContain("skipDialogOpen");
    expect(source).not.toContain("window.prompt");
  });

  it("keeps local snowflake drafts when a refreshed workspace would overwrite unsaved edits", async () => {
    const { useSnowflakeWorkbenchStore } = await import("../src/stores/snowflakeWorkbench");
    const store = useSnowflakeWorkbenchStore();

    store.applyWorkspace(workspace);
    store.updateDraftField("target_reader", "Readers who need family secrets and rain-soaked clues.");

    expect(store.currentStepDirty).toBe(true);
    expect(store.currentStep.draft.target_reader).toBe("Readers who need family secrets and rain-soaked clues.");

    store.applyWorkspace({
      ...workspace,
      steps: [
        {
          ...workspace.steps[0],
          draft: {
            ...workspace.steps[0].draft,
            target_reader: "Server generated replacement.",
          },
        },
        workspace.steps[1],
      ],
    });

    expect(store.currentStep.draft.target_reader).toBe("Readers who need family secrets and rain-soaked clues.");
    expect(store.currentStepDirty).toBe(true);
    expect(store.recoveredDraftNotice).toContain("已恢复未保存草稿");

    setActivePinia(createPinia());
    const restoredStore = useSnowflakeWorkbenchStore();
    restoredStore.applyWorkspace(workspace);

    expect(restoredStore.currentStep.draft.target_reader).toBe("Readers who need family secrets and rain-soaked clues.");
    expect(restoredStore.currentStepDirty).toBe(true);
  });

  it("keeps aggregate workbench styles scoped under the snowflake root", () => {
    const source = readSource("src/views/SnowflakeWorkbenchView.vue");
    const styleBlock = source.match(/<style>\s*([\s\S]*?)<\/style>/)?.[1] || "";
    const bareClassSelectors = styleBlock
      .split(/\r?\n/)
      .map((line) => line.trim().replace(/,$/, ""))
      .filter((line) => line.startsWith("."))
      .filter((line) => line !== ".snowflake-workbench-view" && !line.startsWith(".snowflake-workbench-view "));

    expect(bareClassSelectors).toEqual([]);
  });

  it("renders scene planning field-level hints from editor metadata", () => {
    const source = readSnowflakeViewSource();

    expect(source).toContain("sceneDetailFieldMeta");
    expect(source).toContain("sceneDetailFieldHint");
    expect(source).toContain("sceneDetailFieldPlaceholder");
    expect(source).toContain("sceneDetailFieldRows");
    expect(source).toContain("scenePrimaryForm");
    expect(source).toContain("updateScenePrimaryForm");
    expect(source).toContain("primary_form");
    expect(source).toContain("skipCurrentStep");
  });

  it("carries over the reference scene dynamics theory card for scene planning", () => {
    const source = readSnowflakeViewSource();

    expect(source).toContain('data-testid="snowflake-scene-dynamics-card"');
    expect(source).toContain("场景动力学 — 蔡格尼克开放循环原理");
    expect(source).toContain("主动场景 — 紧张引擎");
    expect(source).toContain("胜利：也要混入代价（否则读者放书）");
    expect(source).toContain("被动场景 — 呼吸与选择");
    expect(source).toContain("决定直接引发下一个目标");
  });

  it("keeps low-frequency project creation out of the persistent workspace columns", () => {
    const source = readSnowflakeViewSource();

    expect(source).toContain("panelOpen");
    expect(source).toContain('data-testid="snowflake-project-launcher"');
    expect(source).toContain('data-testid="snowflake-project-drawer"');
    expect(source).not.toContain('class="snowflake-project-sidebar"');
    expect(source).toMatch(
      /\.snowflake-workbench-shell\s*\{[\s\S]*grid-template-columns:\s*minmax\(0,\s*1fr\)\s+minmax\(260px,\s*320px\)/,
    );
  });

  it("uses a moss paper visual system with explicit readable card colors", () => {
    const source = readSource("src/views/SnowflakeWorkbenchView.vue");
    const appCss = readSource("src/styles/app.css");

    expect(source).toContain("--snowflake-paper");
    expect(source).toContain("--snowflake-ink");
    expect(source).toContain("--snowflake-moss");
    expect(source).toContain("--snowflake-teal");
    expect(source).toMatch(
      /\.snowflake-workbench-view \.project-row,\s*\n\.snowflake-workbench-view \.step-pill\s*\{[\s\S]*color:\s*var\(--snowflake-ink\)/,
    );
    expect(source).toMatch(
      /\.snowflake-workbench-view \.project-row strong,\s*\n\.snowflake-workbench-view \.step-pill strong\s*\{[\s\S]*color:\s*var\(--snowflake-heading\)/,
    );
    expect(source).toMatch(
      /\.snowflake-progress-track span\s*\{[\s\S]*background:\s*linear-gradient\(90deg,\s*var\(--snowflake-moss\),\s*var\(--snowflake-teal\)\)/,
    );
    const workflowActiveBlock = appCss.match(/\.workflow-nav-btn\.active\s*\{[^}]*\}/)?.[0] || "";
    const navActiveBlock = appCss.match(/\.nav-btn\.active\s*\{[^}]*\}/)?.[0] || "";
    expect(appCss).toContain("linear-gradient(135deg, #2f6f62 0%, #3f7d86 100%)");
    expect(workflowActiveBlock).not.toContain("var(--accent)");
    expect(navActiveBlock).not.toContain("var(--accent)");
  });
});

describe("snowflake reference fusion components", () => {
  it("renders a tutorial-style step guide with previous/next and triage handoff", async () => {
    const { default: SnowflakeStepGuideCard } = await import("../src/components/SnowflakeStepGuideCard.vue");
    const step = {
      step_key: "scene_details",
      label: "场景规划",
      english_label: "Scene Planning",
      phase: "雪花第9步",
      description: "为每个场景规划关键信息。主动场景制造紧张，被动场景让读者喘息并期待——两者交替构成故事的引擎。",
      guidance: {
        instruction:
          "【主动场景】\n目标：角色想达成什么？要具体可拍摄/量化\n坩埚：什么力量将角色困在这个处境里？\n冲突：多轮尝试→受阻的循环\n挫折：结尾比开场更糟，制造「开放循环」迫使读者翻页\n\n【反应场景】\n反应：情感先于理性——用身体/行为呈现，别直说「他很害怕」\n困境：真正的两难——每个选项都有代价\n决定：必须决断，决定引发下一个目标\n\n主动→被动→主动→被动……是故事前进的引擎。",
        checklist: [],
      },
      completeness: {
        filled_count: 4,
        total_count: 7,
        missing_fields: ["setback", "decision"],
      },
      health: {
        pressure_score: 62,
        pressure_status: "maybe",
        pressure_flags: ["weak_conflict_escalation", "weak_setback_cost", "decision_missing_next_goal"],
        fix_steps: ["让冲突升级成多轮尝试和受阻。", "让结尾留下更明确的代价。"],
        strengths: ["场景类型清晰。"],
      },
    };
    const steps = [
      { step_key: "scene_list", label: "场景列表" },
      step,
    ];
    const wrapper = mountComponent(SnowflakeStepGuideCard, {
      step,
      steps,
      currentStepIndex: 1,
      completedStepCount: 8,
      totalStepCount: 10,
      currentStepDirty: true,
    });

    try {
      expect(wrapper.el.querySelector('[data-testid="snowflake-step-guide-card"]')).not.toBeNull();
      expect(wrapper.el.textContent).toContain("步骤说明卡");
      expect(wrapper.el.textContent).not.toContain("Scene Planning");
      expect(wrapper.el.textContent).toContain("写作指引");
      expect(wrapper.el.textContent).not.toContain("【主动场景】");
      expect(wrapper.el.querySelector('[data-testid="snowflake-guide-toggle-instruction"]')?.getAttribute("aria-expanded")).toBe("false");
      expect(wrapper.el.querySelector('[data-testid="snowflake-pressure-diagnostic"]')).not.toBeNull();
      expect(wrapper.el.textContent).toContain("结构压力 62");
      expect(wrapper.el.textContent).not.toContain("冲突升级不足");
      expect(wrapper.el.textContent).not.toContain("让冲突升级成多轮尝试和受阻。");
      expect(wrapper.el.textContent).toContain("待补：挫折、决定");
      expect(wrapper.el.textContent).toContain("上一步");
      expect(wrapper.el.textContent).toContain("进入场景急救");

      wrapper.el.querySelector('[data-testid="snowflake-guide-toggle-instruction"]')?.dispatchEvent(new MouseEvent("click"));
      await nextTick();
      expect(wrapper.el.querySelector('[data-testid="snowflake-guide-toggle-instruction"]')?.getAttribute("aria-expanded")).toBe("true");
      expect(wrapper.el.textContent).toContain("【主动场景】");
      expect(wrapper.el.querySelector('[data-testid="snowflake-guide-instruction-body"]')?.textContent).toContain("\n目标：");

      wrapper.el.querySelector('[data-testid="snowflake-guide-toggle-diagnostic"]')?.dispatchEvent(new MouseEvent("click"));
      await nextTick();
      expect(wrapper.el.querySelector('[data-testid="snowflake-guide-toggle-diagnostic"]')?.getAttribute("aria-expanded")).toBe("true");
      expect(wrapper.el.textContent).toContain("冲突升级不足");
      expect(wrapper.el.textContent).toContain("让冲突升级成多轮尝试和受阻。");

      wrapper.el.querySelector('[data-testid="snowflake-step-prev"]')?.dispatchEvent(new MouseEvent("click"));
      wrapper.el.querySelector('[data-testid="snowflake-step-triage"]')?.dispatchEvent(new MouseEvent("click"));
      await nextTick();
    } finally {
      wrapper.unmount();
    }
  });

  it("keeps the step guide compatible when pressure diagnostics are absent", async () => {
    const { default: SnowflakeStepGuideCard } = await import("../src/components/SnowflakeStepGuideCard.vue");
    const step = {
      step_key: "one_sentence_summary",
      label: "一句话概括",
      english_label: "One-Sentence Summary",
      phase: "雪花第1步",
      description: "用一句话概括整部小说。",
      guidance: { instruction: "写出主角、目标、障碍和代价。", checklist: [] },
      completeness: { filled_count: 1, total_count: 1, missing_fields: [] },
    };
    const wrapper = mountComponent(SnowflakeStepGuideCard, {
      step,
      steps: [step],
      currentStepIndex: 0,
      completedStepCount: 1,
      totalStepCount: 10,
    });

    try {
      expect(wrapper.el.querySelector('[data-testid="snowflake-step-guide-card"]')).not.toBeNull();
      expect(wrapper.el.querySelector('[data-testid="snowflake-pressure-diagnostic"]')).toBeNull();
      expect(wrapper.el.textContent).toContain("这一层字段已补齐，可以继续向下扩展。");
    } finally {
      wrapper.unmount();
    }
  });

  it("renders the Snowflake 2.0 quality contract from guidance and health", async () => {
    const { default: SnowflakeStepGuideCard } = await import("../src/components/SnowflakeStepGuideCard.vue");
    const step = {
      step_key: "book_brief",
      label: "读者定位",
      english_label: "Target Audience",
      phase: "基础准备",
      description: "明确目标读者。",
      guidance: {
        instruction: "定义读者承诺。",
        checklist: ["写清楚具体读者。", "写清楚压力。"],
        rubric: { 场景可写性: "能否继续扩展成可写场景？" },
        required_for_materialization: true,
      },
      completeness: { filled_count: 1, total_count: 3, missing_fields: ["target_reader"] },
      health: {
        score: 48,
        status: "maybe",
        strengths: ["类型清晰。"],
        gaps: ["reader_promise_too_generic"],
        next_actions: ["收窄目标读者。"],
        hard_blockers: ["missing_target_reader"],
      },
    };
    const wrapper = mountComponent(SnowflakeStepGuideCard, {
      step,
      steps: [step],
      currentStepIndex: 0,
      completedStepCount: 0,
      totalStepCount: 10,
    });

    try {
      expect(wrapper.el.querySelector('[data-testid="snowflake-pressure-diagnostic"]')).not.toBeNull();
      expect(wrapper.el.textContent).toContain("48");
      expect(wrapper.el.textContent).not.toContain("读者承诺过于宽泛");
      expect(wrapper.el.textContent).not.toContain("收窄目标读者。");
      expect(wrapper.el.textContent).not.toContain("缺少目标读者");
      expect(wrapper.el.textContent).not.toContain("能否继续扩展成可写场景？");
      expect(wrapper.el.textContent).toContain("物化必需");

      wrapper.el.querySelector('[data-testid="snowflake-guide-toggle-checklist"]')?.dispatchEvent(new MouseEvent("click"));
      await nextTick();
      expect(wrapper.el.querySelector('[data-testid="snowflake-guide-toggle-checklist"]')?.getAttribute("aria-expanded")).toBe("true");
      expect(wrapper.el.textContent).toContain("写清楚具体读者。");

      wrapper.el.querySelector('[data-testid="snowflake-guide-toggle-rubric"]')?.dispatchEvent(new MouseEvent("click"));
      await nextTick();
      expect(wrapper.el.querySelector('[data-testid="snowflake-guide-toggle-rubric"]')?.getAttribute("aria-expanded")).toBe("true");
      expect(wrapper.el.textContent).toContain("能否继续扩展成可写场景？");

      wrapper.el.querySelector('[data-testid="snowflake-guide-toggle-diagnostic"]')?.dispatchEvent(new MouseEvent("click"));
      await nextTick();
      expect(wrapper.el.textContent).toContain("读者承诺过于宽泛");
      expect(wrapper.el.textContent).toContain("收窄目标读者。");
      expect(wrapper.el.textContent).toContain("缺少目标读者");
    } finally {
      wrapper.unmount();
    }
  });

  it("switches triage scene cards between proactive and reactive repair fields", async () => {
    const { default: SnowflakeTriageSceneCard } = await import("../src/components/SnowflakeTriageSceneCard.vue");
    const proactive = {
      triage_id: "TRIAGE_SC01",
      scene_id: "SC01",
      title: "审讯室对峙",
      scene_type: "proactive",
      recommended_status: "maybe",
      effective_status: "maybe",
      score: 64,
      missing_fields: ["setback"],
      fix_steps: ["让结尾比开场更糟。"],
      pressure_flags: ["missing_setback"],
      repair_patch: { setback: "证人开口，但把主角家族拖下水。" },
      goal: "拿到证词",
      conflict: "警探拦住她",
      setback: "",
      scene_crucible: "审讯室封闭且时间耗尽",
    };
    const wrapper = mountComponent(SnowflakeTriageSceneCard, { item: proactive });

    try {
      expect(wrapper.el.querySelector('[data-testid="snowflake-triage-scene-card"]')).not.toBeNull();
      expect(wrapper.el.textContent).toContain("主动场景（目标→冲突→挫折）");
      expect(wrapper.el.textContent).toContain("目标");
      expect(wrapper.el.textContent).toContain("冲突");
      expect(wrapper.el.textContent).toContain("挫折");
      expect(wrapper.el.textContent).toContain("急救步骤");
      expect(wrapper.el.textContent).toContain("修复补丁");
      expect(wrapper.el.textContent).toContain("缺少挫折");
      expect(wrapper.el.textContent).not.toContain("missing_setback");
      expect(wrapper.el.querySelector(".triage-repair-apply")?.textContent).toContain("挫折");
      expect(wrapper.el.querySelector(".triage-repair-apply")?.textContent).not.toContain("setback");

    } finally {
      wrapper.unmount();
    }

    const reactive = {
      ...proactive,
      scene_id: "SC02",
      primary_form: "reactive",
      scene_type: "reactive",
      recommended_status: "rewrite",
      effective_status: "rewrite",
      score: 31,
      reaction: "她先失语，再意识到代价。",
      dilemma: "认罪或让凶手逃脱。",
      decision: "签字前发出暗语。",
      repair_patch: {},
    };
    const reactiveWrapper = mountComponent(SnowflakeTriageSceneCard, { item: reactive });

    try {
      expect(reactiveWrapper.el.textContent).toContain("反应场景（反应→困境→决定）");
      expect(reactiveWrapper.el.textContent).toContain("反应");
      expect(reactiveWrapper.el.textContent).toContain("困境");
      expect(reactiveWrapper.el.textContent).toContain("决定");
      expect(reactiveWrapper.el.textContent).toContain("废除指南");
    } finally {
      reactiveWrapper.unmount();
    }
  });

  it("prefers primary_form over legacy scene_type when rendering triage structure", async () => {
    const { default: SnowflakeTriageSceneCard } = await import("../src/components/SnowflakeTriageSceneCard.vue");
    const wrapper = mountComponent(SnowflakeTriageSceneCard, {
      item: {
        scene_id: "SC_PRIMARY",
        title: "Mixed Form Scene",
        primary_form: "reactive",
        scene_type: "proactive",
        recommended_status: "maybe",
        effective_status: "maybe",
        reaction: "She absorbs the blow.",
        dilemma: "Tell the truth and lose the ally, or stay silent and lose the case.",
        decision: "She decides to call the ally next.",
      },
    });

    try {
      expect(wrapper.el.textContent).toContain("反应");
      expect(wrapper.el.textContent).toContain("困境");
      expect(wrapper.el.textContent).toContain("决定");
      expect(wrapper.el.textContent).not.toContain("挫折");
    } finally {
      wrapper.unmount();
    }
  });
});
