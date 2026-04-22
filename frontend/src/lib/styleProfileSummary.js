const FEATURE_LABELS = {
  rhythm: "节奏",
  syntax: "句法",
  imagery: "意象",
  narrative_distance: "叙事距离",
  emotion_curve: "情绪曲线",
  paragraph_density: "段落密度",
  dialogue_ratio: "对白比例",
};

const FEATURE_ORDER = [
  "rhythm",
  "syntax",
  "imagery",
  "narrative_distance",
  "emotion_curve",
  "paragraph_density",
  "dialogue_ratio",
];

const REVIEW_SOURCE_LABELS = {
  style_profile_extract: "样本文本提取",
  manual: "人工录入",
  knowledge_console: "知识控制台",
};

const TARGET_COLLECTION_LABELS = {
  style_rules: "风格规则",
  style_observations: "风格观察",
  calibration_lines: "校准句",
  banned_rule_clusters: "禁用规则",
  voice_cards: "角色声线",
  relation_cards: "关系卡",
  world_rules: "世界规则",
  foreshadow_tracker: "伏笔",
  scene_memories: "场景记忆",
  chapter_memories: "章节记忆",
};

function asTextList(value) {
  if (typeof value === "string" && value.trim()) {
    return [value.trim()];
  }
  if (!Array.isArray(value)) {
    return [];
  }
  return value.filter((item) => typeof item === "string" && item.trim()).map((item) => item.trim());
}

function normalizeFeatureGuidance(featurePayload) {
  if (!featurePayload) {
    return [];
  }
  if (Array.isArray(featurePayload) || typeof featurePayload === "string") {
    return asTextList(featurePayload);
  }
  return asTextList(featurePayload.guidance);
}

function profileFromCandidatePayload(payload) {
  if (!payload || typeof payload !== "object") {
    return null;
  }
  if (payload.style_profile && typeof payload.style_profile === "object") {
    return payload.style_profile;
  }
  return null;
}

function profileFromVersion(version) {
  if (!version || typeof version !== "object") {
    return null;
  }
  if (version.style_profile && typeof version.style_profile === "object") {
    return version.style_profile;
  }
  return null;
}

function valuePresent(value) {
  return typeof value === "string" && value.trim();
}

function compactText(parts) {
  return parts.filter(valuePresent).join(" · ");
}

function isActiveOnApprove(value) {
  return value === 1 || value === true || value === "1";
}

function listsEqual(left, right) {
  if (left.length !== right.length) {
    return false;
  }
  return left.every((item, index) => item === right[index]);
}

function diffStatusFor(before, after) {
  if (!before.length && after.length) {
    return "added";
  }
  if (before.length && !after.length) {
    return "removed";
  }
  if (before.length && after.length && !listsEqual(before, after)) {
    return "changed";
  }
  return "";
}

function runtimeImpactForReview(item) {
  const releaseState = item?.release_state && typeof item.release_state === "object" ? item.release_state : null;
  if (item?.status === "released" || releaseState?.state === "active") {
    return {
      runtimeLabel: "已进入运行时",
      runtimeDetail: releaseState?.message || "发布完成，后续 bundle 构建会读取该版本。",
    };
  }

  if (releaseState?.state === "blocked") {
    return {
      runtimeLabel: releaseState.blocked_reason === "not_verified" ? "需先完成校验" : "暂不可发布",
      runtimeDetail: releaseState.message || "候选尚未满足发布条件。",
    };
  }

  if (item?.status === "approved" && item?.materialize_status === "succeeded" && !isActiveOnApprove(item.active_on_approve)) {
    return {
      runtimeLabel: "可发布到运行时",
      runtimeDetail: "候选已物化，点击发布后会替换运行时版本。",
    };
  }

  if (isActiveOnApprove(item?.active_on_approve)) {
    return {
      runtimeLabel: "批准后进入运行时",
      runtimeDetail: "批准会物化并发布为当前版本，后续 bundle 构建会读取。",
    };
  }

  return {
    runtimeLabel: "需发布后进入运行时",
    runtimeDetail: "批准会先物化候选，发布后才替换运行时版本。",
  };
}

export function buildStyleProfileSummary(profile, options = {}) {
  if (!profile || typeof profile !== "object") {
    return {
      available: false,
      contractVersion: "",
      featureRows: [],
      calibrationLines: [],
      bannedMoves: [],
      source: options.source || "",
    };
  }

  const features = profile.features && typeof profile.features === "object" ? profile.features : {};
  const featureRows = FEATURE_ORDER.map((key) => ({
    key,
    label: FEATURE_LABELS[key] || key,
    guidance: normalizeFeatureGuidance(features[key]),
  })).filter((row) => row.guidance.length);

  return {
    available: Boolean(profile.contract_version || featureRows.length),
    contractVersion: profile.contract_version || "",
    featureRows,
    calibrationLines: asTextList(profile.calibration_lines),
    bannedMoves: asTextList(profile.banned_moves),
    source: options.source || "",
  };
}

