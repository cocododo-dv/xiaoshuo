import { defineStore } from "pinia";

import {
  createLibraryEntity,
  createLibraryRelation,
  deleteLibraryRelation,
  fetchLibraryOverview,
  updateLibraryEntity,
} from "../lib/api";

export const useLibraryStore = defineStore("library", {
  state: () => ({
    projectId: "",
    characters: [],
    entities: [],
    relations: [],
    loading: false,
    error: "",
    actionId: "",
  }),
  getters: {
    /* 实体与人物合并后的全部对象,关系编辑下拉用 */
    allRefs: (state) => [
      ...state.characters.map((item) => ({ ref: item.ref, name: item.name, kind: "character" })),
      ...state.entities.map((item) => ({ ref: item.ref, name: item.name, kind: item.kind })),
    ],
    entitiesByKind: (state) => (kind) => state.entities.filter((item) => item.kind === kind && item.status !== "archived"),
  },
  actions: {
    _applyOverview(payload = {}) {
      this.characters = payload.characters || [];
      this.entities = payload.entities || [];
      this.relations = payload.relations || [];
    },
    async load(projectId) {
      if (!projectId) {
        this.projectId = "";
        this._applyOverview();
        return null;
      }
      this.loading = true;
      this.error = "";
      try {
        const payload = await fetchLibraryOverview(projectId);
        this.projectId = projectId;
        this._applyOverview(payload);
        return payload;
      } catch (error) {
        this.error = error.message;
        throw error;
      } finally {
        this.loading = false;
      }
    },
    async createEntity(payload) {
      this.actionId = "entity-create";
      this.error = "";
      try {
        const created = await createLibraryEntity(this.projectId, payload);
        this.entities = [...this.entities, created];
        return created;
      } catch (error) {
        this.error = error.message;
        throw error;
      } finally {
        this.actionId = "";
      }
    },
    async updateEntity(entityId, payload) {
      this.actionId = `entity-update:${entityId}`;
      this.error = "";
      try {
        const updated = await updateLibraryEntity(this.projectId, entityId, payload);
        this.entities = this.entities.map((item) => (item.entity_id === entityId ? updated : item));
        return updated;
      } catch (error) {
        this.error = error.message;
        throw error;
      } finally {
        this.actionId = "";
      }
    },
    async createRelation(payload) {
      this.actionId = "relation-create";
      this.error = "";
      try {
        const created = await createLibraryRelation(this.projectId, payload);
        this.relations = [...this.relations, created];
        return created;
      } catch (error) {
        this.error = error.message;
        throw error;
      } finally {
        this.actionId = "";
      }
    },
    async removeRelation(relationId) {
      this.actionId = `relation-delete:${relationId}`;
      this.error = "";
      try {
        await deleteLibraryRelation(this.projectId, relationId);
        this.relations = this.relations.filter((item) => item.relation_id !== relationId);
      } catch (error) {
        this.error = error.message;
        throw error;
      } finally {
        this.actionId = "";
      }
    },
  },
});
