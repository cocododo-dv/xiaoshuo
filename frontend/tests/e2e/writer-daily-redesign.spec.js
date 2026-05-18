import { expect, test } from "@playwright/test";

import { configureConnection, switchToAdvancedMode } from "./helpers.js";

const CHAPTER_ID = "CHWD_E2E";
const SCENE_ID = `${CHAPTER_ID}_SC01`;
const DRAFT_ID = `author_draft_scene_${SCENE_ID}`;
const CHAPTER_DRAFT_ID = `author_draft_chapter_${CHAPTER_ID}`;

function chapterListPayload() {
  return {
    items: [
      {
        chapter_id: CHAPTER_ID,
        planned_scene_count: 1,
        chapter_goal: "Daily writer cockpit E2E chapter goal",
        current_phase: "drafting",
        active_scene_count: 1,
        generated_scene_count: 1,
        missing_scene_ids: [],
        completion_status: "complete",
        comparison_status: "aggregate_matches_current",
      },
    ],
  };
}

function chapterDetailPayload() {
  return {
    chapter: {
      chapter_id: CHAPTER_ID,
      planned_scene_count: 1,
      chapter_goal: "Daily writer cockpit E2E chapter goal",
      main_plot_push: "Force a costly choice",
      emotional_target: "Trust fractures but does not collapse",
      ending_effect: "The next chapter has a hook",
      must_not: "",
      notes: "",
    },
    assembled: {
      content: "RUNTIME FINAL TEXT - do not overwrite",
      char_count: 36,
      scene_count: 1,
      generated_scene_count: 1,
      missing_scene_ids: [],
    },
    aggregate: {
      row_id: "chapter_memory_final_CHWD_E2E_v1",
      content: "CHAPTER MEMORY FINAL TEXT - do not overwrite",
      char_count: 44,
      created_at: "2026-04-26T00:00:00Z",
    },
    scenes: [
      {
        scene_id: SCENE_ID,
        chapter_id: CHAPTER_ID,
        scene_seq: 1,
        scene_goal: "Open with a visible pressure choice",
        beats_json: ["enter pressure", "pay a cost"],
        final_scene: {
          row_id: "final_scene_CHWD_E2E_SC01_v1",
          char_count: 36,
          created_at: "2026-04-26T00:00:00Z",
        },
        content: "RUNTIME FINAL TEXT - do not overwrite",
      },
    ],
  };
}

function draftPayload({ content = "AUTHOR DRAFT v1", revisionNo = 1, objectType = "scene", objectId = SCENE_ID } = {}) {
  const draftId = objectType === "scene" ? DRAFT_ID : CHAPTER_DRAFT_ID;
  return {
    draft_id: draftId,
    object_type: objectType,
    object_id: objectId,
    content,
    revision_no: revisionNo,
    source_text_ref: objectType === "scene" ? "final_scene:final_scene_CHWD_E2E_SC01_v1" : "chapter_memory:chapter_memory_final_CHWD_E2E_v1",
    status: "current",
  };
}

function draftEnvelope(draft, overrides = {}) {
  return {
    draft,
    draft_mode: draft.object_type,
    desk_mode: "write_first",
    source_layer: "author_draft",
    runtime_final_ref: "final_scene:final_scene_CHWD_E2E_SC01_v1",
    aggregate_ref: "chapter_memory:chapter_memory_final_CHWD_E2E_v1",
    open_structure_candidates: [],
    open_patch_candidates: [],
    open_draft_proposals: [],
    author_preference_summary: {},
    ...overrides,
  };
}

function proposalPayload(status = "candidate") {
  return {
    proposal_id: "proposal_writer_daily_e2e",
    draft_id: DRAFT_ID,
    object_type: "scene",
    object_id: SCENE_ID,
    proposal_type: "scene_draft",
    content: "AI PROPOSAL TEXT with stronger pressure",
    rationale: "Comparable proposal for the current author draft",
    source_llm_call_id: null,
    status,
    author_decision_note: "",
  };
}

function deepReviewPayload(patchCandidates = []) {
  return {
    latest_evaluation: {
      evaluation_id: "eval_writer_daily_e2e",
      object_type: "scene",
      object_id: SCENE_ID,
      latest_score: 72,
      findings: [
        {
          dimension: "dialogue_subtext",
          severity: "revision",
          issue: "Dialogue explains pressure too directly",
          recommendation: "Move pressure into a visible action.",
          evidence_excerpt: "AI PROPOSAL TEXT",
        },
      ],
    },
    lens_evaluations: [],
    patch_candidates: patchCandidates,
  };
}

