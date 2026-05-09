import { defineStore } from "pinia";

import {
  approveProjectChapterFinal,
  approveProjectOutlinePlan,
  attachProjectReferenceProfile,
  approveSnowflakeArtifact,
  createProject,
  fetchProjectDashboard,
  fetchProjectSnowflake,
  fetchProjects,
  generateProjectOutlinePlan,
  generateSnowflakeStep,
  materializeSnowflakeOutlinePlan,
  resolveProjectBacktrackItem,
  runProjectChapter,
  updateSnowflakeArtifact,
} from "../lib/api";
import { snapshotPayload, snapshotPayloadList } from "../lib/payloadSnapshot";

function defaultDraft() {
  return {
    title: "",
    genre: "",
    target_word_count: "",
    target_chapter_count: "",
    outline_text: "",
    planning_mode: "snowflake",
  };
}

function normalizeProject(payload = {}) {
  return payload?.project || payload || null;
}

function projectIdOf(project) {
  return project?.project_id || "";
}

export const useProjectDashboardStore = defineStore("projectDashboard", {
  state: () => ({
    projects: [],
    selectedProjectId: "",
    dashboard: null,
    draft: defaultDraft(),
    loading: false,
    actionId: "",
    error: "",
    lastActionMessage: "",
    lastReviewPacket: null,
    profileBindDraft: "",
    snowflake: null,
    snowflakeEditDraft: "",
    loaded: false,
  }),
  getters: {
    project: (state) => state.dashboard?.project || state.projects.find((project) => project.project_id === state.selectedProjectId) || null,
    latestPlan: (state) => state.dashboard?.latest_plan || null,
    planChapters: (state) => state.dashboard?.latest_plan?.plan_json?.chapters || [],
    currentChapter: (state) => state.dashboard?.current_chapter || null,
    reviewPacket: (state) => state.dashboard?.review_packet || state.lastReviewPacket || null,
    referenceProfiles: (state) => state.dashboard?.reference_profiles || [],
    backtrackItems: (state) => state.dashboard?.backtrack_items || [],
    pendingBacktrackItems: (state) => (state.dashboard?.backtrack_items || []).filter((item) => item.status === "pending"),
    nextAction: (state) => state.dashboard?.next_action || "generate_outline_plan",
    canCreate: (state) => Boolean(String(state.draft.outline_text || "").trim()),
    snowflakeState: (state) => state.snowflake || null,
    snowflakeSteps: (state) => state.snowflake?.steps || [],
    currentSnowflakeStep: (state) => {
      const currentKey = state.snowflake?.current_step_key;
      return (state.snowflake?.steps || []).find((step) => step.step_key === currentKey) || null;
    },
    readyToMaterializeSnowflake: (state) => Boolean(state.snowflake?.ready_to_materialize),
  },
  actions: {
    applyProject(project) {
      const normalized = normalizeProject(project);
      if (!normalized?.project_id) {
        return null;
      }
      this.selectedProjectId = normalized.project_id;
      const rest = this.projects.filter((item) => item.project_id !== normalized.project_id);
      this.projects = snapshotPayloadList([normalized, ...rest]);
      if (this.dashboard?.project?.project_id === normalized.project_id) {
        this.dashboard = snapshotPayload({
          ...this.dashboard,
          project: normalized,
        });
      }
      return normalized;
    },
    applyDashboard(payload = {}) {
      this.dashboard = snapshotPayload(payload || null);
      const project = this.dashboard?.project;
      if (project?.project_id) {
        this.applyProject(project);
      }
      return this.dashboard;
    },
    applySnowflake(payload = {}) {
      this.snowflake = snapshotPayload(payload || null);
      if (this.snowflake?.project?.project_id) {
        this.applyProject(this.snowflake.project);
      }
      const artifact = this.currentSnowflakeStep?.artifact;
      this.snowflakeEditDraft = artifact?.artifact_json
        ? JSON.stringify(artifact.artifact_json, null, 2)
        : "";
      return this.snowflake;
    },
    resetDraft() {
      this.draft = defaultDraft();
    },
    async initialize({ force = false } = {}) {
      if (this.loaded && !force) {
        return this.dashboard;
      }
      this.loading = true;
      this.error = "";
      try {
        const payload = await fetchProjects();
        this.projects = snapshotPayloadList(payload?.items || []);
        if (!this.selectedProjectId && this.projects.length) {
          this.selectedProjectId = this.projects[0].project_id;
        }
        if (this.selectedProjectId) {
          await this.loadDashboard(this.selectedProjectId);
        }
        this.loaded = true;
        return this.dashboard;
      } catch (error) {
        this.error = error.message;
        throw error;
      } finally {
        this.loading = false;
      }
    },
    async loadDashboard(projectId = this.selectedProjectId) {
      if (!projectId) {
        this.dashboard = null;
        return null;
      }
      this.actionId = `dashboard:${projectId}`;
      this.error = "";
      try {
        const payload = await fetchProjectDashboard(projectId);
        const dashboard = this.applyDashboard(payload);
        if (dashboard?.project?.planning_mode === "snowflake") {
          await this.loadSnowflake(projectId);
        }
        return dashboard;
      } catch (error) {
        this.error = error.message;
        throw error;
      } finally {
        this.actionId = "";
      }
    },
    async selectProject(projectId) {
      this.selectedProjectId = projectId || "";
      return this.loadDashboard(this.selectedProjectId);
    },
    async createFromDraft(override = null) {
      const payload = {
        planning_mode: "snowflake",
        ...this.draft,
        ...(override || {}),
      };
      this.actionId = "create-project";
      this.error = "";
      try {
        const result = await createProject(payload);
        const project = this.applyProject(result?.project || result);
        this.dashboard = snapshotPayload({
          project,
          latest_plan: null,
          chapters: [],
          current_chapter: null,
          reference_profiles: [],
          review_packet: null,
          next_action: "generate_outline_plan",
        });
        if (project?.planning_mode === "snowflake") {
          await this.loadSnowflake(project.project_id);
        }
        this.resetDraft();
        this.lastActionMessage = project?.planning_mode === "snowflake"
          ? "项目已创建，下一步生成雪花规划。"
          : "项目已创建，下一步生成结构计划。";
        return project;
      } catch (error) {
        this.error = error.message;
        throw error;
      } finally {
        this.actionId = "";
      }
    },
    async generateOutlinePlan(payload = {}) {
      const projectId = this.selectedProjectId || projectIdOf(this.project);
      if (!projectId) {
        throw new Error("请先选择项目");
      }
      this.actionId = "generate-outline-plan";
      this.error = "";
      try {
        const result = await generateProjectOutlinePlan(projectId, payload);
        this.applyProject(result?.project);
        this.dashboard = snapshotPayload({
          ...(this.dashboard || {}),
          project: result?.project || this.project,
          latest_plan: result?.plan || null,
          review_packet: null,
          next_action: "approve_outline_plan",
        });
        this.lastActionMessage = "结构计划已生成，等待确认。";
        return result?.plan || null;
      } catch (error) {
        this.error = error.message;
        throw error;
      } finally {
        this.actionId = "";
      }
    },
    async loadSnowflake(projectId = this.selectedProjectId || projectIdOf(this.project)) {
      if (!projectId) {
        this.snowflake = null;
        return null;
      }
      this.actionId = `snowflake:${projectId}`;
      this.error = "";
      try {
        const payload = await fetchProjectSnowflake(projectId);
        return this.applySnowflake(payload);
      } catch (error) {
        this.error = error.message;
        throw error;
      } finally {
        this.actionId = "";
      }
    },
    async generateCurrentSnowflakeStep(payload = {}) {
      const projectId = this.selectedProjectId || projectIdOf(this.project);
      const stepKey = this.currentSnowflakeStep?.step_key || this.snowflake?.current_step_key;
      if (!projectId || !stepKey) {
        throw new Error("当前没有可生成的雪花步骤");
      }
      this.actionId = `snowflake-generate:${stepKey}`;
      this.error = "";
      try {
        const result = await generateSnowflakeStep(projectId, stepKey, payload);
        this.applySnowflake(result?.state || this.snowflake);
        const artifact = result?.artifact || null;
        if (artifact?.artifact_json) {
          this.snowflakeEditDraft = JSON.stringify(artifact.artifact_json, null, 2);
        }
        this.lastActionMessage = "雪花候选已生成，等待确认。";
        return artifact;
      } catch (error) {
        this.error = error.message;
        throw error;
      } finally {
        this.actionId = "";
      }
    },
    async updateSnowflakeArtifact(artifactId, artifactJson) {
      const projectId = this.selectedProjectId || projectIdOf(this.project);
      if (!projectId || !artifactId) {
        throw new Error("当前没有可保存的雪花候选");
      }
      this.actionId = `snowflake-save:${artifactId}`;
      this.error = "";
      try {
        const result = await updateSnowflakeArtifact(projectId, artifactId, { artifact_json: artifactJson });
        this.applySnowflake(result?.state || this.snowflake);
        if (result?.artifact?.artifact_json) {
          this.snowflakeEditDraft = JSON.stringify(result.artifact.artifact_json, null, 2);
        }
        this.lastActionMessage = "雪花候选已保存。";
        return result?.artifact || null;
      } catch (error) {
        this.error = error.message;
        throw error;
      } finally {
        this.actionId = "";
      }
    },
    async approveSnowflakeArtifact(artifactId) {
      const projectId = this.selectedProjectId || projectIdOf(this.project);
      if (!projectId || !artifactId) {
        throw new Error("当前没有可确认的雪花候选");
      }
      this.actionId = `snowflake-approve:${artifactId}`;
      this.error = "";
      try {
        const result = await approveSnowflakeArtifact(projectId, artifactId);
        this.applySnowflake(result?.state || this.snowflake);
        this.lastActionMessage = "雪花步骤已确认，可以进入下一层。";
        return result?.artifact || null;
      } catch (error) {
        this.error = error.message;
        throw error;
      } finally {
        this.actionId = "";
      }
    },
    async materializeSnowflakePlan() {
      const projectId = this.selectedProjectId || projectIdOf(this.project);
      if (!projectId) {
        throw new Error("请先选择项目");
      }
      this.actionId = "snowflake-materialize";
      this.error = "";
      try {
        const result = await materializeSnowflakeOutlinePlan(projectId);
        this.applyProject(result?.project);
        this.dashboard = snapshotPayload({
          ...(this.dashboard || {}),
          project: result?.project || this.project,
          latest_plan: result?.plan || null,
          review_packet: null,
          next_action: "approve_outline_plan",
        });
        this.lastActionMessage = "雪花规划已物化为结构计划，等待确认。";
        return result?.plan || null;
      } catch (error) {
        this.error = error.message;
        throw error;
      } finally {
        this.actionId = "";
      }
    },
    async approveOutlinePlan(planId = this.latestPlan?.plan_id) {
      const projectId = this.selectedProjectId || projectIdOf(this.project);
      if (!projectId || !planId) {
        throw new Error("请先生成结构计划");
      }
      this.actionId = "approve-outline-plan";
      this.error = "";
      try {
        const result = await approveProjectOutlinePlan(projectId, planId);
        this.applyProject(result?.project);
        this.dashboard = snapshotPayload({
          ...(this.dashboard || {}),
          project: result?.project || this.project,
          latest_plan: result?.plan || this.latestPlan,
          current_chapter: null,
          review_packet: null,
          next_action: "run_current_chapter",
        });
        this.lastActionMessage = "结构已确认，可以运行当前章节。";
        return result;
      } catch (error) {
        this.error = error.message;
        throw error;
      } finally {
        this.actionId = "";
      }
    },
    async runCurrentChapter() {
      const projectId = this.selectedProjectId || projectIdOf(this.project);
      const chapterId = this.project?.current_chapter_id || this.currentChapter?.chapter_id;
      if (!projectId || !chapterId) {
        throw new Error("当前没有可运行章节");
      }
      this.actionId = `run:${chapterId}`;
      this.error = "";
      try {
        const result = await runProjectChapter(projectId, chapterId);
        this.applyProject(result?.project);
        this.lastReviewPacket = snapshotPayload(result?.review_packet || null);
        this.dashboard = snapshotPayload({
          ...(this.dashboard || {}),
          project: result?.project || this.project,
          review_packet: result?.review_packet || null,
          next_action: result?.project?.status === "chapter_final_review" ? "approve_chapter_final" : "resolve_blocker",
        });
        this.lastActionMessage = result?.project?.status === "chapter_final_review" ? "章节已到终稿审核。" : "章节运行已停在需要处理的位置。";
        return result;
      } catch (error) {
        this.error = error.message;
        throw error;
      } finally {
        this.actionId = "";
      }
    },
    async approveCurrentChapterFinal() {
      const projectId = this.selectedProjectId || projectIdOf(this.project);
      const chapterId = this.project?.current_chapter_id || this.reviewPacket?.chapter_id;
      if (!projectId || !chapterId) {
        throw new Error("当前没有待批准章节");
      }
      this.actionId = `approve-final:${chapterId}`;
      this.error = "";
      try {
        const result = await approveProjectChapterFinal(projectId, chapterId);
        this.applyProject(result?.project);
        this.dashboard = snapshotPayload({
          ...(this.dashboard || {}),
          project: result?.project || this.project,
          review_packet: null,
          next_action: result?.project?.status === "completed" ? "completed" : "run_current_chapter",
        });
        this.lastActionMessage = result?.next_chapter_id ? "本章已批准，已推进到下一章。" : "全书项目已完成。";
        return result;
      } catch (error) {
        this.error = error.message;
        throw error;
      } finally {
        this.actionId = "";
      }
    },
    async bindReferenceProfile(profileId = this.profileBindDraft) {
      const projectId = this.selectedProjectId || projectIdOf(this.project);
      const normalizedProfileId = String(profileId || "").trim();
      if (!projectId || !normalizedProfileId) {
        throw new Error("请输入 ready 状态的参考画像 ID");
      }
      this.actionId = "bind-reference-profile";
      this.error = "";
      try {
        const result = await attachProjectReferenceProfile(projectId, normalizedProfileId);
        this.applyProject(result?.project);
        this.profileBindDraft = "";
        this.dashboard = snapshotPayload({
          ...(this.dashboard || {}),
          project: result?.project || this.project,
          reference_profiles: [
            result?.reference_profile,
            ...this.referenceProfiles.filter((profile) => profile.profile_id !== normalizedProfileId),
          ].filter(Boolean),
        });
        this.lastActionMessage = "参考画像已绑定到当前项目。";
        return result;
      } catch (error) {
        this.error = error.message;
        throw error;
      } finally {
        this.actionId = "";
      }
    },
    async resolveBacktrackItem(itemId, resolutionNote = "") {
      const projectId = this.selectedProjectId || projectIdOf(this.project);
      if (!projectId || !itemId) {
        throw new Error("当前没有可关闭的返工项");
      }
      this.actionId = `resolve-backtrack:${itemId}`;
      this.error = "";
      try {
        const result = await resolveProjectBacktrackItem(projectId, itemId, { resolution_note: resolutionNote });
        await this.loadDashboard(projectId);
        this.lastActionMessage = "返工项已关闭，可以继续推进项目主流程。";
        return result?.item || null;
      } catch (error) {
        this.error = error.message;
        throw error;
      } finally {
        this.actionId = "";
      }
    },
  },
});
