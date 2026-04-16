import { defineStore } from "pinia";

import {
  fetchActivityEvents,
  fetchJobs,
  fetchTargetActivityGroupItems,
  fetchTargetActivityGroups,
  fetchVectorAliasScopes,
  retryVerify,
  runDuePromotions,
  runRecoverySweep,
} from "../lib/api";
import {
  advanceCursorPager,
  applyCursorPayload,
  buildCursorQuery,
  createCursorPager,
  createCursorPagination,
  filtersSignature,
  resetCursorPager,
  retreatCursorPager,
} from "../lib/cursorPagination";
import { snapshotPayload, snapshotPayloadList } from "../lib/payloadSnapshot";
import { normalizeActivityItems, normalizeTargetActivityGroups } from "../lib/targetActivity";

const ACTIVITY_SECTION_IDS = Object.freeze([
  "recovery_timeline",
  "system_runtime",
  "operator_action",
  "target_groups",
]);

function createAliasFilters() {
  return {
    objectType: "",
    scope: "",
    scopeRefId: "",
    verifyStatus: "",
  };
}

function createJobFilters() {
  return {
    jobType: "",
    status: "",
    objectType: "",
    reviewId: "",
    aliasScope: "",
    workerId: "",
    stuckOnly: false,
  };
}

function createLedgerFilters() {
  return {
    targetRef: "",
    source: "",
    actorRef: "",
  };
}

function createActivitySectionState() {
  return {
    pager: createCursorPager(),
    loaded: false,
    stale: false,
    loading: false,
  };
}

function createActivitySections() {
  return {
    recovery_timeline: createActivitySectionState(),
    system_runtime: createActivitySectionState(),
    operator_action: createActivitySectionState(),
    target_groups: createActivitySectionState(),
  };
}

function createTargetGroupState() {
  return {
    pager: createCursorPager(),
    loaded: false,
    stale: false,
    loading: false,
  };
}

function recoveryEventTimestamp(item) {
  return item?.details_json?.last_action_at || item?.last_action_at || item?.created_at || "";
}

function recoveryEventTimestampValue(item) {
  const timestamp = Date.parse(recoveryEventTimestamp(item));
  return Number.isNaN(timestamp) ? 0 : timestamp;
}

function normalizeRecoveryTimelineItems(items) {
  return [...(items || [])]
    .filter((item) => item?.event_source === "idempotency_recovery")
    .sort((left, right) => {
      const timestampDelta = recoveryEventTimestampValue(right) - recoveryEventTimestampValue(left);
      if (timestampDelta !== 0) {
        return timestampDelta;
      }
      return String(left?.event_id || "").localeCompare(String(right?.event_id || ""));
    });
}

function latestRecoveryActionReceipt(recoveryEvents) {
  const latest = normalizeRecoveryTimelineItems(recoveryEvents).find((item) => item?.last_action_at);
  if (!latest) {
    return null;
  }
  return {
    event_id: latest.event_id,
    event_source: latest.event_source,
    status: latest.status,
    action: latest.last_action,
    action_at: latest.last_action_at,
    actor_ref: latest.last_actor_ref,
    object_ref: latest.object_ref,
    linked_target: latest.linked_target,
    linked_target_ref: latest.linked_target_ref,
    resolution_reason: latest.resolution_reason,
    followup_action: latest.followup_action,
    followup_target: latest.followup_target,
    followup_target_ref: latest.followup_target_ref,
    replay_result: latest.last_replay_result,
    replay_target: latest.replay_target,
  };
}

function selectedActivityStreams(source) {
  return source ? [source] : ["recovery_timeline", "system_runtime", "operator_action"];
}

function buildLookup(items, keySelector) {
  return (items || []).reduce((lookup, item) => {
    const key = typeof keySelector === "function" ? keySelector(item) : item?.[keySelector];
    if (key) {
      lookup[key] = true;
    }
    return lookup;
  }, {});
}

function activitySectionStateFor(store, sectionId) {
  return store.activitySections[sectionId] || null;
}

