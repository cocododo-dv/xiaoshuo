import { defineStore } from "pinia";

import {
  advanceReferenceLearningRun,
  applyReferenceProfile as applyReferenceProfileRequest,
  approveReview,
  fetchReferenceBook,
  fetchReferenceBooks,
  importReferenceBookPath,
  importReferenceBookUpload,
  rejectReview,
  startReferenceLearningRun,
} from "../lib/api";
import { snapshotPayload, snapshotPayloadList } from "../lib/payloadSnapshot";

function defaultPathDraft() {
  return {
    file_path: "",
    title: "",
    author_label: "",
    cloud_policy: "allow_full_cloud",
    analysis_focus: "style_structure",
  };
}

function defaultUploadDraft() {
  return {
    file: null,
    title: "",
    author_label: "",
    cloud_policy: "allow_full_cloud",
    analysis_focus: "style_structure",
  };
}

function reviewIdForFinding(finding) {
  return finding?.review?.review_id || finding?.review_id || "";
}

function normalizeBookId(payload) {
  return payload?.book_id || payload?.book?.book_id || "";
}

function normalizeRun(payload) {
  return payload?.run || payload || null;
}

function decisionMessage(status) {
  return status === "approved" ? "已批准 1 张候选卡。" : "已拒绝 1 张候选卡。";
}

const STALE_PROFILE_MESSAGE = "参考画像已过期，请继续分析重新生成画像。";

function isStaleProfileError(error) {
  return error?.code === "REFERENCE_PROFILE_STALE" || /stale|过期|重新生成/.test(error?.message || "");
}

