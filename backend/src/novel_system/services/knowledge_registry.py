from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from novel_system.db.models import (
    BannedRuleCluster,
    CalibrationLine,
    ChapterMemory,
    ForeshadowTracker,
    NarrativePattern,
    RelationProfile,
    SceneMemory,
    StyleObservation,
    StyleRule,
    VoiceProfile,
    WorldRule,
)

KnowledgeStorageKind = Literal["vector", "direct", "foreshadow", "scene_summary", "chapter_summary"]
KnowledgeScopeKind = Literal["scoped", "character", "relation", "foreshadow", "scene", "chapter"]


@dataclass(frozen=True)
class KnowledgeDescriptor:
    item_types: tuple[str, ...]
    object_type: str
    storage_kind: KnowledgeStorageKind
    model_cls: type[Any]
    lineage_field: str
    text_field: str
    row_prefix: str
    target_collection: str
    scope_kind: KnowledgeScopeKind


DESCRIPTORS: tuple[KnowledgeDescriptor, ...] = (
    KnowledgeDescriptor(
        item_types=("style_observation",),
        object_type="style_observation",
        storage_kind="vector",
        model_cls=StyleObservation,
        lineage_field="style_observation_id",
        text_field="text",
        row_prefix="style_observation",
        target_collection="style_observations",
        scope_kind="scoped",
    ),
    KnowledgeDescriptor(
        item_types=("style_rule_set",),
        object_type="style_rule",
        storage_kind="direct",
        model_cls=StyleRule,
        lineage_field="style_rule_set_id",
        text_field="content",
        row_prefix="style_rule",
        target_collection="style_rules",
        scope_kind="scoped",
    ),
    KnowledgeDescriptor(
        item_types=("banned_rule_cluster",),
        object_type="banned_rule_cluster",
        storage_kind="direct",
        model_cls=BannedRuleCluster,
        lineage_field="banned_cluster_id",
        text_field="content",
        row_prefix="banned_rule_cluster",
        target_collection="banned_rule_clusters",
        scope_kind="scoped",
    ),
    KnowledgeDescriptor(
        item_types=("narrative_pattern",),
        object_type="narrative_pattern",
        storage_kind="direct",
        model_cls=NarrativePattern,
        lineage_field="narrative_pattern_id",
        text_field="content",
        row_prefix="narrative_pattern",
        target_collection="narrative_patterns",
        scope_kind="scoped",
    ),
    KnowledgeDescriptor(
        item_types=("voice_card_candidate",),
        object_type="voice_card",
        storage_kind="direct",
        model_cls=VoiceProfile,
        lineage_field="voice_profile_id",
        text_field="content",
        row_prefix="voice_card",
        target_collection="voice_cards",
        scope_kind="character",
    ),
    KnowledgeDescriptor(
        item_types=("relation_card_candidate",),
        object_type="relation_card",
        storage_kind="direct",
        model_cls=RelationProfile,
        lineage_field="relation_profile_id",
        text_field="content",
        row_prefix="relation_card",
        target_collection="relation_cards",
        scope_kind="relation",
    ),
    KnowledgeDescriptor(
        item_types=("world_rule",),
        object_type="world_rule",
        storage_kind="direct",
        model_cls=WorldRule,
        lineage_field="world_rule_id",
        text_field="content",
        row_prefix="world_rule",
        target_collection="world_rules",
        scope_kind="scoped",
    ),
    KnowledgeDescriptor(
        item_types=("calibration_candidate",),
        object_type="calibration_line",
        storage_kind="vector",
        model_cls=CalibrationLine,
        lineage_field="calibration_line_id",
        text_field="text",
        row_prefix="calibration_line",
        target_collection="calibration_lines",
        scope_kind="scoped",
    ),
    KnowledgeDescriptor(
        item_types=("foreshadow_open", "foreshadow_touch", "foreshadow_resolve"),
        object_type="foreshadow",
        storage_kind="foreshadow",
        model_cls=ForeshadowTracker,
        lineage_field="foreshadow_id",
        text_field="text",
        row_prefix="foreshadow",
        target_collection="foreshadow_tracker",
        scope_kind="foreshadow",
    ),
    KnowledgeDescriptor(
        item_types=("scene_summary",),
        object_type="scene_summary",
        storage_kind="scene_summary",
        model_cls=SceneMemory,
        lineage_field="scene_id",
        text_field="content",
        row_prefix="scene_memory",
        target_collection="scene_memories",
        scope_kind="scene",
    ),
    KnowledgeDescriptor(
        item_types=("chapter_summary",),
        object_type="chapter_summary",
        storage_kind="chapter_summary",
        model_cls=ChapterMemory,
        lineage_field="chapter_id",
        text_field="content",
        row_prefix="chapter_memory",
        target_collection="chapter_memories",
        scope_kind="chapter",
    ),
)

_DESCRIPTOR_BY_ITEM_TYPE = {
    item_type: descriptor
    for descriptor in DESCRIPTORS
    for item_type in descriptor.item_types
}
_DESCRIPTOR_BY_OBJECT_TYPE = {descriptor.object_type: descriptor for descriptor in DESCRIPTORS}


def descriptor_for_item_type(item_type: str) -> KnowledgeDescriptor:
    descriptor = _DESCRIPTOR_BY_ITEM_TYPE.get(item_type)
    if descriptor is None:
        raise KeyError(item_type)
    return descriptor


def descriptor_for_object_type(object_type: str) -> KnowledgeDescriptor:
    descriptor = _DESCRIPTOR_BY_OBJECT_TYPE.get(object_type)
    if descriptor is None:
        raise KeyError(object_type)
    return descriptor


def all_descriptors() -> tuple[KnowledgeDescriptor, ...]:
    return DESCRIPTORS
