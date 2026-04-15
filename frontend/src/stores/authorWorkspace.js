import { defineStore } from "pinia";

import {
  fetchSceneDraft,
  fetchAuthorWorkspace,
  fetchChapterRunStatus,
  fetchChapters,
  reorderChapterScenes,
  runChapterFull,
  saveChapter as postChapter,
  saveScene as postScene,
  trashChapters as postTrashChapters,
  trashScenes as postTrashScenes,
} from "../lib/api";

function changedIds(result, key) {
  return (result?.processed || []).map((item) => item?.[key]).filter(Boolean);
}

function batchMessage(actionLabel, itemLabel, result, key) {
  const ids = changedIds(result, key);
  const blockedCount = Array.isArray(result?.blocked) ? result.blocked.length : 0;
  if (!ids.length && !blockedCount) {
    return `No ${itemLabel} changed.`;
  }
  const parts = [];
  if (ids.length) {
    parts.push(`${actionLabel} ${ids.length} ${itemLabel}: ${ids.join(", ")}`);
  }
  if (blockedCount) {
    parts.push(`blocked ${blockedCount}`);
  }
  return parts.join(" | ");
}

async function refreshAuthorTrashStore() {
  const { useAuthorTrashStore } = await import("./authorTrash.js");
  const authorTrash = useAuthorTrashStore();
  await authorTrash.load();
}

export const useAuthorWorkspaceStore = defineStore("authorWorkspace", {
  state: () => ({
    chapters: [],
    selectedChapterId: "",
    chapter: null,
    chapterState: null,
    chapterRunStatus: null,
    scenes: [],
    sceneDraft: null,
    loading: false,
    actionId: "",
    error: "",
  }),
  actions: {
    clearWorkspace() {
      this.chapter = null;
      this.chapterState = null;
      this.chapterRunStatus = null;
      this.scenes = [];
      this.sceneDraft = null;
    },
    async loadChapters() {
      const payload = await fetchChapters();
      this.chapters = payload.items || [];
      if (!this.chapters.length) {
        this.selectedChapterId = "";
        return;
      }
      const hasSelectedChapter = this.chapters.some((chapter) => chapter.chapter_id === this.selectedChapterId);
      if (!hasSelectedChapter) {
        this.selectedChapterId = this.chapters[0].chapter_id;
      }
    },
    async loadWorkspace(chapterId = this.selectedChapterId) {
      if (!chapterId) {
        this.selectedChapterId = "";
        this.clearWorkspace();
        return;
      }
      const [payload, runStatus] = await Promise.all([
        fetchAuthorWorkspace(chapterId),
        fetchChapterRunStatus(chapterId),
      ]);
      this.selectedChapterId = chapterId;
      this.chapter = payload.chapter || null;
      this.chapterState = payload.chapter_state || null;
      this.chapterRunStatus = runStatus || null;
      this.scenes = payload.scenes || [];
      this.sceneDraft = null;
    },
    async refreshActiveData(preferredChapterId = this.selectedChapterId) {
      await this.loadChapters();
      if (preferredChapterId && this.chapters.some((chapter) => chapter.chapter_id === preferredChapterId)) {
        this.selectedChapterId = preferredChapterId;
      }
      if (!this.selectedChapterId) {
        this.clearWorkspace();
        return;
      }
      await this.loadWorkspace(this.selectedChapterId);
    },
    async initialize() {
      this.loading = true;
      this.error = "";
      try {
        await this.refreshActiveData(this.selectedChapterId);
      } catch (error) {
        this.clearWorkspace();
        this.chapters = [];
        this.error = error.message;
      } finally {
        this.loading = false;
      }
    },
    async selectChapter(chapterId) {
      this.loading = true;
      this.error = "";
      try {
        await this.loadWorkspace(chapterId);
      } catch (error) {
        this.clearWorkspace();
        this.error = error.message;
        throw error;
      } finally {
        this.loading = false;
      }
    },
    async saveChapter(payload) {
      this.actionId = "save-chapter";
      this.error = "";
      try {
        const result = await postChapter(payload);
        await this.refreshActiveData(result.chapter_id);
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
        const result = await postScene({
          ...payload,
          chapter_id: chapterId,
        });
        await this.refreshActiveData(chapterId);
        return `已保存场景 ${result.scene_id}`;
      } catch (error) {
        this.error = error.message;
        throw error;
      } finally {
        this.actionId = "";
      }
    },
    async loadSceneDraft(chapterId = this.selectedChapterId) {
      this.actionId = "load-scene-draft";
      this.error = "";
      try {
        const payload = await fetchSceneDraft(chapterId);
        this.sceneDraft = payload;
        return payload;
      } catch (error) {
        this.sceneDraft = null;
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
        await this.loadWorkspace(this.selectedChapterId);
        return `已调整 ${sceneIds.length} 个场景的顺序`;
      } catch (error) {
        this.error = error.message;
        throw error;
      } finally {
        this.actionId = "";
      }
    },
    async runChapter(chapterId = this.selectedChapterId) {
      this.actionId = "run-chapter";
      this.error = "";
      try {
        const result = await runChapterFull(chapterId);
        await this.refreshActiveData(chapterId);
        return `Chapter run ${result.status}: ${chapterId}`;
      } catch (error) {
        this.error = error.message;
        throw error;
      } finally {
        this.actionId = "";
      }
    },
    async trashScenes(sceneIds) {
      if (!sceneIds?.length) {
        return "尚未选择场景。";
      }
      this.actionId = "trash-scenes";
      this.error = "";
      try {
        const result = await postTrashScenes(sceneIds);
        await this.refreshActiveData(this.selectedChapterId);
        await refreshAuthorTrashStore();
        return batchMessage("已移入作者回收站", "场景", result, "scene_id");
      } catch (error) {
        this.error = error.message;
        throw error;
      } finally {
        this.actionId = "";
      }
    },
    async trashChapters(chapterIds) {
      if (!chapterIds?.length) {
        return "尚未选择章节。";
      }
      this.actionId = "trash-chapters";
      this.error = "";
      try {
        const result = await postTrashChapters(chapterIds);
        const nextChapterId =
          this.selectedChapterId && !chapterIds.includes(this.selectedChapterId) ? this.selectedChapterId : "";
        await this.refreshActiveData(nextChapterId);
        await refreshAuthorTrashStore();
        return batchMessage("已移入作者回收站", "章节", result, "chapter_id");
      } catch (error) {
        this.error = error.message;
        throw error;
      } finally {
        this.actionId = "";
      }
    },
  },
});
