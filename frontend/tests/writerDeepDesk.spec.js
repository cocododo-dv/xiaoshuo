// @vitest-environment jsdom

import { existsSync, readFileSync } from "node:fs";
import path from "node:path";

import { createPinia, setActivePinia } from "pinia";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

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

function chapterListPayload() {
  return {
    items: [
      {
        chapter_id: "DESKFE100",
        chapter_goal: "林岑必须决定是否公开证据。",
        completion_status: "partial",
        comparison_status: "aggregate_missing",
      },
    ],
  };
}

function chapterDetailPayload() {
  return {
    chapter_id: "DESKFE100",
    aggregate: { row_id: "chapter_memory_final_DESKFE100_v1", content: "最终聚合稿。" },
    assembled: { content: "实时拼接稿。" },
    scenes: [
      {
        scene_id: "DESKFE100_SC01",
        chapter_id: "DESKFE100",
        scene_goal: "她先关门再公开录音。",
        final_scene: { row_id: "final_scene_DESKFE100_SC01_v1" },
      },
    ],
  };
}

function authorDraftPayload() {
  return {
    draft: {
      draft_id: "author_draft_scene_DESKFE100_SC01",
      object_type: "scene",
      object_id: "DESKFE100_SC01",
      source_text_ref: "final_scene:final_scene_DESKFE100_SC01_v1",
      content: "作者稿正文。",
      revision_no: 2,
      status: "current",
    },
    draft_mode: "scene",
    desk_mode: "write_first",
    source_layer: "author_draft",
    open_structure_candidates: [],
    open_patch_candidates: [],
    open_draft_proposals: [draftProposalPayload()],
    author_preference_summary: {},
  };
}

function draftProposalPayload(overrides = {}) {
  return {
    proposal_id: overrides.proposal_id || "proposal_DESKFE100_SC01",
    draft_id: "author_draft_scene_DESKFE100_SC01",
    object_type: "scene",
    object_id: "DESKFE100_SC01",
    proposal_type: overrides.proposal_type || "scene_draft",
    proposal_source: overrides.proposal_source || "single_request",
    content: overrides.content || "AI proposal content.",
    rationale: overrides.rationale || "Make the choice cost visible.",
    status: overrides.status || "candidate",
    author_decision_note: overrides.author_decision_note || "",
    created_at: "2026-04-26T00:00:00Z",
    updated_at: "2026-04-26T00:00:00Z",
  };
}

function deskSnapshotPayload() {
  return {
    target: {
      object_type: "scene",
      object_id: "DESKFE100_SC01",
      chapter_id: "DESKFE100",
      scene_id: "DESKFE100_SC01",
    },
    author_draft: authorDraftPayload().draft,
    work_profile: {
      profile_key: "quiet_literary",
      display_name: "文学慢热",
      profile_json: { ending_drive_policy: "soft" },
    },
    runtime_text: {
      source_ref: "final_scene:final_scene_DESKFE100_SC01_v1",
      content: "运行终稿。",
      text_layer: "runtime_final_scene",
    },
    aggregate_text: {
      source_ref: "chapter_memory:chapter_memory_final_DESKFE100_v1",
      content: "最终聚合稿。",
      text_layer: "chapter_memory_final",
    },
    deep_review_summary: {
      overall_score: 0.62,
      top_findings: [{ dimension: "choice_pressure", issue: "代价不够具体。" }],
      judgment_layers: {
        blocking: [],
        revision: [{ dimension: "choice_pressure", issue: "代价不够具体。" }],
        profile_mismatch: [],
        taste: [{ dimension: "image_necessity", issue: "意象略满。" }],
      },
      non_blocking_count: 2,
    },
    open_candidates: [
      {
        candidate_type: "passage_patch",
        patch_id: "patch_DESKFE100",
        candidate_category: "dialogue_rewrite",
        revision_strategy: "反问替代解释",
        preference_tags: ["少解释", "对白更短"],
        inserted_into_author_draft: true,
        replacement_options: [{ option_id: "subtle", label: "更含蓄", replacement_text: "她没有回答。" }],
      },
    ],
    longform_pressure: [
      {
        card_id: "lf_DESKFE100_arc",
        card_type: "character_arc_gap",
        severity: "critical",
        recommendation: { summary: "让人物付出可见代价。" },
      },
    ],
    daily_focus: [
      {
        source: "deep_review",
        severity: "revision",
        target_view: "deepdesk",
        dimension: "choice_pressure",
        title: "代价不够具体。",
      },
    ],
    author_preference_summary: { preferred_moves: ["更含蓄"] },
  };
}

