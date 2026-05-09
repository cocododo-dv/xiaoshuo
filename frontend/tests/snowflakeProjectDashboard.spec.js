// @vitest-environment jsdom

import { readFileSync } from "node:fs";
import path from "node:path";

import { createPinia, setActivePinia } from "pinia";
import { beforeEach, describe, expect, it, vi } from "vitest";

import * as api from "../src/lib/api";

const SOURCE_ROOT = process.cwd();

function readSource(relativePath) {
  return readFileSync(path.join(SOURCE_ROOT, relativePath), "utf8");
}

function okEnvelope(data) {
  return {
    ok: true,
    json: async () => ({ ok: true, data }),
  };
}

const project = {
  project_id: "PRJ_SNOW",
  title: "雨城残响",
  status: "outline_draft",
  planning_mode: "snowflake",
  outline_text: "第一章发现旧信",
  current_chapter_id: null,
  reference_profile_ids: [],
  approved_chapter_ids: [],
};

const snowflakeState = {
  project,
  current_step_key: "book_brief",
  next_action: "generate_snowflake_step",
  blocking_reason: null,
  ready_to_materialize: false,
  steps: [
    {
      step_key: "book_brief",
      label: "读者定位",
      gate_satisfied: false,
      artifact: null,
    },
    {
      step_key: "one_sentence_summary",
      label: "一句话概括",
      gate_satisfied: false,
      artifact: null,
    },
  ],
};

describe("snowflake project dashboard API", () => {
  beforeEach(() => {
    localStorage.clear();
    vi.restoreAllMocks();
  });

  it("exposes snowflake API helpers", async () => {
    globalThis.fetch = vi.fn(async () => okEnvelope({}));

    await api.fetchProjectSnowflake("PRJ_SNOW");
    await api.generateSnowflakeStep("PRJ_SNOW", "book_brief");
    await api.updateSnowflakeArtifact("PRJ_SNOW", "ART_1", { artifact_json: { target_reader: "读者" } });
    await api.approveSnowflakeArtifact("PRJ_SNOW", "ART_1");
    await api.materializeSnowflakeOutlinePlan("PRJ_SNOW");

    const calls = globalThis.fetch.mock.calls.map(([url, options = {}]) => [url, options.method || "GET"]);
    expect(calls).toContainEqual(["http://127.0.0.1:8000/api/v1/projects/PRJ_SNOW/snowflake", "GET"]);
    expect(calls).toContainEqual(["http://127.0.0.1:8000/api/v1/projects/PRJ_SNOW/snowflake/steps/book_brief/generate", "POST"]);
    expect(calls).toContainEqual(["http://127.0.0.1:8000/api/v1/projects/PRJ_SNOW/snowflake/artifacts/ART_1", "PATCH"]);
    expect(calls).toContainEqual(["http://127.0.0.1:8000/api/v1/projects/PRJ_SNOW/snowflake/artifacts/ART_1/approve", "POST"]);
    expect(calls).toContainEqual(["http://127.0.0.1:8000/api/v1/projects/PRJ_SNOW/snowflake/materialize-outline-plan", "POST"]);
  });
});

