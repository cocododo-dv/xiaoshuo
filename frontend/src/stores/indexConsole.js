import { defineStore } from "pinia";

import {
  fetchAliasScopes,
  fetchIndexJobs,
  fetchIndexRuntimeLedger,
  retryVerify,
  runDuePromotions,
  runRecoverySweep,
} from "../lib/api";

function recoveryEventTimestamp(item) {
  return item?.details_json?.last_action_at || item?.last_action_at || item?.created_at || "";
}

function systemRuntimeTimestamp(item) {
  return item?.created_at || "";
}

export const useIndexConsoleStore = defineStore("indexConsole", {
  state: () => ({
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
    async load() {
      this.loading = true;
      this.error = "";
      try {
        const [aliasScopes, jobs, runtimeLedger] = await Promise.all([
          fetchAliasScopes(),
          fetchIndexJobs(),
          fetchIndexRuntimeLedger(),
        ]);
        this.aliasScopes = aliasScopes.items || [];
        this.jobs = jobs.items || [];
        this.recoveryEvents = runtimeLedger.recovery_timeline_items || [];
        this.systemRuntimeEvents = runtimeLedger.system_runtime_timeline_items || [];
        this.operatorActionEvents = runtimeLedger.operator_action_timeline_items || [];
        this.targetActivityGroups = runtimeLedger.target_activity_groups || [];
        this.lastRecoveryActionResult = runtimeLedger.latest_recovery_action_receipt || null;
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
