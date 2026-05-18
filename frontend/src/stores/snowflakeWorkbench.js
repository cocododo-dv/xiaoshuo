import { defineStore } from "pinia";

import {
  acceptSnowflakeWorkspaceScenesStale,
  acceptSnowflakeWorkspaceStepStale,
  approveSnowflakeWorkspaceOutline,
  approveSnowflakeWorkspaceStep,
  applyAuthorStructureCandidateToSnowflake,
  createSnowflakeWorkspaceProject,
  ensureProjectDiscoveryDraft,
  extractAuthorDraftStructure,
  fetchProjectDiscoveryDraft,
  fetchSnowflakeStepHistory,
  fetchSnowflakeWorkspace,
  fetchSnowflakeWorkspaceProjects,
  generateSnowflakeWorkspaceStep,
  materializeSnowflakeWorkspace,
  openProjectChapterDraft,
  applySnowflakeSceneTriageRepair,
  requestSnowflakeSceneTriageSuggestions,
  requestSnowflakeWorkspaceAssistant,
  resyncSnowflakeWorkspace,
  restoreSnowflakeWorkspaceStep,
  saveSnowflakeSceneTriage,
  saveAuthorDraft,
  updateSnowflakeWorkspaceScene,
  updateSnowflakeWorkspaceStep,
} from "../lib/api";

function defaultDraft() {
  return {
    title: "",
    genre: "",
    target_word_count: "",
    target_chapter_count: "",
    outline_text: "",
  };
}

function clonePayload(value) {
  if (value === null || value === undefined) {
    return value;
  }
  return JSON.parse(JSON.stringify(value));
}

function textExcerpt(value, limit = 1800) {
  const text = String(value || "").replace(/\s+/g, " ").trim();
  if (text.length <= limit) {
    return text;
  }
  return `${text.slice(0, limit).trim()}...`;
}

function firstLine(value, fallback = "") {
  return String(value || "")
    .split(/\r?\n/)
    .map((line) => line.trim())
    .find(Boolean)
    || fallback;
}

const LOCAL_STEP_DRAFTS_KEY = "novel-system:snowflake-step-drafts:v1";

function safeStringify(value) {
  try {
    return JSON.stringify(value ?? {});
  } catch {
    return "";
  }
}

function sameDraft(left, right) {
  return safeStringify(left) === safeStringify(right);
}

function readLocalStepDrafts() {
  if (typeof window === "undefined" || !window.localStorage) {
    return {};
  }
  try {
    const parsed = JSON.parse(window.localStorage.getItem(LOCAL_STEP_DRAFTS_KEY) || "{}");
    return parsed && typeof parsed === "object" && !Array.isArray(parsed) ? parsed : {};
  } catch {
    return {};
  }
}

function writeLocalStepDrafts(value) {
  if (typeof window === "undefined" || !window.localStorage) {
    return;
  }
  try {
    const entries = Object.entries(value || {}).filter(([, draft]) => draft?.draftValue !== undefined);
    if (!entries.length) {
      window.localStorage.removeItem(LOCAL_STEP_DRAFTS_KEY);
      return;
    }
    window.localStorage.setItem(LOCAL_STEP_DRAFTS_KEY, JSON.stringify(Object.fromEntries(entries)));
  } catch {
    // Keep the in-memory dirty state usable when localStorage is unavailable.
  }
}

function localDraftKey(projectId, stepKey) {
  return `${projectId || "project"}::${stepKey || "step"}`;
}

function staleStepKey(projectId, step) {
  const artifact = step?.artifact || {};
  return [
    projectId || "project",
    step?.step_key || "step",
    artifact.artifact_id || "artifact",
    artifact.updated_at || artifact.created_at || "",
    artifact.stale_reason || artifact.status || "",
  ].join("::");
}

function staleStorageKey(projectId, step) {
  return `snowflake-stale-dismissed:${staleStepKey(projectId, step)}`;
}

function readDismissedStaleStep(projectId, step) {
  if (typeof localStorage === "undefined") {
    return false;
  }
  try {
    return localStorage.getItem(staleStorageKey(projectId, step)) === "1";
  } catch {
    return false;
  }
}

function writeDismissedStaleStep(projectId, step, value) {
  if (typeof localStorage === "undefined") {
    return;
  }
  try {
    const key = staleStorageKey(projectId, step);
    if (value) {
      localStorage.setItem(key, "1");
    } else {
      localStorage.removeItem(key);
    }
  } catch {
    // Local persistence is a convenience; keep the in-memory state authoritative.
  }
}

function normalizeObject(value) {
  return value && typeof value === "object" && !Array.isArray(value) ? value : {};
}

function projectIdOf(project) {
  return project?.project_id || "";
}

function hasMeaningfulTriage(items) {
  return Array.isArray(items) && items.some((item) => item?.status || item?.notes);
}

function collectionIdentityKey(item) {
  if (!item || typeof item !== "object") {
    return "";
  }
  return item.scene_id || item.character_id || "";
}

function mergeCollectionPatch(base, patch) {
  const baseItems = Array.isArray(base) ? clonePayload(base) : [];
  const patchItems = Array.isArray(patch) ? patch : [];
  if (!patchItems.length) {
    return baseItems;
  }
  const hasStableIds = patchItems.some((item) => collectionIdentityKey(item));
  if (!hasStableIds) {
    return clonePayload(patchItems);
  }
  const merged = [...baseItems];
  patchItems.forEach((patchItem) => {
    const identity = collectionIdentityKey(patchItem);
    if (!identity) {
      merged.push(clonePayload(patchItem));
      return;
    }
    const index = merged.findIndex((item) => collectionIdentityKey(item) === identity);
    if (index === -1) {
      merged.push(clonePayload(patchItem));
      return;
    }
    merged[index] = mergeDraftPatch(merged[index], patchItem);
  });
  return merged;
}