function clearActivitySectionItems(store, sectionId) {
  if (sectionId === "recovery_timeline") {
    store.recoveryEvents = [];
    store.recoveryTimelineItems = [];
    store.lastRecoveryActionResult = null;
    return;
  }
  if (sectionId === "system_runtime") {
    store.systemRuntimeEvents = [];
    store.systemRuntimeTimelineItems = [];
    return;
  }
  if (sectionId === "operator_action") {
    store.operatorActionEvents = [];
    store.operatorActionTimelineItems = [];
    return;
  }
  if (sectionId === "target_groups") {
    store.targetActivityGroups = [];
    store.targetGroupLookup = {};
    store.targetGroupsVersion += 1;
  }
}

function assignActivitySectionItems(store, sectionId, items) {
  if (sectionId === "recovery_timeline") {
    store.recoveryEvents = snapshotPayloadList(items);
    store.recoveryTimelineItems = snapshotPayloadList(normalizeRecoveryTimelineItems(items));
    return;
  }
  if (sectionId === "system_runtime") {
    store.systemRuntimeEvents = snapshotPayloadList(items);
    store.systemRuntimeTimelineItems = snapshotPayloadList(normalizeActivityItems(items));
    return;
  }
  if (sectionId === "operator_action") {
    store.operatorActionEvents = snapshotPayloadList(items);
    store.operatorActionTimelineItems = snapshotPayloadList(normalizeActivityItems(items));
    return;
  }
  if (sectionId === "target_groups") {
    store.targetActivityGroups = snapshotPayloadList(normalizeTargetActivityGroups(items));
    store.targetGroupLookup = buildLookup(store.targetActivityGroups, (group) => group?.target?.target_ref);
    store.targetGroupsVersion += 1;
  }
}

function syncDerivedActivityFlags(store) {
  const sectionStates = Object.values(store.activitySections || {});
  const targetGroupStates = Object.values(store.targetGroupStatesByRef || {});
  store.activityLoading = [...sectionStates, ...targetGroupStates].some((state) => Boolean(state.loading));
  store.activityLoaded = [...sectionStates, ...targetGroupStates].some((state) => Boolean(state.loaded));
  store.activityStale = [...sectionStates, ...targetGroupStates].some((state) => Boolean(state.loaded && state.stale));
}

function resetActivityState(store) {
  ACTIVITY_SECTION_IDS.forEach((sectionId) => {
    const state = activitySectionStateFor(store, sectionId);
    if (!state) {
      return;
    }
    resetCursorPager(state.pager);
    state.loaded = false;
    state.stale = false;
    state.loading = false;
    clearActivitySectionItems(store, sectionId);
  });
  store.targetGroupItemsByRef = {};
  store.targetGroupMetaByRef = {};
  store.targetGroupStatesByRef = {};
  store.targetGroupLookup = {};
  store.targetGroupsVersion += 1;
  store.lastRecoveryActionResult = null;
  syncDerivedActivityFlags(store);
}

function ensureTargetGroupState(store, targetRef) {
  if (!store.targetGroupStatesByRef[targetRef]) {
    store.targetGroupStatesByRef = {
      ...store.targetGroupStatesByRef,
      [targetRef]: createTargetGroupState(),
    };
  }
  return store.targetGroupStatesByRef[targetRef];
}

function upsertTargetGroupMeta(store, targetRef, payload) {
  store.targetGroupMetaByRef = {
    ...store.targetGroupMetaByRef,
    [targetRef]: snapshotPayload({
      target: payload?.target || store.targetGroupMetaByRef[targetRef]?.target || null,
      latestAt: payload?.latest_at || store.targetGroupMetaByRef[targetRef]?.latestAt || null,
      activityCount: payload?.activity_count ?? store.targetGroupMetaByRef[targetRef]?.activityCount ?? 0,
      sources: payload?.sources || store.targetGroupMetaByRef[targetRef]?.sources || [],
      latestActivityKey: payload?.latest_activity_key || store.targetGroupMetaByRef[targetRef]?.latestActivityKey || "",
    }),
  };
}

