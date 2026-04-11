import { defineStore } from "pinia";

import {
  fetchActivityEvents,
  fetchJobs,
  fetchTargetActivityGroups,
  fetchVectorAliasScopes,
  retryVerify,
  runDuePromotions,
  runRecoverySweep,
} from "../lib/api";

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
  };
}

function createLedgerFilters() {
  return {
    targetRef: "",
    source: "",
    actorRef: "",
  };
}

function recoveryEventTimestamp(item) {
  return item?.details_json?.last_action_at || item?.last_action_at || item?.created_at || "";
}

function systemRuntimeTimestamp(item) {
  return item?.created_at || "";
}

function latestRecoveryActionReceipt(recoveryEvents) {
  const latest = [...(recoveryEvents || [])]
    .filter((item) => item?.last_action_at)
    .sort((left, right) => recoveryEventTimestamp(right).localeCompare(recoveryEventTimestamp(left)))[0];
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

export const useIndexConsoleStore = defineStore("indexConsole", {
  state: () => ({
    aliasFilters: createAliasFilters(),
    jobFilters: createJobFilters(),
    ledgerFilters: createLedgerFilters(),
    aliasScopes: [],
    jobs: [],
    recoveryEvents: [],
    systemRuntimeEvents: [],
    operatorActionEvents: [],
    targetActivityGroups: [],
    loading: false,
    actionId: "",
    lastRecoveryResult: null,
    lastRecoveryActionResult: null,
    lastPromotionResult: null,
    error: "",
  }),
  getters: {
    recoveryTimelineItems: (state) =>
      [...(state.recoveryEvents || [])]
        .filter((item) => item.event_source === "idempotency_recovery")
        .sort((left, right) => recoveryEventTimestamp(right).localeCompare(recoveryEventTimestamp(left))),
    systemRuntimeTimelineItems: (state) =>
      [...(state.systemRuntimeEvents || [])].sort((left, right) => {
        const createdAtCompare = systemRuntimeTimestamp(right).localeCompare(systemRuntimeTimestamp(left));
        if (createdAtCompare !== 0) {
          return createdAtCompare;
        }
        return (right?.operation_id || 0) - (left?.operation_id || 0);
      }),
    operatorActionTimelineItems: (state) =>
      [...(state.operatorActionEvents || [])].sort((left, right) => {
        const createdAtCompare = systemRuntimeTimestamp(right).localeCompare(systemRuntimeTimestamp(left));
        if (createdAtCompare !== 0) {
          return createdAtCompare;
        }
        return (right?.operation_id || 0) - (left?.operation_id || 0);
      }),
  },
  actions: {
    clearAliasFilters() {
      this.aliasFilters = createAliasFilters();
    },
    clearJobFilters() {
      this.jobFilters = createJobFilters();
    },
    clearLedgerFilters() {
      this.ledgerFilters = createLedgerFilters();
    },
    async load() {
      this.loading = true;
      this.error = "";
      try {
        const activityFilters = {
          targetRef: this.ledgerFilters.targetRef,
          actorRef: this.ledgerFilters.actorRef,
        };
        const selectedSource = this.ledgerFilters.source || "";
        const requestedStreams = selectedSource
          ? [selectedSource]
          : ["recovery_timeline", "system_runtime", "operator_action"];
        const [aliasScopes, jobs, targetGroups, ...activityPayloads] = await Promise.all([
          fetchVectorAliasScopes(this.aliasFilters),
          fetchJobs(this.jobFilters),
          fetchTargetActivityGroups(this.ledgerFilters),
          ...requestedStreams.map((stream) => fetchActivityEvents({ stream, ...activityFilters })),
        ]);
        const activityByStream = Object.fromEntries(
          requestedStreams.map((stream, index) => [stream, activityPayloads[index]?.items || []]),
        );
        this.aliasScopes = aliasScopes.items || [];
        this.jobs = jobs.items || [];
        this.recoveryEvents = activityByStream.recovery_timeline || [];
        this.systemRuntimeEvents = activityByStream.system_runtime || [];
        this.operatorActionEvents = activityByStream.operator_action || [];
        this.targetActivityGroups = targetGroups.items || [];
        this.lastRecoveryActionResult = latestRecoveryActionReceipt(this.recoveryEvents);
      } catch (error) {
        this.aliasScopes = [];
        this.jobs = [];
        this.recoveryEvents = [];
        this.systemRuntimeEvents = [];
        this.operatorActionEvents = [];
        this.targetActivityGroups = [];
        this.lastRecoveryActionResult = null;
        this.error = error.message;
      } finally {
        this.loading = false;
      }
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
        await this.load();
        return `Ran recovery sweep: reclaimed ${result.reclaimed_jobs ?? 0} stale job${result.reclaimed_jobs === 1 ? "" : "s"}, surfaced ${result.failed_jobs ?? 0} failed job${result.failed_jobs === 1 ? "" : "s"}${result.actor_ref ? ` as ${result.actor_ref}` : ""}`;
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
        await this.load();
        return `Promoted ${result.promoted} due candidate${result.promoted === 1 ? "" : "s"}${result.actor_ref ? ` as ${result.actor_ref}` : ""}`;
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
        await this.load();
        return `Retried verify for ${jobId}${result.actor_ref ? ` as ${result.actor_ref}` : ""}`;
      } catch (error) {
        this.error = error.message;
        throw error;
      } finally {
        this.actionId = "";
      }
    },
  },
});
