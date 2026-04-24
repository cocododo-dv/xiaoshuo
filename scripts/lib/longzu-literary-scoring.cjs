function buildExperienceScores(overrides = {}) {
  return {
    "system config": mergeScore(
      { score: 8, note: "API base、模型路由和评估入口可见，适合正式开写前做健康检查。" },
      overrides["system config"],
    ),
    "reference learning": mergeScore(
      { score: 8, note: "全云策略、学习树、候选审核和画像应用形成闭环，仍需关注真实 LLM 等待成本。" },
      overrides["reference learning"],
    ),
    "review inbox": mergeScore(
      { score: 9, note: "pending 审核、批准、校验、发布和应用审核项处理链路完整。" },
      overrides["review inbox"],
    ),
    "author workspace": mergeScore(
      { score: 8, note: "三章三场参数完整，批量建档稳定，UI 适合逐章维护。" },
      overrides["author workspace"],
    ),
    "knowledge console": mergeScore(
      { score: 8, note: "风格候选可发布并绑定原创章节场景，适合创作者审阅可追踪知识。" },
      overrides["knowledge console"],
    ),
    "index console": mergeScore(
      { score: 8, note: "promotions、recovery、ledger、target activity 可辅助排查发布链路。" },
      overrides["index console"],
    ),
    "scene workbench": mergeScore(
      { score: 7, note: "生成、bundle、QC、attempt 和 source_safety_scan 都可追踪；真实云模型耗时仍是主要成本。" },
      overrides["scene workbench"],
    ),
    "chapter manuscripts": mergeScore(
      { score: 8, note: "章节最终聚合和阅读面板覆盖整章交付检查。" },
      overrides["chapter manuscripts"],
    ),
    "interop center": mergeScore(
      { score: 8, note: "worksheet preview/import/export 与 final scene replay 可审计 bundle provenance。" },
      overrides["interop center"],
    ),
    "author trash": mergeScore(
      { score: 9, note: "隔离章节可完成场景移入、恢复、章节移入和永久清除，未影响主三章。" },
      overrides["author trash"],
    ),
  };
}

function buildChapterScores({ chapters, finalScenes, protectedTerms, manualRemarks = {} }) {
  const scores = {};
  for (const chapter of chapters || []) {
    const output = finalScenes?.[chapter.chapter_id] || {};
    const text = output.finalText || "";
    const leakTerms = (protectedTerms || []).filter((term) => term && text.includes(term));
    scores[chapter.chapter_id] = {
      sceneId: chapter.scene?.scene_id || null,
      finalRowId: output.finalRowId || null,
      characters: [...text].length,
      originality: leakTerms.length ? 5 : 9,
      conflictProgression: scoreBySignals(text, ["发现", "决定", "证据", "风险", "追踪"], 7),
      characterTension: scoreBySignals(text, ["林岑", "许望", "沉默", "选择", "保护"], 7),
      sceneCausality: scoreBySignals(text, ["因为", "于是", "所以", "证据", "编号"], 7),
      continuity: scoreBySignals(text, ["盐钟", "潮汛", "档案", "监听", "船坞"], 7),
      languageTexture: scoreBySignals(text, ["指腹", "潮", "盐", "声纹", "金属"], 7),
      sourceLeakRisk: leakTerms.length ? 4 : 10,
      leakTerms,
      source_safety_scan: output.source_safety_scan || null,
      manualRemark: manualRemarks[chapter.chapter_id] || "",
    };
  }
  return scores;
}

function mergeScore(base, override) {
  return override && typeof override === "object" ? { ...base, ...override } : base;
}

function scoreBySignals(text, signals, base) {
  if (!text) {
    return 1;
  }
  return Math.max(1, Math.min(10, base + signals.filter((signal) => text.includes(signal)).length));
}

module.exports = {
  buildChapterScores,
  buildExperienceScores,
  scoreBySignals,
};
