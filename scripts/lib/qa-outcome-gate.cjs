/* Wave 0 结果门禁的 JS 采集侧（结果闭环治理设计 v1.1 §8 Wave 0）。
 *
 * 唯一权威判定器是 scripts/playwright_audit_summary.py 的 --outcome-gate 模式
 * （backend/tests/test_playwright_audit_summary.py 全覆盖）。本模块只负责把
 * harness 采集到的每场结果组装成 outcome-gate-v1 结构并调用判定器、透传退出码，
 * 供 run-currentdb-three-chapter-qa.cjs 与 run-longzu-full-cloud-qa.cjs 共用，
 * 防止两个 harness 的结果节结构发散。
 *
 * 硬语义：判定器不可执行（python 缺失、脚本被移动等）时按失败处理——
 * 门禁未执行不得视为通过（设计 §11 禁止性规则 2）。
 */
const path = require("node:path");
const { execFileSync } = require("node:child_process");

const NORTHSTAR_PHASE_LIST = [
  "snowflake_planning",
  "materialization",
  "scene_execution",
  "candidate_selection",
  "archive",
  "chapter_aggregation",
];

function tokensFromOutput(job, output) {
  const candidates = [
    output?.generationSummary?.total_tokens,
    output?.generationSummary?.tokens?.total,
    output?.generationSummary?.usage?.total_tokens,
    job?.result_summary?.total_tokens,
    job?.result_summary?.tokens?.total,
  ];
  for (const value of candidates) {
    const num = Number(value);
    if (Number.isFinite(num) && num > 0) {
      return num;
    }
  }
  return null;
}

function buildOutcomeSection({ chapters, finalScenes, expectedChapterCount, expectedScenesPerChapter, northstarPhases }) {
  const plannedScenes = [];
  const sceneRecords = {};
  for (const chapter of chapters) {
    for (const scene of chapter.scenes) {
      plannedScenes.push({ chapter_id: chapter.chapter_id, scene_id: scene.scene_id });
      const output = finalScenes[scene.scene_id] || {};
      const finalChars = (output.finalText || "").length;
      sceneRecords[scene.scene_id] = {
        chapter_id: chapter.chapter_id,
        final_row_id: output.finalRowId || null,
        final_chars: finalChars,
        archived: output.sceneStatus === "archived" && Boolean(output.finalRowId) && finalChars > 0,
        scene_status: output.sceneStatus || "not_started",
        tokens: output.tokens ?? null,
        duration_ms: output.durationMs ?? null,
        attempts: output.attemptNo ?? 0,
        block_reason: output.blockReason || null,
        source_safety: output.source_safety_scan || null,
      };
    }
  }
  const phases = NORTHSTAR_PHASE_LIST.map(
    (phase) =>
      northstarPhases[phase] || {
        phase,
        lane: "missing",
        evidence: "本次运行未到达该阶段（提前失败或阶段未实现）。",
      },
  );
  return {
    schema: "outcome-gate-v1",
    expected: { chapters: expectedChapterCount, scenes_per_chapter: expectedScenesPerChapter },
    planned_scenes: plannedScenes,
    scenes: sceneRecords,
    northstar_phases: phases,
  };
}

function runOutcomeGate(ctx) {
  const { repoRoot, outDir, pythonExecutable, result, writeJson, appendLog } = ctx;
  result.outcome = buildOutcomeSection(ctx);
  writeJson("qa-live-results.json", result);
  writeJson("outcome-gate.json", result.outcome);
  const gateArgs = [
    path.join(repoRoot, "scripts", "playwright_audit_summary.py"),
    "--outcome-gate", path.join(outDir, "qa-live-results.json"),
    "--expected-chapters", String(ctx.expectedChapterCount),
    "--scenes-per-chapter", String(ctx.expectedScenesPerChapter),
    "--gate-output", path.join(outDir, "outcome-gate-verdict.md"),
  ];
  try {
    execFileSync(pythonExecutable, gateArgs, { cwd: repoRoot, stdio: "inherit" });
    result.outcomeGate = { passed: true, verdictPath: "outcome-gate-verdict.md" };
    appendLog({ type: "outcome-gate", passed: true });
    return true;
  } catch (error) {
    const exitCode = typeof error?.status === "number" ? error.status : null;
    result.outcomeGate = {
      passed: false,
      exitCode,
      verdictPath: "outcome-gate-verdict.md",
      error: exitCode === null ? `outcome gate could not execute: ${error?.message || error}` : "outcome gate FAIL",
    };
    appendLog({ type: "outcome-gate", passed: false, exitCode, error: result.outcomeGate.error });
    return false;
  }
}

module.exports = {
  NORTHSTAR_PHASE_LIST,
  tokensFromOutput,
  buildOutcomeSection,
  runOutcomeGate,
};
