// @vitest-environment jsdom

import { readFileSync } from "node:fs";
import path from "node:path";

import { createPinia, setActivePinia } from "pinia";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import * as api from "../src/lib/api";
import { useShellRouter } from "../src/router";

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

function writerRoomPayload() {
  return {
    target: {
      object_type: "scene",
      object_id: "WRFE100_SC01",
      chapter_id: "WRFE100",
      scene_id: "WRFE100_SC01",
    },
    navigation: {
      selected_chapter_id: "WRFE100",
      selected_scene_id: "WRFE100_SC01",
      chapters: [{ chapter_id: "WRFE100", chapter_goal: "确认录音是否真实。" }],
      scenes: [{ scene_id: "WRFE100_SC01", scene_goal: "她必须决定是否公开录音。" }],
    },
    chapter: { chapter_id: "WRFE100", chapter_goal: "确认录音是否真实。" },
    scene_card: {
      scene_id: "WRFE100_SC01",
      scene_goal: "她必须决定是否公开录音。",
      writer_brief_json: {
        character_desire: "确认真相",
        obstacle: "公开会暴露幸存者",
        stakes: "她背负隐瞒真相的嫌疑",
      },
    },
    draft: {
      draft_id: "author_draft_scene_WRFE100_SC01",
      object_type: "scene",
      object_id: "WRFE100_SC01",
      source_text_ref: "final_scene:final_scene_WRFE100_SC01_v1",
      content: "她解释了全部前史。门外无人说话。",
      revision_no: 1,
      status: "current",
    },
    primary_text: {
      source: "author_draft",
      source_ref: "author_draft:author_draft_scene_WRFE100_SC01",
      content: "她解释了全部前史。门外无人说话。",
      revision_no: 1,
    },
    diagnosis: {
      status: "completed",
      score_visible: false,
      evaluation_id: "writer_eval_wrfe100",
      author_visible_summary: {
        label: "先改这个",
        summary: "选择代价还不够具体。",
      },
      advanced_evidence: {
        overall_score: 0.61,
        scores: { choice_pressure: 0.4 },
      },
      top_issue: {
        dimension: "choice_pressure",
        display_priority: "先改这个",
        issue: "选择代价还不够具体。",
        recommendation: "让她用隐瞒换取幸存者安全。",
      },
      keep: "保留门外无人说话的余味。",
      options: [{ kind: "brief", text: "补足可见代价。" }],
    },
    top_issue: {
      dimension: "choice_pressure",
      display_priority: "先改这个",
      issue: "top-level author priority",
      recommendation: "make the cost visible",
    },
    keep_advice: "keep the silence outside the door",
    scene_form: "revelation",
    proposals: [
      {
        proposal_id: "proposal_wrfe100_patch",
        draft_id: "author_draft_scene_WRFE100_SC01",
        object_type: "scene",
        object_id: "WRFE100_SC01",
        proposal_type: "passage_candidate",
        proposal_kind: "local_patch",
        replacement_text: "她没有解释，只把证据袋推到桌沿。",
        content: "她没有解释，只把证据袋推到桌沿。门外无人说话。",
        merge_status: "pending",
        status: "candidate",
      },
    ],
    proposal_cards: [
      {
        proposal_id: "proposal_wrfe100_patch",
        proposal_kind: "local_patch",
        display_kind: "局部改法",
        excerpt: "candidate excerpt",
        status: "candidate",
      },
    ],
    context_pressure: [
      {
        card_id: "lf_wrfe100_arc",
        card_type: "character_arc_gap",
        severity: "major",
        recommendation: { summary: "让她付出一个眼前代价。" },
      },
    ],
    longform_cards: [
      {
        card_id: "lf_wrfe100_promise",
        card_type: "promise_without_payoff",
        severity: "critical",
        title: "unpaid promise",
        summary: "settle the recording promise before adding a new one",
      },
    ],
    next_actions: [{ action: "write", label: "继续写正文", reason: "正文是当前工作中心。" }],
    author_preference_summary: { rejected_ai_traces: ["过度解释人物意识"] },
  };
}

