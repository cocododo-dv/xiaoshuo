const SOURCE_DEFINITIONS = [
  {
    key: "voice_profile",
    label: "Voice profile",
    collection: "source_version_refs",
    logicalIdKey: "voice_profile_id",
    rowIdKey: "voice_profile_row_id",
    versionKey: "voice_profile_version",
    digestKey: "voice_card",
  },
  {
    key: "relation_profile",
    label: "Relation profile",
    collection: "source_version_refs",
    logicalIdKey: "relation_profile_id",
    rowIdKey: "relation_profile_row_id",
    versionKey: "relation_profile_version",
    digestKey: "relation_card",
  },
  {
    key: "scene_memory_prev",
    label: "Previous scene memory",
    collection: "source_version_refs",
    logicalIdKey: "scene_memory_prev",
    rowIdKey: null,
    versionKey: null,
    digestKey: "scene_memory",
  },
  {
    key: "style_rule",
    label: "Style rule set",
    collection: "source_version_refs",
    logicalIdKey: "style_rule_set_id",
    rowIdKey: null,
    versionKey: null,
    digestKey: "style_rule",
  },
  {
    key: "banned_rule",
    label: "Banned rule cluster",
    collection: "source_version_refs",
    logicalIdKey: "banned_cluster_id",
    rowIdKey: null,
    versionKey: null,
    digestKey: "banned_rule",
  },
  {
    key: "calibration_line",
    label: "Calibration line",
    collection: "source_version_refs",
    logicalIdKey: "calibration_line_ids",
    rowIdKey: null,
    versionKey: null,
    digestKey: "calibration_line",
    multiple: true,
  },
  {
    key: "scene_summary",
    label: "Scene summary",
    collection: "source_version_refs",
    logicalIdKey: "scene_summary_id",
    rowIdKey: null,
    versionKey: null,
    digestKey: "scene_summary",
  },
  {
    key: "chapter_summary",
    label: "Chapter summary",
    collection: "source_version_refs",
    logicalIdKey: "chapter_summary_id",
    rowIdKey: null,
    versionKey: null,
    digestKey: "chapter_summary",
  },
  {
    key: "world_rule",
    label: "World rule",
    collection: "resolved_ref_ids",
    logicalIdKey: "world_rule_ids",
    rowIdKey: null,
    versionKey: null,
    digestKey: "world_rule",
    multiple: true,
  },
  {
    key: "foreshadow",
    label: "Open foreshadow",
    collection: "resolved_ref_ids",
    logicalIdKey: "open_foreshadow_ids",
    rowIdKey: null,
    versionKey: null,
    digestKey: "foreshadow",
    multiple: true,
  },
];

const SLOT_LABELS = {
  chapter_goal: "Chapter goal",
  scene_card: "Scene card",
  pov_voice: "POV voice",
  relation: "Relation",
  prev_scene_memory: "Previous scene memory",
  style_rules: "Style rules",
  banned_rules: "Banned rules",
  calibration_lines: "Calibration lines",
  world_rules: "World rules",
  foreshadow: "Foreshadow",
  scene_summary: "Scene summary",
  chapter_summary: "Chapter summary",
};

export function buildBundleProvenance(snapshot) {
  if (!snapshot) {
    return {
      available: false,
      sources: [],
      injections: [],
    };
  }

  const sourceVersionRefs = snapshot.source_version_refs || {};
  const resolvedRefIds = snapshot.resolved_ref_ids || {};
  const inlineDigests = snapshot.inline_digests || {};
  const orderedInjections = snapshot.ordered_injections || [];

  const sources = SOURCE_DEFINITIONS.flatMap((definition) => {
    const collection = definition.collection === "resolved_ref_ids" ? resolvedRefIds : sourceVersionRefs;
    const rawLogicalId = collection[definition.logicalIdKey];
    if (!rawLogicalId || (Array.isArray(rawLogicalId) && !rawLogicalId.length)) {
      return [];
    }

    const logicalIds = Array.isArray(rawLogicalId) ? rawLogicalId : [rawLogicalId];

    return logicalIds.map((logicalId) => ({
      key: definition.key,
      label: definition.label,
      logicalId,
      rowId: definition.rowIdKey ? sourceVersionRefs[definition.rowIdKey] ?? null : null,
      version: definition.versionKey ? sourceVersionRefs[definition.versionKey] ?? null : null,
      digest: inlineDigests[definition.digestKey] ?? "-",
    }));
  });

  const injections = orderedInjections.map((entry) => ({
    slot: entry.slot,
    slotLabel: SLOT_LABELS[entry.slot] || entry.slot,
    refId: entry.ref_id,
    digestKey: entry.digest_key,
    digest: inlineDigests[entry.digest_key] ?? "-",
  }));

  return {
    available: sources.length > 0 || injections.length > 0,
    sources,
    injections,
  };
}
