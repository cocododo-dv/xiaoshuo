/* Five-chapter outcome evidence builder.  The Python gate is authoritative. */
const crypto = require("node:crypto");
const path = require("node:path");
const { execFileSync } = require("node:child_process");

const OUTCOME_SCHEMA = "outcome-gate-v2";
const RUN_MANIFEST_SCHEMA = "five-chapter-run-manifest-v1";
const NORTHSTAR_PHASE_LIST = [
  "snowflake_planning",
  "materialization",
  "scene_execution",
  "candidate_selection",
  "archive",
  "chapter_aggregation",
];

function canonicalize(value) {
  if (Array.isArray(value)) return value.map(canonicalize);
  if (value && typeof value === "object") {
    return Object.fromEntries(
      Object.keys(value).sort().map((key) => [key, canonicalize(value[key])]),
    );
  }
  return value;
}

function canonicalJson(value) {
  return JSON.stringify(canonicalize(value));
}

function sha256Text(value) {
  return crypto.createHash("sha256").update(String(value), "utf8").digest("hex");
}

function sha256Bytes(value) {
  return crypto.createHash("sha256").update(value).digest("hex");
}

function sha256Canonical(value) {
  return sha256Text(canonicalJson(value));
}

function tokensFromOutput(job, output) {
  const candidates = [
    output?.generationSummary?.total_tokens,
    output?.generationSummary?.tokens?.total,
    output?.generationSummary?.usage?.total_tokens,
    job?.result_summary?.total_tokens,
    job?.result_summary?.tokens?.total,
  ];
  for (const value of candidates) {
    const number = Number(value);
    if (Number.isFinite(number) && number > 0) return number;
  }
  return null;
}

function normalizeModelCall(sceneId, summary) {
  const source = summary && typeof summary === "object" ? summary : {};
  return {
    scene_id: sceneId,
    llm_call_id: source.llm_call_id || source.call_id || null,
    provider: source.provider || null,
    model: source.model || null,
    prompt_hash: source.prompt_hash || null,
    prompt_tokens: source.prompt_tokens ?? source.tokens?.prompt ?? null,
    completion_tokens: source.completion_tokens ?? source.tokens?.completion ?? null,
    total_tokens: source.total_tokens ?? source.tokens?.total ?? source.usage?.total_tokens ?? null,
    latency_ms: source.latency_ms ?? source.latency ?? null,
    finish_reason: source.finish_reason ?? null,
    error_code: source.error_code ?? null,
    created_at: source.created_at ?? null,
  };
}

function normalizeAggregate(chapter, raw) {
  const content = raw?.assembled?.content ?? raw?.content ?? "";
  const sceneIds = chapter.scenes.map((scene) => scene.scene_id);
  return {
    chapter_id: chapter.chapter_id,
    completion_status: raw?.completion_status ?? null,
    authority_source: "chapter_manuscript",
    scene_ids: raw?.assembled?.scene_ids ?? raw?.scene_ids ?? sceneIds,
    content,
    content_sha256: sha256Text(content),
  };
}

function q0Q1Unresolved(output) {
  if (Number.isInteger(output?.q0Q1Unresolved)) return output.q0Q1Unresolved;
  const issues = [...(output?.hardQc?.issues || []), ...(output?.softQc?.issues || [])];
  return issues.filter((issue) => {
    const level = String(issue?.quality_level || issue?.level || issue?.severity || "").toUpperCase();
    const resolution = String(issue?.resolution_status || issue?.status || "").toLowerCase();
    return ["Q0", "Q1"].includes(level) && !["resolved", "accepted", "waived"].includes(resolution);
  }).length;
}