describe("writer room shell", () => {
  beforeEach(() => {
    setActivePinia(createPinia());
    vi.resetModules();
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("keeps the writer room registered as the small-revision entry after the snowflake workbench", () => {
    const router = useShellRouter();
    const routerSource = readSource("src/router.js");
    const appSource = readSource("src/App.vue");

    router.reset();

    expect(router.activeView.value).toBe("snowflake-workbench");
    expect(router.views[0]).toEqual(expect.objectContaining({
      id: "snowflake-workbench",
      writerPrimary: true,
      writerLabel: "雪花工作台",
    }));
    expect(router.viewMeta("writer-room")).toEqual(expect.objectContaining({
      id: "writer-room",
      writerPrimary: true,
      writerLabel: "小修写作",
      legacyLabel: "文本优先工作台",
    }));
    expect(router.viewMeta("writer-room").nextViews).toEqual(["snowflake-workbench", "deepdesk", "manuscripts"]);
    expect(routerSource).toContain('id: "snowflake-workbench"');
    expect(routerSource).toContain('id: "writer-room"');
    expect(appSource).toContain('"snowflake-workbench": defineAsyncComponent');
    expect(appSource).toContain('"writer-room": defineAsyncComponent');
    expect(appSource).toContain("./views/WriterRoomView.vue");
  });

  it("keeps the writer room source focused on modes and author-visible cards", () => {
    const viewSource = readSource("src/views/WriterRoomView.vue");

    expect(viewSource).toContain("proposalModeOptions");
    expect(viewSource).toContain("writer-room-proposal-mode-near_final");
    expect(viewSource).toContain("generateProposalSet");
    expect(viewSource).toContain("rejectProposal");
    expect(viewSource).toContain("longformCards");
    expect(viewSource).not.toContain("advanced_evidence");
  });

  it("keeps writer room draft actions inside the shared feedback loop", () => {
    const viewSource = readSource("src/views/WriterRoomView.vue");

    expect(viewSource).toContain("useFlowActionFeedback");
    expect(viewSource).toContain("FlowActionReceipt");
    expect(viewSource).toContain("WRITER_DRAFT_SCOPE");
    expect(viewSource).toContain("WRITER_PROPOSAL_SCOPE");
    expect(viewSource).toContain("scheduleAutoSave");
    expect(viewSource).toContain("window.setTimeout");
    expect(viewSource).toContain("1500");
    expect(viewSource).toContain("保存中...");
    expect(viewSource).toContain("已自动保存");
    expect(viewSource).toContain("保存失败");
    expect(viewSource).toContain("beforeunload");
    expect(viewSource).toContain('data-testid="writer-room-context-strip"');
    expect(viewSource).toContain("下一步：比较候选或继续小修正文");
    expect(viewSource).toContain("正文已保存");
  });

  it("exposes writer room and draft-scoped proposal API helpers", async () => {
    globalThis.fetch = vi.fn(async () => okEnvelope({}));

    await api.fetchWriterRoom("scene", "WRFE100_SC01");
    await api.openProjectChapterDraft("PRJ_WRFE", {
      chapter_id: "WRFE100",
      initial_content: "first chapter text",
      source: "discovery",
    });
    await api.fetchAuthorDraftProposalDiff("author_draft_scene_WRFE100_SC01", "proposal_wrfe100_patch");
    await api.applyAuthorDraftScopedProposal("author_draft_scene_WRFE100_SC01", {
      proposal_id: "proposal_wrfe100_patch",
      apply_mode: "local_patch",
    });
    await api.generateAuthorDraftProposalSet("author_draft_scene_WRFE100_SC01", {
      mode: "near_final",
      instruction: "keep the salt bell",
    });
    await api.rejectAuthorDraftProposal("proposal_wrfe100_patch", { note: "too direct" });

    const urls = globalThis.fetch.mock.calls.map(([url]) => String(url));
    expect(urls).toContain("http://127.0.0.1:8000/api/v1/writer-room/scene/WRFE100_SC01");
    expect(urls).toContain("http://127.0.0.1:8000/api/v1/projects/PRJ_WRFE/chapter-drafts/open");
    expect(urls).toContain(
      "http://127.0.0.1:8000/api/v1/author-drafts/author_draft_scene_WRFE100_SC01/proposals/proposal_wrfe100_patch/diff",
    );
    expect(urls).toContain("http://127.0.0.1:8000/api/v1/author-drafts/author_draft_scene_WRFE100_SC01/apply-proposal");
    expect(urls).toContain("http://127.0.0.1:8000/api/v1/author-drafts/author_draft_scene_WRFE100_SC01/proposals/generate-set");
    expect(urls).toContain("http://127.0.0.1:8000/api/v1/author-draft-proposals/proposal_wrfe100_patch/reject");
  });

  it("uses inherited author drafts for normal writer room ensure and keeps an explicit blank path available", () => {
    const storeSource = readSource("src/stores/writerRoom.js");

    expect(storeSource).toContain("ensureAuthorDraft");
    expect(storeSource).toContain("ensureBlankDraft");
    expect(storeSource).toContain("openProjectChapterDraft");
    expect(storeSource).toContain("openChapterDraft");
    expect(storeSource).toContain("await ensureAuthorDraft(this.objectType, this.objectId)");
    expect(storeSource).toContain("await ensureBlankAuthorDraft(this.objectType, this.objectId)");
  });

  it("opens a project chapter draft as the writer-first room payload", async () => {
    globalThis.fetch = vi.fn(async (url, options = {}) => {
      const requestUrl = String(url);
      if (requestUrl.includes("/projects/PRJ_WRFE/chapter-drafts/open")) {
        const body = JSON.parse(options.body || "{}");
        expect(body.initial_content).toBe("first chapter text");
        return okEnvelope({
          ...writerRoomPayload(),
          target: {
            object_type: "chapter",
            object_id: "WRFE100",
            chapter_id: "WRFE100",
            scene_id: null,
          },
          scene_card: null,
          draft: {
            ...writerRoomPayload().draft,
            draft_id: "author_draft_chapter_WRFE100",
            object_type: "chapter",
            object_id: "WRFE100",
            content: "first chapter text",
          },
          primary_text: {
            source: "author_draft",
            source_ref: "author_draft:author_draft_chapter_WRFE100",
            content: "first chapter text",
            revision_no: 1,
          },
        });
      }
      throw new Error(`Unexpected fetch: ${requestUrl}`);
    });

    const { useWriterRoomStore } = await import("../src/stores/writerRoom.js");
    const store = useWriterRoomStore();

    await store.openChapterDraft("PRJ_WRFE", {
      chapter_id: "WRFE100",
      initial_content: "first chapter text",
    });

    expect(store.objectType).toBe("chapter");
    expect(store.objectId).toBe("WRFE100");
    expect(store.draft.draft_id).toBe("author_draft_chapter_WRFE100");
    expect(store.draftContent).toBe("first chapter text");
  });

  it("uses an in-app rejection dialog and readable diff viewer instead of browser prompt", () => {
    const viewSource = readSource("src/views/WriterRoomView.vue");
    const diffSource = readSource("src/components/DiffViewer.vue");

    expect(viewSource).toContain("rejectDialog");
    expect(viewSource).toContain("pendingRejectProposal");
    expect(viewSource).toContain('data-testid="writer-room-reject-dialog"');
    expect(viewSource).toContain("DiffViewer");
    expect(viewSource).not.toContain("window.prompt");
    expect(viewSource).not.toContain("<pre>{{ diffPreview.before_text || \"\" }}</pre>");
    expect(viewSource).not.toContain("<pre>{{ diffPreview.after_text || \"\" }}</pre>");
    expect(diffSource).toContain('data-testid="diff-viewer-before"');
    expect(diffSource).toContain('data-testid="diff-viewer-after"');
    expect(diffSource).toContain("diff-line-added");
    expect(diffSource).toContain("diff-line-removed");
    expect(viewSource).toContain("preference_remembered");
    expect(viewSource).not.toContain("作者在写作房间拒绝此改法。");
  });

  it("hydrates writer room payload and applies proposals through diff-first flow", async () => {
    globalThis.fetch = vi.fn(async (url, options = {}) => {
      const requestUrl = String(url);
      if (requestUrl.includes("/writer-room/scene/WRFE100_SC01")) {
        return okEnvelope(writerRoomPayload());
      }
      if (requestUrl.includes("/proposals/proposal_wrfe100_patch/diff")) {
        return okEnvelope({
          draft_id: "author_draft_scene_WRFE100_SC01",
          proposal_id: "proposal_wrfe100_patch",
          merge_status: "clean",
          before_text: "她解释了全部前史。门外无人说话。",
          after_text: "她没有解释，只把证据袋推到桌沿。门外无人说话。",
        });
      }
      if (requestUrl.includes("/apply-proposal")) {
        const body = JSON.parse(options.body || "{}");
        expect(body.proposal_id).toBe("proposal_wrfe100_patch");
        return okEnvelope({
          proposal: { ...writerRoomPayload().proposals[0], status: "accepted", merge_status: "applied" },
          draft: {
            ...writerRoomPayload().draft,
            content: "她没有解释，只把证据袋推到桌沿。门外无人说话。",
            revision_no: 2,
          },
          open_draft_proposals: [],
          author_preference_summary: {},
        });
      }
      if (requestUrl.includes("/proposals/generate-set")) {
        const body = JSON.parse(options.body || "{}");
        expect(body.mode).toBe("near_final");
        expect(body.instruction).toBe("keep the salt bell");
        expect(body.target_range.source_excerpt).toBe("她解释了全部前史。");
        return okEnvelope({
          draft_id: "author_draft_scene_WRFE100_SC01",
          mode: "near_final",
          proposals: [
            {
              proposal_id: "proposal_generated_near_final",
              draft_id: "author_draft_scene_WRFE100_SC01",
              object_type: "scene",
              object_id: "WRFE100_SC01",
              proposal_type: "near_final_rewrite",
              proposal_kind: "near_final_rewrite",
              content: "near-final candidate",
              status: "candidate",
              merge_status: "pending",
            },
            {
              proposal_id: "proposal_generated_language",
              draft_id: "author_draft_scene_WRFE100_SC01",
              object_type: "scene",
              object_id: "WRFE100_SC01",
              proposal_type: "language_pass",
              proposal_kind: "language_pass",
              content: "language candidate",
              status: "candidate",
              merge_status: "pending",
            },
            {
              proposal_id: "proposal_generated_dialogue",
              draft_id: "author_draft_scene_WRFE100_SC01",
              object_type: "scene",
              object_id: "WRFE100_SC01",
              proposal_type: "dialogue_pass",
              proposal_kind: "dialogue_pass",
              content: "dialogue candidate",
              status: "candidate",
              merge_status: "pending",
            },
          ],
        });
      }
      if (requestUrl.includes("/author-draft-proposals/proposal_generated_near_final/reject")) {
        return okEnvelope({
          proposal: {
            proposal_id: "proposal_generated_near_final",
            draft_id: "author_draft_scene_WRFE100_SC01",
            proposal_type: "near_final_rewrite",
            proposal_kind: "near_final_rewrite",
            status: "rejected",
            merge_status: "pending",
          },
          draft: writerRoomPayload().draft,
        });
      }
      throw new Error(`Unexpected fetch: ${requestUrl}`);
    });

    const { useWriterRoomStore } = await import("../src/stores/writerRoom.js");
    const store = useWriterRoomStore();

    await store.load("scene", "WRFE100_SC01");
    expect(store.primaryText.content).toContain("她解释了全部前史");
    expect(store.topIssue.issue).toBe("top-level author priority");
    expect(store.keepAdvice).toBe("keep the silence outside the door");
    expect(store.sceneForm).toBe("revelation");
    expect(store.scoreVisible).toBe(false);
    expect(store.proposals[0].proposal_kind).toBe("local_patch");
    expect(store.proposalCards[0].display_kind).toBe("局部改法");
    expect(store.contextPressure[0].card_type).toBe("character_arc_gap");
    expect(store.longformCards[0].card_type).toBe("promise_without_payoff");

    const generated = await store.generateProposalSet({
      mode: "near_final",
      instruction: "keep the salt bell",
      target_range: { unit: "text", source_excerpt: "她解释了全部前史。" },
    });
    expect(generated.mode).toBe("near_final");
    expect(store.proposalCards[0].proposal_kind).toBe("near_final_rewrite");
    expect(store.proposalCards[0].display_kind).toBe("近终稿重写");

    await store.rejectProposal("proposal_generated_near_final", { note: "too direct" });
    expect(store.proposalCards.find((proposal) => proposal.proposal_id === "proposal_generated_near_final").status).toBe("rejected");

    const diff = await store.previewProposal("proposal_wrfe100_patch");
    expect(diff.after_text).toContain("证据袋");

    await store.applyProposal("proposal_wrfe100_patch", { apply_mode: "local_patch" });
    expect(store.draft.content).toContain("证据袋");
    expect(store.primaryText.content).toContain("证据袋");
    expect(store.draft.revision_no).toBe(2);
    expect(store.proposals.find((proposal) => proposal.proposal_id === "proposal_wrfe100_patch").merge_status).toBe("applied");
  });
});
