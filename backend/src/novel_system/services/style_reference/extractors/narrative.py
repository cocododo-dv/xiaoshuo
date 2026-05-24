"""NarrativeExtractor:叙事层 4 sub_dim 抽取(quality_strong / gpt-5)。

sub_dim:
- narrative.perspective
- narrative.pacing
- narrative.time_handling
- narrative.information_density
"""

from __future__ import annotations

from novel_system.services.style_reference.dimensions import Layer
from novel_system.services.style_reference.extractors.base import BaseExtractor


class NarrativeExtractor(BaseExtractor):
    layer = Layer.NARRATIVE
    extract_node_id = "style_ref_extract_narrative"
