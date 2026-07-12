"""Wave 4 — POV 减法投影（设计 §5.6 / §7.11 / 不变量 11）。

问题：`NarrativeEventLog.format_state_for_prompt` 与 `information_asymmetry_digest`
向**写作提示词**注入全量权威状态，包括非 POV 角色的 `secret_held_by` /
`believes_false` 正文——模型从输入层就看见了 POV 不该知道的秘密（G-05）。

本服务对**写作提示词**做减法投影：只保留 POV 应知的信息，抑制他人秘密内容。
硬 QC 仍读全量权威状态（`project_character_state` / `check_consistency` 不受影响）——
"机器守下限用全量，写作上限受 POV 约束"。

6 个知识级别（§5.6）由现有事件结构派生，无需 schema 迁移：

- ``public``       —— 非信息不对称键的事实（在场角色可观察），照旧注入
- ``secret_owner`` —— ``secret_held_by`` 事实：持有者知道、他人不知
- ``known``        —— POV 自身事实 ∪ POV 的 ``character_learns`` ∪ POV 持有/已被揭示的秘密
                       ∪ POV 在场场景断言的公共事实（回填启发式）
- ``believed_false``—— POV 的 ``believes_false``（POV 据此行动，注入）
- ``suspected``    —— POV 的 ``character_learns`` 且 ``payload_json.knowledge_status=='suspected'``
- ``unknown``      —— 其余，不注入

退化性质：只对信息不对称键做 POV 过滤，公共事实照旧。项目若无任何秘密/错误信念，
投影输出与全量注入等价——"无显式秘密标注 → 等价全量"是逐事实过滤的自然结果（§5.6）。

调用约定：``pov_character_id=None`` 表示全知视角（无单一受限 POV 可保护），委派回
``NarrativeEventLog`` 的全量实现——因此所有以 pov=None 调用的既有行为逐字节不变。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from novel_system.db.models import NarrativeEvent, SceneCard
from novel_system.services.narrative_event_log import (
    INFORMATION_ASYMMETRY_FACT_KEYS,
    NarrativeEventLog,
)

# 秘密性质的信息不对称键——这些键的**内容**受 POV 过滤；其余事实为公共。
_SECRET_CONTENT_KEYS = ("secret_held_by", "believes_false")


@dataclass(slots=True)
class PovProjection:
    """一次投影的结构化结果（供 digest 格式化与脱敏共用）。"""

    pov_character_id: str
    public_facts_by_char: dict[str, dict[str, str]] = field(default_factory=dict)
    pov_owned_secrets: list[tuple[str, str]] = field(default_factory=list)  # (key, value)
    suppressed_secret_owners: list[str] = field(default_factory=list)
    suppressed_secret_values: set[str] = field(default_factory=set)


class PovKnowledgeProjection:
    """POV 视角的写作提示词投影器。"""

    def __init__(self, session: Session) -> None:
        self.session = session
        self.log = NarrativeEventLog(session)

    # ------------------------------------------------------------------
    # 知识归属查询
    # ------------------------------------------------------------------

    def _pov_learns_events(
        self, pov_character_id: str, project_id: str, up_to_scene_seq: int,
    ) -> list[NarrativeEvent]:
        query = (
            select(NarrativeEvent)
            .where(
                NarrativeEvent.project_id == project_id,
                NarrativeEvent.entity_id == pov_character_id,
                NarrativeEvent.event_type == "character_learns",
                NarrativeEvent.scene_seq <= up_to_scene_seq,
            )
            .order_by(NarrativeEvent.scene_seq.asc(), NarrativeEvent.created_at.asc())
        )
        return list(self.session.execute(query).scalars().all())

    @staticmethod
    def _is_suspected(event: NarrativeEvent) -> bool:
        payload = event.payload_json or {}
        return str(payload.get("knowledge_status") or "").strip().lower() == "suspected"

    def _pov_learned_values(
        self, pov_character_id: str, project_id: str, up_to_scene_seq: int,
    ) -> set[str]:
        return {
            e.fact_value
            for e in self._pov_learns_events(pov_character_id, project_id, up_to_scene_seq)
        }

    def _onstage_public_values(
        self, project_id: str, pov_character_id: str, up_to_scene_seq: int,
    ) -> set[str]:
        """回填启发式：POV 在场场景断言的公共事实 → POV 已知（防饿死上下文，§5.6）。

        只取公共事实（非秘密键）；秘密不因"在场"默认已知（保守策略）。
        """
        scene_rows = self.session.execute(
            select(SceneCard.scene_id, SceneCard.onstage_chars_json, SceneCard.scene_seq)
            .where(SceneCard.project_id == project_id, SceneCard.scene_seq <= up_to_scene_seq)
        ).all()
        onstage_scene_ids = {
            sid for sid, onstage, _seq in scene_rows
            if isinstance(onstage, list) and pov_character_id in onstage
        }
        if not onstage_scene_ids:
            return set()
        events = self.session.execute(
            select(NarrativeEvent).where(
                NarrativeEvent.project_id == project_id,
                NarrativeEvent.scene_seq <= up_to_scene_seq,
            )
        ).scalars().all()
        return {
            e.fact_value
            for e in events
            if e.scene_id in onstage_scene_ids and e.fact_key not in INFORMATION_ASYMMETRY_FACT_KEYS
        }

    def pov_known_fact_values(
        self, project_id: str, scene_seq: int, pov_character_id: str,
    ) -> set[str]:
        """POV 已知的全部事实值集合——供脱敏与信息盲区判定。"""
        up_to = scene_seq - 1
        values: set[str] = set()
        own = self.log.project_character_state(pov_character_id, project_id, up_to_scene_seq=up_to)
        values |= {pf.fact_value for pf in own.facts.values()}
        values |= self._pov_learned_values(pov_character_id, project_id, up_to)
        values |= self._onstage_public_values(project_id, pov_character_id, up_to)
        return values

    def _secret_known_to_pov(
        self, secret_value: str, owner_id: str, pov_character_id: str,
        project_id: str, up_to_scene_seq: int,
    ) -> bool:
        if owner_id == pov_character_id:
            return True
        # 秘密已显式向 POV 揭示？
        revealed = self.session.execute(
            select(NarrativeEvent.fact_value).where(
                NarrativeEvent.project_id == project_id,
                NarrativeEvent.entity_id == owner_id,
                NarrativeEvent.fact_key == "revealed_to",
                NarrativeEvent.scene_seq <= up_to_scene_seq,
            )
        ).scalars().all()
        if pov_character_id in revealed:
            return True
        # POV 是否已获知该秘密内容（character_learns）？
        if secret_value in self._pov_learned_values(pov_character_id, project_id, up_to_scene_seq):
            return True
        return False

    def suppressed_secret_values(
        self, project_id: str, scene_seq: int, pov_character_id: str,
        onstage_character_ids: list[str] | None = None,
    ) -> set[str]:
        """非 POV 角色持有、且 POV 不知的秘密/错误信念内容集合。"""
        up_to = scene_seq - 1
        chars = onstage_character_ids or self.log._characters_in_project(project_id)
        values: set[str] = set()
        for char_id in chars:
            if char_id == pov_character_id:
                continue
            state = self.log.project_character_state(char_id, project_id, up_to_scene_seq=up_to)
            for key in _SECRET_CONTENT_KEYS:
                pf = state.facts.get(key)
                if pf and not self._secret_known_to_pov(
                    pf.fact_value, char_id, pov_character_id, project_id, up_to,
                ):
                    values.add(pf.fact_value)
        return values

    # ------------------------------------------------------------------
    # 写作提示词投影
    # ------------------------------------------------------------------

    def format_state_for_prompt(
        self,
        project_id: str,
        scene_seq: int,
        *,
        pov_character_id: str | None = None,
        onstage_character_ids: list[str] | None = None,
    ) -> str:
        """POV 过滤的权威状态摘要（写作提示词用）。

        pov=None → 委派回全量实现（全知视角，逐字节不变）。
        """
        if not pov_character_id:
            return self.log.format_state_for_prompt(
                project_id, scene_seq, onstage_character_ids=onstage_character_ids,
            )

        up_to = scene_seq - 1
        chars = onstage_character_ids or self.log._characters_in_project(project_id)
        lines: list[str] = [
            "## Authoritative Character State (from event log, do NOT contradict)",
        ]
        suppressed_owners: list[str] = []

        for char_id in chars:
            state = self.log.project_character_state(char_id, project_id, up_to_scene_seq=up_to)
            if not state.facts:
                continue
            visible: list[tuple[str, str]] = []
            for key, value in sorted(state.as_dict().items()):
                if key in INFORMATION_ASYMMETRY_FACT_KEYS:
                    if char_id == pov_character_id or self._secret_known_to_pov(
                        value, char_id, pov_character_id, project_id, up_to,
                    ):
                        visible.append((key, value))
                    elif key in _SECRET_CONTENT_KEYS and char_id not in suppressed_owners:
                        suppressed_owners.append(char_id)
                    # 非 POV 秘密内容：抑制（不注入）
                else:
                    visible.append((key, value))  # 公共事实
            if not visible:
                continue
            lines.append(f"\n### {char_id}")
            for key, value in visible:
                lines.append(f"- {key}: {value}")

        # POV 已知 / 怀疑（character_learns 分流）
        known_regular: list[tuple[str, str]] = []
        suspected: list[tuple[str, str]] = []
        for evt in self._pov_learns_events(pov_character_id, project_id, up_to):
            (suspected if self._is_suspected(evt) else known_regular).append(
                (evt.fact_key, evt.fact_value)
            )
        if known_regular:
            lines.append(f"\n### POV知识边界 ({pov_character_id} 已知信息)")
            for key, value in known_regular:
                lines.append(f"- {key}: {value}")
        if suspected:
            lines.append(f"\n### POV怀疑 ({pov_character_id} 尚未确证，勿写成既定事实)")
            for key, value in suspected:
                lines.append(f"- {key}: {value}（尚未确证/suspected）")

        # 信息差写作约束——内容无关（§5.6.4）
        if suppressed_owners:
            lines.append("\n## 写作约束（信息差·勿泄漏内容）")
            for owner in suppressed_owners:
                lines.append(
                    f"- 角色 {owner} 掌握 {pov_character_id} 未知的信息；"
                    f"勿在 {pov_character_id} 视角泄漏其内容。"
                )

        # 地点 / 物品状态（公共，保持全量实现一致）
        lines.extend(self._entity_state_lines(project_id, up_to))

        return "\n".join(lines) if len(lines) > 1 else ""

    def _entity_state_lines(self, project_id: str, up_to_scene_seq: int) -> list[str]:
        out: list[str] = []
        for entity_type, header in (
            ("location", "## Authoritative Location State (from event log, do NOT contradict)"),
            ("item", "## Authoritative Item State (from event log, do NOT contradict)"),
        ):
            ids = self.log._entities_of_type_in_project(project_id, entity_type)
            block: list[str] = []
            for eid in ids:
                state = self.log.project_entity_state(
                    entity_type, eid, project_id, up_to_scene_seq=up_to_scene_seq,
                )
                if state.facts:
                    block.append(f"\n### {eid}")
                    for key, value in sorted(state.as_dict().items()):
                        block.append(f"- {key}: {value}")
            if block:
                out.append("\n" + header)
                out.extend(block)
        return out

    def information_asymmetry_digest(
        self,
        project_id: str,
        scene_seq: int,
        onstage_character_ids: list[str],
        *,
        pov_character_id: str | None = None,
    ) -> str:
        """POV 视角的信息不对称摘要——只显示 POV 独有认知，他人独有内容仅给盲区提示。

        pov=None → 委派回全量实现（逐字节不变）。
        """
        if not pov_character_id:
            return self.log.information_asymmetry_digest(
                project_id, scene_seq, onstage_character_ids,
            )
        if len(onstage_character_ids) < 2:
            return ""

        up_to = scene_seq - 1
        lines: list[str] = [
            "## Information Asymmetry (POV-filtered, do NOT leak hidden content)",
        ]

        pov_knows = {
            f"{f.fact_key}:{f.fact_value}"
            for f in self.log.known_facts_for_character(
                pov_character_id, project_id, up_to_scene_seq=up_to,
            )
        }
        exclusive_lines: list[str] = []
        blind_owners: list[str] = []
        for other in onstage_character_ids:
            if other == pov_character_id:
                continue
            other_knows = {
                f"{f.fact_key}:{f.fact_value}"
                for f in self.log.known_facts_for_character(
                    other, project_id, up_to_scene_seq=up_to,
                )
            }
            for fact in sorted(pov_knows - other_knows):
                exclusive_lines.append(f"  - {fact}")
            other_state = self.log.project_character_state(other, project_id, up_to_scene_seq=up_to)
            has_secret = any(other_state.facts.get(k) for k in _SECRET_CONTENT_KEYS)
            if (other_knows - pov_knows) or has_secret:
                if other not in blind_owners:
                    blind_owners.append(other)

        if exclusive_lines:
            lines.append(f"\n### {pov_character_id} 独有认知（可据此行动）")
            # 去重保序
            seen: set[str] = set()
            for ln in exclusive_lines:
                if ln not in seen:
                    seen.add(ln)
                    lines.append(ln)
        if blind_owners:
            lines.append("\n### 信息盲区（勿在 POV 视角泄漏内容）")
            for owner in blind_owners:
                lines.append(f"  - 角色 {owner} 掌握 {pov_character_id} 未知的信息")

        pov_state = self.log.project_character_state(pov_character_id, project_id, up_to_scene_seq=up_to)
        own_secrets = [pov_state.facts[k].fact_value for k in _SECRET_CONTENT_KEYS if pov_state.facts.get(k)]
        if own_secrets:
            lines.append(f"\n### {pov_character_id} 自身秘密/信念")
            for s in own_secrets:
                lines.append(f"  - {s}")

        return "\n".join(lines) if len(lines) > 1 else ""

    # ------------------------------------------------------------------
    # finding 证据脱敏（§7.11 / 不变量 11）
    # ------------------------------------------------------------------

    @staticmethod
    def _finding_blob(finding: Any) -> str:
        if isinstance(finding, str):
            return finding
        if isinstance(finding, dict):
            parts: list[str] = []
            for key in (
                "authority_ref", "expected", "actual", "evidence", "message",
                "instruction", "recommended_action",
            ):
                val = finding.get(key)
                if val:
                    parts.append(str(val))
            details = finding.get("details")
            if isinstance(details, dict):
                parts.append(" ".join(str(v) for v in details.values()))
            spans = finding.get("evidence_spans")
            if isinstance(spans, list):
                parts.append(" ".join(str(s) for s in spans))
            return " ".join(parts)
        return str(finding)

    def desensitize_findings(
        self,
        findings: list[Any],
        project_id: str,
        scene_seq: int,
        *,
        pov_character_id: str | None = None,
        onstage_character_ids: list[str] | None = None,
    ) -> tuple[list[Any], list[Any]]:
        """把回灌自动补丁的 finding 拆成 (safe, redacted)。

        引用了非 POV 已知秘密的 finding 不得进入自动补丁提示词，改标
        ``author_confirmation_only`` 走作者确认修订（不变量 11）。pov=None 或无秘密
        时全部放行。硬 QC 自身不经此路径（始终读全量）。
        """
        if not findings or not pov_character_id:
            return list(findings), []
        suppressed = self.suppressed_secret_values(
            project_id, scene_seq, pov_character_id, onstage_character_ids,
        )
        if not suppressed:
            return list(findings), []
        safe: list[Any] = []
        redacted: list[Any] = []
        for finding in findings:
            blob = self._finding_blob(finding)
            if any(sv and sv in blob for sv in suppressed):
                if isinstance(finding, dict):
                    redacted.append({
                        **finding,
                        "author_confirmation_only": True,
                        "desensitized_reason": "references_non_pov_secret",
                    })
                else:
                    redacted.append(finding)
            else:
                safe.append(finding)
        return safe, redacted

    def redact_brief(
        self,
        brief_lines: list[str],
        project_id: str,
        scene_seq: int,
        *,
        pov_character_id: str | None = None,
        onstage_character_ids: list[str] | None = None,
    ) -> list[str]:
        """从自动补丁 brief（``list[str]`` 指令）中剔除引用非 POV 秘密的条目。"""
        safe, _redacted = self.desensitize_findings(
            list(brief_lines), project_id, scene_seq,
            pov_character_id=pov_character_id,
            onstage_character_ids=onstage_character_ids,
        )
        return [s for s in safe if isinstance(s, str)]