export function buildReviewImpactSummary(item) {
  const payload = item?.candidate_payload_json && typeof item.candidate_payload_json === "object"
    ? item.candidate_payload_json
    : {};
  const source = payload.source || "";
  const contractVersion = payload.contract_version || payload.style_profile?.contract_version || "";
  const lineageKey = payload.lineage_key || "";
  const scopeDetail = compactText([payload.scope, payload.scope_ref_id]);
  const targetCollection = item?.target_collection || "";
  const targetLabel = TARGET_COLLECTION_LABELS[targetCollection] || item?.item_type || targetCollection || "候选知识";
  const targetDetail = compactText([
    lineageKey ? `替换同血缘：${lineageKey}` : "",
    scopeDetail ? `作用域：${scopeDetail}` : "",
  ]);
  const runtimeImpact = runtimeImpactForReview(item);
  const sourceLabel = REVIEW_SOURCE_LABELS[source] || source || "审核候选";
  const sourceDetail = compactText([
    source && !REVIEW_SOURCE_LABELS[source] ? source : "",
    contractVersion,
  ]);

  return {
    available: Boolean(source || contractVersion || lineageKey || targetCollection || item?.item_type),
    sourceLabel,
    sourceDetail,
    targetLabel,
    targetDetail,
    ...runtimeImpact,
  };
}

export function buildStyleProfileDiffSummary(activeProfile, candidateProfile) {
  if (!candidateProfile || typeof candidateProfile !== "object") {
    return {
      available: false,
      baselineLabel: "",
      rows: [],
      counts: { added: 0, changed: 0, removed: 0 },
    };
  }

  const activeFeatures = activeProfile?.features && typeof activeProfile.features === "object"
    ? activeProfile.features
    : {};
  const candidateFeatures = candidateProfile.features && typeof candidateProfile.features === "object"
    ? candidateProfile.features
    : {};
  const rows = FEATURE_ORDER.map((key) => {
    const before = normalizeFeatureGuidance(activeFeatures[key]);
    const after = normalizeFeatureGuidance(candidateFeatures[key]);
    const status = diffStatusFor(before, after);
    return status
      ? {
          key,
          label: FEATURE_LABELS[key] || key,
          status,
          before,
          after,
        }
      : null;
  }).filter(Boolean);
  const counts = rows.reduce(
    (acc, row) => {
      acc[row.status] += 1;
      return acc;
    },
    { added: 0, changed: 0, removed: 0 },
  );

  return {
    available: rows.length > 0,
    baselineLabel: activeProfile ? "对比当前生效画像" : "当前无生效画像",
    rows,
    counts,
  };
}

export function buildStyleProfileRiskSummary(diffSummary) {
  if (!diffSummary?.available) {
    return {
      available: false,
      severity: "",
      title: "",
      reasons: [],
      actionHint: "",
    };
  }

  const counts = diffSummary.counts || { added: 0, changed: 0, removed: 0 };
  const total = (counts.added || 0) + (counts.changed || 0) + (counts.removed || 0);
  if ((counts.removed || 0) > 0) {
    return {
      available: true,
      severity: "high",
      title: "高风险风格替换",
      reasons: [`移除了 ${counts.removed} 个已生效风格维度。`],
      actionHint: "批准前请确认这些维度不再需要，或先补充替代规则。",
    };
  }

  if (total >= 3 || (counts.changed || 0) >= 2) {
    return {
      available: true,
      severity: "medium",
      title: "大范围风格调整",
      reasons: [`一次改变 ${total} 个风格维度。`],
      actionHint: "批准前请确认这是一轮有意的画像重写，而不是样本偏差。",
    };
  }

  return {
    available: false,
    severity: "",
    title: "",
    reasons: [],
    actionHint: "",
  };
}

export function styleProfileSummaryFromReviewItem(item) {
  const profile = profileFromCandidatePayload(item?.candidate_payload_json);
  return buildStyleProfileSummary(profile, { source: "review_item" });
}

export function styleProfileSummaryFromKnowledgeDetail(detail) {
  const candidateProfile = detail?.candidate_version?.style_profile;
  if (candidateProfile) {
    return buildStyleProfileSummary(candidateProfile, { source: "candidate_version" });
  }

  const review = (detail?.workflow?.review_items || []).find((item) =>
    profileFromCandidatePayload(item?.candidate_payload_json),
  );
  return buildStyleProfileSummary(profileFromCandidatePayload(review?.candidate_payload_json), {
    source: review ? "workflow_review" : "",
  });
}

export function styleProfileDiffFromKnowledgeDetail(detail) {
  const candidateProfile = profileFromVersion(detail?.candidate_version);
  if (!candidateProfile) {
    return buildStyleProfileDiffSummary(null, null);
  }
  return buildStyleProfileDiffSummary(profileFromVersion(detail?.active_version), candidateProfile);
}

export function styleProfileDiffFromReviewItem(item) {
  const candidateProfile = profileFromCandidatePayload(item?.candidate_payload_json);
  if (!candidateProfile) {
    return buildStyleProfileDiffSummary(null, null);
  }
  return buildStyleProfileDiffSummary(item?.style_profile_baseline || null, candidateProfile);
}

export function styleProfileRiskFromKnowledgeDetail(detail) {
  return buildStyleProfileRiskSummary(styleProfileDiffFromKnowledgeDetail(detail));
}

export function styleProfileRiskFromReviewItem(item) {
  return buildStyleProfileRiskSummary(styleProfileDiffFromReviewItem(item));
}
