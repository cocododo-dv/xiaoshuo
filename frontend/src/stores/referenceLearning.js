// referenceLearning store(PR-5 重写)
// 状态结构对齐后端 /api/v2/style-reference/* 18 端点(PR-4 实装)
//
// useWriterPathProgress 契约保留 5 字段(不可改名 / 语义):
//   - loaded
//   - books
//   - profiles
//   - pendingDecisionCount
//   - actionId
//
// 旧 round-based UI 已删除(advanceRun / approveFinding 旧 flow);新 PR-5
// 走 RunOrchestrator + 按 sub_dim 分桶的 findings 视图。

import { defineStore } from "pinia";

import {
  applyStyleReferenceProfile,
  cancelStyleReferenceRun,
  deleteStyleReferenceBinding,
  deleteStyleReferenceBook,
  fetchStyleReferenceBook,
  fetchStyleReferenceProfile,
  fetchStyleReferenceRun,
  importStyleReferenceBookPath,
  importStyleReferenceBookUpload,
  listStyleReferenceBindings,
  listStyleReferenceBooks,
  listStyleReferenceProfiles,
  listStyleReferenceRunFindings,
  previewStyleReferenceProfile,
  reclassifyStyleReferenceBook,
  reviewStyleReferenceFinding,
  startStyleReferenceRun,
  synthesizeStyleReferenceProfile,
} from "../lib/api/styleReference";
import { snapshotPayload, snapshotPayloadList } from "../lib/payloadSnapshot";

const SUB_DIMS_PHASE_1 = [
  "language.sentence_structure",
  "language.vocabulary",
  "language.rhetoric",
  "language.punctuation",
  "narrative.perspective",
  "narrative.pacing",
  "narrative.time_handling",
  "narrative.information_density",
];

function emptyFindingsBucket() {
  const bucket = {};
  for (const dim of SUB_DIMS_PHASE_1) {
    bucket[dim] = { observations: [], forbidden_patterns: [] };
  }
  return bucket;
}

function defaultPathDraft() {
  return {
    file_path: "",
    title: "",
    author_label: "",
    cloud_policy: "local_only",
  };
}

function defaultUploadDraft() {
  return {
    file: null,
    title: "",
    author_label: "",
    cloud_policy: "local_only",
  };
}

function defaultApplyDraft() {
  return {
    scope: "project",
    scope_ref_id: "",
    task_type: "scene_generation",
    strategy: "A",
  };
}

function generateActionId(prefix) {
  return `${prefix}_${Date.now()}_${Math.random().toString(36).slice(2, 8)}`;
}

