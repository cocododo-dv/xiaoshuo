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
  return version == null ? "引用" : `v${version}`;
}
</script>

<template>
  <article class="paper provenance-card">
    <div class="provenance-head">
      <div>
        <h3>构包溯源</h3>
        <p class="muted provenance-copy">
          追踪哪些源数据行参与了构包，以及它们进入场景运行时的精确顺序。
        </p>
      </div>
      <span v-if="provenance.available" class="badge">快照已就绪</span>
    </div>

    <div v-if="!provenance.available" class="empty">先运行一次场景，才能捕获可追踪的构包快照。</div>
    <div v-else class="provenance-grid">
      <section class="provenance-section">
        <div class="provenance-label">可追踪来源</div>
        <div v-if="provenance.styleProfile" class="style-profile-panel" data-testid="bundle-style-profile-panel">
          <div class="receipt-head">
            <strong>风格画像契约</strong>
            <span class="badge">{{ provenance.styleProfile.contractVersion || "style_profile" }}</span>
          </div>
          <ol v-if="provenance.styleProfile.featureRows.length" class="style-score-list">
            <li v-for="feature in provenance.styleProfile.featureRows" :key="feature.name">
              <span>{{ feature.name }}</span>
              <small>{{ feature.guidance.join("; ") }}</small>
            </li>
          </ol>
          <p v-if="provenance.styleProfile.calibrationLines.length" class="muted">
            calibration: {{ provenance.styleProfile.calibrationLines.join("; ") }}
          </p>
          <p v-if="provenance.styleProfile.bannedMoves.length" class="muted">
            banned: {{ provenance.styleProfile.bannedMoves.join("; ") }}
          </p>
        </div>
        <div v-if="provenance.sources.length" class="source-stack">
          <article v-for="source in provenance.sources" :key="source.key" class="source-card">
            <div class="source-top">
              <strong>{{ source.label }}</strong>
              <span class="source-version">{{ formatVersion(source.version) }}</span>
            </div>
            <p class="source-id">{{ source.logicalId }}</p>
            <p class="muted source-row">数据行：{{ source.rowId || "构包内本地引用" }}</p>
            <p class="source-digest">{{ source.digest }}</p>
          </article>
        </div>
        <p v-else class="empty">当前这个构包里只有基础章节和场景引用。</p>
      </section>

      <section class="provenance-section">
        <div class="provenance-label">注入顺序</div>
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
