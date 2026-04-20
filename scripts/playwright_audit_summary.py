from __future__ import annotations

import argparse
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


def main() -> int:
    parser = argparse.ArgumentParser(description="Summarize Playwright CLI artifacts into UTF-8 Markdown.")
    parser.add_argument("--artifacts", default=str(DEFAULT_ARTIFACT_DIR), help="Directory containing playwright-cli artifacts.")
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT), help="UTF-8 Markdown summary path.")
    args = parser.parse_args()
    summary = build_summary(args.artifacts, args.output)
    print(
        "wrote {output_path} ({snapshot_count} snapshots, {download_count} downloads, {console_issue_count} console issues)".format(
            **summary
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
