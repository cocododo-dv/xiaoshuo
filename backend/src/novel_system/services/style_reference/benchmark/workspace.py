"""只读公开清单的生成工作区准备器。"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from novel_system.services.style_reference.benchmark.manifest import (
    STYLE_BENCHMARK_SCHEMA_VERSION,
    StyleBenchmarkManifest,
)


def prepare_generation_workspace(
    manifest: StyleBenchmarkManifest,
    output_dir: str | Path,
) -> dict[str, Any]:
    """落训练语料和完整生成矩阵；本函数没有隐藏清单参数。"""

    root = Path(output_dir).expanduser().resolve()
    # 哈希分目录避免清单/语料升级后旧匿名文件与新计划混在同一目录；不删除
    # 用户工作区中的任何历史产物。
    training_dir = root / "training" / manifest.public_manifest_hash[:16]
    training_dir.mkdir(parents=True, exist_ok=True)
    authors: list[dict[str, Any]] = []
    for author in manifest.authors:
        destination = training_dir / f"{author.anonymous_corpus_id}.txt"
        destination.write_text(author.anonymous_training_text, encoding="utf-8")
        authors.append(
            {
                "author_id": author.author_id,
                "anonymous_corpus_id": author.anonymous_corpus_id,
                "label": author.label,
                "training_corpus_path": str(destination),
                "training_corpus_checksum": author.training_checksum,
                "train_work_count": len(author.train_works),
                "train_char_count": sum(work.char_count for work in author.train_works),
                "rights": author.rights,
            }
        )

    matrix = [
        {
            "case_id": case.case_id,
            "arm": "neutral",
            "target_author_id": None,
        }
        for case in manifest.cases
    ] + [
        {
            "case_id": case.case_id,
            "arm": "styled",
            "target_author_id": author.author_id,
            "training_corpus_checksum": author.training_checksum,
        }
        for case in manifest.cases
        for author in manifest.authors
    ]
    plan = {
        "schema_version": STYLE_BENCHMARK_SCHEMA_VERSION,
        "benchmark_id": manifest.benchmark_id,
        "manifest_version": manifest.manifest_version,
        "public_manifest_hash": manifest.public_manifest_hash,
        "boundary": {
            "private_manifest_loaded": False,
            "holdout_text_available_to_generator": False,
            "split_unit": "whole_work",
        },
        "generation_contract": {
            "neutral": "每个场景只生成一次中性结构稿，不注入任何目标风格。",
            "styled": "所有作者分支必须复用该场景同一份中性稿，并经 style_reference_module 生成。",
            "prompt_audit": "保存实际发送给模型的完整提示词到 actual_prompt_text，评分时检查隐藏语料泄漏。",
            "identity_blinding": "作者名、author_id、原篇名和原文件名不得进入模型请求；只发送匿名正文和抽象 Profile。",
            "lineage_fields": [
                "generation_path",
                "style_reference_profile_id",
                "reference_profile_ids",
                "training_corpus_checksum",
                "source_neutral_sha256",
            ],
        },
        "authors": authors,
        "cases": [case.public_payload() for case in manifest.cases],
        "matrix": matrix,
    }
    results_template = {
        "schema_version": 1,
        "benchmark_id": manifest.benchmark_id,
        "manifest_version": manifest.manifest_version,
        "public_manifest_hash": manifest.public_manifest_hash,
        "generations": [
            {
                "case_id": cell["case_id"],
                "arm": cell["arm"],
                "target_author_id": cell.get("target_author_id"),
                "generated_text": "",
                "actual_prompt_text": "",
                "generation_metadata": {
                    "generation_path": (
                        "neutral_draft"
                        if cell["arm"] == "neutral"
                        else "style_reference_module"
                    ),
                    "reference_profile_ids": [],
                    **(
                        {
                            "style_reference_profile_id": "",
                            "training_corpus_checksum": cell[
                                "training_corpus_checksum"
                            ],
                            "source_neutral_sha256": "",
                        }
                        if cell["arm"] == "styled"
                        else {}
                    ),
                },
            }
            for cell in matrix
        ],
    }
    _write_json(root / "generation_plan.json", plan)
    _write_json(root / "results_template.json", results_template)
    return {
        "output_dir": str(root),
        "generation_plan_path": str(root / "generation_plan.json"),
        "results_template_path": str(root / "results_template.json"),
        "training_corpus_paths": [row["training_corpus_path"] for row in authors],
        "matrix_cell_count": len(matrix),
        "public_manifest_hash": manifest.public_manifest_hash,
    }


def write_json(path: str | Path, payload: Any) -> None:
    _write_json(Path(path), payload)


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(f"{path.suffix}.tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    temporary.replace(path)