export const useReferenceLearningStore = defineStore("referenceLearning", {
  state: () => ({
    // useWriterPathProgress 契约(保留命名/语义)
    loaded: false,
    books: [],
    profiles: [],
    pendingDecisionCount: 0,
    actionId: null,
    // useWriterPathProgress 还消费 detail / lastApplicationGuidance
    detail: null,                       // 历史字段;applyProfile 后更新为 { book, profiles }
    lastApplicationGuidance: null,      // applyProfile 成功后写入 review_ids / binding_id 等

    // PR-5 新增字段
    selectedBookId: null,
    currentBook: null,
    currentRun: null,
    findings: emptyFindingsBucket(),
    currentProfile: null,
    bindings: [],
    previewSamples: [],

    // 表单 drafts
    importMode: "path",
    pathDraft: defaultPathDraft(),
    uploadDraft: defaultUploadDraft(),
    applyDraft: defaultApplyDraft(),

    // 通用 UI 状态
    loading: false,
    error: null,
    lastActionMessage: null,
    stale: false,
  }),

  getters: {
    selectedBook(state) {
      return state.currentBook;
    },
    coverage(state) {
      return state.currentRun?.coverage_json ?? {};
    },
    approvedDecisionCount(state) {
      let count = 0;
      for (const bucket of Object.values(state.findings)) {
        for (const f of bucket.observations) {
          if (f.status === "approved") count += 1;
        }
        for (const f of bucket.forbidden_patterns) {
          if (f.status === "approved") count += 1;
        }
      }
      return count;
    },
    rejectedDecisionCount(state) {
      let count = 0;
      for (const bucket of Object.values(state.findings)) {
        for (const f of bucket.observations) {
          if (f.status === "rejected") count += 1;
        }
        for (const f of bucket.forbidden_patterns) {
          if (f.status === "rejected") count += 1;
        }
      }
      return count;
    },
    hasReadyProfile(state) {
      return state.profiles.some((p) => p.status === "active" || p.status === "draft");
    },
  },

  actions: {
    markStale() {
      this.stale = true;
    },
    markFresh() {
      this.stale = false;
    },

    resetImportDrafts() {
      this.pathDraft = defaultPathDraft();
      this.uploadDraft = defaultUploadDraft();
      this.error = null;
    },

    _setActionStart(prefix) {
      this.actionId = generateActionId(prefix);
      this.loading = true;
      this.error = null;
    },
    _setActionEnd(message = null) {
      this.loading = false;
      this.actionId = null;
      if (message) {
        this.lastActionMessage = message;
      }
    },
    _setActionError(error) {
      this.loading = false;
      this.actionId = null;
      this.error = error?.message || String(error || "未知错误");
      throw error;
    },

    async initialize() {
      if (this.loaded && !this.stale) return;
      await this.loadBooks();
      this.loaded = true;
      this.markFresh();
    },

    async loadBooks(status = null) {
      this._setActionStart("load_books");
      try {
        const data = await listStyleReferenceBooks(status ? { status } : {});
        this.books = snapshotPayloadList(data?.books ?? []);
        this._setActionEnd();
      } catch (err) {
        this._setActionError(err);
      }
    },

    async selectBook(bookId) {
      if (!bookId) {
        this.selectedBookId = null;
        this.currentBook = null;
        this.currentRun = null;
        this.findings = emptyFindingsBucket();
        this.profiles = [];
        this.currentProfile = null;
        this.bindings = [];
        this.previewSamples = [];
        return;
      }
      this._setActionStart("select_book");
      try {
        const detail = await fetchStyleReferenceBook(bookId);
        this.selectedBookId = bookId;
        this.currentBook = snapshotPayload(detail?.book ?? null);
        const profilesPayload = await listStyleReferenceProfiles({ bookId });
        this.profiles = snapshotPayloadList(profilesPayload?.profiles ?? []);
        // 找最近的 active / draft profile 作为 currentProfile
        this.currentProfile = this.profiles.find((p) => p.status === "active")
          || this.profiles.find((p) => p.status === "draft")
          || null;
        // run 与 findings 由调用方按需 loadRun / loadRunFindings
        this.currentRun = null;
        this.findings = emptyFindingsBucket();
        this.previewSamples = [];
        this.bindings = [];
        this._setActionEnd();
      } catch (err) {
        this._setActionError(err);
      }
    },

    async deleteBook(bookId) {
      this._setActionStart("delete_book");
      try {
        await deleteStyleReferenceBook(bookId);
        this.books = this.books.filter((b) => b.book_id !== bookId);
        if (this.selectedBookId === bookId) {
          await this.selectBook(null);
        }
        this._setActionEnd("已删除参考书及其衍生数据。");
      } catch (err) {
        this._setActionError(err);
      }
    },

    async reclassifyBook(bookId) {
      this._setActionStart("reclassify_book");
      try {
        const result = await reclassifyStyleReferenceBook(bookId);
        this._setActionEnd(`段落重新分类已${result?.status === "reclassify_pending" ? "排队" : "执行"}。`);
      } catch (err) {
        this._setActionError(err);
      }
    },

    async importPath() {
      this._setActionStart("import_path");
      try {
        const payload = { ...this.pathDraft };
        const result = await importStyleReferenceBookPath(payload);
        await this.loadBooks();
        if (result?.book?.book_id) {
          await this.selectBook(result.book.book_id);
        }
        this.resetImportDrafts();
        this._setActionEnd("参考书已导入并完成分段。");
        return result;
      } catch (err) {
        this._setActionError(err);
      }
    },

    async importUpload() {
      this._setActionStart("import_upload");
      try {
        if (!this.uploadDraft.file) {
          throw new Error("请先选择要上传的文件。");
        }
        const result = await importStyleReferenceBookUpload({
          file: this.uploadDraft.file,
          title: this.uploadDraft.title,
          authorLabel: this.uploadDraft.author_label,
          cloudPolicy: this.uploadDraft.cloud_policy,
        });
        await this.loadBooks();
        if (result?.book?.book_id) {
          await this.selectBook(result.book.book_id);
        }
        this.resetImportDrafts();
        this._setActionEnd("参考书已上传并完成分段。");
        return result;
      } catch (err) {
        this._setActionError(err);
      }
    },

    async startRun(layers = ["language", "narrative"]) {
      if (!this.selectedBookId) {
        this.error = "请先选择一本参考书。";
        return;
      }
      this._setActionStart("start_run");
      try {
        const result = await startStyleReferenceRun(this.selectedBookId, { layers });
        if (result?.run_id) {
          await this.loadRun(result.run_id);
          await this.loadRunFindings(result.run_id);
        }
        this._setActionEnd("抽取已完成,可查看 8 sub_dim findings。");
        return result;
      } catch (err) {
        this._setActionError(err);
      }
    },

    async loadRun(runId) {
      try {
        const data = await fetchStyleReferenceRun(runId);
        this.currentRun = snapshotPayload(data?.run ?? null);
      } catch (err) {
        this.error = err?.message || String(err || "未知错误");
        throw err;
      }
    },

    async cancelRun(runId) {
      this._setActionStart("cancel_run");
      try {
        await cancelStyleReferenceRun(runId);
        if (this.currentRun && this.currentRun.run_id === runId) {
          this.currentRun = { ...this.currentRun, status: "cancelled" };
        }
        this._setActionEnd("已取消抽取。");
      } catch (err) {
        this._setActionError(err);
      }
    },

    async loadRunFindings(runId, filters = {}) {
      try {
        const data = await listStyleReferenceRunFindings(runId, filters);
        const bucket = emptyFindingsBucket();
        for (const f of data?.findings ?? []) {
          const subDim = f.sub_dimension;
          if (!bucket[subDim]) {
            bucket[subDim] = { observations: [], forbidden_patterns: [] };
          }
          if (f.finding_kind === "forbidden_pattern") {
            bucket[subDim].forbidden_patterns.push(snapshotPayload(f));
          } else {
            bucket[subDim].observations.push(snapshotPayload(f));
          }
        }
        this.findings = bucket;
        this._recountPendingDecisions();
      } catch (err) {
        this.error = err?.message || String(err || "未知错误");
        throw err;
      }
    },

    async reviewFinding(findingId, decision, comment = null) {
      this._setActionStart("review_finding");
      try {
        const result = await reviewStyleReferenceFinding(findingId, { decision, comment });
        // 更新本地 finding.status
        for (const bucket of Object.values(this.findings)) {
          for (const list of [bucket.observations, bucket.forbidden_patterns]) {
            const idx = list.findIndex((f) => f.finding_id === findingId);
            if (idx >= 0) {
              list[idx] = {
                ...list[idx],
                status: decision,
                review_id: result?.review_id ?? list[idx].review_id,
              };
            }
          }
        }
        this._recountPendingDecisions();
        this._setActionEnd(`finding 已${decision === "approved" ? "通过" : decision === "rejected" ? "驳回" : "重置为 pending"}。`);
        return result;
      } catch (err) {
        this._setActionError(err);
      }
    },

    _recountPendingDecisions() {
      let pending = 0;
      for (const bucket of Object.values(this.findings)) {
        for (const f of bucket.observations) {
          if (f.status === "pending") pending += 1;
        }
        for (const f of bucket.forbidden_patterns) {
          if (f.status === "pending") pending += 1;
        }
      }
      this.pendingDecisionCount = pending;
    },

    async synthesizeProfile(runId) {
      this._setActionStart("synthesize_profile");
      try {
        const data = await synthesizeStyleReferenceProfile(runId);
        const profile = snapshotPayload(data?.profile ?? null);
        if (profile) {
          this.currentProfile = profile;
          // 把新 profile 添加到 list 顶部
          this.profiles = [profile, ...this.profiles.filter((p) => p.profile_id !== profile.profile_id)];
        }
        this._setActionEnd("已聚合为 StyleProfile,可生成 3 段示例预览或应用到项目。");
        return profile;
      } catch (err) {
        this._setActionError(err);
      }
    },

    async loadProfile(profileId) {
      try {
        const data = await fetchStyleReferenceProfile(profileId);
        this.currentProfile = snapshotPayload(data?.profile ?? null);
      } catch (err) {
        this.error = err?.message || String(err || "未知错误");
        throw err;
      }
    },

    async loadProfiles(bookId = null) {
      try {
        const data = await listStyleReferenceProfiles(bookId ? { bookId } : {});
        this.profiles = snapshotPayloadList(data?.profiles ?? []);
      } catch (err) {
        this.error = err?.message || String(err || "未知错误");
        throw err;
      }
    },

    async previewProfile(profileId) {
      this._setActionStart("preview_profile");
      try {
        const data = await previewStyleReferenceProfile(profileId);
        this.previewSamples = snapshotPayloadList(data?.samples ?? []);
        this._setActionEnd(`已生成 ${this.previewSamples.length} 段示例。`);
        return this.previewSamples;
      } catch (err) {
        this._setActionError(err);
      }
    },

    async applyProfile(profileId) {
      this._setActionStart("apply_profile");
      try {
        const result = await applyStyleReferenceProfile(profileId, {
          scope: this.applyDraft.scope,
          scopeRefId: this.applyDraft.scope_ref_id || null,
          taskType: this.applyDraft.task_type,
          strategy: this.applyDraft.strategy,
        });
        this.lastApplicationGuidance = result || null;
        await this.loadBindings(profileId);
        this._setActionEnd(
          `已创建 ${result?.review_ids?.length ?? 0} 条审阅项,binding=${result?.binding_id}。前往 ReviewInbox 审批后规则将自动入库。`
        );
        return result;
      } catch (err) {
        this._setActionError(err);
      }
    },

    async loadBindings(profileId) {
      try {
        const data = await listStyleReferenceBindings(profileId);
        this.bindings = snapshotPayloadList(data?.bindings ?? []);
      } catch (err) {
        this.error = err?.message || String(err || "未知错误");
        throw err;
      }
    },

    async deleteBinding(bindingId) {
      this._setActionStart("delete_binding");
      try {
        await deleteStyleReferenceBinding(bindingId);
        this.bindings = this.bindings.filter((b) => b.binding_id !== bindingId);
        this._setActionEnd("绑定已删除。");
      } catch (err) {
        this._setActionError(err);
      }
    },
  },
});
