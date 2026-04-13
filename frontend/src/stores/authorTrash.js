import { defineStore } from "pinia";

import {
  fetchAuthorTrash,
  purgeChapters as postPurgeChapters,
  purgeScenes as postPurgeScenes,
  restoreChapters as postRestoreChapters,
  restoreScenes as postRestoreScenes,
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

async function refreshAuthorWorkspaceStore() {
  const { useAuthorWorkspaceStore } = await import("./authorWorkspace.js");
  const authorWorkspace = useAuthorWorkspaceStore();
  await authorWorkspace.initialize();
}

export const useAuthorTrashStore = defineStore("authorTrash", {
  state: () => ({
    chapters: [],
    scenes: [],
    loading: false,
    actionId: "",
    error: "",
  }),
  actions: {
    async load() {
      this.loading = true;
      this.error = "";
      try {
        const payload = await fetchAuthorTrash();
        this.chapters = payload.chapters || [];
        this.scenes = payload.scenes || [];
      } catch (error) {
        this.chapters = [];
        this.scenes = [];
        this.error = error.message;
      } finally {
        this.loading = false;
      }
    },
    async restoreChapters(chapterIds) {
      if (!chapterIds?.length) {
        return "No chapters selected.";
      }
      this.actionId = "restore-chapters";
      this.error = "";
      try {
        const result = await postRestoreChapters(chapterIds);
        await refreshAuthorWorkspaceStore();
        await this.load();
        return batchMessage("Restored", "chapters", result, "chapter_id");
      } catch (error) {
        this.error = error.message;
        throw error;
      } finally {
        this.actionId = "";
      }
    },
    async restoreScenes(sceneIds) {
      if (!sceneIds?.length) {
        return "No scenes selected.";
      }
      this.actionId = "restore-scenes";
      this.error = "";
      try {
        const result = await postRestoreScenes(sceneIds);
        await refreshAuthorWorkspaceStore();
        await this.load();
        return batchMessage("Restored", "scenes", result, "scene_id");
      } catch (error) {
        this.error = error.message;
        throw error;
      } finally {
        this.actionId = "";
      }
    },
    async purgeChapters(chapterIds) {
      if (!chapterIds?.length) {
        return "No chapters selected.";
      }
      this.actionId = "purge-chapters";
      this.error = "";
      try {
        const result = await postPurgeChapters(chapterIds);
        await refreshAuthorWorkspaceStore();
        await this.load();
        return batchMessage("Purged", "chapters", result, "chapter_id");
      } catch (error) {
        this.error = error.message;
        throw error;
      } finally {
        this.actionId = "";
      }
    },
    async purgeScenes(sceneIds) {
      if (!sceneIds?.length) {
        return "No scenes selected.";
      }
      this.actionId = "purge-scenes";
      this.error = "";
      try {
        const result = await postPurgeScenes(sceneIds);
        await refreshAuthorWorkspaceStore();
        await this.load();
        return batchMessage("Purged", "scenes", result, "scene_id");
      } catch (error) {
        this.error = error.message;
        throw error;
      } finally {
        this.actionId = "";
      }
    },
  },
});
