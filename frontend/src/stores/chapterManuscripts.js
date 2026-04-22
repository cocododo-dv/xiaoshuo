import { defineStore } from "pinia";

import {
  fetchAuthorTrash,
  fetchChapterManuscriptDetail,
  fetchChapterManuscripts,
  purgeChapters as postPurgeChapters,
  purgeScenes as postPurgeScenes,
  reorderChapterScenes,
  restoreChapters as postRestoreChapters,
  restoreScenes as postRestoreScenes,
  runChapterFinalAggregate,
  runChapterFull,
  saveChapter as postChapter,
  saveScene as postScene,
  trashChapters as postTrashChapters,
  trashScenes as postTrashScenes,
} from "../lib/api";
import { snapshotPayload, snapshotPayloadList } from "../lib/payloadSnapshot";

function changedIds(result, key) {
  return (result?.processed || []).map((item) => item?.[key]).filter(Boolean);
}

function batchMessage(actionLabel, itemLabel, result, key) {
  const ids = changedIds(result, key);
  const blockedCount = Array.isArray(result?.blocked) ? result.blocked.length : 0;
  if (!ids.length && !blockedCount) {
    return `没有${itemLabel}发生变化。`;
  }
  const parts = [];
  if (ids.length) {
    parts.push(`${actionLabel} ${ids.length} 个${itemLabel}: ${ids.join(", ")}`);
  }
  if (blockedCount) {
    parts.push(`阻塞 ${blockedCount} 个`);
  }
  return parts.join(" | ");
}

function sourcePayload(detail, source) {
  if (!detail) {
    return null;
  }
  if (source === "aggregate") {
    return detail.aggregate || null;
  }
  return detail.assembled || null;
}

function markdownTitle(detail, source) {
  const chapterId = detail?.chapter?.chapter_id || "chapter";
  const label = source === "aggregate" ? "最终聚合版本" : "实时拼接版本";
  return `# ${chapterId}\n\n> ${label}\n\n`;
}

