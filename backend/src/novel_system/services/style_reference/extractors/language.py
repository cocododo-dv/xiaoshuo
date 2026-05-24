"""LanguageExtractor:语言层 4 sub_dim 抽取(quality_strong / gpt-5)。

sub_dim:
- language.sentence_structure
- language.vocabulary
- language.rhetoric
- language.punctuation
"""

from __future__ import annotations

from novel_system.services.style_reference.dimensions import Layer
from novel_system.services.style_reference.extractors.base import BaseExtractor


class LanguageExtractor(BaseExtractor):
    layer = Layer.LANGUAGE
    extract_node_id = "style_ref_extract_language"
