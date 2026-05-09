const OBJECT_TYPE_LABELS = {
  author_draft: "作者稿",
  author_draft_chapter: "章节作者稿",
  author_draft_scene: "场景作者稿",
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
  quality: "质量信号",
  chapter_promise: "章节承诺",
  reader_hook: "读者钩子",
  foreshadow: "伏笔",
};

const SCOPE_LABELS = {
  global: "全局",
  chapter: "章节",
  scene: "场景",
};

const TECHNICAL_PREFIX_LABELS = {
  author_draft: "作者稿",
  calibration_line: "校准句",
  chapter_promise: "章节承诺",
  quality: "质量信号",
  review: "审核",
  review_reffind: "参考审核",
  job: "任务",
  snapshot: "快照",
  embed: "向量",
};

function labelForObjectType(value) {
  return OBJECT_TYPE_LABELS[value] || value || "-";
}

function labelForScope(value) {
  return SCOPE_LABELS[value] || value || "-";
}

function normalizedText(value) {
  return String(value || "")
    .replace(/\s+/g, " ")
    .trim();
}

function compactDisplayText(value, maxLength = 28) {
  const text = normalizedText(value);
  if (!text || text.length <= maxLength) {
    return text;
  }
  return text.slice(0, maxLength);
}

function chapterHeadline(value) {
  const text = normalizedText(value);
  if (/^第.+章[：:]/.test(text)) {
    const [headline] = text.split(/[，,。]/u);
    if (headline && headline.length >= 8) {
      return headline;
    }
  }
  return text;
}

function entityTitle(item, keys = []) {
  if (typeof item === "string") {
    return "";
  }
  for (const key of keys) {
    const value = normalizedText(item?.[key]);
    if (value) {
      return value;
    }
  }
  return "";
}

function stripCurrentDbTimestamp(value) {
  return normalizedText(value)
    .replace(/CDBQA_\d{14}_/g, "CDBQA_RUN_")
    .replace(/\b20\d{12}\b/g, "RUN_TS");
}

function currentDbSortValue(value) {
  const raw = String(value || "");
  const match = raw.match(/CDBQA_(\d{14})/);
  if (match) {
    return Number(match[1]);
  }
  const generic = raw.match(/\b(20\d{12})\b/);
  return generic ? Number(generic[1]) : 0;
}

function chapterOrdinalFromId(raw) {
  const value = String(raw || "");
  const match = value.match(/(?:^|_)(\d{1,3})(?:$|_|SC\d+)/);
  if (!match) {
    return "";
  }
  return `第 ${Number(match[1])} 章`;
}

function sceneOrdinalFromId(raw) {
  const value = String(raw || "");
  const match = value.match(/SC(\d{1,3})$/i);
  if (!match) {
    return "场景";
  }
  return `场景 ${Number(match[1])}`;
}

export function shortTechnicalRef(value, maxLength = 36) {
  const raw = normalizedText(value);
  if (!raw || raw.length <= maxLength) {
    return raw;
  }
  const tailLength = Math.max(6, Math.floor(maxLength * 0.32));
  const headLength = Math.max(8, maxLength - tailLength - 3);
  return `${raw.slice(0, headLength)}...${raw.slice(-tailLength)}`;
}

export function formatChapterChoice(chapter) {
  const raw = typeof chapter === "string" ? chapter : chapter?.chapter_id || "";
  const title = chapterHeadline(entityTitle(chapter, ["chapter_title", "title", "chapter_goal", "goal"]));
  const ordinal = chapterOrdinalFromId(raw);
  const label = compactDisplayText(title || ordinal || raw || "未命名章节", 24);
  const technical = shortTechnicalRef(raw, 34);
  return {
    value: raw,
    label,
    detail: [ordinal, technical].filter(Boolean).join(" / "),
    raw,
    technical,
    groupKey: stripCurrentDbTimestamp(title || raw),
    sortValue: currentDbSortValue(raw),
  };
}

export function formatSceneChoice(scene) {
  const raw = typeof scene === "string" ? scene : scene?.scene_id || "";
  const title = entityTitle(scene, ["scene_title", "title", "scene_goal", "goal"]);
  const ordinal = sceneOrdinalFromId(raw);
  const label = compactDisplayText(title || ordinal || raw || "未命名场景", 28);
  const technical = shortTechnicalRef(raw, 34);
  return {
    value: raw,
    label,
    detail: [ordinal, technical].filter(Boolean).join(" / "),
    raw,
    technical,
    groupKey: stripCurrentDbTimestamp(title || raw),
    sortValue: currentDbSortValue(raw),
  };
}

export function compactEntityOptions(items = [], options = {}) {
  const {
    idKey = "id",
    titleKeys = [],
    selectedId = "",
    formatter = (item) => ({
      value: item?.[idKey] || "",
      label: entityTitle(item, titleKeys) || item?.[idKey] || "",
      raw: item?.[idKey] || "",
      groupKey: stripCurrentDbTimestamp(entityTitle(item, titleKeys) || item?.[idKey] || ""),
      sortValue: currentDbSortValue(item?.[idKey]),
    }),
  } = options;

  const groups = new Map();
  items.forEach((item, index) => {
    const formatted = formatter(item);
    const value = formatted.value || item?.[idKey] || "";
    const groupKey = formatted.groupKey || stripCurrentDbTimestamp(entityTitle(item, titleKeys) || value);
    const entry = {
      ...formatted,
      value,
      item,
      index,
      selected: value === selectedId,
      sortValue: formatted.sortValue || currentDbSortValue(value),
    };
    const group = groups.get(groupKey) || { index, entries: [] };
    group.entries.push(entry);
    groups.set(groupKey, group);
  });

  const output = [];
  let hiddenCount = 0;
  for (const group of groups.values()) {
    const latest = [...group.entries].sort((a, b) => b.sortValue - a.sortValue || b.index - a.index)[0];
    const selected = group.entries.find((entry) => entry.selected);
    if (selected && selected.value !== latest.value) {
      output.push(selected, latest);
      hiddenCount += Math.max(0, group.entries.length - 2);
    } else {
      output.push(selected || latest);
      hiddenCount += Math.max(0, group.entries.length - 1);
    }
  }

  return {
    options: output,
    hiddenCount,
    totalCount: items.length,
  };
}

export function formatReadableTargetRef(targetRef) {
  const raw = normalizedText(targetRef);
  if (!raw) {
    return { label: "-", raw: "", technical: "" };
  }

  const [objectType, scope, ...rest] = raw.split(":");
  const typeLabel = labelForObjectType(objectType);
  const technical = shortTechnicalRef(raw, 42);
  const prefixLabel = TECHNICAL_PREFIX_LABELS[objectType] || typeLabel;
  if (scope && rest.length) {
    return {
      label: `${prefixLabel} / ${labelForScope(scope)}`,
      detail: shortTechnicalRef(rest.join(":"), 32),
      raw,
      technical,
    };
  }
  if (scope) {
    return {
      label: `${prefixLabel} / ${labelForScope(scope)}`,
      detail: "",
      raw,
      technical,
    };
  }
  return { label: prefixLabel || raw, detail: "", raw, technical };
}

export function formatGuidedTargetRef(targetRef) {
  const readable = formatReadableTargetRef(targetRef);
  if (!readable.raw) {
    return readable;
  }

  const [objectType] = readable.raw.split(":", 1);
  const typeLabel = labelForObjectType(objectType);
  if (typeLabel && ["review_item", "human_review_event", "verify_job", "reindex_job"].includes(objectType)) {
    return { ...readable, label: typeLabel };
  }

  return readable;
}