export const useIndexConsoleStore = defineStore("indexConsole", {
  state: () => ({
    aliasFilters: createAliasFilters(),
    jobFilters: createJobFilters(),
    ledgerFilters: createLedgerFilters(),
    jobPager: createCursorPager(),
    jobFilterSignature: filtersSignature(createJobFilters()),
    activityFilterSignature: filtersSignature(createLedgerFilters()),
    activitySections: createActivitySections(),
    aliasScopes: [],
    jobs: [],
    jobsVersion: 0,
    jobLookup: {},
    recoveryEvents: [],
    systemRuntimeEvents: [],
    operatorActionEvents: [],
    recoveryTimelineItems: [],
    systemRuntimeTimelineItems: [],
    operatorActionTimelineItems: [],
    targetActivityGroups: [],
    targetGroupsVersion: 0,
    targetGroupLookup: {},
    targetGroupItemsByRef: {},
    targetGroupMetaByRef: {},
    targetGroupStatesByRef: {},
    loaded: false,
    stale: false,
    activityLoaded: false,
    activityStale: false,
    loading: false,
    activityLoading: false,
    actionId: "",
    lastRecoveryResult: null,
    lastRecoveryActionResult: null,
    lastPromotionResult: null,
    error: "",
  }),
  getters: {
    jobPagination: (state) => state.jobPager.pagination,
    jobCursor: (state) => state.jobPager.cursor,
    jobCursorStack: (state) => state.jobPager.cursorStack,
    activitySectionState: (state) => (sectionId) => state.activitySections[sectionId] || createActivitySectionState(),
    activitySectionPagination: (state) => (sectionId) =>
      state.activitySections[sectionId]?.pager?.pagination || createCursorPagination(),
    targetGroupState: (state) => (targetRef) => state.targetGroupStatesByRef[targetRef] || createTargetGroupState(),
    targetGroupPagination: (state) => (targetRef) =>
      state.targetGroupStatesByRef[targetRef]?.pager?.pagination || createCursorPagination(),
    targetGroupMeta: (state) => (targetRef) => state.targetGroupMetaByRef[targetRef] || null,
    hasJob: (state) => (jobId) => Boolean(jobId && state.jobLookup[jobId]),
    hasTargetActivityGroup: (state) => (targetRef) => Boolean(targetRef && state.targetGroupLookup[targetRef]),
  },
  actions: {
    markStale({ summary = true, activity = true } = {}) {
      if (summary) {
        this.stale = true;
      }
      if (activity) {
        Object.values(this.activitySections).forEach((section) => {
          if (section.loaded) {
            section.stale = true;
          }
        });
        Object.values(this.targetGroupStatesByRef).forEach((section) => {
          if (section.loaded) {
            section.stale = true;
          }
        });
        syncDerivedActivityFlags(this);
      }
    },
    markFresh() {
      this.loaded = true;
      this.stale = false;
    },
    clearAliasFilters() {
      this.aliasFilters = createAliasFilters();
      this.markStale({ summary: true, activity: false });
    },
    clearJobFilters() {
      this.jobFilters = createJobFilters();
      this.markStale({ summary: true, activity: false });
    },
    clearLedgerFilters() {
      this.ledgerFilters = createLedgerFilters();
      resetActivityState(this);
      this.activityFilterSignature = filtersSignature(this.ledgerFilters);
    },
    syncJobPager({ reset = false } = {}) {
      const nextSignature = filtersSignature(this.jobFilters);
      if (reset || nextSignature !== this.jobFilterSignature) {
        resetCursorPager(this.jobPager);
      }
      this.jobFilterSignature = nextSignature;
    },
    syncActivityPagers({ reset = false } = {}) {
      const nextSignature = filtersSignature(this.ledgerFilters);
      if (!reset && nextSignature === this.activityFilterSignature) {
        return;
      }
      this.activityFilterSignature = nextSignature;
      resetActivityState(this);
    },
    assignJobs(items) {
      const snapshotItems = snapshotPayloadList(items);
      this.jobs = snapshotItems;
      this.jobLookup = buildLookup(snapshotItems, "job_id");
      this.jobsVersion += 1;
    },
    async loadJobs({ reset = false } = {}) {
      this.syncJobPager({ reset });
      const filters = {
        ...this.jobFilters,
        ...buildCursorQuery(this.jobPager),
      };
      if (!filters.workerId) {
        delete filters.workerId;
      }
      if (!filters.stuckOnly) {
        delete filters.stuckOnly;
      }
      const payload = await fetchJobs(filters);
      this.assignJobs(applyCursorPayload(this.jobPager, payload));
    },
    async loadSummary({ force = false } = {}) {
      if (this.loaded && !this.stale && !force) {
        return;
      }
      this.loading = true;
      this.error = "";
      try {
        const [aliasScopes] = await Promise.all([
          fetchVectorAliasScopes(this.aliasFilters),
          this.loadJobs({ reset: force }),
        ]);
        this.aliasScopes = snapshotPayloadList(aliasScopes.items || []);
        this.markFresh();
      } catch (error) {
        this.aliasScopes = [];
        this.assignJobs([]);
        this.loaded = false;
        this.error = error.message;
      } finally {
        this.loading = false;
      }
    },
    async loadActivitySection(sectionId, { force = false, reset = false } = {}) {
      this.syncActivityPagers({ reset });
      const section = activitySectionStateFor(this, sectionId);
      if (!section) {
        return;
      }
      if (section.loaded && !section.stale && !force) {
        return;
      }

      section.loading = true;
      this.error = "";
      syncDerivedActivityFlags(this);

      try {
        const filters = {
          targetRef: this.ledgerFilters.targetRef,
          actorRef: this.ledgerFilters.actorRef,
          ...buildCursorQuery(section.pager),
        };
        let payload;
        if (sectionId === "target_groups") {
          if (this.ledgerFilters.source) {
            filters.source = this.ledgerFilters.source;
          }
          payload = await fetchTargetActivityGroups(filters);
        } else {
          payload = await fetchActivityEvents({
            stream: sectionId,
            ...filters,
          });
        }

        const items = applyCursorPayload(section.pager, payload);
        assignActivitySectionItems(this, sectionId, items);
        if (sectionId === "target_groups") {
          (this.targetActivityGroups || []).forEach((group) => {
            upsertTargetGroupMeta(this, group.target.target_ref, {
              target: group.target,
              latest_at: group.latest_at,
              activity_count: group.activity_count,
              sources: group.sources,
              latest_activity_key: group.latest_activity_key,
            });
          });
        }
        if (sectionId === "recovery_timeline" && !section.pager.cursor && !section.pager.cursorStack.length) {
          this.lastRecoveryActionResult = latestRecoveryActionReceipt(this.recoveryTimelineItems);
        }
        section.loaded = true;
        section.stale = false;
      } catch (error) {
        clearActivitySectionItems(this, sectionId);
        section.loaded = false;
        this.error = error.message;
      } finally {
        section.loading = false;
        syncDerivedActivityFlags(this);
      }
    },
    async ensureLoaded(options = {}) {
      await this.loadSummary(options);
    },
    async load({ force = false } = {}) {
      await this.loadSummary({ force });
    },
    async ensureActivitySectionLoaded(sectionId, options = {}) {
      await this.loadActivitySection(sectionId, options);
    },
    async ensureActivityLoaded({ force = false, reset = false } = {}) {
      this.syncActivityPagers({ reset });
      const sections = [...selectedActivityStreams(this.ledgerFilters.source || ""), "target_groups"];
      await Promise.all(
        sections.map((sectionId) => this.loadActivitySection(sectionId, { force })),
      );
    },
    async nextJobPage() {
      if (!advanceCursorPager(this.jobPager)) {
        return;
      }
      this.loading = true;
      this.error = "";
      try {
        await this.loadJobs();
        this.markFresh();
      } catch (error) {
        this.error = error.message;
      } finally {
        this.loading = false;
      }
    },
    async previousJobPage() {
      if (!retreatCursorPager(this.jobPager)) {
        return;
      }
      this.loading = true;
      this.error = "";
      try {
        await this.loadJobs();
        this.markFresh();
      } catch (error) {
        this.error = error.message;
      } finally {
        this.loading = false;
      }
    },
    async nextActivitySectionPage(sectionId) {
      const section = activitySectionStateFor(this, sectionId);
      if (!section || !advanceCursorPager(section.pager)) {
        return;
      }
      await this.loadActivitySection(sectionId, { force: true });
    },
    async previousActivitySectionPage(sectionId) {
      const section = activitySectionStateFor(this, sectionId);
      if (!section || !retreatCursorPager(section.pager)) {
        return;
      }
      await this.loadActivitySection(sectionId, { force: true });
    },
    async ensureTargetGroupItemsLoaded(targetRef, { force = false, reset = false } = {}) {
      this.syncActivityPagers({ reset });
      const section = ensureTargetGroupState(this, targetRef);
      if (section.loaded && !section.stale && !force) {
        return;
      }

      section.loading = true;
      this.error = "";
      syncDerivedActivityFlags(this);

      try {
        const filters = {
          actorRef: this.ledgerFilters.actorRef,
          ...buildCursorQuery(section.pager),
        };
        if (this.ledgerFilters.source) {
          filters.source = this.ledgerFilters.source;
        }
        const payload = await fetchTargetActivityGroupItems(targetRef, filters);
        this.targetGroupItemsByRef = {
          ...this.targetGroupItemsByRef,
          [targetRef]: snapshotPayloadList(applyCursorPayload(section.pager, payload)),
        };
        upsertTargetGroupMeta(this, targetRef, payload);
        section.loaded = true;
        section.stale = false;
      } catch (error) {
        this.targetGroupItemsByRef = {
          ...this.targetGroupItemsByRef,
          [targetRef]: snapshotPayloadList([]),
        };
        section.loaded = false;
        this.error = error.message;
      } finally {
        section.loading = false;
        syncDerivedActivityFlags(this);
      }
    },
    async nextTargetGroupItemsPage(targetRef) {
      const section = ensureTargetGroupState(this, targetRef);
      if (!advanceCursorPager(section.pager)) {
        return;
      }
      await this.ensureTargetGroupItemsLoaded(targetRef, { force: true });
    },
    async previousTargetGroupItemsPage(targetRef) {
      const section = ensureTargetGroupState(this, targetRef);
      if (!retreatCursorPager(section.pager)) {
        return;
      }
      await this.ensureTargetGroupItemsLoaded(targetRef, { force: true });
    },
    recordRecoveryAction(result) {
      this.lastRecoveryActionResult = result;
    },
    async runRecovery() {
      this.actionId = "recovery";
      this.error = "";
      try {
        const result = await runRecoverySweep();
        this.lastRecoveryResult = result;
        this.syncJobPager({ reset: true });
        await this.loadSummary({ force: true });
        this.markStale({ summary: false, activity: true });
        if (this.activityLoaded) {
          await this.ensureActivityLoaded({ force: true, reset: true });
        }
        return `已执行恢复扫描：回收 ${result.reclaimed_jobs ?? 0} 个过期任务，发现 ${result.failed_jobs ?? 0} 个失败任务${result.actor_ref ? `，操作员 ${result.actor_ref}` : ""}`;
      } catch (error) {
        this.error = error.message;
        throw error;
      } finally {
        this.actionId = "";
      }
    },
    async runDuePromotions() {
      this.actionId = "promotions";
      this.error = "";
      try {
        const result = await runDuePromotions();
        this.lastPromotionResult = result;
        this.syncJobPager({ reset: true });
        await this.loadSummary({ force: true });
        this.markStale({ summary: false, activity: true });
        if (this.activityLoaded) {
          await this.ensureActivityLoaded({ force: true, reset: true });
        }
        return `已发布 ${result.promoted} 个到期候选${result.actor_ref ? `，操作员 ${result.actor_ref}` : ""}`;
      } catch (error) {
        this.error = error.message;
        throw error;
      } finally {
        this.actionId = "";
      }
    },
    async retryVerifyJob(jobId) {
      this.actionId = jobId;
      this.error = "";
      try {
        const result = await retryVerify(jobId);
        this.syncJobPager({ reset: true });
        await this.loadSummary({ force: true });
        this.markStale({ summary: false, activity: true });
        if (this.activityLoaded) {
          await this.ensureActivityLoaded({ force: true, reset: true });
        }
        return `已重试校验 ${jobId}${result.actor_ref ? `，操作员 ${result.actor_ref}` : ""}`;
      } catch (error) {
        this.error = error.message;
        throw error;
      } finally {
        this.actionId = "";
      }
    },
  },
});
