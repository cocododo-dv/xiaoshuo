const SOURCE_DEFINITIONS = [
  {
    key: "voice_profile",
    label: "声线档案",
    collection: "source_version_refs",
    logicalIdKey: "voice_profile_id",
    rowIdKey: "voice_profile_row_id",
    versionKey: "voice_profile_version",
    digestKey: "voice_card",
  },
  {
    key: "relation_profile",
    label: "关系档案",
    collection: "source_version_refs",
    logicalIdKey: "relation_profile_id",
    rowIdKey: "relation_profile_row_id",
    versionKey: "relation_profile_version",
    digestKey: "relation_card",
  },
  {
    key: "scene_memory_prev",
    label: "上一场景记忆",
    collection: "source_version_refs",
    logicalIdKey: "scene_memory_prev",
    rowIdKey: null,
    versionKey: null,
    digestKey: "scene_memory",
  },
  {
    key: "style_rule",
    label: "风格规则集",
    collection: "source_version_refs",
    logicalIdKey: "style_rule_set_id",
    rowIdKey: null,
    versionKey: null,
    digestKey: "style_rule",
  },
  {
    key: "style_profile",
    label: "风格画像契约",
    collection: "source_version_refs",
    logicalIdKey: "style_profile_contract",
    rowIdKey: null,
    versionKey: null,
    digestKey: "style_profile",
  },
  {
    key: "banned_rule",
    label: "禁忌规则簇",
    collection: "source_version_refs",
    logicalIdKey: "banned_cluster_id",
    rowIdKey: null,
    versionKey: null,
    digestKey: "banned_rule",
  },
  {
    key: "calibration_line",
    label: "校准句",
    collection: "source_version_refs",
    logicalIdKey: "calibration_line_ids",
    rowIdKey: null,
    versionKey: null,
    digestKey: "calibration_line",
    multiple: true,
  },
  {
    key: "narrative_pattern",
    label: "叙事结构",
    collection: "source_version_refs",
    logicalIdKey: "narrative_pattern_ids",
    rowIdKey: null,
    versionKey: null,
    digestKey: "narrative_pattern",
    multiple: true,
  },
  {
    key: "scene_summary",
    label: "场景摘要",
    collection: "source_version_refs",
    logicalIdKey: "scene_summary_id",
    rowIdKey: null,
    versionKey: null,
    digestKey: "scene_summary",
  },
  {
    key: "chapter_summary",
    label: "章节摘要",
    collection: "source_version_refs",
    logicalIdKey: "chapter_summary_id",
    rowIdKey: null,
    versionKey: null,
    digestKey: "chapter_summary",
  },
  {
    key: "world_rule",
    label: "世界规则",
    collection: "resolved_ref_ids",
    logicalIdKey: "world_rule_ids",
    rowIdKey: null,
    versionKey: null,
    digestKey: "world_rule",
    multiple: true,
  },
  {
    key: "foreshadow",
    label: "开放伏笔",
    collection: "resolved_ref_ids",
    logicalIdKey: "open_foreshadow_ids",
    rowIdKey: null,
    versionKey: null,
    digestKey: "foreshadow",
    multiple: true,
  },
];

const SLOT_LABELS = {
  chapter_goal: "章节目标",
  scene_card: "场景卡片",
  pov_voice: "视角声线",
  relation: "关系设定",
  prev_scene_memory: "上一场景记忆",
  style_rules: "风格规则",
  style_profile: "风格画像契约",
  banned_rules: "禁忌规则",
  calibration_lines: "校准句",
  narrative_patterns: "叙事结构",
  world_rules: "世界规则",
  foreshadow: "伏笔",
  scene_summary: "场景摘要",
  chapter_summary: "章节摘要",
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
  const styleProfile = parseStyleProfileDigest(
    inlineDigests.style_profile,
    sourceVersionRefs.style_profile_contract,
  );

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
    ...(styleProfile ? { styleProfile } : {}),
  };
}

function parseStyleProfileDigest(rawDigest, contractFallback = null) {
  if (typeof rawDigest !== "string" || !rawDigest.trim()) {
    return null;
  }

  let payload;
  try {
    payload = JSON.parse(rawDigest);
  } catch {
    return {
      contractVersion: contractFallback || null,
      featureRows: [],
      calibrationLines: [],
      bannedMoves: [],
      raw: rawDigest,
    };
  }

  const features = payload?.features && typeof payload.features === "object" ? payload.features : {};
  const featureRows = Object.entries(features)
    .map(([name, feature]) => ({
      name,
      guidance: normalizeTextList(feature?.guidance ?? feature),
    }))
    .filter((item) => item.guidance.length);

  return {
    contractVersion: payload.contract_version || contractFallback || null,
    featureRows,
    calibrationLines: normalizeTextList(payload.calibration_lines),
    bannedMoves: normalizeTextList(payload.banned_moves),
    raw: rawDigest,
  };
}

function normalizeTextList(value) {
  if (typeof value === "string" && value.trim()) {
    return [value.trim()];
  }
  if (!Array.isArray(value)) {
    return [];
  }
  return value.filter((item) => typeof item === "string" && item.trim()).map((item) => item.trim());
}
