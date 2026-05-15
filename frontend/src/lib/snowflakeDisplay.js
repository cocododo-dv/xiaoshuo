const FIELD_LABELS = {
  category: "类型",
  target_reader: "目标读者",
  story_kind: "故事类型",
  delight_reason: "读者沉迷原因",
  genre_promise: "类型承诺",
  expected_reader_emotion: "期待读者情绪",
  summary: "概括",
  sentences: "五句骨架",
  three_act_check: "三幕校验",
  moral_premise: "主题前提",
  paragraphs: "段落梗概",
  characters: "角色",
  scenes: "场景",
  scene_crucible: "坩埚",
  crucible: "坩埚",
  goal: "目标",
  conflict: "冲突",
  setback: "挫折",
  reaction: "反应",
  dilemma: "困境",
  decision: "决定",
  exit_change: "离场变化",
  hook: "钩子",
  target_length_band: "目标篇幅",
  pov_character_id: "视角角色",
  primary_form: "场景主形态",
  scene_type: "场景类型",
};

const DIAGNOSTIC_LABELS = {
  reader_promise_too_generic: "读者承诺过于宽泛",
  story_pressure_too_generic: "故事压力过于宽泛",
  reader_emotion_missing: "读者情绪缺失",
  logline_lacks_pressure_turn: "一句话缺少压力转折",
  five_sentence_spine_incomplete: "五句骨架不完整",
  disaster_chain_too_soft: "灾难链压力不足",
  character_pressure_missing: "角色压力缺失",
  synopsis_missing: "梗概缺失",
  synopsis_lacks_escalation: "梗概缺少升级",
  scene_list_missing: "场景列表缺失",
  scene_jobs_too_generic: "场景职责过于宽泛",
  missing_scenes: "缺少场景",
  scene_core_empty: "场景核心为空",
  weak_crucible_pressure: "坩埚压力不足",
  weak_goal_specificity: "目标不够具体",
  weak_conflict_escalation: "冲突升级不足",
  weak_setback_cost: "挫折代价不足",
  weak_reaction_specificity: "反应不够具体",
  fake_dilemma: "困境不是真两难",
  weak_decision_next_goal: "决定没有引出下一目标",
  decision_missing_next_goal: "决定没有引出下一目标",
};

const STEP_LABELS = {
  book_brief: "读者定位",
  one_sentence_summary: "一句话概括",
  one_paragraph_summary: "一段话概括",
  character_sheets: "角色摘要表",
  short_synopsis: "一页梗概",
  character_synopses: "角色背景故事",
  long_synopsis: "长篇大纲",
  character_bibles: "角色全档案",
  scene_list: "场景列表",
  scene_details: "场景规划",
};

const ARTIFACT_STATUS_LABELS = {
  draft: "草稿",
  pending_review: "待确认",
  approved: "已确认",
  stale: "需复核",
  skipped: "已跳过",
};

export function fieldLabel(value) {
  const key = String(value || "");
  return FIELD_LABELS[key] || key;
}

export function diagnosticLabel(value) {
  const key = String(value || "");
  if (!key) {
    return "";
  }
  if (DIAGNOSTIC_LABELS[key]) {
    return DIAGNOSTIC_LABELS[key];
  }
  if (key.startsWith("missing_")) {
    return `缺少${fieldLabel(key.replace(/^missing_/, ""))}`;
  }
  return key;
}

export function sourceLabel(value) {
  const key = String(value || "").toLowerCase();
  if (!key || key === "fallback") {
    return "离线演示内容";
  }
  if (key === "llm") {
    return "模型建议";
  }
  return key || "本地建议";
}

export function sceneFormLabel(value) {
  return String(value || "").toLowerCase() === "reactive" ? "反应场景" : "主动场景";
}

export function stepKeyLabel(value) {
  const key = String(value || "");
  return STEP_LABELS[key] || key;
}

export function artifactStatusLabel(value) {
  const key = String(value || "draft");
  return ARTIFACT_STATUS_LABELS[key] || key;
}

export function patchKeyListLabel(value) {
  const keys = value && typeof value === "object" && !Array.isArray(value) ? Object.keys(value) : [];
  return keys.map(fieldLabel).filter(Boolean).join("、");
}