function buildOutcomeSection(ctx) {
  const {
    chapters,
    finalScenes,
    expectedChapterCount,
    expectedScenesPerChapter,
    northstarPhases,
  } = ctx;
  const plannedScenes = [];
  const sceneRecords = {};
  const modelCalls = [];
  for (const chapter of chapters) {
    for (const scene of chapter.scenes) {
      const sceneId = scene.scene_id;
      plannedScenes.push({ chapter_id: chapter.chapter_id, scene_id: sceneId });
      const output = finalScenes[sceneId] || {};
      const finalText = typeof output.finalText === "string" ? output.finalText : "";
      const attempts = Array.isArray(output.attempts) ? output.attempts : [];
      const call = normalizeModelCall(sceneId, output.generationSummary);
      modelCalls.push(call);
      sceneRecords[sceneId] = {
        chapter_id: chapter.chapter_id,
        final_row_id: output.finalRowId || null,
        final_text: finalText,
        final_chars: finalText.length,
        final_text_sha256: sha256Text(finalText),
        authority: {
          object_type: "FinalScene",
          row_id: output.finalRowId || null,
          status: output.sceneStatus || null,
        },
        archived: output.sceneStatus === "archived" && Boolean(output.finalRowId) && finalText.trim().length > 0,
        scene_status: output.sceneStatus || "not_started",
        tokens: output.tokens ?? tokensFromOutput(null, output),
        duration_ms: output.durationMs ?? null,
        attempt_count: attempts.length,
        attempt_evidence: attempts,
        block_reason: output.blockReason || null,
        source_safety: output.source_safety_scan || null,
        q0_q1_unresolved: q0Q1Unresolved(output),
        model_call: call,
      };
    }
  }

  const chapterAggregates = {};
  for (const chapter of chapters) {
    chapterAggregates[chapter.chapter_id] = normalizeAggregate(
      chapter,
      ctx.chapterAggregates?.[chapter.chapter_id],
    );
  }
  const candidateEvents = Array.isArray(ctx.candidateSelectionEvents) ? ctx.candidateSelectionEvents : [];
  const candidateSelection = {
    count: candidateEvents.length,
    events: candidateEvents,
    events_sha256: sha256Canonical(candidateEvents),
  };
  const phases = NORTHSTAR_PHASE_LIST.map((phase) => northstarPhases[phase] || {
    phase,
    lane: "missing",
    interaction_count: 0,
    requirements: [],
    requests: [],
    evidence: "phase not reached",
  });
  const costSummary = ctx.costEvidence || null;
  const runId = ctx.runId || ctx.result?.meta?.runId || ctx.result?.meta?.operatorRef || null;
  const projectId = ctx.projectId || ctx.result?.meta?.created?.projectId || null;
  const manifest = {
    schema: RUN_MANIFEST_SCHEMA,
    provenance: "real_model",
    run_id: runId,
    project_id: projectId,
    lane_id: ctx.laneId || ctx.result?.meta?.referenceLaneId || null,
    reference_source_basis: ctx.referenceSourceBasis || ctx.result?.meta?.referenceSourceBasis || null,
    expected: { chapters: expectedChapterCount, scenes_per_chapter: expectedScenesPerChapter },
    planned_scene_ids: plannedScenes.map((item) => item.scene_id),
    model_calls: modelCalls,
    offline_deterministic_required_count: ctx.offlineDeterministicRequiredCount ?? null,
    cost_summary: costSummary,
    candidate_events_sha256: candidateSelection.events_sha256,
    recovery_state_sha256: ctx.recoveryEvidence?.after?.hashes?.state_sha256 || null,
  };
  return {
    schema: OUTCOME_SCHEMA,
    expected: { chapters: expectedChapterCount, scenes_per_chapter: expectedScenesPerChapter },
    planned_scenes: plannedScenes,
    scenes: sceneRecords,
    chapter_aggregates: chapterAggregates,
    candidate_selection: candidateSelection,
    northstar_phases: phases,
    recovery: ctx.recoveryEvidence || null,
    run: {
      provenance: "real_model",
      run_id: runId,
      project_id: projectId,
      started_at: ctx.result?.meta?.startedAt || null,
      finished_at: ctx.result?.meta?.finishedAt || null,
      manifest,
      manifest_hash: sha256Canonical(manifest),
    },
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
  OUTCOME_SCHEMA,
  RUN_MANIFEST_SCHEMA,
  NORTHSTAR_PHASE_LIST,
  canonicalJson,
  sha256Text,
  sha256Bytes,
  sha256Canonical,
  tokensFromOutput,
  buildOutcomeSection,
  runOutcomeGate,
};