export const useChapterManuscriptsStore = defineStore("chapterManuscripts", {
  state: () => ({
    items: [],
    selectedChapterId: "",
    detail: null,
    trash: { chapters: [], scenes: [] },
    loaded: false,
    stale: false,
    loading: false,
    actionId: "",
    error: "",
  }),
  getters: {
    canUseAggregate: (state) => Boolean(state.detail?.aggregate?.content),
    selectedItem: (state) => state.items.find((item) => item.chapter_id === state.selectedChapterId) || null,
  },
  actions: {
    markStale() {
      this.stale = true;
    },
    markFresh() {
      this.loaded = true;
      this.stale = false;
    },
    clearDetail() {
      this.detail = null;
    },
    async loadList() {
      const payload = await fetchChapterManuscripts();
      this.items = snapshotPayloadList(payload.items || []);
      if (!this.items.length) {
        this.selectedChapterId = "";
        this.clearDetail();
        return;
      }
      if (!this.items.some((item) => item.chapter_id === this.selectedChapterId)) {
        this.selectedChapterId = this.items[0].chapter_id;
      }
    },
    async loadDetail(chapterId = this.selectedChapterId) {
      if (!chapterId) {
        this.selectedChapterId = "";
        this.clearDetail();
        return;
      }
      const payload = await fetchChapterManuscriptDetail(chapterId);
      this.selectedChapterId = chapterId;
      this.detail = snapshotPayload(payload);
    },
    async loadTrash() {
      const payload = await fetchAuthorTrash();
      this.trash = {
        chapters: snapshotPayloadList(payload.chapters || []),
        scenes: snapshotPayloadList(payload.scenes || []),
      };
    },
    async refreshSelected(preferredChapterId = this.selectedChapterId) {
      await this.loadList();
      if (preferredChapterId && this.items.some((item) => item.chapter_id === preferredChapterId)) {
        this.selectedChapterId = preferredChapterId;
      }
      if (this.selectedChapterId) {
        await this.loadDetail(this.selectedChapterId);
      } else {
        this.clearDetail();
      }
    },
    async initialize({ force = false } = {}) {
      if (this.loaded && !this.stale && !force) {
        return;
      }
      this.loading = true;
      this.error = "";
      try {
        await this.refreshSelected(this.selectedChapterId);
        this.markFresh();
      } catch (error) {
        this.items = [];
        this.clearDetail();
        this.loaded = false;
        this.error = error.message;
      } finally {
        this.loading = false;
      }
    },
    async ensureLoaded(options = {}) {
      await this.initialize(options);
    },
    async selectChapter(chapterId) {
      this.loading = true;
      this.error = "";
      try {
        await this.loadDetail(chapterId);
        this.markFresh();
      } catch (error) {
        this.clearDetail();
        this.error = error.message;
        throw error;
      } finally {
        this.loading = false;
      }
    },
    exportText(source = "assembled") {
      return sourcePayload(this.detail, source)?.content || "";
    },
    exportMarkdown(source = "assembled") {
      return `${markdownTitle(this.detail, source)}${this.exportText(source)}`;
    },
    async saveChapter(payload) {
      this.actionId = "save-chapter";
      this.error = "";
      try {
        const result = await postChapter(payload);
        await this.refreshSelected(result.chapter_id);
        this.markFresh();
        return `已保存章节 ${result.chapter_id}`;
      } catch (error) {
        this.error = error.message;
        throw error;
      } finally {
        this.actionId = "";
      }
    },
    async saveScene(payload) {
      this.actionId = `save-scene:${payload.scene_id || "new"}`;
      this.error = "";
      try {
        const chapterId = payload.chapter_id || this.selectedChapterId;
        const result = await postScene({ ...payload, chapter_id: chapterId });
        await this.refreshSelected(chapterId);
        this.markFresh();
        return `已保存场景 ${result.scene_id}`;
      } catch (error) {
        this.error = error.message;
        throw error;
      } finally {
        this.actionId = "";
      }
    },
    async reorderScenes(sceneIds, lastSceneId) {
      this.actionId = "reorder-scenes";
      this.error = "";
      try {
        await reorderChapterScenes(this.selectedChapterId, {
          scene_ids: sceneIds,
          last_scene_id: lastSceneId,
        });
        await this.refreshSelected(this.selectedChapterId);
        return `已调整 ${sceneIds.length} 个场景顺序`;
      } catch (error) {
        this.error = error.message;
        throw error;
      } finally {
        this.actionId = "";
      }
    },
    async runSelectedChapter(chapterId = this.selectedChapterId) {
      this.actionId = "run-chapter";
      this.error = "";
      try {
        const result = await runChapterFull(chapterId);
        await this.refreshSelected(chapterId);
        return `章节运行 ${result.status || "completed"}: ${chapterId}`;
      } catch (error) {
        this.error = error.message;
        throw error;
      } finally {
        this.actionId = "";
      }
    },
    async runFinalAggregate(chapterId = this.selectedChapterId) {
      this.actionId = "run-final-aggregate";
      this.error = "";
      try {
        const result = await runChapterFinalAggregate(chapterId);
        await this.refreshSelected(chapterId);
        return `最终聚合 ${result.status}: ${result.chapter_memory_row_id || chapterId}`;
      } catch (error) {
        this.error = error.message;
        throw error;
      } finally {
        this.actionId = "";
      }
    },
    async trashChapters(chapterIds) {
      this.actionId = "trash-chapters";
      this.error = "";
      try {
        const result = await postTrashChapters(chapterIds);
        const nextChapterId =
          this.selectedChapterId && !chapterIds.includes(this.selectedChapterId) ? this.selectedChapterId : "";
        await this.refreshSelected(nextChapterId);
        await this.loadTrash();
        return batchMessage("已移入回收站", "章节", result, "chapter_id");
      } catch (error) {
        this.error = error.message;
        throw error;
      } finally {
        this.actionId = "";
      }
    },
    async trashScenes(sceneIds) {
      this.actionId = "trash-scenes";
      this.error = "";
      try {
        const result = await postTrashScenes(sceneIds);
        await this.refreshSelected(this.selectedChapterId);
        await this.loadTrash();
        return batchMessage("已移入回收站", "场景", result, "scene_id");
      } catch (error) {
        this.error = error.message;
        throw error;
      } finally {
        this.actionId = "";
      }
    },
    async restoreChapters(chapterIds) {
      this.actionId = "restore-chapters";
      this.error = "";
      try {
        const result = await postRestoreChapters(chapterIds);
        await this.refreshSelected(this.selectedChapterId);
        await this.loadTrash();
        return batchMessage("已恢复", "章节", result, "chapter_id");
      } catch (error) {
        this.error = error.message;
        throw error;
      } finally {
        this.actionId = "";
      }
    },
    async restoreScenes(sceneIds) {
      this.actionId = "restore-scenes";
      this.error = "";
      try {
        const result = await postRestoreScenes(sceneIds);
        await this.refreshSelected(this.selectedChapterId);
        await this.loadTrash();
        return batchMessage("已恢复", "场景", result, "scene_id");
      } catch (error) {
        this.error = error.message;
        throw error;
      } finally {
        this.actionId = "";
      }
    },
    async purgeChapters(chapterIds) {
      this.actionId = "purge-chapters";
      this.error = "";
      try {
        const result = await postPurgeChapters(chapterIds);
        await this.refreshSelected(this.selectedChapterId);
        await this.loadTrash();
        return batchMessage("已彻底清理", "章节", result, "chapter_id");
      } catch (error) {
        this.error = error.message;
        throw error;
      } finally {
        this.actionId = "";
      }
    },
    async purgeScenes(sceneIds) {
      this.actionId = "purge-scenes";
      this.error = "";
      try {
        const result = await postPurgeScenes(sceneIds);
        await this.refreshSelected(this.selectedChapterId);
        await this.loadTrash();
        return batchMessage("已彻底清理", "场景", result, "scene_id");
      } catch (error) {
        this.error = error.message;
        throw error;
      } finally {
        this.actionId = "";
      }
    },
  },
});
