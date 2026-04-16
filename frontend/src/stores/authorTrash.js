import { defineStore } from "pinia";

import {
  fetchAuthorTrash,
  purgeChapters as postPurgeChapters,
  purgeScenes as postPurgeScenes,
  restoreChapters as postRestoreChapters,
  restoreScenes as postRestoreScenes,
} from "../lib/api";
import { snapshotPayloadList } from "../lib/payloadSnapshot";

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

async function markAuthorWorkspaceStale() {
  const { useAuthorWorkspaceStore } = await import("./authorWorkspace.js");
  const authorWorkspace = useAuthorWorkspaceStore();
  authorWorkspace.markStale();
}

function assignChapterList(store, chapters) {
  store.chapters = snapshotPayloadList(chapters);
  store.chapterListVersion += 1;
}

function assignSceneList(store, scenes) {
  store.scenes = snapshotPayloadList(scenes);
  store.sceneListVersion += 1;
}

export const useAuthorTrashStore = defineStore("authorTrash", {
  state: () => ({
    chapters: [],
    chapterListVersion: 0,
    scenes: [],
    sceneListVersion: 0,
    loaded: false,
    stale: false,
    loading: false,
    actionId: "",
    error: "",
  }),
  actions: {
    markStale() {
      this.stale = true;
    },
    markFresh() {
      this.loaded = true;
      this.stale = false;
    },
    async load({ force = false } = {}) {
      if (this.loaded && !this.stale && !force) {
        return;
      }
      this.loading = true;
      this.error = "";
      try {
        const payload = await fetchAuthorTrash();
        assignChapterList(this, payload.chapters || []);
        assignSceneList(this, payload.scenes || []);
        this.markFresh();
      } catch (error) {
        assignChapterList(this, []);
        assignSceneList(this, []);
        this.loaded = false;
        this.error = error.message;
      } finally {
        this.loading = false;
      }
    },
    async ensureLoaded(options = {}) {
      await this.load(options);
    },
    async restoreChapters(chapterIds) {
      if (!chapterIds?.length) {
        return "尚未选择章节。";
      }
      this.actionId = "restore-chapters";
      this.error = "";
      try {
        const result = await postRestoreChapters(chapterIds);
        await markAuthorWorkspaceStale();
        await this.load({ force: true });
        return batchMessage("已恢复", "章节", result, "chapter_id");
      } catch (error) {
        this.error = error.message;
        throw error;
      } finally {
        this.actionId = "";
      }
    },
    async restoreScenes(sceneIds) {
      if (!sceneIds?.length) {
        return "尚未选择场景。";
      }
      this.actionId = "restore-scenes";
      this.error = "";
      try {
        const result = await postRestoreScenes(sceneIds);
        await markAuthorWorkspaceStale();
        await this.load({ force: true });
        return batchMessage("已恢复", "场景", result, "scene_id");
      } catch (error) {
        this.error = error.message;
        throw error;
      } finally {
        this.actionId = "";
      }
    },
    async purgeChapters(chapterIds) {
      if (!chapterIds?.length) {
        return "尚未选择章节。";
      }
      this.actionId = "purge-chapters";
      this.error = "";
      try {
        const result = await postPurgeChapters(chapterIds);
        await markAuthorWorkspaceStale();
        await this.load({ force: true });
        return batchMessage("已彻底清理", "章节", result, "chapter_id");
      } catch (error) {
        this.error = error.message;
        throw error;
      } finally {
        this.actionId = "";
      }
    },
    async purgeScenes(sceneIds) {
      if (!sceneIds?.length) {
        return "尚未选择场景。";
      }
      this.actionId = "purge-scenes";
      this.error = "";
      try {
        const result = await postPurgeScenes(sceneIds);
        await markAuthorWorkspaceStale();
        await this.load({ force: true });
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
