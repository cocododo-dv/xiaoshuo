"""SceneExtractor:场景层 4 sub_dim 抽取(PR-6,quality_strong / gpt-5)。

sub_dim:
- scene.environment        — 场所/天气/自然物呈现机制
- scene.character_portrayal — 人物外貌/衣着/神态/行为展示
- scene.dialogue           — 对话密度/长短/轮次/隐喻性
- scene.sensory_priority   — 五感优先级与并置
"""

from __future__ import annotations

from novel_system.services.style_reference.dimensions import Layer
from novel_system.services.style_reference.extractors.base import BaseExtractor


class SceneExtractor(BaseExtractor):
    layer = Layer.SCENE
    extract_node_id = "style_ref_extract_scene"