describe("snowflake project dashboard store", () => {
  beforeEach(() => {
    localStorage.clear();
    setActivePinia(createPinia());
    vi.restoreAllMocks();
  });

  it("creates new projects in snowflake mode and drives proposal approval", async () => {
    const generatedArtifact = {
      artifact_id: "ART_BOOK",
      step_key: "book_brief",
      version: 1,
      status: "pending_review",
      artifact_json: { target_reader: "喜欢旧案的读者" },
      diagnosis_json: { message: "候选已生成" },
    };
    const approvedState = {
      ...snowflakeState,
      current_step_key: "one_sentence_summary",
      steps: [
        {
          ...snowflakeState.steps[0],
          gate_satisfied: true,
          artifact: { ...generatedArtifact, status: "approved", approved_at: "now" },
        },
        snowflakeState.steps[1],
      ],
    };

    globalThis.fetch = vi.fn(async (url, options = {}) => {
      const method = options.method || "GET";
      if (url.endsWith("/api/v1/projects") && method === "GET") {
        return okEnvelope({ items: [] });
      }
      if (url.endsWith("/api/v1/projects") && method === "POST") {
        expect(JSON.parse(options.body).planning_mode).toBe("snowflake");
        return okEnvelope({ project });
      }
      if (url.endsWith("/api/v1/projects/PRJ_SNOW/dashboard")) {
        return okEnvelope({
          project,
          latest_plan: null,
          chapters: [],
          reference_profiles: [],
          next_action: "generate_snowflake_step",
        });
      }
      if (url.endsWith("/api/v1/projects/PRJ_SNOW/snowflake") && method === "GET") {
        return okEnvelope(snowflakeState);
      }
      if (url.endsWith("/api/v1/projects/PRJ_SNOW/snowflake/steps/book_brief/generate")) {
        return okEnvelope({ artifact: generatedArtifact, state: snowflakeState });
      }
      if (url.endsWith("/api/v1/projects/PRJ_SNOW/snowflake/artifacts/ART_BOOK")) {
        return okEnvelope({
          artifact: { ...generatedArtifact, artifact_json: { target_reader: "作者编辑后的读者" } },
          state: snowflakeState,
        });
      }
      if (url.endsWith("/api/v1/projects/PRJ_SNOW/snowflake/artifacts/ART_BOOK/approve")) {
        return okEnvelope({ artifact: { ...generatedArtifact, status: "approved" }, state: approvedState });
      }
      throw new Error(`Unexpected fetch ${method} ${url}`);
    });

    const { useProjectDashboardStore } = await import("../src/stores/projectDashboard");
    const store = useProjectDashboardStore();
    await store.createFromDraft({ title: "雨城残响", outline_text: "第一章发现旧信" });
    await store.loadSnowflake();
    const artifact = await store.generateCurrentSnowflakeStep();
    await store.updateSnowflakeArtifact(artifact.artifact_id, { target_reader: "作者编辑后的读者" });
    await store.approveSnowflakeArtifact(artifact.artifact_id);

    expect(store.project.planning_mode).toBe("snowflake");
    expect(store.snowflakeState.current_step_key).toBe("one_sentence_summary");
    expect(store.currentSnowflakeStep.step_key).toBe("one_sentence_summary");
    expect(store.lastActionMessage).toBe("雪花步骤已确认，可以进入下一层。");
  });

  it("materializes approved snowflake steps into a reviewable outline plan", async () => {
    const readyState = {
      ...snowflakeState,
      current_step_key: null,
      next_action: "materialize_outline_plan",
      ready_to_materialize: true,
      steps: snowflakeState.steps.map((step) => ({ ...step, gate_satisfied: true })),
    };
    const plan = {
      plan_id: "PLAN_SNOW",
      status: "pending_review",
      plan_json: {
        source: "snowflake_method",
        chapters: [{ chapter_id: "PRJ_SNOW_CH01", scenes: [] }],
      },
    };

    globalThis.fetch = vi.fn(async (url) => {
      if (url.endsWith("/api/v1/projects/PRJ_SNOW/snowflake/materialize-outline-plan")) {
        return okEnvelope({ project: { ...project, status: "outline_review" }, plan });
      }
      if (url.endsWith("/api/v1/projects/PRJ_SNOW/snowflake")) {
        return okEnvelope(readyState);
      }
      throw new Error(`Unexpected fetch ${url}`);
    });

    const { useProjectDashboardStore } = await import("../src/stores/projectDashboard");
    const store = useProjectDashboardStore();
    store.applyDashboard({ project, latest_plan: null, chapters: [], next_action: "materialize_outline_plan" });
    store.snowflake = readyState;

    const materialized = await store.materializeSnowflakePlan();

    expect(materialized.plan_id).toBe("PLAN_SNOW");
    expect(store.latestPlan.plan_json.source).toBe("snowflake_method");
    expect(store.lastActionMessage).toBe("雪花规划已物化为结构计划，等待确认。");
  });
});

describe("snowflake project dashboard UI source", () => {
  it("shows snowflake progress, proposal editing, stale state, and materialization controls", () => {
    const source = readSource("src/views/ProjectDashboardView.vue");

    expect(source).toContain("雪花规划");
    expect(source).toContain("snowflake-step-list");
    expect(source).toContain("snowflake-artifact-editor");
    expect(source).toContain("确认本步");
    expect(source).toContain("整理成章节结构");
    expect(source).toContain("stale");
  });
});
