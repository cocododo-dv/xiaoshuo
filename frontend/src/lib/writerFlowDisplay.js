const BODY_EMPTY_REASON_LABELS = {
  no_generated_scenes: "还没有场景完成生成",
  manuscript_body_empty: "正文汇总为空，请检查运行状态",
};

const COMPLETION_STATUS_LABELS = {
  complete: "全部场景已完成",
  partial: "部分场景已完成",
  empty: "还没有可审阅正文",
  pending: "等待起草",
};

const NEXT_ACTION_LABELS = {
  run_current_chapter: "可以开始起草当前章",
  view_chapter_progress: "正在起草，请查看进度",
  approve_chapter_final: "请审阅并批准本章",
  resolve_blocker: "需要先处理阻塞项",
  resolve_backtrack_items: "需要先处理返工项",
  completed: "项目主线已完成",
};

const RUN_STATUS_LABELS = {
  idle: "等待开始起草",
  queued: "已排队，等待后台起草",
  running: "后台正在起草",
  blocked: "起草被阻塞，需要处理",
  failed: "起草失败，需要查看原因",
  completed: "本章起草已完成",
};

const ERROR_MESSAGE_LABELS = [
  [/pending replanning work/i, "有返工项待处理，处理后才能继续起草。"],
  [/human review/i, "有场景需要人工处理后才能继续。"],
  [/manual hold/i, "本章被人工挂起，解除后才能继续。"],
  [/did not produce a final scene/i, "当前场景没有生成可审阅正文。"],
  [/llm disabled/i, "当前未启用真实模型，不能生成正式正文。"],
];

export function runStatusLabel(status, nextAction = "") {
  const normalized = String(status || "").trim();
  if (RUN_STATUS_LABELS[normalized]) {
    return RUN_STATUS_LABELS[normalized];
  }
  return nextActionLabel(nextAction);
}

export function nextActionLabel(action) {
  return NEXT_ACTION_LABELS[String(action || "").trim()] || "等待下一步";
}

export function bodyEmptyReasonLabel(reason) {
  return BODY_EMPTY_REASON_LABELS[String(reason || "").trim()] || "章节起草完成后会在这里显示正文。";
}

export function completionStatusLabel(status) {
  return COMPLETION_STATUS_LABELS[String(status || "").trim()] || "等待起草";
}

export function bodySourceLabel(source) {
  const normalized = String(source || "").trim().toLowerCase();
  if (normalized === "fallback") {
    return "离线演示正文";
  }
  if (normalized === "aggregate") {
    return "终稿汇总正文";
  }
  if (normalized === "assembled") {
    return "场景汇总正文";
  }
  return "";
}

export function sceneDisplayLabel(chapter, sceneId) {
  const normalizedSceneId = String(sceneId || "").trim();
  const scenes = Array.isArray(chapter?.scenes) ? chapter.scenes : [];
  const index = scenes.findIndex((scene) => String(scene?.scene_id || "") === normalizedSceneId);
  if (index !== -1) {
    const scene = scenes[index];
    const seq = scene.scene_seq || index + 1;
    const title = String(scene.title || scene.scene_goal || scene.hook || scene.scene_id || "").trim();
    return title ? `第 ${seq} 场：${title}` : `第 ${seq} 场`;
  }
  if (normalizedSceneId) {
    return `当前场景：${normalizedSceneId}`;
  }
  if (chapter?.chapter_goal) {
    return "本章整体";
  }
  return "-";
}

export function chapterListLabel(chapter, index = 0) {
  const seq = Number.isFinite(Number(chapter?.chapter_seq)) && Number(chapter?.chapter_seq) > 0
    ? Number(chapter.chapter_seq)
    : Number(index) + 1;
  return `第 ${seq} 章`;
}

export function latestErrorLabel(error) {
  const message = typeof error === "string" ? error : String(error?.message || "");
  for (const [pattern, label] of ERROR_MESSAGE_LABELS) {
    if (pattern.test(message)) {
      return label;
    }
  }
  return message || "";
}

export function backtrackScopeLabel(item) {
  const scope = String(item?.scope || "").toLowerCase();
  if (scope === "project") {
    return "全项目";
  }
  if (scope === "chapter") {
    return item?.chapter_id ? `章节 ${item.chapter_id}` : "章节";
  }
  if (scope === "scene") {
    return item?.scene_id ? `场景 ${item.scene_id}` : "场景";
  }
  if (scope === "character") {
    return "角色线";
  }
  if (scope === "scene_list") {
    return "场景规划";
  }
  return "影响范围待确认";
}

export function targetWordCountLabel(band) {
  if (!band || typeof band !== "object") {
    return "";
  }
  if (band.label) {
    return band.label;
  }
  if (band.min && band.max) {
    return `${band.min}-${band.max} 字`;
  }
  return "";
}

export function missingSceneLabels(packet) {
  if (Array.isArray(packet?.missing_scene_labels) && packet.missing_scene_labels.length) {
    return packet.missing_scene_labels;
  }
  const missingIds = new Set((packet?.missing_scene_ids || []).map((item) => String(item || "")).filter(Boolean));
  const reviews = Array.isArray(packet?.scene_reviews) ? packet.scene_reviews : [];
  reviews.forEach((review) => {
    if (review?.missing && review?.scene_id) {
      missingIds.add(String(review.scene_id));
    }
  });
  return [...missingIds].map((sceneId) => {
    const review = reviews.find((item) => String(item?.scene_id || "") === sceneId);
    if (!review) {
      return sceneId;
    }
    const seq = review.scene_seq || "";
    const title = review.title || sceneId;
    return seq ? `第 ${seq} 场：${title}` : title;
  });
}