function qualityStatePayload(overrides = {}) {
  return {
    scene_id: "DESKFE100_SC01",
    contract: {
      contract_id: "scene_quality_contract_DESKFE100_SC01_a1",
      contract_version: "scene_quality_contract_v1",
      contract_hash: "hash_quality_contract",
      payload: {
        visible_desire: "确认录音是否真实。",
        forced_choice: "公开证据或先保护幸存者。",
        price_paid: "暂时背负隐瞒真相的嫌疑。",
        ending_action: "把证据分成两份。",
      },
    },
    latest_run: overrides.latest_run || {
      run_id: "auto_rewrite_DESKFE100_SC01_a1",
      status: "candidate_ready",
      branch: "full_scene",
      failure_class: "choice_pressure",
      candidate_draft_row_id: "draft_auto_rewrite_DESKFE100_SC01_a1",
      gate_results: { promotable: true },
      promotion_blockers: [],
    },
    promotion: overrides.promotion || { eligible: true, blockers: [] },
  };
}

describe("writer deep revision desk", () => {
  beforeEach(() => {
    setActivePinia(createPinia());
    vi.resetModules();
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("registers a dedicated deep revision desk route and lazy view", () => {
    const routerSource = readSource("src/router.js");
    const appSource = readSource("src/App.vue");

    expect(routerSource).toContain('id: "deepdesk"');
    expect(routerSource).toContain("写作与深改台");
    expect(routerSource).toContain("写作深改");
    expect(routerSource).toContain("反向提取戏剧卡");
    expect(routerSource).toContain('nextViews: ["author", "manuscripts", "longform", "workbench"]');
    expect(appSource).toContain("deepdesk: defineAsyncComponent");
    expect(appSource).toContain("./views/WriterDeepDeskView.vue");
  });

  it("exposes blank draft, structure extraction, deep review, passage patch, and author preference API helpers", () => {
    const apiSource = readSource("src/lib/api.js");

    expect(apiSource).toContain("fetchAuthorDeskSnapshot");
    expect(apiSource).toContain("/api/v1/author-desk");
    expect(apiSource).toContain("fetchAuthorDraftEvents");
    expect(apiSource).toContain("/events");
    expect(apiSource).toContain("fetchCurrentAuthorDraft");
    expect(apiSource).toContain("ensureAuthorDraft");
    expect(apiSource).toContain("ensureBlankAuthorDraft");
    expect(apiSource).toContain("deriveAuthorDraftFromGeneration");
    expect(apiSource).toContain("fetchAuthorDraftProposals");
    expect(apiSource).toContain("generateAuthorDraftProposal");
    expect(apiSource).toContain("generateAuthorDraftProposalSet");
    expect(apiSource).toContain("applyAuthorDraftProposal");
    expect(apiSource).toContain("rejectAuthorDraftProposal");
    expect(apiSource).toContain("analyzeLiteraryQualityText");
    expect(apiSource).toContain("saveAuthorDraft");
    expect(apiSource).toContain("recordAuthorDraftCandidateEvent");
    expect(apiSource).toContain("applyAuthorDraftPatchOption");
    expect(apiSource).toContain("extractAuthorDraftStructure");
    expect(apiSource).toContain("applyAuthorStructureCandidate");
    expect(apiSource).toContain("rejectAuthorStructureCandidate");
    expect(apiSource).toContain("fetchSceneDeepReview");
    expect(apiSource).toContain("runSceneDeepReview");
    expect(apiSource).toContain("fetchChapterDeepReview");
    expect(apiSource).toContain("runChapterDeepReview");
    expect(apiSource).toContain("createPassagePatchCandidate");
    expect(apiSource).toContain("acceptPassagePatchCandidate");
    expect(apiSource).toContain("rejectPassagePatchCandidate");
    expect(apiSource).toContain("fetchAuthorPreferenceProfile");
    expect(apiSource).toContain("fetchSceneQualityState");
    expect(apiSource).toContain("generateSceneQualityContract");
    expect(apiSource).toContain("runSceneAutoRewrite");
    expect(apiSource).toContain("promoteAutoRewriteRun");
    expect(apiSource).toContain("rollbackAutoRewriteRun");
    expect(apiSource).toContain("/deep-review");
    expect(apiSource).toContain("/quality-state");
    expect(apiSource).toContain("/quality-contract");
    expect(apiSource).toContain("/auto-rewrite");
    expect(apiSource).toContain("/auto-rewrite-runs");
    expect(apiSource).toContain("/passages/patch-candidates");
    expect(apiSource).toContain("/author-drafts");
    expect(apiSource).toContain("/ensure-blank");
    expect(apiSource).toContain("/derive-from-generation");
    expect(apiSource).toContain("/proposals/generate");
    expect(apiSource).toContain("/proposals/generate-set");
    expect(apiSource).toContain("/author-draft-proposals");
    expect(apiSource).toContain("/apply-patch-option");
    expect(apiSource).toContain("/structure-extract");
    expect(apiSource).toContain("/author-structure-candidates");
    expect(apiSource).toContain("/author-preference-profile");
  });

  it("calls author desk snapshot, draft events, and draft proposal API helpers", async () => {
    globalThis.fetch = vi.fn(async () => okEnvelope({}));

    await api.fetchAuthorDeskSnapshot("scene", "DESKFE100_SC01");
    await api.fetchAuthorDraftEvents("author_draft_scene_DESKFE100_SC01");
    await api.fetchAuthorDraftProposals("author_draft_scene_DESKFE100_SC01");
    await api.generateAuthorDraftProposal("author_draft_scene_DESKFE100_SC01", { proposal_type: "scene_draft" });
    await api.generateAuthorDraftProposalSet("author_draft_scene_DESKFE100_SC01", { instruction: "three lanes" });
    await api.applyAuthorDraftProposal("proposal_DESKFE100_SC01", { apply_mode: "replace" });
    await api.rejectAuthorDraftProposal("proposal_DESKFE100_SC01", { note: "too direct" });

    const urls = globalThis.fetch.mock.calls.map(([url]) => url);
    expect(urls).toContain("http://127.0.0.1:8000/api/v1/author-desk/scene/DESKFE100_SC01/snapshot");
    expect(urls).toContain("http://127.0.0.1:8000/api/v1/author-drafts/author_draft_scene_DESKFE100_SC01/events");
    expect(urls).toContain("http://127.0.0.1:8000/api/v1/author-drafts/author_draft_scene_DESKFE100_SC01/proposals");
    expect(urls).toContain("http://127.0.0.1:8000/api/v1/author-drafts/author_draft_scene_DESKFE100_SC01/proposals/generate");
    expect(urls).toContain("http://127.0.0.1:8000/api/v1/author-drafts/author_draft_scene_DESKFE100_SC01/proposals/generate-set");
    expect(urls).toContain("http://127.0.0.1:8000/api/v1/author-draft-proposals/proposal_DESKFE100_SC01/apply");
    expect(urls).toContain("http://127.0.0.1:8000/api/v1/author-draft-proposals/proposal_DESKFE100_SC01/reject");
  });

  it("calls scene quality contract, auto rewrite, promote, and rollback API helpers", async () => {
    globalThis.fetch = vi.fn(async () => okEnvelope({}));

    await api.fetchSceneQualityState("DESKFE100_SC01");
    await api.generateSceneQualityContract("DESKFE100_SC01");
    await api.runSceneAutoRewrite("DESKFE100_SC01", { mode: "auto" });
    await api.promoteAutoRewriteRun("auto_rewrite_DESKFE100_SC01_a1");
    await api.rollbackAutoRewriteRun("auto_rewrite_DESKFE100_SC01_a1");

    const urls = globalThis.fetch.mock.calls.map(([url]) => url);
    expect(urls).toContain("http://127.0.0.1:8000/api/v1/scenes/DESKFE100_SC01/quality-state");
    expect(urls).toContain("http://127.0.0.1:8000/api/v1/scenes/DESKFE100_SC01/quality-contract");
    expect(urls).toContain("http://127.0.0.1:8000/api/v1/scenes/DESKFE100_SC01/auto-rewrite");
    expect(urls).toContain("http://127.0.0.1:8000/api/v1/auto-rewrite-runs/auto_rewrite_DESKFE100_SC01_a1/promote");
    expect(urls).toContain("http://127.0.0.1:8000/api/v1/auto-rewrite-runs/auto_rewrite_DESKFE100_SC01_a1/rollback");
  });

  it("hydrates quality state and runs auto rewrite promotion controls in the store", async () => {
    globalThis.fetch = vi.fn(async (url) => {
      const path = String(url);
      if (path.includes("/chapter-manuscripts/DESKFE100")) {
        return okEnvelope(chapterDetailPayload());
      }
      if (path.includes("/chapter-manuscripts")) {
        return okEnvelope(chapterListPayload());
      }
      if (path.includes("/ensure-blank")) {
        return okEnvelope(authorDraftPayload());
      }
      if (path.includes("/deep-review")) {
        return okEnvelope({ latest_evaluation: null, lens_evaluations: [], patch_candidates: [] });
      }
      if (path.includes("/author-preference-profile")) {
        return okEnvelope({ profile: { summary: {} } });
      }
      if (path.includes("/author-desk/scene/DESKFE100_SC01/snapshot")) {
        return okEnvelope(deskSnapshotPayload());
      }
      if (path.includes("/events")) {
        return okEnvelope({ events: [] });
      }
      if (path.endsWith("/quality-contract")) {
        return okEnvelope({ contract: qualityStatePayload().contract });
      }
      if (path.endsWith("/auto-rewrite")) {
        return okEnvelope({ run: qualityStatePayload().latest_run, quality_state: qualityStatePayload() });
      }
      if (path.endsWith("/promote")) {
        return okEnvelope({
          run: { ...qualityStatePayload().latest_run, status: "promoted", promoted_final_scene_row_id: "final_scene_DESKFE100_SC01_auto_1" },
        });
      }
      if (path.endsWith("/rollback")) {
        return okEnvelope({
          run: { ...qualityStatePayload().latest_run, status: "rolled_back", promoted_final_scene_row_id: "final_scene_DESKFE100_SC01_auto_1" },
        });
      }
      if (path.includes("/quality-state")) {
        return okEnvelope(qualityStatePayload());
      }
      return okEnvelope({});
    });

    const { useWriterDeepDeskStore } = await import("../src/stores/writerDeepDesk.js");
    const store = useWriterDeepDeskStore();

    await store.initialize({ force: true });
    await store.setDraftMode("scene");

    expect(store.qualityState.contract.contract_version).toBe("scene_quality_contract_v1");
    expect(store.qualityPromotionEligible).toBe(true);

    const rewriteMessage = await store.runSceneAutoRewrite({ mode: "auto" });
    expect(rewriteMessage).toContain("auto_rewrite_DESKFE100_SC01_a1");
    expect(store.autoRewriteRun.branch).toBe("full_scene");

    const promoteMessage = await store.promoteAutoRewriteRun("auto_rewrite_DESKFE100_SC01_a1");
    expect(promoteMessage).toContain("promoted");
    expect(store.autoRewriteRun.status).toBe("promoted");

    const rollbackMessage = await store.rollbackAutoRewriteRun("auto_rewrite_DESKFE100_SC01_a1");
    expect(rollbackMessage).toContain("rolled_back");
    expect(store.autoRewriteRun.status).toBe("rolled_back");
  });

  it("hydrates the writer desk snapshot, timeline, and longform pressure in the store", async () => {
    globalThis.fetch = vi.fn(async (url) => {
      const path = String(url);
      if (path.includes("/chapter-manuscripts/DESKFE100")) {
        return okEnvelope(chapterDetailPayload());
      }
      if (path.includes("/chapter-manuscripts")) {
        return okEnvelope(chapterListPayload());
      }
      if (path.includes("/ensure-blank")) {
        return okEnvelope(authorDraftPayload());
      }
      if (path.includes("/deep-review")) {
        return okEnvelope({ latest_evaluation: null, lens_evaluations: [], patch_candidates: [] });
      }
      if (path.includes("/author-preference-profile")) {
        return okEnvelope({ profile: { summary: { preferred_moves: ["更含蓄"] } } });
      }
      if (path.includes("/author-desk/scene/DESKFE100_SC01/snapshot")) {
        return okEnvelope(deskSnapshotPayload());
      }
      if (path.includes("/author-drafts/author_draft_scene_DESKFE100_SC01/events")) {
        return okEnvelope({
          draft_id: "author_draft_scene_DESKFE100_SC01",
          events: [{ event_type: "created" }, { event_type: "edited" }],
        });
      }
      return okEnvelope({});
    });

    const { useWriterDeepDeskStore } = await import("../src/stores/writerDeepDesk.js");
    const store = useWriterDeepDeskStore();

    await store.initialize({ force: true });
    await store.setDraftMode("scene");

    expect(store.authorDeskSnapshot.target.object_id).toBe("DESKFE100_SC01");
    expect(store.longformPressure[0].card_type).toBe("character_arc_gap");
    expect(store.workProfile.display_name).toBe("文学慢热");
    expect(store.dailyFocus[0].dimension).toBe("choice_pressure");
    expect(store.judgmentLayers.taste[0].dimension).toBe("image_necessity");
    expect(store.snapshotOpenCandidates[0].candidate_category).toBe("dialogue_rewrite");
    expect(store.snapshotOpenCandidates[0].preference_tags).toEqual(["少解释", "对白更短"]);
    expect(store.draftProposalRows[0].proposal_id).toBe("proposal_DESKFE100_SC01");
    expect(store.draftEvents.map((event) => event.event_type)).toEqual(["created", "edited"]);
    expect(store.deskStage).toBe("write");
    store.setDeskStage("longform");
    expect(store.deskStage).toBe("longform");
  });

  it("keeps AI draft proposals separate until the author applies or rejects them", async () => {
    globalThis.fetch = vi.fn(async (url, options = {}) => {
      const path = String(url);
      if (path.includes("/chapter-manuscripts/DESKFE100")) {
        return okEnvelope(chapterDetailPayload());
      }
      if (path.includes("/chapter-manuscripts")) {
        return okEnvelope(chapterListPayload());
      }
      if (path.includes("/ensure-blank")) {
        return okEnvelope(authorDraftPayload());
      }
      if (path.includes("/proposals/generate")) {
        return okEnvelope({ proposal: draftProposalPayload({ proposal_id: "proposal_generated", content: "Generated proposal." }) });
      }
      if (path.includes("/author-draft-proposals/proposal_generated/apply")) {
        const body = JSON.parse(options.body || "{}");
        return okEnvelope({
          proposal: draftProposalPayload({ proposal_id: "proposal_generated", status: "accepted", content: "Generated proposal." }),
          draft: {
            ...authorDraftPayload().draft,
            content: body.apply_mode === "append" ? `${authorDraftPayload().draft.content}\n\nGenerated proposal.` : "Generated proposal.",
            revision_no: 3,
          },
          open_draft_proposals: [],
          author_preference_summary: {},
        });
      }
      if (path.includes("/author-draft-proposals/proposal_reject/reject")) {
        return okEnvelope({
          proposal: draftProposalPayload({ proposal_id: "proposal_reject", status: "rejected", author_decision_note: "too direct" }),
          draft: { ...authorDraftPayload().draft },
          open_draft_proposals: [],
          author_preference_summary: {},
        });
      }
      if (path.includes("/deep-review")) {
        return okEnvelope({ latest_evaluation: null, lens_evaluations: [], patch_candidates: [] });
      }
      if (path.includes("/author-preference-profile")) {
        return okEnvelope({ profile: { summary: {} } });
      }
      if (path.includes("/author-desk/scene/DESKFE100_SC01/snapshot")) {
        return okEnvelope(deskSnapshotPayload());
      }
      if (path.includes("/events")) {
        return okEnvelope({ events: [] });
      }
      return okEnvelope({});
    });

    const { useWriterDeepDeskStore } = await import("../src/stores/writerDeepDesk.js");
    const store = useWriterDeepDeskStore();

    await store.initialize({ force: true });
    await store.setDraftMode("scene");

    const proposalMessage = await store.generateDraftProposal({ proposal_type: "scene_draft" });
    expect(proposalMessage).toContain("proposal_generated");
    expect(store.draftProposalRows[0].proposal_id).toBe("proposal_generated");
    expect(store.draftContent).toBe(authorDraftPayload().draft.content);

    await store.applyDraftProposal("proposal_generated", { apply_mode: "append" });
    expect(store.draftContent).toContain("Generated proposal.");
    expect(store.authorDraft.revision_no).toBe(3);

    store.draftProposals = [draftProposalPayload({ proposal_id: "proposal_reject" })];
    await store.rejectDraftProposal("proposal_reject", { note: "too direct" });
    expect(store.draftProposalRows[0].status).toBe("rejected");
    expect(store.draftProposalRows[0].author_decision_note).toBe("too direct");
  });

  it("generates the three author proposal lanes as separate candidates", async () => {
    globalThis.fetch = vi.fn(async (url) => {
      const path = String(url);
      if (path.includes("/chapter-manuscripts/DESKFE100")) {
        return okEnvelope(chapterDetailPayload());
      }
      if (path.includes("/chapter-manuscripts")) {
        return okEnvelope(chapterListPayload());
      }
      if (path.includes("/ensure-blank")) {
        return okEnvelope(authorDraftPayload());
      }
      if (path.includes("/proposals/generate-set")) {
        return okEnvelope({
          proposals: [
            draftProposalPayload({ proposal_id: "proposal_structure", proposal_type: "structure_candidate", proposal_source: "author_cockpit_triad" }),
            draftProposalPayload({ proposal_id: "proposal_passage", proposal_type: "passage_candidate", proposal_source: "author_cockpit_triad" }),
            draftProposalPayload({ proposal_id: "proposal_language", proposal_type: "language_candidate", proposal_source: "author_cockpit_triad" }),
          ],
        });
      }
      if (path.includes("/deep-review")) {
        return okEnvelope({ latest_evaluation: null, lens_evaluations: [], patch_candidates: [] });
      }
      if (path.includes("/author-preference-profile")) {
        return okEnvelope({ profile: { summary: {} } });
      }
      if (path.includes("/author-desk/scene/DESKFE100_SC01/snapshot")) {
        return okEnvelope(deskSnapshotPayload());
      }
      if (path.includes("/events")) {
        return okEnvelope({ events: [] });
      }
      return okEnvelope({});
    });

    const { useWriterDeepDeskStore } = await import("../src/stores/writerDeepDesk.js");
    const store = useWriterDeepDeskStore();

    await store.initialize({ force: true });
    await store.setDraftMode("scene");
    const message = await store.generateDraftProposalSet({ instruction: "three lanes" });

    expect(message).toContain("3");
    expect(store.draftProposalRows.map((row) => row.proposal_type)).toEqual([
      "language_candidate",
      "passage_candidate",
      "structure_candidate",
      "scene_draft",
    ]);
    expect(store.draftProposalRows[0].proposal_source).toBe("author_cockpit_triad");
  });

  it("adds a focused store without deep watchers for long chapter text", () => {
    const storePath = path.join(SOURCE_ROOT, "src/stores/writerDeepDesk.js");
    expect(existsSync(storePath)).toBe(true);
    const source = readSource("src/stores/writerDeepDesk.js");

    expect(source).toContain('defineStore("writerDeepDesk"');
    expect(source).toContain('draftMode: "chapter"');
    expect(source).toContain("authorDraft");
    expect(source).toContain("authorDeskSnapshot");
    expect(source).toContain("draftEvents");
    expect(source).toContain("draftProposals");
    expect(source).toContain("draftProposalRows");
    expect(source).toContain("dailyFocus");
    expect(source).toContain("workProfile");
    expect(source).toContain("judgmentLayers");
    expect(source).toContain("inlineQualitySpanFindings");
    expect(source).toContain("span_findings");
    expect(source).toContain("longformPressure");
    expect(source).toContain('deskStage: "write"');
    expect(source).toContain("loadAuthorDeskSnapshot");
    expect(source).toContain("loadDraftEvents");
    expect(source).toContain("draftContent");
    expect(source).toContain("draftDirty");
    expect(source).toContain("ensureAuthorDraft");
    expect(source).toContain("ensureBlankAuthorDraft as ensureBlankAuthorDraftApi");
    expect(source).toContain("deriveAuthorDraftFromGeneration");
    expect(source).toContain("fetchAuthorDraftProposals");
    expect(source).toContain("generateAuthorDraftProposal");
    expect(source).toContain("applyAuthorDraftProposal");
    expect(source).toContain("rejectAuthorDraftProposal");
    expect(source).toContain("applyAuthorDraftPatchOption");
    expect(source).toContain("runFullScene");
    expect(source).toContain('deskMode: "write_first"');
    expect(source).toContain("setDeskMode");
    expect(source).toContain("runAiDraftToAuthorDraft");
    expect(source).toContain("generateDraftProposal");
    expect(source).toContain("generateDraftProposalSet");
    expect(source).toContain("applyDraftProposal");
    expect(source).toContain("rejectDraftProposal");
    expect(source).toContain("analyzeCurrentDraftQuality");
    expect(source).toContain("saveAuthorDraft");
    expect(source).toContain("recordAuthorDraftCandidateEvent");
    expect(source).toContain("structureCandidates");
    expect(source).toContain("structureCandidateRows");
    expect(source).toContain("extractAuthorStructure");
    expect(source).toContain("applyStructureCandidate");
    expect(source).toContain("rejectStructureCandidate");
    expect(source).toContain("insertCandidateOption");
    expect(source).toContain("runChapterDeepReview");
    expect(source).toContain("createPassagePatchCandidate");
    expect(source).toContain("acceptPassagePatchCandidate");
    expect(source).toContain("rejectPassagePatchCandidate");
    expect(source).toContain("qualityState");
    expect(source).toContain("autoRewriteRun");
    expect(source).toContain("loadSceneQualityState");
    expect(source).toContain("runSceneAutoRewrite");
    expect(source).toContain("promoteAutoRewriteRun");
    expect(source).toContain("rollbackAutoRewriteRun");
    expect(source).not.toContain("deep: true");
  });

  it("renders a quiet reader, diagnosis rail, patch candidates, and preference draft", () => {
    const viewPath = path.join(SOURCE_ROOT, "src/views/WriterDeepDeskView.vue");
    expect(existsSync(viewPath)).toBe(true);
    const source = readSource("src/views/WriterDeepDeskView.vue");

    expect(source).toContain('data-testid="writer-deep-desk"');
    expect(source).toContain('data-testid="deep-desk-reader"');
    expect(source).toContain('data-testid="draft-mode-chapter"');
    expect(source).toContain('data-testid="draft-mode-scene"');
    expect(source).toContain('data-testid="desk-mode-write-first"');
    expect(source).toContain('data-testid="desk-mode-ai-draft"');
    expect(source).toContain('data-testid="desk-stage-write"');
    expect(source).toContain('data-testid="desk-stage-ai"');
    expect(source).toContain('data-testid="desk-stage-review"');
    expect(source).toContain('data-testid="desk-stage-longform"');
    expect(source).toContain('data-testid="desk-longform-pressure"');
    expect(source).toContain('data-testid="author-draft-events"');
    expect(source).toContain('data-testid="draft-proposals"');
    expect(source).toContain('data-testid="draft-proposal-generate"');
    expect(source).toContain('data-testid="draft-proposal-generate-set"');
    expect(source).toContain('data-testid="author-daily-focus"');
    expect(source).toContain('data-testid="author-work-profile"');
    expect(source).toContain('data-testid="judgment-layers"');
    expect(source).toContain('data-testid="draft-proposal-apply-replace"');
    expect(source).toContain('data-testid="draft-proposal-apply-append"');
    expect(source).toContain('data-testid="draft-proposal-apply-new-version"');
    expect(source).toContain('data-testid="draft-proposal-reject"');
    expect(source).toContain("candidateCategoryLabel");
    expect(source).toContain("candidateMetaLine");
    expect(source).toContain("已放入稿件");
    expect(source).toContain("偏好标签");
    expect(source).toContain('data-testid="author-draft-editor"');
    expect(source).toContain('data-testid="author-draft-ensure-blank"');
    expect(source).toContain('data-testid="author-draft-save"');
    expect(source).toContain('data-testid="structure-extract-run"');
    expect(source).toContain('data-testid="author-structure-candidates"');
    expect(source).toContain('data-testid="author-structure-apply"');
    expect(source).toContain('data-testid="author-structure-reject"');
    expect(source).toContain('data-testid="deep-review-run"');
    expect(source).toContain('data-testid="patch-candidate-create"');
    expect(source).toContain('data-testid="deep-review-findings"');
    expect(source).toContain('data-testid="inline-quality-span-findings"');
    expect(source).toContain('data-testid="scene-quality-contract"');
    expect(source).toContain('data-testid="scene-auto-rewrite-run"');
    expect(source).toContain('data-testid="scene-auto-rewrite-promote"');
    expect(source).toContain('data-testid="scene-auto-rewrite-rollback"');
    expect(source).toContain('data-testid="passage-patch-candidates"');
    expect(source).toContain('data-testid="author-preference-profile"');
    expect(source).toContain("写作与深改台");
    expect(source).toContain("我先写");
    expect(source).toContain("AI 起草");
    expect(source).toContain("深改诊断");
    expect(source).toContain("长篇压力");
    expect(source).toContain("AI 草稿提案");
    expect(source).toContain("三类候选");
    expect(source).toContain("今日焦点");
    expect(source).toContain("作品档案");
    expect(source).toContain("追加到当前稿");
    expect(source).toContain("作为新版本");
    expect(source).toContain("创建空白作者稿");
    expect(source).toContain("反向提取戏剧卡");
    expect(source).toContain("结构候选");
    expect(source).toContain("场景质量契约");
    expect(source).toContain("自动重写");
    expect(source).toContain("晋级为运行终稿");
    expect(source).toContain("回滚");
    expect(source).toContain("作者稿");
    expect(source).toContain("运行终稿");
    expect(source).toContain("最终聚合稿");
    expect(source).toContain("放入稿件");
    expect(source).toContain("candidate.status !== 'candidate'");
  });

  it("uses the writer desk as the default first screen", () => {
    const routerSource = readSource("src/router.js");

    expect(routerSource).toContain('const activeView = ref("deepdesk")');
    expect(routerSource).toContain('const visitedViews = ref(["deepdesk"])');
  });
});
