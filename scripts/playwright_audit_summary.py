from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path
from typing import Any


SNAPSHOT_GLOB = "page-*.yml"
CONSOLE_GLOB = "console-*.log"
DOWNLOAD_GLOBS = ("*.md", "*.txt", "*.json")
GENERATED_SUMMARY_NAMES = {"audit-summary.md", "playwright-audit-summary.md"}
ISSUE_RE = re.compile(r"\b(error|warning|failed|exception|traceback)\b", re.IGNORECASE)
DEFAULT_ARTIFACT_DIR = Path(".playwright-cli")
DEFAULT_OUTPUT = Path("docs/reports/playwright-audit-summary.md")


def build_summary(artifact_dir: str | Path, output_path: str | Path) -> dict[str, Any]:
    artifact_path = Path(artifact_dir)
    output = Path(output_path)
    snapshots = sorted(artifact_path.glob(SNAPSHOT_GLOB))
    console_logs = sorted(artifact_path.glob(CONSOLE_GLOB))
    downloads = _download_files(artifact_path)
    console_issues = _console_issues(console_logs)

    markdown = _render_markdown(
        artifact_path=artifact_path,
        snapshots=snapshots,
        console_logs=console_logs,
        downloads=downloads,
        console_issues=console_issues,
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(markdown, encoding="utf-8", newline="\n")
    return {
        "artifact_dir": str(artifact_path),
        "output_path": str(output),
        "snapshot_count": len(snapshots),
        "console_log_count": len(console_logs),
        "console_issue_count": len(console_issues),
        "download_count": len(downloads),
    }


def _download_files(artifact_path: Path) -> list[Path]:
    files: list[Path] = []
    for pattern in DOWNLOAD_GLOBS:
        files.extend(artifact_path.glob(pattern))
    return sorted(
        {
            path
            for path in files
            if not path.name.startswith("page-")
            and not path.name.startswith("console-")
            and path.name not in GENERATED_SUMMARY_NAMES
        }
    )


def _console_issues(console_logs: list[Path]) -> list[tuple[Path, str]]:
    issues: list[tuple[Path, str]] = []
    for log_path in console_logs:
        for line in _read_lines(log_path):
            if ISSUE_RE.search(line):
                issues.append((log_path, line.strip()))
    return issues


def _render_markdown(
    *,
    artifact_path: Path,
    snapshots: list[Path],
    console_logs: list[Path],
    downloads: list[Path],
    console_issues: list[tuple[Path, str]],
) -> str:
    lines = [
        "# Playwright 走查产物摘要",
        "",
        f"- 产物目录：`{artifact_path}`",
        f"- 页面快照：{len(snapshots)}",
        f"- 控制台日志：{len(console_logs)}",
        f"- 控制台问题：{len(console_issues)}",
        f"- 下载/导出文件：{len(downloads)}",
        "",
        "## 页面快照",
        "",
    ]
    if snapshots:
        for snapshot in snapshots:
            excerpt = _snapshot_excerpt(snapshot)
            lines.append(f"### `{snapshot.name}`")
            lines.extend(f"- {item}" for item in excerpt)
            lines.append("")
    else:
        lines.extend(["未找到页面快照。", ""])

    lines.extend(["## 下载与导出", ""])
    if downloads:
        for download in downloads:
            preview = _file_preview(download, max_lines=8)
            lines.append(f"### `{download.name}`")
            lines.extend(f"- {item}" for item in preview)
            lines.append("")
    else:
        lines.extend(["未找到下载或导出文件。", ""])

    lines.extend(["## 控制台问题", ""])
    if console_issues:
        for log_path, issue in console_issues[:50]:
            lines.append(f"- `{log_path.name}`：{issue}")
    else:
        lines.append("未发现 error/warning/failed/exception/traceback 关键字。")
    lines.append("")
    return "\n".join(lines)


def _snapshot_excerpt(path: Path) -> list[str]:
    headings: list[str] = []
    generic_hits: list[str] = []
    for line in _read_lines(path):
        clean = _clean_snapshot_line(line)
        if not clean:
            continue
        if "heading " in line or "button " in line:
            headings.append(clean)
        elif any(marker in clean for marker in ("completed", "Interop", "Reference Learning")):
            generic_hits.append(clean)
        if len(headings) >= 4 and len(generic_hits) >= 4:
            break
    excerpt = headings[:4] + generic_hits[:4]
    return excerpt or ["无可读摘要行。"]


def _file_preview(path: Path, *, max_lines: int) -> list[str]:
    preview: list[str] = []
    for line in _read_lines(path):
        clean = line.strip()
        if clean:
            preview.append(clean)
        if len(preview) >= max_lines:
            break
    return preview or ["文件为空。"]


def _read_lines(path: Path) -> list[str]:
    try:
        return path.read_text(encoding="utf-8").splitlines()
    except UnicodeDecodeError:
        return path.read_text(encoding="utf-8", errors="replace").splitlines()


def _clean_snapshot_line(line: str) -> str:
    clean = line.strip().lstrip("-").strip()
    clean = re.sub(r"\s*\[ref=[^\]]+\]", "", clean)
    clean = re.sub(r"\s*\[cursor=pointer\]", "", clean)
    return clean.strip()


# ---------------------------------------------------------------------------
# Wave 0 结果门禁（outcome gate）——设计 v1.1 §8 Wave 0 的单一权威判定器。
# harness（run-currentdb-three-chapter-qa.cjs / run-longzu-full-cloud-qa.cjs）
# 只负责采集每场结果并调用本判定器；判定失败或判定器不可执行时退出码非零。
# ---------------------------------------------------------------------------

OUTCOME_SCHEMA = "outcome-gate-v2"
RUN_MANIFEST_SCHEMA = "five-chapter-run-manifest-v1"
RECOVERY_SCHEMA = "five-chapter-recovery-v1"
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
NORTHSTAR_PHASES = (
    "snowflake_planning",
    "materialization",
    "scene_execution",
    "candidate_selection",
    "archive",
    "chapter_aggregation",
)
REQUIRED_SCENE_FIELDS = (
    "chapter_id",
    "final_row_id",
    "final_text",
    "final_chars",
    "final_text_sha256",
    "authority",
    "archived",
    "scene_status",
    "tokens",
    "duration_ms",
    "attempt_count",
    "attempt_evidence",
    "block_reason",
    "source_safety",
    "q0_q1_unresolved",
    "model_call",
)
CHAPTER_SCORE_FIELDS = (
    "originality",
    "conflictProgression",
    "characterTension",
    "sceneCausality",
    "continuity",
    "sourceLeakRisk",
)

UI_REQUIREMENT_SPECS = {
    "snowflake_planning": {
        "step-save": ("PATCH", re.compile(r"/snowflake-workspace/steps/[^/?]+(?:\?|$)")),
        "step-approve": ("POST", re.compile(r"/snowflake-workspace/steps/[^/]+/approve(?:\?|$)")),
    },
    "materialization": {
        "materialize": ("POST", re.compile(r"/snowflake-workspace/materialize(?:\?|$)")),
        "outline-approve": ("POST", re.compile(r"/snowflake-workspace/outline/approve(?:\?|$)")),
    },
    "scene_execution": {
        "run-job-create": ("POST", re.compile(r"/api/v1/scenes/[^/]+/run/jobs(?:\?|$)")),
    },
    "candidate_selection": {
        "candidate-select": ("POST", re.compile(r"/style-candidates/[^/]+/select(?:\?|$)")),
        "selection-resume": ("POST", re.compile(r"/resume-after-selection(?:\?|$)")),
    },
    "archive": {
        "adopt-current": ("POST", re.compile(r"/adopt-current(?:\?|$)")),
    },
    "chapter_aggregation": {
        "final-aggregate": ("POST", re.compile(r"/runtime/aggregate/final(?:\?|$)")),
    },
}


def canonical_sha256(value: Any) -> str:
    payload = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def text_sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _positive_int(value: Any) -> bool:
    return type(value) is int and value > 0


def _non_negative_number(value: Any) -> bool:
    return type(value) in (int, float) and value >= 0


def _valid_hash(value: Any) -> bool:
    return isinstance(value, str) and SHA256_RE.fullmatch(value) is not None


def _add_failure(
    failures: list[dict[str, Any]],
    code: str,
    detail: str,
    scenes: list[str] | None = None,
) -> None:
    failures.append({"code": code, "detail": detail, "scenes": scenes or []})


def _ui_required_counts(expected_chapters: int, expected_scenes: int) -> dict[str, dict[str, int]]:
    selected = min(3, expected_scenes)
    return {
        "snowflake_planning": {"step-save": 10, "step-approve": 10},
        "materialization": {"materialize": 1, "outline-approve": 1},
        "scene_execution": {"run-job-create": expected_scenes},
        "candidate_selection": {"candidate-select": selected, "selection-resume": selected},
        "archive": {"adopt-current": expected_scenes},
        "chapter_aggregation": {"final-aggregate": expected_chapters},
    }


def _validate_ui_receipts(
    outcome: dict[str, Any],
    *,
    expected_chapters: int,
    expected_scenes: int,
    failures: list[dict[str, Any]],
) -> None:
    entries = outcome.get("northstar_phases")
    if not isinstance(entries, list):
        _add_failure(failures, "NORTHSTAR_RECEIPTS_MISSING", "缺少北极星 UI 阶段回执列表。")
        return
    by_phase: dict[str, dict[str, Any]] = {}
    duplicate_phases: list[str] = []
    for entry in entries:
        if not isinstance(entry, dict) or not str(entry.get("phase") or "").strip():
            continue
        phase = str(entry["phase"])
        if phase in by_phase:
            duplicate_phases.append(phase)
        by_phase[phase] = entry
    if duplicate_phases:
        _add_failure(
            failures,
            "NORTHSTAR_PHASE_DUPLICATE",
            "UI 阶段回执重复：" + ", ".join(sorted(set(duplicate_phases))),
        )

    required_counts = _ui_required_counts(expected_chapters, expected_scenes)
    for phase in NORTHSTAR_PHASES:
        entry = by_phase.get(phase)
        if not isinstance(entry, dict):
            _add_failure(failures, "NORTHSTAR_PHASE_NOT_UI", f"{phase}=missing")
            continue
        if entry.get("lane") != "ui":
            _add_failure(failures, "NORTHSTAR_PHASE_NOT_UI", f"{phase}={entry.get('lane') or 'missing'}")
            continue
        if not _positive_int(entry.get("interaction_count")):
            _add_failure(failures, "NORTHSTAR_INTERACTION_INVALID", f"{phase} 缺少真实 locator 交互计数。")
        if not str(entry.get("evidence") or "").strip():
            _add_failure(failures, "NORTHSTAR_EVIDENCE_MISSING", f"{phase} 缺少可读证据说明。")
        requirements = entry.get("requirements") if isinstance(entry.get("requirements"), list) else []
        requests = entry.get("requests") if isinstance(entry.get("requests"), list) else []
        req_by_id = {
            str(item.get("id")): item
            for item in requirements
            if isinstance(item, dict) and item.get("id")
        }
        for requirement_id, required_count in required_counts[phase].items():
            requirement = req_by_id.get(requirement_id)
            expected_method, path_pattern = UI_REQUIREMENT_SPECS[phase][requirement_id]
            if not isinstance(requirement, dict):
                _add_failure(
                    failures,
                    "NORTHSTAR_REQUIREMENT_MISSING",
                    f"{phase} 缺少 {requirement_id} 计数回执。",
                )
                continue
            min_count = requirement.get("min")
            matched = requirement.get("matched")
            if not _positive_int(min_count) or int(min_count) < required_count:
                _add_failure(
                    failures,
                    "NORTHSTAR_REQUIREMENT_UNDERSIZED",
                    f"{phase}/{requirement_id} min={min_count!r}，要求至少 {required_count}。",
                )
            if not _positive_int(matched) or int(matched) < required_count:
                _add_failure(
                    failures,
                    "NORTHSTAR_RECEIPT_SHORTFALL",
                    f"{phase}/{requirement_id} matched={matched!r}，要求至少 {required_count}。",
                )
            matching_requests = [
                request
                for request in requests
                if isinstance(request, dict)
                and request.get("requirement_id") == requirement_id
                and str(request.get("method") or "").upper() == expected_method
                and type(request.get("status")) is int
                and 200 <= request["status"] < 300
                and request.get("resource_type") in {"fetch", "xhr"}
                and path_pattern.search(str(request.get("url") or ""))
            ]
            if len(matching_requests) < required_count:
                _add_failure(
                    failures,
                    "NORTHSTAR_REQUEST_EVIDENCE_SHORTFALL",
                    f"{phase}/{requirement_id} 只有 {len(matching_requests)} 条可复验浏览器请求，要求 {required_count}。",
                )
            if type(matched) is int and matched != len(matching_requests):
                _add_failure(
                    failures,
                    "NORTHSTAR_RECEIPT_COUNT_MISMATCH",
                    f"{phase}/{requirement_id} matched={matched}，但原始 2xx 请求为 {len(matching_requests)}。",
                )


def _validate_recovery_snapshot(
    snapshot: Any,
    *,
    label: str,
    chapter_ids: set[str],
    scene_ids: set[str],
    failures: list[dict[str, Any]],
) -> dict[str, str] | None:
    if not isinstance(snapshot, dict):
        _add_failure(failures, "RECOVERY_SNAPSHOT_MISSING", f"缺少 {label} 恢复快照。")
        return None
    hashes = snapshot.get("hashes") if isinstance(snapshot.get("hashes"), dict) else {}
    raw_parts = {
        "catalog": snapshot.get("catalog"),
        "scenes": snapshot.get("scenes"),
        "selections": snapshot.get("selections"),
        "aggregates": snapshot.get("aggregates"),
    }
    if not isinstance(raw_parts["catalog"], dict):
        _add_failure(failures, "RECOVERY_CATALOG_MISSING", f"{label} 缺少目录原始数据。")
    if not isinstance(raw_parts["scenes"], dict):
        _add_failure(failures, "RECOVERY_SCENES_MISSING", f"{label} 缺少场景原始数据。")
    if not isinstance(raw_parts["selections"], list):
        _add_failure(failures, "RECOVERY_SELECTIONS_MISSING", f"{label} 缺少候选选择原始数据。")
    if not isinstance(raw_parts["aggregates"], dict):
        _add_failure(failures, "RECOVERY_AGGREGATES_MISSING", f"{label} 缺少章节聚合原始数据。")
    if (
        not isinstance(raw_parts["catalog"], dict)
        or not isinstance(raw_parts["scenes"], dict)
        or not isinstance(raw_parts["selections"], list)
        or not isinstance(raw_parts["aggregates"], dict)
    ):
        return None

    computed = {
        "catalog_sha256": canonical_sha256(raw_parts["catalog"]),
        "content_sha256": canonical_sha256(raw_parts["scenes"]),
        "selection_sha256": canonical_sha256(raw_parts["selections"]),
        "aggregate_sha256": canonical_sha256(raw_parts["aggregates"]),
        "state_sha256": canonical_sha256(raw_parts),
    }
    for key, expected_hash in computed.items():
        if hashes.get(key) != expected_hash:
            _add_failure(
                failures,
                "RECOVERY_HASH_INVALID",
                f"{label}.{key} 无法由原始快照复算。",
            )

    catalog_chapters = raw_parts["catalog"].get("chapters") if isinstance(raw_parts["catalog"], dict) else None
    catalog_ids = {
        str(item.get("chapter_id") or "")
        for item in (catalog_chapters or [])
        if isinstance(item, dict)
    }
    catalog_scene_ids = {
        str(scene_id)
        for item in (catalog_chapters or [])
        if isinstance(item, dict)
        for scene_id in (item.get("scene_ids") or [])
    }
    if catalog_ids != chapter_ids or catalog_scene_ids != scene_ids:
        _add_failure(failures, "RECOVERY_CATALOG_SET_MISMATCH", f"{label} 目录章/场集合与计划不一致。")
    if set(raw_parts["scenes"]) != scene_ids:
        _add_failure(failures, "RECOVERY_SCENE_SET_MISMATCH", f"{label} 场景快照集合与计划不一致。")
    if set(raw_parts["aggregates"]) != chapter_ids:
        _add_failure(failures, "RECOVERY_AGGREGATE_SET_MISMATCH", f"{label} 聚合快照集合与计划不一致。")
    for scene_id, record in raw_parts["scenes"].items():
        if not isinstance(record, dict):
            _add_failure(failures, "RECOVERY_SCENE_INVALID", f"{label}/{scene_id} 快照不是对象。", [scene_id])
            continue
        text = record.get("final_text")
        if not isinstance(text, str) or not text.strip() or record.get("final_text_sha256") != text_sha256(text):
            _add_failure(failures, "RECOVERY_SCENE_HASH_INVALID", f"{label}/{scene_id} 正文哈希不可复算。", [scene_id])
    for chapter_id, record in raw_parts["aggregates"].items():
        if not isinstance(record, dict):
            _add_failure(failures, "RECOVERY_AGGREGATE_INVALID", f"{label}/{chapter_id} 聚合不是对象。")
            continue
        content = record.get("content")
        if not isinstance(content, str) or not content.strip() or record.get("content_sha256") != text_sha256(content):
            _add_failure(failures, "RECOVERY_AGGREGATE_HASH_INVALID", f"{label}/{chapter_id} 聚合正文哈希不可复算。")
    return computed


def _validate_recovery(
    outcome: dict[str, Any],
    *,
    chapter_ids: set[str],
    scene_ids: set[str],
    candidate_events: list[dict[str, Any]],
    failures: list[dict[str, Any]],
) -> dict[str, Any] | None:
    recovery = outcome.get("recovery")
    if not isinstance(recovery, dict) or recovery.get("schema") != RECOVERY_SCHEMA:
        _add_failure(failures, "RECOVERY_EVIDENCE_MISSING", f"真实门要求 {RECOVERY_SCHEMA} 恢复证据。")
        return None
    cache = recovery.get("cache_clear") if isinstance(recovery.get("cache_clear"), dict) else {}
    for field in (
        "performed",
        "local_storage_cleared",
        "session_storage_cleared",
        "cookies_cleared",
        "cache_storage_cleared",
    ):
        if cache.get(field) is not True:
            _add_failure(failures, "CACHE_CLEAR_NOT_PROVEN", f"cache_clear.{field} 必须为 true。")
    restart = recovery.get("backend_restart") if isinstance(recovery.get("backend_restart"), dict) else {}
    if restart.get("performed") is not True or restart.get("health_verified") is not True:
        _add_failure(failures, "BACKEND_RESTART_NOT_PROVEN", "受控后端重启及健康检查未完成。")
    before_pid = str(restart.get("before_pid") or "").strip()
    after_pid = str(restart.get("after_pid") or "").strip()
    if not before_pid or not after_pid or before_pid == after_pid or restart.get("pid_changed") is not True:
        _add_failure(failures, "BACKEND_PID_NOT_CHANGED", "重启前后后端 PID 缺失或未变化。")
    before_hashes = _validate_recovery_snapshot(
        recovery.get("before"),
        label="before",
        chapter_ids=chapter_ids,
        scene_ids=scene_ids,
        failures=failures,
    )
    after_hashes = _validate_recovery_snapshot(
        recovery.get("after"),
        label="after",
        chapter_ids=chapter_ids,
        scene_ids=scene_ids,
        failures=failures,
    )
    if before_hashes is not None and after_hashes is not None and before_hashes != after_hashes:
        _add_failure(failures, "RECOVERY_STATE_HASH_MISMATCH", "清缓存并重启后目录、正文、选择或聚合哈希发生变化。")
    expected_selections = {
        str(item.get("scene_id") or ""): str(item.get("selected_row_id") or "")
        for item in candidate_events
        if isinstance(item, dict)
    }
    for label in ("before", "after"):
        snapshot = recovery.get(label) if isinstance(recovery.get(label), dict) else {}
        actual = {
            str(item.get("scene_id") or ""): str(item.get("selected_row_id") or "")
            for item in (snapshot.get("selections") or [])
            if isinstance(item, dict)
        }
        if actual != expected_selections:
            _add_failure(failures, "RECOVERY_SELECTION_SET_MISMATCH", f"{label} 终选状态与 UI 候选终选事件不一致。")
    return recovery


def evaluate_outcome_gate(
    report: dict[str, Any],
    *,
    expected_chapters: int = 5,
    scenes_per_chapter: int = 3,
) -> dict[str, Any]:
    """Fail-closed five-chapter release gate over recomputable raw evidence."""
    failures: list[dict[str, Any]] = []
    stats = {
        "expected_scenes": expected_chapters * scenes_per_chapter,
        "planned_scenes": 0,
        "archived_scenes": 0,
        "aggregated_chapters": 0,
    }

    outcome = report.get("outcome")
    if not isinstance(outcome, dict):
        _add_failure(failures, "LEGACY_REPORT_NO_OUTCOME", "报告缺少结果节；步骤完成不能替代真实结果。")
        return {"passed": False, "failures": failures, "stats": stats}
    if outcome.get("schema") != OUTCOME_SCHEMA:
        _add_failure(
            failures,
            "OUTCOME_SCHEMA_UNSUPPORTED",
            f"真实发布门只接受 {OUTCOME_SCHEMA}；收到 {outcome.get('schema')!r}，旧 schema 仅供诊断。",
        )
        return {"passed": False, "failures": failures, "stats": stats}

    expected = outcome.get("expected") if isinstance(outcome.get("expected"), dict) else {}
    if expected.get("chapters") != expected_chapters or expected.get("scenes_per_chapter") != scenes_per_chapter:
        _add_failure(
            failures,
            "EXPECTED_SCALE_MISMATCH",
            f"报告声明规模 {expected!r} 与门禁参数 {expected_chapters}×{scenes_per_chapter} 不一致。",
        )

    planned = [item for item in (outcome.get("planned_scenes") or []) if isinstance(item, dict)]
    scenes = outcome.get("scenes") if isinstance(outcome.get("scenes"), dict) else {}
    stats["planned_scenes"] = len(planned)
    if len(planned) != stats["expected_scenes"]:
        _add_failure(
            failures,
            "SCENE_COVERAGE_INVALID",
            f"计划场景必须恰为 {stats['expected_scenes']}，实际 {len(planned)}。",
        )

    planned_scene_ids = [str(item.get("scene_id") or "").strip() for item in planned]
    planned_chapter_ids = [str(item.get("chapter_id") or "").strip() for item in planned]
    if any(not scene_id for scene_id in planned_scene_ids) or any(not chapter_id for chapter_id in planned_chapter_ids):
        _add_failure(failures, "PLANNED_ID_MISSING", "计划章/场 ID 不得为空。")
    if len(set(planned_scene_ids)) != len(planned_scene_ids):
        _add_failure(failures, "PLANNED_SCENE_DUPLICATE", "计划场景 ID 必须唯一。")
    chapter_ids = set(planned_chapter_ids)
    scene_ids = set(planned_scene_ids)
    if len(chapter_ids) != expected_chapters:
        _add_failure(
            failures,
            "CHAPTER_CARDINALITY_INVALID",
            f"必须恰有 {expected_chapters} 个唯一章节，实际 {len(chapter_ids)}。",
        )
    for chapter_id in sorted(chapter_ids):
        count = sum(1 for item in planned if str(item.get("chapter_id") or "").strip() == chapter_id)
        if count != scenes_per_chapter:
            _add_failure(
                failures,
                "SCENES_PER_CHAPTER_INVALID",
                f"章节 {chapter_id} 必须恰有 {scenes_per_chapter} 个唯一场景，实际 {count}。",
            )
    if set(scenes) != scene_ids:
        _add_failure(failures, "SCENE_RECORD_SET_MISMATCH", "场景结果集合必须与计划场景集合完全一致。")

    scenes_without_final: list[str] = []
    incomplete_records: list[str] = []
    archived_by_chapter: dict[str, int] = {}
    for item in planned:
        scene_id = str(item.get("scene_id") or "")
        chapter_id = str(item.get("chapter_id") or "")
        record = scenes.get(scene_id)
        if not isinstance(record, dict):
            scenes_without_final.append(scene_id)
            continue
        missing_fields = [field for field in REQUIRED_SCENE_FIELDS if field not in record]
        if missing_fields:
            incomplete_records.append(f"{scene_id}: 缺字段 {', '.join(missing_fields)}")
        final_text = record.get("final_text")
        final_chars = record.get("final_chars")
        authority = record.get("authority") if isinstance(record.get("authority"), dict) else {}
        archived_ok = (
            record.get("archived") is True
            and record.get("scene_status") == "archived"
            and isinstance(final_text, str)
            and bool(final_text.strip())
            and type(final_chars) is int
            and final_chars == len(final_text)
            and bool(record.get("final_row_id"))
            and authority.get("object_type") == "FinalScene"
            and authority.get("row_id") == record.get("final_row_id")
            and authority.get("status") == "archived"
            and record.get("final_text_sha256") == text_sha256(final_text or "")
        )
        if archived_ok:
            stats["archived_scenes"] += 1
            archived_by_chapter[chapter_id] = archived_by_chapter.get(chapter_id, 0) + 1
        else:
            scenes_without_final.append(scene_id)

        if not _positive_int(record.get("tokens")):
            incomplete_records.append(f"{scene_id}: tokens 必须为正整数")
        if not _non_negative_number(record.get("duration_ms")) or record.get("duration_ms") <= 0:
            incomplete_records.append(f"{scene_id}: duration_ms 必须为正数")
        attempts = record.get("attempt_evidence")
        if not _positive_int(record.get("attempt_count")) or not isinstance(attempts, list) or len(attempts) < 1:
            incomplete_records.append(f"{scene_id}: attempt_count/attempt_evidence 缺少真实尝试记录")
        elif record.get("attempt_count") != len(attempts):
            incomplete_records.append(f"{scene_id}: attempt_count 与 attempt_evidence 数量不一致")
        if record.get("q0_q1_unresolved") != 0 or type(record.get("q0_q1_unresolved")) is not int:
            incomplete_records.append(f"{scene_id}: q0_q1_unresolved 必须显式为整数 0")
        safety = record.get("source_safety") if isinstance(record.get("source_safety"), dict) else {}
        if (
            safety.get("safe") is not True
            or not isinstance(safety.get("blocked_terms"), list)
            or safety.get("blocked_terms")
            or not isinstance(safety.get("risks"), list)
            or safety.get("risks")
            or not isinstance(safety.get("source_profile_ids"), list)
            or not safety.get("source_profile_ids")
        ):
            incomplete_records.append(f"{scene_id}: source_safety 必须显式安全、零风险并带 profile provenance")
        call = record.get("model_call") if isinstance(record.get("model_call"), dict) else {}
        if (
            call.get("scene_id") != scene_id
            or not str(call.get("llm_call_id") or "").strip()
            or not str(call.get("provider") or "").strip()
            or call.get("provider") == "offline_deterministic"
            or not str(call.get("model") or "").strip()
            or not str(call.get("prompt_hash") or "").strip()
            or not _positive_int(call.get("total_tokens"))
            or not _non_negative_number(call.get("latency_ms"))
            or call.get("error_code") not in (None, "")
            or not str(call.get("created_at") or "").strip()
        ):
            incomplete_records.append(f"{scene_id}: model_call 缺少可验证真实模型调用字段")

    if scenes_without_final:
        _add_failure(
            failures,
            "SCENE_WITHOUT_ARCHIVED_FINAL",
            f"{len(scenes_without_final)} 场缺少权威、非空且哈希可复算的 FinalScene 归档正文。",
            scenes_without_final,
        )

    if incomplete_records:
        _add_failure(
            failures,
            "OUTCOME_RECORD_INCOMPLETE",
            "每场必须输出真实模型、token、耗时、尝试、Q0/Q1、权威正文与来源安全证据；" + "；".join(incomplete_records),
            [entry.split(":", 1)[0] for entry in incomplete_records],
        )

    aggregates = outcome.get("chapter_aggregates") if isinstance(outcome.get("chapter_aggregates"), dict) else {}
    if set(aggregates) != chapter_ids:
        _add_failure(failures, "CHAPTER_AGGREGATE_SET_MISMATCH", "章节聚合集合必须与五章计划完全一致。")
    for chapter_id in sorted(chapter_ids):
        aggregate = aggregates.get(chapter_id)
        expected_scene_ids = [
            str(item.get("scene_id")) for item in planned if str(item.get("chapter_id")) == chapter_id
        ]
        if not isinstance(aggregate, dict):
            _add_failure(failures, "CHAPTER_AGGREGATE_MISSING", f"章节 {chapter_id} 缺少聚合证据。")
            continue
        content = aggregate.get("content")
        valid = (
            aggregate.get("chapter_id") == chapter_id
            and aggregate.get("completion_status") == "complete"
            and aggregate.get("authority_source") == "chapter_manuscript"
            and aggregate.get("scene_ids") == expected_scene_ids
            and isinstance(content, str)
            and bool(content.strip())
            and aggregate.get("content_sha256") == text_sha256(content or "")
        )
        if valid:
            cursor = 0
            for expected_scene_id in expected_scene_ids:
                scene_text = str((scenes.get(expected_scene_id) or {}).get("final_text") or "")
                position = content.find(scene_text, cursor) if scene_text else -1
                if position < 0:
                    valid = False
                    break
                cursor = position + len(scene_text)
        if not valid:
            _add_failure(
                failures,
                "CHAPTER_AGGREGATE_INVALID",
                f"章节 {chapter_id} 聚合必须完整、哈希可复算，并按计划顺序包含三场权威正文。",
            )
        else:
            stats["aggregated_chapters"] += 1

    candidate = outcome.get("candidate_selection") if isinstance(outcome.get("candidate_selection"), dict) else {}
    candidate_events = candidate.get("events") if isinstance(candidate.get("events"), list) else []
    required_candidates = min(3, stats["expected_scenes"])
    selected_scene_ids = [str(item.get("scene_id") or "") for item in candidate_events if isinstance(item, dict)]
    if (
        any(not isinstance(item, dict) for item in candidate_events)
        or
        candidate.get("count") != len(candidate_events)
        or len(candidate_events) < required_candidates
        or len(set(selected_scene_ids)) != len(selected_scene_ids)
        or not set(selected_scene_ids).issubset(scene_ids)
        or any(not str(item.get("selected_row_id") or "").strip() for item in candidate_events if isinstance(item, dict))
        or candidate.get("events_sha256") != canonical_sha256(candidate_events)
    ):
        _add_failure(
            failures,
            "CANDIDATE_SELECTION_EVIDENCE_INVALID",
            f"至少 {required_candidates} 个不同场景必须有可复算的候选终选事件。",
        )

    _validate_ui_receipts(
        outcome,
        expected_chapters=expected_chapters,
        expected_scenes=stats["expected_scenes"],
        failures=failures,
    )
    recovery = _validate_recovery(
        outcome,
        chapter_ids=chapter_ids,
        scene_ids=scene_ids,
        candidate_events=candidate_events,
        failures=failures,
    )

    run = outcome.get("run") if isinstance(outcome.get("run"), dict) else {}
    manifest = run.get("manifest") if isinstance(run.get("manifest"), dict) else {}
    manifest_hash = run.get("manifest_hash")
    if run.get("provenance") != "real_model":
        _add_failure(failures, "RUN_PROVENANCE_NOT_REAL_MODEL", "五章真实门要求 provenance=real_model。")
    for field in ("run_id", "project_id", "started_at", "finished_at"):
        if not str(run.get(field) or "").strip():
            _add_failure(failures, "RUN_FIELD_MISSING", f"run.{field} 缺失。")
    if manifest.get("schema") != RUN_MANIFEST_SCHEMA or manifest_hash != canonical_sha256(manifest):
        _add_failure(failures, "RUN_MANIFEST_HASH_INVALID", "运行 manifest 缺失、版本错误或哈希不可复算。")
    if (
        manifest.get("run_id") != run.get("run_id")
        or manifest.get("project_id") != run.get("project_id")
        or manifest.get("provenance") != "real_model"
        or manifest.get("expected") != {"chapters": expected_chapters, "scenes_per_chapter": scenes_per_chapter}
        or manifest.get("planned_scene_ids") != planned_scene_ids
        or not str(manifest.get("lane_id") or "").strip()
        or not str(manifest.get("reference_source_basis") or "").strip()
    ):
        _add_failure(failures, "RUN_MANIFEST_CONTENT_INVALID", "运行 manifest 与固定 lane、规模或计划对象不一致。")
    manifest_calls = manifest.get("model_calls") if isinstance(manifest.get("model_calls"), list) else []
    call_scene_ids = [str(item.get("scene_id") or "") for item in manifest_calls if isinstance(item, dict)]
    call_ids = [str(item.get("llm_call_id") or "") for item in manifest_calls if isinstance(item, dict)]
    if (
        len(manifest_calls) != stats["expected_scenes"]
        or set(call_scene_ids) != scene_ids
        or len(set(call_scene_ids)) != len(call_scene_ids)
        or len(set(call_ids)) != len(call_ids)
        or manifest.get("offline_deterministic_required_count") != 0
    ):
        _add_failure(failures, "MODEL_CALL_MANIFEST_INVALID", "manifest 必须逐场绑定唯一真实模型调用且无离线替代。")
    else:
        for call in manifest_calls:
            scene_call = (scenes.get(str(call.get("scene_id"))) or {}).get("model_call")
            if call != scene_call:
                _add_failure(failures, "MODEL_CALL_MANIFEST_MISMATCH", "manifest 模型调用与场景证据不一致。")
                break
    cost = manifest.get("cost_summary") if isinstance(manifest.get("cost_summary"), dict) else {}
    if (
        not _positive_int(cost.get("total_tokens"))
        or not _non_negative_number(cost.get("total_cost"))
        or not _positive_int(cost.get("call_count"))
        or not str(cost.get("currency") or "").strip()
        or type(cost.get("is_estimate")) is not bool
        or cost.get("archived_scene_count") != stats["expected_scenes"]
        or cost.get("archived_chapter_count") != expected_chapters
    ):
        _add_failure(failures, "COST_EVIDENCE_INVALID", "成本摘要必须含完整 token、调用数、币种、估算口径和归档分母。")
    recovery_state_hash = (
        ((recovery or {}).get("after") or {}).get("hashes", {}).get("state_sha256")
        if isinstance(recovery, dict)
        else None
    )
    if (
        manifest.get("candidate_events_sha256") != candidate.get("events_sha256")
        or manifest.get("recovery_state_sha256") != recovery_state_hash
    ):
        _add_failure(failures, "RUN_MANIFEST_EVIDENCE_MISMATCH", "manifest 未绑定候选选择或恢复终态哈希。")

    chapter_scores = report.get("chapterScores")
    fake_score_chapters: list[str] = []
    if isinstance(chapter_scores, dict):
        for chapter_id, entry in chapter_scores.items():
            if not isinstance(entry, dict) or entry.get("no_draft") is True:
                continue
            has_numeric_score = any(
                isinstance(entry.get(field), (int, float)) for field in CHAPTER_SCORE_FIELDS
            )
            if has_numeric_score and archived_by_chapter.get(str(chapter_id), 0) == 0:
                fake_score_chapters.append(str(chapter_id))
    if fake_score_chapters:
        failures.append(
            {
                "code": "EMPTY_CHAPTER_FAKE_SCORE",
                "detail": (
                    "以下章节没有任何归档非空正文，却生成了正常文学分数或安全结论（空章节不得报'暂无明显风险'）："
                    + ", ".join(sorted(fake_score_chapters))
                ),
                "scenes": [],
            }
        )

    return {"passed": not failures, "failures": failures, "stats": stats}


def render_gate_verdict(verdict: dict[str, Any], report: dict[str, Any]) -> str:
    stats = verdict["stats"]
    lines = [
        "# 五章结果门禁判定",
        "",
        f"- 判定：**{'通过' if verdict['passed'] else '失败'}**",
        f"- 基准：{stats['expected_scenes']} 场（计划 {stats['planned_scenes']} 场，归档非空 {stats['archived_scenes']} 场）",
        "",
    ]
    if verdict["failures"]:
        lines.append("## 失败原因")
        lines.append("")
        for failure in verdict["failures"]:
            lines.append(f"- `{failure['code']}`：{failure['detail']}")
            if failure.get("scenes"):
                lines.append(f"  - 涉及场景：{', '.join(failure['scenes'])}")
        lines.append("")
    outcome = report.get("outcome")
    if isinstance(outcome, dict):
        scenes = outcome.get("scenes") if isinstance(outcome.get("scenes"), dict) else {}
        lines.extend(
            [
                "## 每场结果",
                "",
                "| 场景 | 章节 | 状态 | 归档 | 字数 | 最终行 | tokens | 耗时ms | 重试 | 阻断原因 |",
                "| --- | --- | --- | --- | ---: | --- | ---: | ---: | ---: | --- |",
            ]
        )
        for item in outcome.get("planned_scenes") or []:
            scene_id = str(item.get("scene_id") or "")
            record = scenes.get(scene_id) or {}
            lines.append(
                "| {scene} | {chapter} | {status} | {archived} | {chars} | {row} | {tokens} | {duration} | {attempts} | {reason} |".format(
                    scene=scene_id,
                    chapter=item.get("chapter_id") or "",
                    status=record.get("scene_status") or "missing_record",
                    archived="是" if record.get("archived") else "否",
                    chars=record.get("final_chars") if record.get("final_chars") is not None else 0,
                    row=record.get("final_row_id") or "无",
                    tokens=record.get("tokens") if record.get("tokens") is not None else "-",
                    duration=record.get("duration_ms") if record.get("duration_ms") is not None else "-",
                    attempts=record.get("attempt_count") if record.get("attempt_count") is not None else "-",
                    reason=record.get("block_reason") or "-",
                )
            )
        lines.append("")
    else:
        lines.extend(["## 每场结果", "", "报告为旧版形状，无结果级数据可展示。", ""])
    return "\n".join(lines)


def run_outcome_gate_cli(args: argparse.Namespace) -> int:
    report_path = Path(args.outcome_gate)
    try:
        report = json.loads(report_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        verdict = {
            "passed": False,
            "failures": [
                {
                    "code": "GATE_INPUT_UNREADABLE",
                    "detail": f"无法读取结果报告 {report_path}：{error}",
                    "scenes": [],
                }
            ],
            "stats": {"expected_scenes": args.expected_chapters * args.scenes_per_chapter, "planned_scenes": 0, "archived_scenes": 0, "aggregated_chapters": 0},
        }
        report = {}
    else:
        verdict = evaluate_outcome_gate(
            report,
            expected_chapters=args.expected_chapters,
            scenes_per_chapter=args.scenes_per_chapter,
        )
    markdown = render_gate_verdict(verdict, report)
    if args.gate_output:
        gate_output = Path(args.gate_output)
        gate_output.parent.mkdir(parents=True, exist_ok=True)
        gate_output.write_text(markdown, encoding="utf-8", newline="\n")
    stats = verdict["stats"]
    print(
        "outcome-gate: {verdict} (planned {planned}/{expected}, archived {archived})".format(
            verdict="PASS" if verdict["passed"] else "FAIL",
            planned=stats["planned_scenes"],
            expected=stats["expected_scenes"],
            archived=stats["archived_scenes"],
        )
    )
    for failure in verdict["failures"]:
        print(f"outcome-gate failure {failure['code']}: {failure['detail']}")
    return 0 if verdict["passed"] else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Summarize Playwright CLI artifacts into UTF-8 Markdown, or judge a QA run's outcome gate."
    )
    parser.add_argument("--artifacts", default=str(DEFAULT_ARTIFACT_DIR), help="Directory containing playwright-cli artifacts.")
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT), help="UTF-8 Markdown summary path.")
    parser.add_argument("--outcome-gate", default=None, help="Path to a harness qa-live-results.json to judge at the outcome level.")
    parser.add_argument("--expected-chapters", type=int, default=5, help="Outcome gate: required chapter count (default 5).")
    parser.add_argument("--scenes-per-chapter", type=int, default=3, help="Outcome gate: required scenes per chapter (default 3).")
    parser.add_argument("--gate-output", default=None, help="Outcome gate: optional UTF-8 Markdown verdict path.")
    args = parser.parse_args(argv)
    if args.outcome_gate:
        return run_outcome_gate_cli(args)
    summary = build_summary(args.artifacts, args.output)
    print(
        "wrote {output_path} ({snapshot_count} snapshots, {download_count} downloads, {console_issue_count} console issues)".format(
            **summary
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