export const useReferenceLearningStore = defineStore("referenceLearning", {
  state: () => ({
    books: [],
    selectedBookId: "",
    detail: null,
    currentRun: null,
    currentRound: null,
    loading: false,
    actionId: "",
    error: "",
    lastActionMessage: "",
    importMode: "path",
    pathDraft: defaultPathDraft(),
    uploadDraft: defaultUploadDraft(),
    applyDraft: {
      scope: "chapter",
      scope_ref_id: "",
    },
    loaded: false,
    stale: false,
  }),
  getters: {
    selectedBook: (state) => state.books.find((book) => book.book_id === state.selectedBookId) || null,
    profiles: (state) => state.detail?.profiles || [],
    coverage: (state) => state.detail?.coverage || state.currentRun?.coverage || {},
    findings: (state) => state.currentRound?.findings || [],
    pendingDecisionCount: (state) =>
      (state.currentRound?.findings || []).filter((finding) => {
        const status = finding?.review?.status || finding?.status;
        return status === "pending";
      }).length,
    approvedDecisionCount: (state) =>
      (state.currentRound?.findings || []).filter((finding) => {
        const status = finding?.review?.status || finding?.status;
        return status === "approved";
      }).length,
    rejectedDecisionCount: (state) =>
      (state.currentRound?.findings || []).filter((finding) => {
        const status = finding?.review?.status || finding?.status;
        return status === "rejected";
      }).length,
  },
  actions: {
    markStale() {
      this.stale = true;
    },
    markFresh() {
      this.loaded = true;
      this.stale = false;
    },
    resetImportDrafts() {
      this.pathDraft = defaultPathDraft();
      this.uploadDraft = defaultUploadDraft();
    },
    async initialize({ force = false } = {}) {
      if (this.loaded && !this.stale && !force) {
        return;
      }
      this.loading = true;
      this.error = "";
      try {
        await this.loadBooks();
        const nextBookId = this.selectedBookId || this.books[0]?.book_id || "";
        if (nextBookId) {
          await this.selectBook(nextBookId);
        }
        this.markFresh();
      } catch (error) {
        this.error = error.message;
        throw error;
      } finally {
        this.loading = false;
      }
    },
    async loadBooks() {
      const payload = await fetchReferenceBooks();
      this.books = snapshotPayloadList(payload.items || []);
      if (this.selectedBookId && !this.books.some((book) => book.book_id === this.selectedBookId)) {
        this.selectedBookId = "";
      }
      return this.books;
    },
    async selectBook(bookId) {
      if (!bookId) {
        this.selectedBookId = "";
        this.detail = null;
        this.currentRun = null;
        this.currentRound = null;
        return null;
      }
      this.actionId = `select:${bookId}`;
      this.error = "";
      try {
        const detail = await fetchReferenceBook(bookId);
        this.selectedBookId = bookId;
        this.detail = snapshotPayload(detail);
        this.currentRun = snapshotPayload(detail.latest_run || null);
        this.currentRound = snapshotPayload(detail.latest_round || this.currentRound || null);
        return this.detail;
      } catch (error) {
        this.error = error.message;
        throw error;
      } finally {
        this.actionId = "";
      }
    },
    async importPath(payload = this.pathDraft) {
      this.actionId = "import-path";
      this.error = "";
      try {
        const result = await importReferenceBookPath({
          ...defaultPathDraft(),
          ...payload,
        });
        const bookId = normalizeBookId(result);
        await this.loadBooks();
        if (bookId) {
          await this.selectBook(bookId);
        }
        this.lastActionMessage = `已导入参考书：${result.book?.title || bookId || "未命名"}。下一步：启动学习。`;
        return result;
      } catch (error) {
        this.error = error.message;
        throw error;
      } finally {
        this.actionId = "";
      }
    },
    async importUpload(file = this.uploadDraft.file, overrides = {}) {
      if (!file) {
        throw new Error("请选择一个 TXT 或 MD 文件");
      }
      this.actionId = "import-upload";
      this.error = "";
      try {
        const result = await importReferenceBookUpload({
          ...defaultUploadDraft(),
          ...this.uploadDraft,
          ...overrides,
          file,
        });
        const bookId = normalizeBookId(result);
        await this.loadBooks();
        if (bookId) {
          await this.selectBook(bookId);
        }
        this.lastActionMessage = `已导入参考书：${result.book?.title || bookId || "未命名"}。下一步：启动学习。`;
        return result;
      } catch (error) {
        this.error = error.message;
        throw error;
      } finally {
        this.actionId = "";
      }
    },
    async startRun(payload = { batch_size: 8 }) {
      const bookId = this.selectedBookId;
      if (!bookId) {
        throw new Error("请先选择一本参考书");
      }
      this.actionId = "start-run";
      this.error = "";
      try {
        const result = await startReferenceLearningRun(bookId, payload);
        this.currentRun = snapshotPayload(normalizeRun(result));
        this.currentRound = null;
        await this.loadBooks();
        this.lastActionMessage = "学习任务已启动。下一步：点击「继续分析」生成候选卡。";
        return result;
      } catch (error) {
        this.error = error.message;
        throw error;
      } finally {
        this.actionId = "";
      }
    },
    async advanceRun() {
      const bookId = this.selectedBookId;
      const runId = this.currentRun?.run_id || this.detail?.latest_run?.run_id;
      if (!bookId || !runId) {
        throw new Error("请先启动学习任务");
      }
      this.actionId = "advance-run";
      this.error = "";
      try {
        const result = await advanceReferenceLearningRun(bookId, runId);
        if (result.run) {
          this.currentRun = snapshotPayload(result.run);
        }
        if (result.round) {
          this.currentRound = snapshotPayload(result.round);
          this.lastActionMessage = `已生成第 ${result.round.round_index || 1} 轮候选卡，请审核 ${
            result.round.findings?.length || 0
          } 张卡片。`;
        }
        if (result.profile) {
          this.currentRound = null;
          this.lastActionMessage = "参考书画像已生成。下一步：选择应用范围，并创建审核项。";
        }
        await this.loadBooks();
        if (bookId) {
          await this.selectBook(bookId);
          if (result.round) {
            this.currentRound = snapshotPayload(result.round);
          }
        }
        return result;
      } catch (error) {
        this.error = error.message;
        throw error;
      } finally {
        this.actionId = "";
      }
    },
    updateFindingDecision(reviewId, status, result = {}) {
      if (!this.currentRound?.findings?.length) {
        return;
      }
      const findings = this.currentRound.findings.map((finding) => {
        if (reviewIdForFinding(finding) !== reviewId) {
          return finding;
        }
        const review = {
          ...(finding.review || {}),
          ...result,
          review_id: reviewId,
          status,
        };
        return {
          ...finding,
          status,
          review,
        };
      });
      this.currentRound = snapshotPayload({
        ...this.currentRound,
        findings,
      });
    },
    async approveFinding(reviewId, payload = {}) {
      if (!reviewId) {
        throw new Error("缺少审核项 ID");
      }
      this.actionId = `approve:${reviewId}`;
      this.error = "";
      try {
        const result = await approveReview(reviewId, payload);
        this.updateFindingDecision(reviewId, "approved", result);
        this.lastActionMessage = decisionMessage("approved", reviewId, result);
        return result;
      } catch (error) {
        this.error = error.message;
        throw error;
      } finally {
        this.actionId = "";
      }
    },
    async rejectFinding(reviewId, reason = "") {
      if (!reviewId) {
        throw new Error("缺少审核项 ID");
      }
      this.actionId = `reject:${reviewId}`;
      this.error = "";
      try {
        const result = await rejectReview(reviewId, reason ? { reason } : {});
        this.updateFindingDecision(reviewId, "rejected", result);
        this.lastActionMessage = decisionMessage("rejected", reviewId, result);
        return result;
      } catch (error) {
        this.error = error.message;
        throw error;
      } finally {
        this.actionId = "";
      }
    },
    async applyProfile(profileId, payload = this.applyDraft) {
      const bookId = this.selectedBookId || this.detail?.book?.book_id;
      if (!bookId || !profileId) {
        throw new Error("缺少参考书画像");
      }
      this.actionId = `apply:${profileId}`;
      this.error = "";
      try {
        const result = await applyReferenceProfileRequest(bookId, profileId, {
          scope: payload.scope || "global",
          scope_ref_id: payload.scope === "global" ? "global" : payload.scope_ref_id,
        });
        const reviewIds = (result.reviews || []).map((review) => review.review_id).filter(Boolean);
        this.lastActionMessage = `已创建 ${reviewIds.length || 1} 个应用审核项，请到审核收件箱确认。`;
        return result;
      } catch (error) {
        if (isStaleProfileError(error)) {
          this.error = STALE_PROFILE_MESSAGE;
          this.lastActionMessage = STALE_PROFILE_MESSAGE;
          try {
            await this.selectBook(bookId);
          } catch {
          }
          this.error = STALE_PROFILE_MESSAGE;
          throw new Error(STALE_PROFILE_MESSAGE);
        }
        this.error = error.message;
        throw error;
      } finally {
        this.actionId = "";
      }
    },
  },
});
