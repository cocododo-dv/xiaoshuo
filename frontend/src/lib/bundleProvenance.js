const SOURCE_DEFINITIONS = [
  {
    key: "voice_profile",
    label: "Voice profile",
    logicalIdKey: "voice_profile_id",
    rowIdKey: "voice_profile_row_id",
    versionKey: "voice_profile_version",
    digestKey: "voice_card",
  },
  {
    key: "relation_profile",
    label: "Relation profile",
    logicalIdKey: "relation_profile_id",
    rowIdKey: "relation_profile_row_id",
    versionKey: "relation_profile_version",
    digestKey: "relation_card",
  },
  {
    key: "scene_memory_prev",
    label: "Previous scene memory",
    logicalIdKey: "scene_memory_prev",
    rowIdKey: null,
    versionKey: null,
    digestKey: "scene_memory",
  },
];

const SLOT_LABELS = {
  chapter_goal: "Chapter goal",
  scene_card: "Scene card",
  pov_voice: "POV voice",
  relation: "Relation",
  prev_scene_memory: "Previous scene memory",
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
  const inlineDigests = snapshot.inline_digests || {};
  const orderedInjections = snapshot.ordered_injections || [];

  const sources = SOURCE_DEFINITIONS.flatMap((definition) => {
    const logicalId = sourceVersionRefs[definition.logicalIdKey];
    if (!logicalId) {
      return [];
    }

    return [
      {
        key: definition.key,
        label: definition.label,
        logicalId,
        rowId: definition.rowIdKey ? sourceVersionRefs[definition.rowIdKey] ?? null : null,
        version: definition.versionKey ? sourceVersionRefs[definition.versionKey] ?? null : null,
        digest: inlineDigests[definition.digestKey] ?? "-",
      },
    ];
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