function patchCandidatePayload(status = "candidate", inserted = false) {
  return {
    patch_id: "patch_writer_daily_e2e",
    object_type: "scene",
    object_id: SCENE_ID,
    issue_dimension: "dialogue_subtext",
    source_excerpt: "AI PROPOSAL TEXT",
    candidate_category: "local_rewrite",
    rationale: "Make the pressure visible.",
    status,
    author_decision: status === "accepted" ? "accepted" : "pending",
    inserted_into_author_draft: inserted ? 1 : 0,
    replacement_options: [
      {
        option_id: "option_writer_daily_e2e",
        label: "visible pressure",
        tone: "tense",
        replacement_text: "LOCAL CANDIDATE TEXT with a concrete cost",
        why_it_helps: "Turns explanation into action.",
      },
    ],
  };
}

async function fulfill(route, data) {
  await route.fulfill({ json: { ok: true, data } });
}

test("runs the daily writer cockpit proposal, revision, local candidate, and inline quality loop", async ({ page }) => {
  let sceneDraft = draftPayload();
  let chapterDraft = draftPayload({
    objectType: "chapter",
    objectId: CHAPTER_ID,
    content: "CHAPTER AUTHOR DRAFT v1",
  });
  let proposal = null;
  let patchCandidate = null;

  await page.route("**/api/v1/chapter-manuscripts", async (route) => {
    await fulfill(route, chapterListPayload());
  });
  await page.route(`**/api/v1/chapter-manuscripts/${CHAPTER_ID}`, async (route) => {
    await fulfill(route, chapterDetailPayload());
  });
  await page.route(`**/api/v1/author-drafts/chapter/${CHAPTER_ID}/ensure-blank`, async (route) => {
    await fulfill(route, draftEnvelope(chapterDraft));
  });
  await page.route(`**/api/v1/author-drafts/scene/${SCENE_ID}/ensure-blank`, async (route) => {
    await fulfill(route, draftEnvelope(sceneDraft, { open_draft_proposals: proposal ? [proposal] : [] }));
  });
  await page.route(`**/api/v1/author-drafts/${DRAFT_ID}/events`, async (route) => {
    await fulfill(route, {
      events: [
        proposal?.status === "accepted"
          ? { event_id: "event_proposal_applied", event_type: "proposal_applied", note: "append proposal" }
          : null,
        patchCandidate?.inserted_into_author_draft
          ? { event_id: "event_candidate_saved", event_type: "candidate_saved", note: "saved into author draft" }
          : null,
      ].filter(Boolean),
    });
  });
  await page.route(`**/api/v1/author-drafts/${CHAPTER_DRAFT_ID}/events`, async (route) => {
    await fulfill(route, { events: [] });
  });
  await page.route(`**/api/v1/author-desk/**/snapshot`, async (route) => {
    await fulfill(route, {
      open_candidates: patchCandidate ? [patchCandidate] : [],
      longform_pressure: [
        {
          card_id: "longform_card_writer_daily_e2e",
          card_type: "character_arc_gap",
          severity: "major",
          chapter_id: CHAPTER_ID,
          scene_id: SCENE_ID,
          title: "Character arc gap blocks the next scene",
          recommended_action: "Return to the writer cockpit and adjust the scene.",
        },
      ],
      deep_review_summary: { score: 72 },
    });
  });
  await page.route("**/api/v1/author-preference-profile", async (route) => {
    await fulfill(route, {
      profile: {
        profile_id: "author_pref_global_global_proposals",
        status: "draft",
        runtime_eligible: 0,
        summary_json: { proposal_decisions: proposal ? [{ proposal_id: proposal.proposal_id, decision: proposal.status }] : [] },
      },
    });
  });
  await page.route(`**/api/v1/scenes/${SCENE_ID}/deep-review`, async (route) => {
    await fulfill(route, deepReviewPayload(patchCandidate ? [patchCandidate] : []));
  });
  await page.route(`**/api/v1/scenes/${SCENE_ID}/quality-state`, async (route) => {
    await fulfill(route, {
      scene_id: SCENE_ID,
      contract: null,
      promotion: { eligible: false, blockers: [] },
      latest_run: null,
    });
  });
  await page.route(`**/api/v1/chapters/${CHAPTER_ID}/deep-review`, async (route) => {
    await fulfill(route, deepReviewPayload([]));
  });
  await page.route(`**/api/v1/author-drafts/${DRAFT_ID}/proposals/generate`, async (route) => {
    proposal = proposalPayload("candidate");
    await fulfill(route, { proposal });
  });
  await page.route(`**/api/v1/author-draft-proposals/proposal_writer_daily_e2e/apply`, async (route) => {
    const payload = route.request().postDataJSON();
    proposal = { ...proposalPayload("accepted"), author_decision_note: payload.note || "" };
    sceneDraft = draftPayload({
      content: `${sceneDraft.content}\n\n${proposal.content}`,
      revisionNo: 2,
    });
    await fulfill(route, draftEnvelope(sceneDraft, { proposal }));
  });
  await page.route(`**/api/v1/author-drafts/${DRAFT_ID}`, async (route) => {
    const payload = route.request().postDataJSON();
    sceneDraft = draftPayload({
      content: payload.content,
      revisionNo: sceneDraft.revision_no + 1,
    });
    await fulfill(route, draftEnvelope(sceneDraft));
  });
  await page.route("**/api/v1/passages/patch-candidates", async (route) => {
    patchCandidate = patchCandidatePayload();
    await fulfill(route, { candidate: patchCandidate });
  });
  await page.route(`**/api/v1/author-drafts/${DRAFT_ID}/apply-patch-option`, async (route) => {
    patchCandidate = patchCandidatePayload("candidate", true);
    sceneDraft = draftPayload({
      content: sceneDraft.content.replace("AI PROPOSAL TEXT", "LOCAL CANDIDATE TEXT with a concrete cost"),
      revisionNo: sceneDraft.revision_no + 1,
    });
    await fulfill(route, draftEnvelope(sceneDraft));
  });
  await page.route(`**/api/v1/author-drafts/${DRAFT_ID}/candidate-events`, async (route) => {
    await fulfill(route, { event: { event_id: "event_candidate_saved", event_type: "candidate_saved" } });
  });
  await page.route("**/api/v1/passage-patch-candidates/patch_writer_daily_e2e/accept", async (route) => {
    patchCandidate = patchCandidatePayload("accepted", true);
    await fulfill(route, { candidate: patchCandidate });
  });
  await page.route("**/api/v1/literary-quality/analyze-text", async (route) => {
    await fulfill(route, {
      object_type: "scene",
      object_id: SCENE_ID,
      content: sceneDraft.content,
      findings: [],
      span_findings: [
        {
          dimension: "template_action_reuse",
          severity: "revision",
          start: 0,
          end: 20,
          evidence: sceneDraft.content.slice(0, 20),
          recommended_action: "Vary the action template before finaling the scene.",
        },
      ],
      risk_clusters: [],
      recommended_next_action: { action: "revise", label: "Revise local action template" },
    });
  });

  await page.goto("/");
  await configureConnection(page, { operatorRef: "ops.writer-daily.e2e" });
  await page.reload();
  await switchToAdvancedMode(page);
  await page.getByTestId("nav-deepdesk").click();

  await expect(page.getByTestId("writer-deep-desk")).toBeVisible();
  await page.getByTestId("draft-mode-scene").click();
  await expect(page.getByTestId("author-draft-editor")).toHaveValue("AUTHOR DRAFT v1");

  await page.getByTestId("draft-proposal-generate").click();
  await expect(page.getByTestId("draft-proposals")).toContainText("AI PROPOSAL TEXT with stronger pressure");
  await expect(page.getByTestId("author-draft-editor")).toHaveValue("AUTHOR DRAFT v1");

  await page.getByTestId("draft-proposal-apply-append").click();
  await expect(page.getByTestId("author-draft-editor")).toHaveValue(/AI PROPOSAL TEXT with stronger pressure/);
  await expect(page.getByTestId("deep-desk-reader")).toContainText("FinalScene final_scene_CHWD_E2E_SC01_v1");
  await expect(page.getByTestId("deep-desk-reader")).toContainText("ChapterMemory chapter_memory_final_CHWD_E2E_v1");

  await page.getByTestId("author-draft-editor").fill(`${sceneDraft.content}\n\nAUTHOR POLISH PASS`);
  await page.getByTestId("author-draft-save").click();
  await expect(page.getByTestId("author-draft-events")).toContainText("append proposal");

  await page.getByTestId("deep-review-run").click();
  await expect(page.getByTestId("deep-review-findings")).toContainText("Dialogue explains pressure too directly");

  await page.getByTestId("patch-candidate-create").click();
  await expect(page.getByTestId("passage-patch-candidates")).toContainText("LOCAL CANDIDATE TEXT with a concrete cost");
  await page.locator(".deep-option button").first().click();
  await expect(page.getByTestId("author-draft-editor")).toHaveValue(/LOCAL CANDIDATE TEXT with a concrete cost/);

  await page.getByTestId("author-draft-save").click();
  await expect(page.getByTestId("author-draft-events")).toContainText("saved into author draft");

  await page.getByTestId("inline-quality-run").click();
  await expect(page.getByTestId("inline-quality-span-findings")).toContainText("template_action_reuse");
});
