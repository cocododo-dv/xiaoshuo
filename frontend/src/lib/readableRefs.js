const OBJECT_TYPE_LABELS = {
  calibration_line: "校准句",
  style_rule: "风格规则",
  style_observation: "风格观察",
  narrative_pattern: "叙事结构",
  banned_rule_cluster: "禁忌规则簇",
  voice_card: "声线卡",
  relation_card: "关系卡",
  world_rule: "世界规则",
  review_item: "审核",
  human_review_event: "人工审核事件",
  verify_job: "校验任务",
  reindex_job: "重建任务",
  scene_card: "场景",
  knowledge_entry: "知识",
};

const SCOPE_LABELS = {
  global: "全局",
  chapter: "章节",
  scene: "场景",
};

function labelForObjectType(value) {
  return OBJECT_TYPE_LABELS[value] || value || "-";
}

function labelForScope(value) {
  return SCOPE_LABELS[value] || value || "-";
}

export function formatReadableTargetRef(targetRef) {
  const raw = String(targetRef || "").trim();
  if (!raw) {
    return { label: "-", raw: "" };
  }

  const [objectType, scope, ...rest] = raw.split(":");
  const typeLabel = labelForObjectType(objectType);
  if (scope && rest.length) {
    return {
      label: `${typeLabel} / ${labelForScope(scope)} / ${labelForScope(rest.join(":"))}`,
      raw,
    };
  }
  if (scope) {
    return {
      label: `${typeLabel} / ${labelForScope(scope)}`,
      raw,
    };
  }
  return { label: typeLabel || raw, raw };
}
