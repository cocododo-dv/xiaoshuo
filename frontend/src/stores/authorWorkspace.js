import { defineStore } from "pinia";

import { fetchAuthorWorkspace, fetchChapters, reorderChapterScenes, saveChapter as postChapter, saveScene as postScene } from "../lib/api";

export const useAuthorWorkspaceStore = defineStore("authorWorkspace", {
  state: () => ({
    chapters: [],
    selectedChapterId: "",
    chapter: null,
    chapterState: null,
    scenes: [],
    loading: false,
    actionId: "",
    error: "",
  }),
  actions: {
    clearWorkspace() {
      this.chapter = null;
      this.chapterState = null;
      this.scenes = [];
    },
    async loadChapters() {
      const payload = await fetchChapters();
      this.chapters = payload.items || [];
      if (!this.selectedChapterId && this.chapters.length) {
        this.selectedChapterId = this.chapters[0].chapter_id;
      }
    },
    async loadWorkspace(chapterId = this.selectedChapterId) {
      if (!chapterId) {
        this.selectedChapterId = "";
        this.clearWorkspace();
        return;
      }
      const payload = await fetchAuthorWorkspace(chapterId);
      this.selectedChapterId = chapterId;
      this.chapter = payload.chapter || null;
      this.chapterState = payload.chapter_state || null;
      this.scenes = payload.scenes || [];
    },
    async initialize() {
      this.loading = true;
      this.error = "";
      try {
        await this.loadChapters();
        await this.loadWorkspace(this.selectedChapterId);
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
        await this.loadChapters();
        await this.loadWorkspace(result.chapter_id);
        return `Saved chapter ${result.chapter_id}`;
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
        await this.loadWorkspace(chapterId);
        await this.loadChapters();
        return `Saved scene ${result.scene_id}`;
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
        await this.loadWorkspace(this.selectedChapterId);
        return `Reordered ${sceneIds.length} scenes`;
      } catch (error) {
        this.error = error.message;
        throw error;
      } finally {
        this.actionId = "";
      }
    },
  },
});
