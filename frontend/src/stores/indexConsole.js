import { defineStore } from "pinia";

import { fetchAliasScopes, fetchIndexJobs, retryVerify, runRecoverySweep } from "../lib/api";

export const useIndexConsoleStore = defineStore("indexConsole", {
  state: () => ({
    aliasScopes: [],
    jobs: [],
    loading: false,
    actionId: "",
    error: "",
  }),
  actions: {
    async load() {
      this.loading = true;
      this.error = "";
      try {
        const [aliasScopes, jobs] = await Promise.all([fetchAliasScopes(), fetchIndexJobs()]);
        this.aliasScopes = aliasScopes.items || [];
        this.jobs = jobs.items || [];
      } catch (error) {
        this.aliasScopes = [];
        this.jobs = [];
        this.error = error.message;
      } finally {
        this.loading = false;
      }
    },
    async runRecovery() {
      this.actionId = "recovery";
      this.error = "";
      try {
        await runRecoverySweep();
        await this.load();
        return "Ran recovery sweep";
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
        await retryVerify(jobId);
        await this.load();
        return `Retried verify for ${jobId}`;
      } catch (error) {
        this.error = error.message;
        throw error;
      } finally {
        this.actionId = "";
      }
    },
  },
});
