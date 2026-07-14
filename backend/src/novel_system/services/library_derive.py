"""FE-ALIGN Phase 6: 资料库半自动派生（D5 默认）。

成稿归档钩子（P7 写回链）或手动触发：从章节正文提取候选实体/别名/时间线事件，
**不直接入库** —— 产 idea 卡进待办（dedupe_key=derive:{chapter}:{name}），
actions=[确认入库（effect create_entity / add_timeline_event）、忽略]。

LLM 未配置时静默跳过（不阻塞归档）；任务路由 config/models.yaml 的
`library_derive` 节点 + 提示词 config/prompts.yaml（走 call_llm_node 既有模式）。
"""
from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from novel_system.db.models import (
    AuthorDraft,
    ChapterGoal,
    LibraryEntity,
    SceneCard,
    StoryCharacter,
)
from novel_system.services.catalog import chapter_title
from novel_system.services.errors import DomainError
from novel_system.services.llm_accounting import LLMCallContext
from novel_system.services.review_cards import ReviewCardService
from novel_system.settings import get_settings

logger = logging.getLogger(__name__)

DERIVE_NODE_ID = "library_derive"


class LibraryDeriveService:
    def __init__(self, session: Session, *, llm_client: Any | None = None) -> None:
        self.session = session
        self._llm_client = llm_client

    def derive_from_chapter(self, project_id: str, chapter_id: str) -> dict[str, Any]:
        if not chapter_id:
            raise DomainError("LIBRARY_DERIVE_CHAPTER_REQUIRED", "chapter_id is required", status_code=400)
        settings = get_settings()
        if not settings.llm_enabled:
            # author_action 模式：提示而不阻塞
            return {
                "skipped": True,
                "reason": "llm_disabled",
                "author_action": {
                    "title": "未配置 LLM",
                    "message": "资料派生需要启用 LLM。归档不受影响；配置后可在资料库手动重跑派生。",
                    "target_view": "system-config",
                },
            }
        content = self._chapter_text(project_id, chapter_id)
        if not content.strip():
            return {"skipped": True, "reason": "no_content"}
        candidates = self._extract(project_id, chapter_id, content)
        created = self._push_cards(project_id, chapter_id, candidates)
        return {"skipped": False, "candidates": len(candidates), "cards_created": created}

    # ---- internals ----

    def _chapter_text(self, project_id: str, chapter_id: str) -> str:
        scene_ids = [
            row
            for row in self.session.execute(
                select(SceneCard.scene_id).where(
                    SceneCard.chapter_id == chapter_id, SceneCard.trashed_flag == 0
                )
            ).scalars().all()
        ]
        if not scene_ids:
            return ""
        drafts = self.session.execute(
            select(AuthorDraft).where(
                AuthorDraft.object_type == "scene",
                AuthorDraft.object_id.in_(scene_ids),
                AuthorDraft.status == "current",
            )
        ).scalars().all()
        return "\n\n".join(d.content for d in drafts if d.content)

    def _known_names(self, project_id: str) -> set[str]:
        names = {
            row
            for row in self.session.execute(
                select(LibraryEntity.name).where(LibraryEntity.project_id == project_id)
            ).scalars().all()
        }
        names |= {
            row
            for row in self.session.execute(
                select(StoryCharacter.display_name).where(StoryCharacter.project_id == project_id)
            ).scalars().all()
        }
        return names

    def _build_client(self) -> Any:
        from novel_system.services.llm_client import LLMClient
        from novel_system.services.system_config import load_llm_provider_runtime_configs

        settings = get_settings()
        return LLMClient(
            provider=settings.llm_provider,
            base_url=settings.llm_base_url,
            api_key=settings.llm_api_key,
            timeout_seconds=settings.llm_timeout_seconds,
            provider_configs=load_llm_provider_runtime_configs(),
        )

    def _extract(self, project_id: str, chapter_id: str, content: str) -> list[dict[str, Any]]:
        from novel_system.services.style_reference._llm_helper import LLMNodeError, call_llm_node
        from novel_system.services.style_reference.untrusted_data import UntrustedPayload

        client = self._llm_client or self._build_client()
        payload = {
            "chapter_text": content[:12000],
            "known_names": sorted(self._known_names(project_id)),
        }
        try:
            structured = call_llm_node(
                DERIVE_NODE_ID,
                UntrustedPayload(payload),
                client,
                session=self.session,
                context=LLMCallContext(
                    scope_type="project",
                    scope_id=project_id,
                    project_id=project_id,
                    chapter_id=chapter_id,
                    node_id=DERIVE_NODE_ID,
                    step=f"library_derive:{chapter_id}",
                ),
            )
        except LLMNodeError as exc:
            logger.warning("library derive llm call failed: %s", exc)
            return []
        out: list[dict[str, Any]] = []
        for item in structured.get("entities") or []:
            name = str((item or {}).get("name") or "").strip()
            if not name:
                continue
            out.append(
                {
                    "candidate_type": "entity",
                    "name": name,
                    "kind": str(item.get("kind") or "concept"),
                    "summary": str(item.get("summary") or ""),
                    "aliases": list(item.get("aliases") or []),
                }
            )
        for item in structured.get("timeline_events") or []:
            label = str((item or {}).get("label") or "").strip()
            if not label:
                continue
            out.append(
                {
                    "candidate_type": "timeline_event",
                    "name": label,
                    "time_label": str(item.get("time_label") or ""),
                    "note": str(item.get("note") or ""),
                }
            )
        return out

    def _push_cards(self, project_id: str, chapter_id: str, candidates: list[dict[str, Any]]) -> int:
        cards = ReviewCardService(self.session)
        chapter = self.session.get(ChapterGoal, chapter_id)
        chapter_label = chapter_title(chapter) if chapter is not None else chapter_id
        known = self._known_names(project_id)
        created = 0
        for cand in candidates:
            if cand["name"] in known:
                continue
            if cand["candidate_type"] == "entity":
                effect = {
                    "type": "create_entity",
                    "name": cand["name"],
                    "kind": cand.get("kind") or "concept",
                    "summary": cand.get("summary") or "",
                    "aliases": cand.get("aliases") or [],
                }
                detail = f"归档《{chapter_label}》时提取到新设定「{cand['name']}」。确认后会作为实体进入资料库与关系图。"
            else:
                effect = {
                    "type": "add_timeline_event",
                    "label": cand["name"],
                    "time_label": cand.get("time_label") or "",
                    "chapter_ref": chapter_label,
                    "note": cand.get("note") or "",
                }
                detail = f"归档《{chapter_label}》时提取到时间线事件「{cand['name']}」。确认后会进入大事记。"
            result = cards.create_card(
                {
                    "project_id": project_id,
                    "kind": "idea",
                    "priority": 2,
                    "title": f"发现新{'设定' if cand['candidate_type'] == 'entity' else '事件'}：{cand['name']}",
                    "source": "资料派生",
                    "where": f"成稿归档 · {chapter_label}",
                    "detail": detail,
                    "dedupe_key": f"derive:{chapter_id}:{cand['name']}",
                    "actions": [
                        {"label": "确认入库", "intent": "primary", "op": "resolve", "effect": effect},
                        {"label": "忽略", "intent": "quiet", "op": "resolve"},
                    ],
                },
                actor_ref="library_derive",
            )
            if not result.get("deduped"):
                created += 1
        return created
