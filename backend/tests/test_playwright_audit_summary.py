from __future__ import annotations

import importlib.util
from pathlib import Path


def _load_summary_module():
    script_path = Path(__file__).resolve().parents[2] / "scripts" / "playwright_audit_summary.py"
    spec = importlib.util.spec_from_file_location("playwright_audit_summary", script_path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_playwright_audit_summary_writes_utf8_markdown(tmp_path) -> None:
    module = _load_summary_module()
    artifact_dir = tmp_path / ".playwright-cli"
    artifact_dir.mkdir()
    removed_demo_label = "Demo " + "Studio"
    (artifact_dir / "page-2026-04-20T08-07-21-714Z.yml").write_text(
        "- generic [ref=e1]:\n"
        "  - heading \"参考书学习\" [level=2]\n"
        "  - button \"刷新\"\n"
        "  - generic [ref=e2]: Reference Learning\n"
        f"  - generic [ref=e3]: {removed_demo_label}\n",
        encoding="utf-8",
    )
    (artifact_dir / "page-2026-04-20T08-07-47-205Z.yml").write_text(
        "- generic [ref=e1]:\n"
        "  - heading \"互操作中心\" [level=2]\n"
        "  - generic [ref=e2]: 结果信封\n",
        encoding="utf-8",
    )
    (artifact_dir / "console-2026-04-20T07-00-01-564Z.log").write_text(
        "[warning] Password field is not contained in a form\n"
        "[error] Failed to fetch http://127.0.0.1:8000/api/v1/reference-books\n",
        encoding="utf-8",
    )
    (artifact_dir / "reference-export.md").write_text(
        "# Reference Export\n\n- 安全状态：通过\n\n抽象叙事技法样例\n",
        encoding="utf-8",
    )
    (artifact_dir / "audit-summary.md").write_text(
        "# Playwright 走查产物摘要\n",
        encoding="utf-8",
    )

    output_path = tmp_path / "audit-summary.md"
    summary = module.build_summary(artifact_dir, output_path)

    assert output_path.read_bytes().startswith("# Playwright 走查产物摘要".encode("utf-8"))
    text = output_path.read_text(encoding="utf-8")
    assert summary["snapshot_count"] == 2
    assert summary["download_count"] == 1
    assert summary["console_issue_count"] == 2
    assert "page-2026-04-20T08-07-21-714Z.yml" in text
    assert "参考书学习" in text
    assert removed_demo_label not in text
    assert "reference-export.md" in text
    assert "安全状态：通过" in text
    assert "Failed to fetch" in text


def test_playwright_audit_summary_defaults_to_tracked_report_and_ignores_raw_artifacts() -> None:
    module = _load_summary_module()
    repo_root = Path(__file__).resolve().parents[2]

    assert module.DEFAULT_OUTPUT == Path("docs/reports/playwright-audit-summary.md")
    assert ".playwright-cli/" in (repo_root / ".gitignore").read_text(encoding="utf-8").splitlines()
