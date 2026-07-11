from __future__ import annotations

import argparse
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

OUTCOME_SCHEMA = "outcome-gate-v1"
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
    "final_chars",
    "archived",
    "scene_status",
    "tokens",
    "duration_ms",
    "attempts",
    "block_reason",
    "source_safety",
)
CHAPTER_SCORE_FIELDS = (
    "originality",
    "conflictProgression",
    "characterTension",
    "sceneCausality",
    "continuity",
    "sourceLeakRisk",
)


def evaluate_outcome_gate(
    report: dict[str, Any],
    *,
    expected_chapters: int = 5,
    scenes_per_chapter: int = 3,
) -> dict[str, Any]:
    """结果级判定：无非空后端归档正文即失败，与步骤 ok 标志无关。"""
    failures: list[dict[str, Any]] = []
    stats = {
        "expected_scenes": expected_chapters * scenes_per_chapter,
        "planned_scenes": 0,
        "archived_scenes": 0,
    }

    outcome = report.get("outcome")
    if not isinstance(outcome, dict) or outcome.get("schema") != OUTCOME_SCHEMA:
        failures.append(
            {
                "code": "LEGACY_REPORT_NO_OUTCOME",
                "detail": "报告缺少 outcome-gate-v1 结果节：旧版'步骤完成即通过'报告一律按失败处理。",
                "scenes": [],
            }
        )
        return {"passed": False, "failures": failures, "stats": stats}

    planned = [item for item in (outcome.get("planned_scenes") or []) if isinstance(item, dict)]
    scenes = outcome.get("scenes") if isinstance(outcome.get("scenes"), dict) else {}
    stats["planned_scenes"] = len(planned)

    if len(planned) < stats["expected_scenes"]:
        failures.append(
            {
                "code": "SCENE_COVERAGE_SHORTFALL",
                "detail": (
                    f"计划场景 {len(planned)} 场，低于基准要求 "
                    f"{expected_chapters} 章 × {scenes_per_chapter} 场 = {stats['expected_scenes']} 场。"
                ),
                "scenes": [],
            }
        )

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
        try:
            final_chars = int(record.get("final_chars") or 0)
        except (TypeError, ValueError):
            final_chars = 0
        archived_ok = bool(record.get("archived")) and bool(record.get("final_row_id")) and final_chars > 0
        if archived_ok:
            stats["archived_scenes"] += 1
            archived_by_chapter[chapter_id] = archived_by_chapter.get(chapter_id, 0) + 1
        else:
            scenes_without_final.append(scene_id)

    if scenes_without_final:
        failures.append(
            {
                "code": "SCENE_WITHOUT_ARCHIVED_FINAL",
                "detail": (
                    f"{len(scenes_without_final)} 场无非空后端归档正文（final_row_id 为空、"
                    "正文为空或未达归档态）；流程跑完只能叫执行结束，不能叫成稿成功。"
                ),
                "scenes": scenes_without_final,
            }
        )

    if incomplete_records:
        failures.append(
            {
                "code": "OUTCOME_RECORD_INCOMPLETE",
                "detail": "每场必须输出 token、耗时、重试、阻断、最终稿与来源安全结果；" + "；".join(incomplete_records),
                "scenes": [entry.split(":", 1)[0] for entry in incomplete_records],
            }
        )

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

    lanes: dict[str, str] = {}
    for phase_entry in outcome.get("northstar_phases") or []:
        if isinstance(phase_entry, dict) and phase_entry.get("phase"):
            lanes[str(phase_entry["phase"])] = str(phase_entry.get("lane") or "missing")
    non_ui_phases = [
        f"{phase}={lanes.get(phase, 'missing')}" for phase in NORTHSTAR_PHASES if lanes.get(phase) != "ui"
    ]
    if non_ui_phases:
        failures.append(
            {
                "code": "NORTHSTAR_PHASE_NOT_UI",
                "detail": (
                    "北极星要求全链走真实 UI；以下阶段仍为 API 深链或缺失（API 深链仅作诊断通道）："
                    + "; ".join(non_ui_phases)
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
                    attempts=record.get("attempts") if record.get("attempts") is not None else "-",
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
            "stats": {"expected_scenes": args.expected_chapters * args.scenes_per_chapter, "planned_scenes": 0, "archived_scenes": 0},
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
