<script setup>
import { computed } from "vue";

import { buildBundleProvenance } from "../lib/bundleProvenance";

const props = defineProps({
  snapshot: {
    type: Object,
    default: null,
  },
});

const provenance = computed(() => buildBundleProvenance(props.snapshot));

function formatVersion(version) {
  return version == null ? "Reference" : `v${version}`;
}
</script>

<template>
  <article class="paper provenance-card">
    <div class="provenance-head">
      <div>
        <h3>Bundle Provenance</h3>
        <p class="muted provenance-copy">
          Trace which source rows fed the bundle and the exact order they were injected into the scene run.
        </p>
      </div>
      <span v-if="provenance.available" class="badge">Snapshot live</span>
    </div>

    <div v-if="!provenance.available" class="empty">Run the scene once to capture a traceable bundle snapshot.</div>
    <div v-else class="provenance-grid">
      <section class="provenance-section">
        <div class="provenance-label">Traceable sources</div>
        <div v-if="provenance.sources.length" class="source-stack">
          <article v-for="source in provenance.sources" :key="source.key" class="source-card">
            <div class="source-top">
              <strong>{{ source.label }}</strong>
              <span class="source-version">{{ formatVersion(source.version) }}</span>
            </div>
            <p class="source-id">{{ source.logicalId }}</p>
            <p class="muted source-row">Row: {{ source.rowId || "bundle-local reference" }}</p>
            <p class="source-digest">{{ source.digest }}</p>
          </article>
        </div>
        <p v-else class="empty">This bundle only contains base chapter and scene references right now.</p>
      </section>

      <section class="provenance-section">
        <div class="provenance-label">Injection order</div>
        <ol class="injection-list">
          <li
            v-for="(injection, index) in provenance.injections"
            :key="`${injection.slot}-${injection.refId}-${index}`"
            class="injection-item"
          >
            <div class="injection-top">
              <span class="injection-index">{{ String(index + 1).padStart(2, "0") }}</span>
              <div>
                <strong>{{ injection.slotLabel }}</strong>
                <p class="muted injection-ref">{{ injection.refId }}</p>
              </div>
            </div>
            <p class="injection-digest">{{ injection.digest }}</p>
          </li>
        </ol>
      </section>
    </div>
  </article>
</template>