function mergeDraftPatch(base, patch) {
  if (Array.isArray(base) || Array.isArray(patch)) {
    return mergeCollectionPatch(base, patch);
  }
  if (base && typeof base === "object" && patch && typeof patch === "object") {
    const merged = { ...base };
    Object.entries(patch).forEach(([key, value]) => {
      merged[key] = mergeDraftPatch(base[key], value);
    });
    return merged;
  }
  return clonePayload(patch);
}

export const useSnowflakeWorkbenchStore = defineStore("snowflakeWorkbench", {
  state: () => ({
    draft: defaultDraft(),
    projects: [],
    selectedProjectId: "",
    selectedStepKey: "",
    project: null,
    workspace: null,
    assistantReplies: [],
    stepHistory: null,
    triageDrafts: [],
    workbenchMode: "planning",
    selectedTriageSceneId: "",
    triageFilter: "all",
    dirtyStepKeys: {},
    localStepDrafts: readLocalStepDrafts(),
    recoveredDraftNotice: "",
    loading: false,
    loaded: false,
    actionId: "",
    error: "",
    lastActionMessage: "",
    dismissedStaleStepKeys: {},
    discoveryDraft: null,
    discoveryDraftContent: "",
    discoveryDraftSavedContent: "",
    discoveryStructureCandidate: null,
    discoveryImportedStepKeys: [],
  }),
  getters: {
    steps: (state) => state.workspace?.steps || [],
    currentStep(state) {
      const preferredStepKey =
        state.selectedStepKey || state.workspace?.current_step_key || state.workspace?.steps?.[0]?.step_key || "";
      return (state.workspace?.steps || []).find((step) => step.step_key === preferredStepKey) || null;
    },
    triageItems: (state) => state.workspace?.triage_items || [],
    sceneBoard: (state) => state.workspace?.scene_board || { chapters: [], scenes: [] },
    selectedTriageItem(state) {
      const items = state.triageDrafts || [];
      return items.find((item) => item?.scene_id && item.scene_id === state.selectedTriageSceneId) || items[0] || null;
    },
    filteredTriageItems(state) {
      const filter = String(state.triageFilter || "all");
      const items = state.triageDrafts || [];
      if (filter === "all") {
        return items;
      }
      if (filter === "manual") {
        return items.filter((item) => Boolean(item?.status));
      }
      return items.filter((item) => String(item?.effective_status || item?.status || "").toLowerCase() === filter);
    },
    staleScenePlanIds: (state) => (state.workspace?.scene_board?.scenes || [])
      .filter((scene) => scene?.status === "stale" && !scene?.stale_accepted_at)
      .map((scene) => scene.scene_plan_id)
      .filter(Boolean),
    latestPlan: (state) => state.workspace?.latest_plan || null,
    materializationGate: (state) =>
      state.workspace?.materialization_gate || { status: "blocked", blockers: ["雪花步骤尚未完成。"], warnings: [] },
    pendingResyncScenes: (state) => state.workspace?.resync_status?.pending_scenes || [],
    pendingResyncCount: (state) => Number(state.workspace?.resync_status?.pending_count || 0),
    readyToMaterialize: (state) => Boolean(state.workspace?.ready_to_materialize),
    canCreate: (state) => Boolean(String(state.draft.outline_text || "").trim()),
    currentStepDirty(state) {
      const preferredStepKey =
        state.selectedStepKey || state.workspace?.current_step_key || state.workspace?.steps?.[0]?.step_key || "";
      return Boolean(preferredStepKey && state.dirtyStepKeys?.[preferredStepKey]);
    },
    isStaleStepDismissed: (state) => (step) => {
      const projectId = state.selectedProjectId || projectIdOf(state.project) || projectIdOf(state.workspace?.project);
      return Boolean(
        step?.artifact?.status === "stale"
        && (
          state.dismissedStaleStepKeys?.[staleStepKey(projectId, step)]
          || readDismissedStaleStep(projectId, step)
        ),
      );
    },
    hasUnsavedStepDrafts: (state) => Object.values(state.dirtyStepKeys || {}).some(Boolean),
    discoveryDraftDirty: (state) =>
      String(state.discoveryDraftContent || "") !== String(state.discoveryDraftSavedContent || ""),
  },
  actions: {
    resetDraft() {
      this.draft = defaultDraft();
    },
    applyProjects(items = []) {
      this.projects = clonePayload(items) || [];
      return this.projects;
    },
    _activeProjectId() {
      return this.selectedProjectId || projectIdOf(this.project) || projectIdOf(this.workspace?.project);
    },
    _writeLocalStepDrafts(nextDrafts) {
      this.localStepDrafts = { ...(nextDrafts || {}) };
      writeLocalStepDrafts(this.localStepDrafts);
    },
    _persistStepDraft(stepKey, draftValue, projectId = this._activeProjectId()) {
      if (!projectId || !stepKey) {
        return;
      }
      const key = localDraftKey(projectId, stepKey);
      this._writeLocalStepDrafts({
        ...this.localStepDrafts,
        [key]: {
          projectId,
          stepKey,
          draftValue: clonePayload(draftValue || {}),
          dirtySince: this.localStepDrafts?.[key]?.dirtySince || new Date().toISOString(),
          baseUpdatedAt: this.currentStep?.artifact?.updated_at || this.currentStep?.updated_at || null,
        },
      });
    },
    _dropLocalStepDraft(stepKey, projectId = this._activeProjectId()) {
      if (!projectId || !stepKey) {
        return;
      }
      const key = localDraftKey(projectId, stepKey);
      if (!this.localStepDrafts?.[key]) {
        return;
      }
      const next = { ...this.localStepDrafts };
      delete next[key];
      this._writeLocalStepDrafts(next);
    },
    _persistDirtyDrafts() {
      const projectId = this._activeProjectId();
      if (!projectId || !this.workspace?.steps?.length) {
        return;
      }
      (this.workspace.steps || []).forEach((step) => {
        if (step?.step_key && this.dirtyStepKeys?.[step.step_key]) {
          this._persistStepDraft(step.step_key, step.draft || {}, projectId);
        }
      });
    },
    _restoreLocalDrafts(nextWorkspace) {
      const projectId = projectIdOf(nextWorkspace?.project);
      const dirtyStepKeys = {};
      let recoveredCount = 0;
      if (!projectId || !Array.isArray(nextWorkspace?.steps)) {
        this.recoveredDraftNotice = "";
        return dirtyStepKeys;
      }
      const nextLocalDrafts = { ...this.localStepDrafts };
      nextWorkspace.steps.forEach((step) => {
        if (!step?.step_key) {
          return;
        }
        const key = localDraftKey(projectId, step.step_key);
        const localDraft = nextLocalDrafts[key];
        if (!localDraft) {
          return;
        }
        if (sameDraft(localDraft.draftValue, step.draft || {})) {
          delete nextLocalDrafts[key];
          return;
        }
        step.draft = clonePayload(localDraft.draftValue || {});
        dirtyStepKeys[step.step_key] = true;
        recoveredCount += 1;
      });
      if (recoveredCount) {
        this.recoveredDraftNotice = `已恢复未保存草稿 ${recoveredCount} 处，服务端刷新没有覆盖你的修改。`;
      } else {
        this.recoveredDraftNotice = "";
      }
      this._writeLocalStepDrafts(nextLocalDrafts);
      return dirtyStepKeys;
    },
    applyWorkspace(workspace, options = {}) {
      this._persistDirtyDrafts();
      const nextWorkspace = clonePayload(workspace);
      if (!nextWorkspace) {
        this.workspace = null;
        this.project = null;
        this.stepHistory = null;
        this.triageDrafts = [];
        this.assistantReplies = [];
        this.dirtyStepKeys = {};
        this.recoveredDraftNotice = "";
        this.discoveryDraft = null;
        this.discoveryDraftContent = "";
        this.discoveryDraftSavedContent = "";
        this.discoveryStructureCandidate = null;
        this.discoveryImportedStepKeys = [];
        return null;
      }
      const restoredDirtyStepKeys = this._restoreLocalDrafts(nextWorkspace);
      this.workspace = nextWorkspace;
      this.project = nextWorkspace?.project || null;
      this.triageDrafts = clonePayload(nextWorkspace?.triage_items || []);
      this.assistantReplies = clonePayload(nextWorkspace?.assistant_history || []);
      const selectedStillExists = this.triageDrafts.some((item) => item?.scene_id === this.selectedTriageSceneId);
      if (!selectedStillExists) {
        this.selectedTriageSceneId = this.triageDrafts[0]?.scene_id || "";
      }
      this.dirtyStepKeys = restoredDirtyStepKeys;
      if (this.project?.project_id) {
        this.selectedProjectId = this.project.project_id;
        const rest = (this.projects || []).filter((item) => item.project_id !== this.project.project_id);
        this.projects = [clonePayload(this.project), ...rest];
      }

      const stepKeys = (nextWorkspace?.steps || []).map((step) => step.step_key);
      const preferCurrent = options.preferCurrent ?? true;
      if (preferCurrent) {
        this.selectedStepKey = nextWorkspace?.current_step_key || stepKeys[0] || "";
      } else if (!stepKeys.includes(this.selectedStepKey)) {
        this.selectedStepKey = nextWorkspace?.current_step_key || stepKeys[0] || "";
      }
      return this.workspace;
    },
    selectStep(stepKey) {
      if (!stepKey) {
        return;
      }
      this.selectedStepKey = stepKey;
    },
    setWorkbenchMode(mode) {
      const normalized = mode === "triage" ? "triage" : "planning";
      this.workbenchMode = normalized;
      if (normalized === "triage" && !this.selectedTriageSceneId && this.triageDrafts.length) {
        this.selectedTriageSceneId = this.triageDrafts[0].scene_id || "";
      }
      if (normalized === "triage") {
        const sceneStep = (this.steps || []).find((step) => step.step_key === "scene_details");
        if (sceneStep?.step_key) {
          this.selectedStepKey = sceneStep.step_key;
        }
      }
    },
    selectTriageScene(sceneId) {
      const normalized = String(sceneId || "").trim();
      this.selectedTriageSceneId = normalized;
      const sceneStep = (this.steps || []).find((step) => step.step_key === "scene_details");
      if (sceneStep?.step_key) {
        this.selectedStepKey = sceneStep.step_key;
      }
    },
    setTriageFilter(filter) {
      this.triageFilter = String(filter || "all");
    },
    dismissStaleStep(step = this.currentStep) {
      if (!step?.step_key || step?.artifact?.status !== "stale") {
        return;
      }
      const projectId = this._activeProjectId();
      this.dismissedStaleStepKeys = {
        ...(this.dismissedStaleStepKeys || {}),
        [staleStepKey(projectId, step)]: true,
      };
      writeDismissedStaleStep(projectId, step, true);
    },
    restoreStaleStep(step = this.currentStep) {
      if (!step?.step_key) {
        return;
      }
      const projectId = this._activeProjectId();
      const key = staleStepKey(projectId, step);
      if (!this.dismissedStaleStepKeys?.[key]) {
        return;
      }
      const next = { ...(this.dismissedStaleStepKeys || {}) };
      delete next[key];
      this.dismissedStaleStepKeys = next;
      writeDismissedStaleStep(projectId, step, false);
    },
    _markStepDirty(stepKey = this.currentStep?.step_key) {
      if (!stepKey) {
        return;
      }
      this.dirtyStepKeys = {
        ...this.dirtyStepKeys,
        [stepKey]: true,
      };
      const step = (this.workspace?.steps || []).find((item) => item?.step_key === stepKey);
      if (step) {
        this._persistStepDraft(stepKey, step.draft || {});
      }
    },
    _markStepClean(stepKey = this.currentStep?.step_key) {
      if (!stepKey || !this.dirtyStepKeys?.[stepKey]) {
        return;
      }
      const next = { ...this.dirtyStepKeys };
      delete next[stepKey];
      this.dirtyStepKeys = next;
      this._dropLocalStepDraft(stepKey);
    },
    _ensureCurrentStep() {
      const step = this.currentStep;
      if (!step) {
        throw new Error("当前没有可编辑的雪花步骤");
      }
      if (!step.draft || typeof step.draft !== "object") {
        step.draft = {};
      }
      return step;
    },
    updateDraftField(key, value) {
      const step = this._ensureCurrentStep();
      step.draft[key] = value;
      this._markStepDirty(step.step_key);
    },
    updateNestedDraftField(parentKey, key, value) {
      const step = this._ensureCurrentStep();
      if (!step.draft[parentKey] || typeof step.draft[parentKey] !== "object") {
        step.draft[parentKey] = {};
      }
      step.draft[parentKey][key] = value;
      this._markStepDirty(step.step_key);
    },
    replaceDraftListField(key, value) {
      const step = this._ensureCurrentStep();
      step.draft[key] = Array.isArray(value) ? [...value] : [];
      this._markStepDirty(step.step_key);
    },
    updateDraftArrayItem(key, index, value) {
      const step = this._ensureCurrentStep();
      const items = Array.isArray(step.draft[key]) ? [...step.draft[key]] : [];
      while (items.length <= index) {
        items.push("");
      }
      items[index] = value;
      step.draft[key] = items;
      this._markStepDirty(step.step_key);
    },
    addDraftCollectionItem(key, template = {}) {
      const step = this._ensureCurrentStep();
      const items = Array.isArray(step.draft[key]) ? [...step.draft[key]] : [];
      items.push(clonePayload(template));
      step.draft[key] = items;
      this._markStepDirty(step.step_key);
    },
    updateDraftCollectionItem(key, index, field, value) {
      const step = this._ensureCurrentStep();
      const items = Array.isArray(step.draft[key]) ? [...step.draft[key]] : [];
      if (!items[index]) {
        items[index] = {};
      }
      items[index] = {
        ...items[index],
        [field]: value,
      };
      step.draft[key] = items;
      this._markStepDirty(step.step_key);
    },
    replaceDraftCollectionListField(key, index, field, value) {
      this.updateDraftCollectionItem(key, index, field, Array.isArray(value) ? [...value] : []);
    },
    async initialize({ force = false } = {}) {
      if (this.loaded && !force) {
        return this.workspace;
      }
      this.loading = true;
      this.error = "";
      try {
        const payload = await fetchSnowflakeWorkspaceProjects();
        this.applyProjects(payload?.items || []);
        if (!this.selectedProjectId && this.projects.length) {
          this.selectedProjectId = this.projects[0].project_id;
        }
        if (this.selectedProjectId) {
          await this.loadWorkspace(this.selectedProjectId);
        }
        this.loaded = true;
        return this.workspace;
      } catch (error) {
        this.error = error.message;
        throw error;
      } finally {
        this.loading = false;
      }
    },
    async loadWorkspace(projectId = this.selectedProjectId) {
      if (!projectId) {
        this.project = null;
        this.workspace = null;
        this.triageDrafts = [];
        this.assistantReplies = [];
        return null;
      }
      this.actionId = `workspace:${projectId}`;
      this.error = "";
      try {
        const payload = await fetchSnowflakeWorkspace(projectId);
        return this.applyWorkspace(payload);
      } catch (error) {
        this.error = error.message;
        throw error;
      } finally {
        this.actionId = "";
      }
    },
    async selectProject(projectId) {
      this.selectedProjectId = projectId || "";
      return this.loadWorkspace(this.selectedProjectId);
    },
    _applyDiscoveryDraft(result = {}) {
      const draft = clonePayload(result?.draft || result || null);
      this.discoveryDraft = draft;
      this.discoveryDraftContent = draft?.content || "";
      this.discoveryDraftSavedContent = this.discoveryDraftContent;
      this.discoveryStructureCandidate = clonePayload(result?.latest_structure_candidate || null);
      return this.discoveryDraft;
    },
    async loadDiscoveryDraft(projectId = this._activeProjectId()) {
      if (!projectId) {
        return null;
      }
      this.actionId = "discovery-load";
      this.error = "";
      try {
        const result = await fetchProjectDiscoveryDraft(projectId);
        return this._applyDiscoveryDraft(result);
      } catch (error) {
        this.error = error.message;
        throw error;
      } finally {
        this.actionId = "";
      }
    },
    async ensureDiscoveryDraft(projectId = this._activeProjectId()) {
      if (!projectId) {
        throw new Error("Please select a project before opening the discovery draft.");
      }
      this.actionId = "discovery-ensure";
      this.error = "";
      try {
        const result = await ensureProjectDiscoveryDraft(projectId);
        return this._applyDiscoveryDraft(result);
      } catch (error) {
        this.error = error.message;
        throw error;
      } finally {
        this.actionId = "";
      }
    },
    setDiscoveryDraftContent(value) {
      this.discoveryDraftContent = String(value || "");
    },
    async saveDiscoveryDraft() {
      const draft = this.discoveryDraft || (await this.ensureDiscoveryDraft());
      if (!draft?.draft_id) {
        return null;
      }
      this.actionId = "discovery-save";
      this.error = "";
      try {
        const result = await saveAuthorDraft(draft.draft_id, {
          content: this.discoveryDraftContent,
          base_revision_no: draft.revision_no,
          note: "saved from snowflake discovery draft",
        });
        this.discoveryDraft = clonePayload(result?.draft || null);
        this.discoveryDraftContent = this.discoveryDraft?.content || "";
        this.discoveryDraftSavedContent = this.discoveryDraftContent;
        this.lastActionMessage = "自由草稿已保存。";
        return this.discoveryDraft;
      } catch (error) {
        this.error = error.message;
        throw error;
      } finally {
        this.actionId = "";
      }
    },
    async extractDiscoveryStructure(payload = {}) {
      const draft = this.discoveryDraft || (await this.ensureDiscoveryDraft());
      if (!draft?.draft_id) {
        return null;
      }
      if (this.discoveryDraftDirty) {
        await this.saveDiscoveryDraft();
      }
      this.actionId = "discovery-extract";
      this.error = "";
      try {
        const result = await extractAuthorDraftStructure(draft.draft_id, {
          mode: "project_snowflake",
          ...(payload || {}),
        });
        this.discoveryStructureCandidate = clonePayload(result?.candidate || result || null);
        this.lastActionMessage = "已提取为待确认的雪花候选。";
        return this.discoveryStructureCandidate;
      } catch (error) {
        this.error = error.message;
        throw error;
      } finally {
        this.actionId = "";
      }
    },
    async applyDiscoveryStructure(payload = {}) {
      const candidateId =
        payload.candidate_id
        || this.discoveryStructureCandidate?.candidate_id
        || this.discoveryStructureCandidate?.structure_candidate_id
        || "";
      if (!candidateId) {
        throw new Error("Please extract a discovery structure candidate first.");
      }
      this.actionId = "discovery-apply";
      this.error = "";
      try {
        const result = await applyAuthorStructureCandidateToSnowflake(candidateId, payload);
        if (result?.workspace) {
          this.applyWorkspace(result.workspace, { preferCurrent: false });
        }
        this.discoveryImportedStepKeys = clonePayload(result?.imported_step_keys || []);
        this.discoveryStructureCandidate = clonePayload(result?.candidate || this.discoveryStructureCandidate);
        this.lastActionMessage = "自由草稿候选已写入雪花待审步骤。";
        return result;
      } catch (error) {
        this.error = error.message;
        throw error;
      } finally {
        this.actionId = "";
      }
    },
    async openDiscoveryChapterDraft(payload = {}) {
      const projectId = this._activeProjectId();
      if (!projectId) {
        throw new Error("Please select a project before opening a chapter draft.");
      }
      const draft = this.discoveryDraft || (await this.ensureDiscoveryDraft(projectId));
      if (!draft?.draft_id) {
        return null;
      }
      if (this.discoveryDraftDirty) {
        await this.saveDiscoveryDraft();
      }
      const content = this.discoveryDraftContent || this.discoveryDraft?.content || "";
      this.actionId = "discovery-open-chapter";
      this.error = "";
      try {
        const result = await openProjectChapterDraft(projectId, {
          initial_content: content,
          chapter_goal: firstLine(content, this.project?.title || "Writer-first chapter"),
          source: "discovery",
          source_ref: `project_discovery:${projectId}`,
          writer_brief_json: {
            origin: "discovery_draft",
            source_draft_id: draft.draft_id,
            excerpt: textExcerpt(content, 800),
          },
          ...(payload || {}),
        });
        this.lastActionMessage = "WriterRoom chapter draft is ready.";
        return clonePayload(result || null);
      } catch (error) {
        this.error = error.message;
        throw error;
      } finally {
        this.actionId = "";
      }
    },
    async openSceneChapterDraft(scene = {}) {
      const projectId = this._activeProjectId();
      if (!projectId) {
        throw new Error("Please select a project before opening a scene chapter draft.");
      }
      const result = await openProjectChapterDraft(projectId, {
        chapter_id: scene.chapter_id || "",
        chapter_goal: scene.chapter_goal || scene.summary || scene.title || "",
        source: "snowflake_scene",
        source_ref: scene.scene_plan_id || scene.scene_id || "",
        writer_brief_json: {
          origin: "snowflake_scene",
          scene_plan_id: scene.scene_plan_id || "",
          scene_id: scene.scene_id || "",
          summary: scene.summary || scene.title || "",
          goal: scene.goal || scene.scene_goal || "",
          conflict: scene.conflict || scene.scene_crucible || "",
          hook: scene.hook || "",
        },
      });
      this.lastActionMessage = "WriterRoom chapter draft is ready.";
      return clonePayload(result || null);
    },
    async createProject(override = null) {
      const payload = {
        ...this.draft,
        ...(override || {}),
      };
      this.actionId = "create-project";
      this.error = "";
      try {
        const result = await createSnowflakeWorkspaceProject(payload);
        this.project = clonePayload(result?.project || null);
        if (result?.workspace) {
          this.applyWorkspace(result.workspace);
        } else if (this.project?.project_id) {
          await this.loadWorkspace(this.project.project_id);
        }
        this.resetDraft();
        this.lastActionMessage = "项目已创建，进入雪花工作台。";
        return this.project;
      } catch (error) {
        this.error = error.message;
        throw error;
      } finally {
        this.actionId = "";
      }
    },
    async generateCurrentStep(payload = {}) {
      const projectId = this.selectedProjectId || projectIdOf(this.project);
      const stepKey = this.currentStep?.step_key;
      if (!projectId || !stepKey) {
        throw new Error("当前没有可生成的雪花步骤");
      }
      this.actionId = `generate:${stepKey}`;
      this.error = "";
      try {
        const result = await generateSnowflakeWorkspaceStep(projectId, stepKey, payload);
        this.applyWorkspace(result?.workspace, { preferCurrent: false });
        this.selectedStepKey = stepKey;
        this.lastActionMessage = "雪花候选已生成，等待确认。";
        return result?.step || null;
      } catch (error) {
        this.error = error.message;
        throw error;
      } finally {
        this.actionId = "";
      }
    },
    async skipCurrentStep(skipReason) {
      const reason = String(skipReason || "").trim();
      if (!reason) {
        throw new Error("跳过雪花步骤需要写明原因");
      }
      const step = await this.generateCurrentStep({
        skip: true,
        skip_reason: reason,
      });
      this.lastActionMessage = "雪花步骤已记录跳过原因，可以继续下一层。";
      return step;
    },
    async saveCurrentStep() {
      const projectId = this.selectedProjectId || projectIdOf(this.project);
      const step = this.currentStep;
      if (!projectId || !step?.step_key) {
        throw new Error("当前没有可保存的雪花步骤");
      }
      this.actionId = `save:${step.step_key}`;
      this.error = "";
      try {
        const result = await updateSnowflakeWorkspaceStep(projectId, step.step_key, { draft: step.draft || {} });
        this.applyWorkspace(result?.workspace, { preferCurrent: false });
        this.selectedStepKey = step.step_key;
        this._markStepClean(step.step_key);
        this.lastActionMessage = "雪花步骤草稿已保存。";
        return result?.step || null;
      } catch (error) {
        this.error = error.message;
        throw error;
      } finally {
        this.actionId = "";
      }
    },
    async approveCurrentStep() {
      const projectId = this.selectedProjectId || projectIdOf(this.project);
      const stepKey = this.currentStep?.step_key;
      if (!projectId || !stepKey) {
        throw new Error("当前没有可确认的雪花步骤");
      }
      if (this.currentStepDirty) {
        await this.saveCurrentStep();
      }
      this.actionId = `approve:${stepKey}`;
      this.error = "";
      try {
        const result = await approveSnowflakeWorkspaceStep(projectId, stepKey);
        this.applyWorkspace(result?.workspace);
        this.lastActionMessage = "雪花步骤已确认，可以进入下一层。";
        return result?.step || null;
      } catch (error) {
        this.error = error.message;
        throw error;
      } finally {
        this.actionId = "";
      }
    },
    async loadCurrentStepHistory({ includeDraft = false } = {}) {
      const projectId = this.selectedProjectId || projectIdOf(this.project);
      const stepKey = this.currentStep?.step_key;
      if (!projectId || !stepKey) {
        throw new Error("请先选择一个雪花步骤");
      }
      this.actionId = `history:${stepKey}`;
      this.error = "";
      try {
        const result = await fetchSnowflakeStepHistory(projectId, stepKey, { includeDraft });
        this.stepHistory = clonePayload(result || { step_key: stepKey, items: [] });
        return this.stepHistory;
      } catch (error) {
        this.error = error.message;
        throw error;
      } finally {
        this.actionId = "";
      }
    },
    async restoreStepFromHistory(stepRunId) {
      const projectId = this.selectedProjectId || projectIdOf(this.project);
      const stepKey = this.currentStep?.step_key;
      if (!projectId || !stepKey) {
        throw new Error("请先选择一个雪花步骤");
      }
      if (!stepRunId) {
        throw new Error("请选择要恢复的历史版本");
      }
      this.actionId = `restore:${stepKey}`;
      this.error = "";
      try {
        const result = await restoreSnowflakeWorkspaceStep(projectId, stepKey, { step_run_id: stepRunId });
        if (result?.workspace) {
          this.applyWorkspace(result.workspace, { preferCurrent: false });
          this.selectedStepKey = stepKey;
          this._markStepClean(stepKey);
        }
        this.lastActionMessage = "历史草稿已恢复为新的待审版本，请检查后再确认。";
        await this.loadCurrentStepHistory();
        return result;
      } catch (error) {
        this.error = error.message;
        throw error;
      } finally {
        this.actionId = "";
      }
    },
    async requestAssistantFromDiscoveryDraft() {
      const excerpt = textExcerpt(this.discoveryDraftContent || this.discoveryDraft?.content || "");
      if (!excerpt) {
        throw new Error("自由草稿为空，先写一点人物、场景或故事想法。");
      }
      return this.requestAssistant({
        message: `请参考下面的自由草稿，为当前雪花步骤补一版可编辑草稿；只给建议和候选补稿，不要替我确认。\n\n自由草稿摘录：\n${excerpt}`,
        discovery_draft_excerpt: excerpt,
      });
    },
    async requestAssistant(input) {
      const projectId = this.selectedProjectId || projectIdOf(this.project);
      if (!projectId) {
        throw new Error("请先选择项目");
      }
      const focusSceneId = this.workbenchMode === "triage" ? this.selectedTriageSceneId : "";
      const sceneStep =
        focusSceneId && this.currentStep?.step_key !== "scene_details"
          ? (this.steps || []).find((step) => step.step_key === "scene_details")
          : this.currentStep;
      const payload =
        typeof input === "string"
          ? {
            step_key: sceneStep?.step_key,
            message: input,
            draft_override: clonePayload(sceneStep?.draft || {}),
            ...(focusSceneId ? { focus_scene_id: focusSceneId } : {}),
          }
          : {
            step_key: sceneStep?.step_key,
            draft_override: clonePayload(sceneStep?.draft || {}),
            ...(focusSceneId ? { focus_scene_id: focusSceneId } : {}),
            ...(input || {}),
          };
      this.actionId = "assistant";
      this.error = "";
      try {
        const result = await requestSnowflakeWorkspaceAssistant(projectId, payload);
        if (Array.isArray(result?.assistant_history)) {
          this.assistantReplies = clonePayload(result.assistant_history);
        } else {
          this.assistantReplies = [...this.assistantReplies, clonePayload(result)];
        }
        this.lastActionMessage = "助手建议已更新。";
        return result;
      } catch (error) {
        this.error = error.message;
        throw error;
      } finally {
        this.actionId = "";
      }
    },
    applyAssistantCandidate(reply) {
      const step = this._ensureCurrentStep();
      const candidatePatch = normalizeObject(reply?.candidate_patch);
      if (!Object.keys(candidatePatch).length) {
        return step.draft;
      }
      step.draft = mergeDraftPatch(normalizeObject(step.draft), candidatePatch);
      this._markStepDirty(step.step_key);
      return step.draft;
    },
    async requestSceneTriageSuggestions(input = {}) {
      const projectId = this.selectedProjectId || projectIdOf(this.project);
      if (!projectId) {
        throw new Error("请先选择项目");
      }
      const sceneStep =
        this.currentStep?.step_key === "scene_details"
          ? this.currentStep
          : (this.steps || []).find((step) => step.step_key === "scene_details");
      this.actionId = "scene-triage-suggest";
      this.error = "";
      try {
        const result = await requestSnowflakeSceneTriageSuggestions(projectId, {
          draft_override: clonePayload(sceneStep?.draft || {}),
          ...(input || {}),
        });
        this.triageDrafts = clonePayload(result?.items || []);
        this.lastActionMessage = "场景体检建议已更新。";
        return result;
      } catch (error) {
        this.error = error.message;
        throw error;
      } finally {
        this.actionId = "";
      }
    },
    async saveSceneTriage(items = this.triageDrafts) {
      const projectId = this.selectedProjectId || projectIdOf(this.project);
      if (!projectId) {
        throw new Error("请先选择项目");
      }
      this.actionId = "scene-triage";
      this.error = "";
      try {
        const result = await saveSnowflakeSceneTriage(projectId, { items });
        this.applyWorkspace(result?.workspace, { preferCurrent: false });
        this.triageDrafts = clonePayload(result?.items || []);
        this.lastActionMessage = "场景体检标记已保存。";
        return result?.items || [];
      } catch (error) {
        this.error = error.message;
        throw error;
      } finally {
        this.actionId = "";
      }
    },
    async bulkMarkTriage(status, scope = "filtered") {
      const normalizedStatus = ["pass", "maybe", "rewrite"].includes(String(status || "").toLowerCase())
        ? String(status || "").toLowerCase()
        : "";
      if (!normalizedStatus) {
        throw new Error("Unknown scene triage status.");
      }
      const sourceItems = scope === "all" ? (this.triageDrafts || []) : (this.filteredTriageItems || []);
      const targetIds = new Set(sourceItems.map((item) => item?.scene_plan_id || item?.scene_id).filter(Boolean));
      if (!targetIds.size) {
        return [];
      }
      const nextItems = (this.triageDrafts || []).map((item) => {
        const identity = item?.scene_plan_id || item?.scene_id;
        if (!targetIds.has(identity)) {
          return item;
        }
        const recommended = String(item?.recommended_status || "").toLowerCase();
        return {
          ...item,
          status: normalizedStatus,
          manual_status: normalizedStatus,
          effective_status: normalizedStatus,
          manual_override: Boolean(recommended && recommended !== normalizedStatus),
          triage_source: "author_saved",
        };
      });
      this.triageDrafts = clonePayload(nextItems);
      return this.saveSceneTriage(this.triageDrafts);
    },
    async acceptStaleStep(step = this.currentStep, payload = {}) {
      const projectId = this.selectedProjectId || projectIdOf(this.project);
      const stepKey = step?.step_key || this.currentStep?.step_key;
      if (!projectId || !stepKey) {
        throw new Error("No stale snowflake step is selected.");
      }
      this.actionId = `accept-stale:${stepKey}`;
      this.error = "";
      try {
        const result = await acceptSnowflakeWorkspaceStepStale(projectId, stepKey, payload);
        if (result?.workspace) {
          this.applyWorkspace(result.workspace, { preferCurrent: false });
          this.selectedStepKey = stepKey;
        }
        this.lastActionMessage = "已复核，当前内容仍可继续使用。";
        return result?.step || null;
      } catch (error) {
        this.error = error.message;
        throw error;
      } finally {
        this.actionId = "";
      }
    },
    async acceptStaleScenes(scenePlanIds = this.staleScenePlanIds, payload = {}) {
      const projectId = this.selectedProjectId || projectIdOf(this.project);
      const ids = (Array.isArray(scenePlanIds) ? scenePlanIds : [scenePlanIds]).filter(Boolean);
      if (!projectId || !ids.length) {
        throw new Error("No stale scene plans are selected.");
      }
      this.actionId = "accept-stale-scenes";
      this.error = "";
      try {
        const result = await acceptSnowflakeWorkspaceScenesStale(projectId, {
          scene_plan_ids: ids,
          ...(payload || {}),
        });
        if (result?.workspace) {
          this.applyWorkspace(result.workspace, { preferCurrent: false });
        }
        this.lastActionMessage = "已复核场景规划，当前版本仍可继续整理成章节结构。";
        return result?.accepted_scenes || [];
      } catch (error) {
        this.error = error.message;
        throw error;
      } finally {
        this.actionId = "";
      }
    },
    async updateScenePlan(scenePlanId, patch = {}) {
      const projectId = this.selectedProjectId || projectIdOf(this.project);
      const normalizedScenePlanId = String(scenePlanId || "").trim();
      if (!projectId || !normalizedScenePlanId) {
        throw new Error("请选择要更新的雪花场景");
      }
      this.actionId = `scene-plan:${normalizedScenePlanId}`;
      this.error = "";
      try {
        const result = await updateSnowflakeWorkspaceScene(projectId, normalizedScenePlanId, patch || {});
        this.applyWorkspace(result?.workspace, { preferCurrent: false });
        this.lastActionMessage = "场景计划已更新。";
        return result?.scene || null;
      } catch (error) {
        this.error = error.message;
        throw error;
      } finally {
        this.actionId = "";
      }
    },
    async applyTriageRepair(triageId) {
      const projectId = this.selectedProjectId || projectIdOf(this.project);
      const normalizedTriageId = String(triageId || "").trim();
      if (!projectId || !normalizedTriageId) {
        throw new Error("请选择要应用的修复");
      }
      this.actionId = `triage-apply:${normalizedTriageId}`;
      this.error = "";
      try {
        const result = await applySnowflakeSceneTriageRepair(projectId, normalizedTriageId);
        this.applyWorkspace(result?.workspace, { preferCurrent: false });
        this.lastActionMessage = "修复已应用到场景计划。";
        return result?.scene || null;
      } catch (error) {
        this.error = error.message;
        throw error;
      } finally {
        this.actionId = "";
      }
    },
    async materializeOutline() {
      const projectId = this.selectedProjectId || projectIdOf(this.project);
      if (!projectId) {
        throw new Error("请先选择项目");
      }
      this.actionId = "materialize-outline";
      this.error = "";
      try {
        const result = await materializeSnowflakeWorkspace(projectId);
        const mergedWorkspace = result?.workspace
          ? {
            ...clonePayload(result.workspace),
            triage_items: hasMeaningfulTriage(result.workspace.triage_items)
              ? clonePayload(result.workspace.triage_items)
              : clonePayload(this.triageItems),
          }
          : null;
        this.applyWorkspace(mergedWorkspace, { preferCurrent: false });
        this.lastActionMessage = "雪花规划已整理为章节结构草案，等待确认。";
        return result?.plan || null;
      } catch (error) {
        this.error = error.message;
        throw error;
      } finally {
        this.actionId = "";
      }
    },
    async approveOutline() {
      const projectId = this.selectedProjectId || projectIdOf(this.project);
      if (!projectId) {
        throw new Error("请先选择项目");
      }
      this.actionId = "approve-outline";
      this.error = "";
      try {
        const result = await approveSnowflakeWorkspaceOutline(projectId);
        this.applyWorkspace(result?.workspace, { preferCurrent: false });
        this.lastActionMessage = "结构已确认，可以进入章节运行。";
        return result?.plan || null;
      } catch (error) {
        this.error = error.message;
        throw error;
      } finally {
        this.actionId = "";
      }
    },
    async previewResync(scenePlanIds = null) {
      const projectId = this.selectedProjectId || projectIdOf(this.project);
      if (!projectId) {
        throw new Error("请先选择项目");
      }
      const pendingIds = Array.isArray(scenePlanIds) ? scenePlanIds : this.pendingResyncScenes.map((scene) => scene.scene_plan_id);
      this.actionId = "preview-resync";
      this.error = "";
      try {
        const result = await resyncSnowflakeWorkspace(projectId, {
          scene_plan_ids: pendingIds.filter(Boolean),
          dry_run: true,
        });
        this.lastActionMessage = "已预览可同步的雪花变更。";
        return result;
      } catch (error) {
        this.error = error.message;
        throw error;
      } finally {
        this.actionId = "";
      }
    },
    async resyncScenes(scenePlanIds = null) {
      const projectId = this.selectedProjectId || projectIdOf(this.project);
      if (!projectId) {
        throw new Error("请先选择项目");
      }
      const pendingIds = Array.isArray(scenePlanIds) ? scenePlanIds : this.pendingResyncScenes.map((scene) => scene.scene_plan_id);
      this.actionId = "resync-scenes";
      this.error = "";
      try {
        const result = await resyncSnowflakeWorkspace(projectId, {
          scene_plan_ids: pendingIds.filter(Boolean),
        });
        this.applyWorkspace(result?.workspace, { preferCurrent: false });
        this.lastActionMessage = "已把选中的雪花规划同步到结构卡。";
        return result;
      } catch (error) {
        this.error = error.message;
        throw error;
      } finally {
        this.actionId = "";
      }
    },
  },
});
