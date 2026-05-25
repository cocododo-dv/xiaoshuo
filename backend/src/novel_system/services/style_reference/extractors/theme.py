"""ThemeExtractor:主题层 4 sub_dim 抽取(PR-6,quality_strong / gpt-5)。

sub_dim:
- theme.emotional_tone        — 情绪基调与节奏
- theme.values                — 价值观倾向
- theme.motifs                — 反复意象与母题
- theme.narrative_philosophy  — 对人/历史/命运的态度
"""

from __future__ import annotations

from novel_system.services.style_reference.dimensions import Layer
from novel_system.services.style_reference.extractors.base import BaseExtractor


class ThemeExtractor(BaseExtractor):
    layer = Layer.THEME
    extract_node_id = "style_ref_extract_theme"
