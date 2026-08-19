"""跨内容风格参考基准。

公开侧只负责训练语料与生成矩阵；隐藏侧只在评分时加载整篇留出作品。
"""

from novel_system.services.style_reference.benchmark.manifest import (
    StyleBenchmarkBundle,
    StyleBenchmarkManifest,
    load_style_benchmark,
    load_style_benchmark_manifest,
)
from novel_system.services.style_reference.benchmark.live import (
    run_live_benchmark_workspace,
)
from novel_system.services.style_reference.benchmark.scoring import (
    build_blind_review_artifacts,
    score_style_benchmark,
)

__all__ = [
    "StyleBenchmarkBundle",
    "StyleBenchmarkManifest",
    "build_blind_review_artifacts",
    "load_style_benchmark",
    "load_style_benchmark_manifest",
    "run_live_benchmark_workspace",
    "score_style_benchmark",
]
