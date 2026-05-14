from __future__ import annotations

import hashlib
import re
import threading
import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from novel_system.db.models import (
    ChapterGoal,
    ChapterRunJob,
    ChapterState,
    FinalScene,
    OperationLog,
    OutlinePlan,
    ReferenceProfile,
    SceneCard,
    SceneRunState,
    StoryProject,
    utcnow,
)
from novel_system.db.session import SessionLocal
from novel_system.services.chapter_manuscripts import ChapterManuscriptService
from novel_system.services.chapter_runner import ChapterRunnerService
from novel_system.services.errors import DomainError
from novel_system.services.hash_engine import canonical_json
from novel_system.services.llm_task_runner import LLMNodeExecutionError, LLMNodeRunner
from novel_system.services.project_backtracks import ProjectBacktrackService
from novel_system.services.prompt_builder import PromptBuilder
from novel_system.services.snowflake_steps import SNOWFLAKE_METHOD_VERSION
from novel_system.settings import get_settings

PROJECT_STATUS_OUTLINE_DRAFT = "outline_draft"
PROJECT_STATUS_OUTLINE_REVIEW = "outline_review"
PROJECT_STATUS_CHAPTER_READY = "chapter_ready"
PROJECT_STATUS_CHAPTER_RUNNING = "chapter_running"
PROJECT_STATUS_CHAPTER_BLOCKED = "chapter_blocked"
PROJECT_STATUS_CHAPTER_FINAL_REVIEW = "chapter_final_review"
PROJECT_STATUS_COMPLETED = "completed"

PLAN_STATUS_PENDING_REVIEW = "pending_review"
PLAN_STATUS_APPROVED = "approved"

REFERENCE_SAFETY_RULES = [
    "参考书只进入抽象风格画像，不复制原文表达。",
    "不得复刻参考书人物、设定、桥段、特殊意象或标志性句式。",
    "运行时只使用节奏、句法、叙事手法、结构技巧和禁复刻规则。",
]


class ProjectService:
    def __init__(self, session: Session) -> None:
        self.session = session

    def create(self, payload: dict[str, Any]) -> dict[str, Any]:
        outline_text = str(payload.get("outline_text") or "").strip()
        if not outline_text:
            raise DomainError("PROJECT_OUTLINE_REQUIRED", "outline_text is required", status_code=400)

        planning_mode = _planning_mode(payload.get("planning_mode"))
        project = StoryProject(
            project_id=self._next_project_id(),
            title=str(payload.get("title") or "未命名小说").strip() or "未命名小说",
            genre=_optional_text(payload.get("genre")),
            target_word_count=_optional_positive_int(payload.get("target_word_count")),
            target_chapter_count=_optional_positive_int(payload.get("target_chapter_count")),
            outline_text=outline_text,
            planning_mode=planning_mode,
            snowflake_schema_version=SNOWFLAKE_METHOD_VERSION if planning_mode == "snowflake" else None,
            status=PROJECT_STATUS_OUTLINE_DRAFT,
            approved_chapter_ids_json=[],
            reference_profile_ids_json=[],
        )
        self.session.add(project)
        self.session.flush()
        return {"project": project_payload(project)}

    def list(self) -> dict[str, Any]:
        projects = self.session.execute(
            select(StoryProject).order_by(StoryProject.created_at.desc(), StoryProject.project_id.desc())
        ).scalars().all()
        return {"items": [project_summary_payload(project) for project in projects]}

    def dashboard(self, project_id: str) -> dict[str, Any]:
        project = self.require_project(project_id)
        latest_plan = self._latest_plan(project_id)
        chapters = self._chapter_payloads(project_id)
        current_chapter = next(
            (chapter for chapter in chapters if chapter["chapter_id"] == project.current_chapter_id),
            None,
        )
        backtrack_items = ProjectBacktrackService(self.session).list(project_id)["items"]
        return {
            "project": project_payload(project),
            "latest_plan": outline_plan_payload(latest_plan) if latest_plan else None,
            "chapters": chapters,
            "current_chapter": current_chapter,
            "reference_profiles": self._reference_profile_payloads(project),
            "backtrack_items": backtrack_items,
            "review_packet": ProjectChapterFlowService(self.session).review_packet(project, project.current_chapter_id),
            "next_action": self._next_action(project, latest_plan, backtrack_items=backtrack_items),
            "runtime": {
                "llm_enabled": bool(get_settings().llm_enabled),
                "generation_mode": "live" if get_settings().llm_enabled else "offline_disabled",
            },
        }

    def attach_reference_profile(self, project_id: str, profile_id: str) -> dict[str, Any]:
        project = self.require_project(project_id)
        profile = self.session.get(ReferenceProfile, profile_id)
        if profile is None:
            raise DomainError("REFERENCE_PROFILE_NOT_FOUND", "reference profile not found", status_code=404)
        if profile.status != "ready":
            raise DomainError(
                "REFERENCE_PROFILE_NOT_READY",
                "reference profile must be ready before binding to a project",
                status_code=409,
            )

        profile_ids = list(project.reference_profile_ids_json or [])
        if profile.profile_id not in profile_ids:
            profile_ids.append(profile.profile_id)
        project.reference_profile_ids_json = profile_ids
        self.session.flush()
        return {
            "project": project_payload(project),
            "reference_profile": reference_profile_payload(profile),
        }

    def approve_outline_plan(self, project_id: str, plan_id: str) -> dict[str, Any]:
        project = self.require_project(project_id)
        plan = self._require_plan(project_id, plan_id)
        if plan.status == PLAN_STATUS_APPROVED:
            return self._approved_plan_result(project, plan)
        if plan.status != PLAN_STATUS_PENDING_REVIEW:
            raise DomainError("OUTLINE_PLAN_NOT_REVIEWABLE", "outline plan is not pending review")

        chapters = list((plan.plan_json or {}).get("chapters") or [])
        if not chapters:
            raise DomainError("OUTLINE_PLAN_EMPTY", "outline plan has no chapters", status_code=422)

        created_chapter_count = 0
        created_scene_count = 0
        for chapter_plan in chapters:
            chapter_id = str(chapter_plan.get("chapter_id") or "").strip()
            if not chapter_id:
                raise DomainError("OUTLINE_PLAN_INVALID", "chapter_id is required", status_code=422)
            chapter = self.session.get(ChapterGoal, chapter_id)
            if chapter is None:
                chapter = ChapterGoal(chapter_id=chapter_id, chapter_goal="")
                self.session.add(chapter)
                created_chapter_count += 1
            elif chapter.project_id and chapter.project_id != project.project_id:
                raise DomainError("CHAPTER_ALREADY_OWNED", "chapter belongs to another project")

            chapter.project_id = project.project_id
            chapter.outline_plan_id = plan.plan_id
            chapter.planned_scene_count = len(chapter_plan.get("scenes") or [])
            chapter.mid_aggregate_enabled = 0
            chapter.chapter_goal = str(chapter_plan.get("chapter_goal") or chapter_plan.get("title") or chapter_id)
            chapter.main_plot_push = _optional_text(chapter_plan.get("main_plot_push"))
            chapter.emotional_target = _optional_text(chapter_plan.get("emotional_target"))
            chapter.ending_effect = _optional_text(chapter_plan.get("ending_effect"))
            chapter.must_not = _optional_text(chapter_plan.get("must_not"))
            chapter.notes = _optional_text(chapter_plan.get("notes"))
            chapter.writer_brief_json = {
                "source": (plan.plan_json or {}).get("source") or "project_outline_plan",
                "project_id": project.project_id,
                "outline_plan_id": plan.plan_id,
                "chapter_title": chapter_plan.get("title"),
                "reference_safety": list((plan.plan_json or {}).get("reference_safety") or REFERENCE_SAFETY_RULES),
                **dict(chapter_plan.get("writer_brief_json") or {}),
            }

            state = self.session.get(ChapterState, chapter.chapter_id)
            if state is None:
                self.session.add(
                    ChapterState(
                        chapter_id=chapter.chapter_id,
                        current_phase="drafting",
                        mid_aggregate_enabled_effective=0,
                        aggregate_block_reason="none",
                    )
                )

            scenes = list(chapter_plan.get("scenes") or [])
            for index, scene_plan in enumerate(scenes, start=1):
                scene_id = str(scene_plan.get("scene_id") or f"{chapter_id}_SC{index:02d}").strip()
                scene = self.session.get(SceneCard, scene_id)
                if scene is None:
                    scene = SceneCard(scene_id=scene_id, chapter_id=chapter_id, scene_seq=index, scene_goal="")
                    self.session.add(scene)
                    created_scene_count += 1
                elif scene.project_id and scene.project_id != project.project_id:
                    raise DomainError("SCENE_ALREADY_OWNED", "scene belongs to another project")

                scene.chapter_id = chapter_id
                scene.project_id = project.project_id
                scene.outline_plan_id = plan.plan_id
                scene.scene_seq = int(scene_plan.get("scene_seq") or index)
                scene.pov_character_id = _optional_text(scene_plan.get("pov_character_id"))
                scene.onstage_chars_json = _string_list(scene_plan.get("onstage_chars_json"))
                scene.location = _optional_text(scene_plan.get("location"))
                scene.scene_goal = str(scene_plan.get("scene_goal") or chapter.chapter_goal)
                scene.beats_json = _string_list(scene_plan.get("beats_json")) or [scene.scene_goal]
                scene.must_include_text = _optional_text(scene_plan.get("must_include_text"))
                scene.forbidden_text = _optional_text(scene_plan.get("forbidden_text")) or "不得复制参考书原文表达、人物、设定或桥段。"
                scene.exit_change = _optional_text(scene_plan.get("exit_change"))
                scene.hook = _optional_text(scene_plan.get("hook"))
                scene.target_length_band = _optional_text(scene_plan.get("target_length_band")) or "medium"
                scene.scene_type = _optional_text(scene_plan.get("scene_type")) or "outline_driven"
                scene.is_chapter_last = 1 if index == len(scenes) else 0
                scene.writer_brief_json = {
                    "source": (plan.plan_json or {}).get("source") or "project_outline_plan",
                    "project_id": project.project_id,
                    "outline_plan_id": plan.plan_id,
                    "reference_safety": list((plan.plan_json or {}).get("reference_safety") or REFERENCE_SAFETY_RULES),
                    **dict(scene_plan.get("writer_brief_json") or {}),
                }

                if self.session.get(SceneRunState, scene.scene_id) is None:
                    self.session.add(SceneRunState(scene_id=scene.scene_id, scene_status="ready"))

        plan.status = PLAN_STATUS_APPROVED
        plan.approved_at = utcnow()
        project.active_outline_plan_id = plan.plan_id
        project.current_chapter_id = str(chapters[0]["chapter_id"])
        project.status = PROJECT_STATUS_CHAPTER_READY
        self.session.flush()
        return {
            "project": project_payload(project),
            "plan": outline_plan_payload(plan),
            "created_chapter_count": created_chapter_count,
            "created_scene_count": created_scene_count,
        }

    def require_project(self, project_id: str) -> StoryProject:
        project = self.session.get(StoryProject, project_id)
        if project is None:
            raise DomainError("PROJECT_NOT_FOUND", "project not found", status_code=404)
        return project

    def _approved_plan_result(self, project: StoryProject, plan: OutlinePlan) -> dict[str, Any]:
        chapters = self._chapter_payloads(project.project_id)
        scene_count = sum(len(chapter.get("scenes") or []) for chapter in chapters)
        return {
            "project": project_payload(project),
            "plan": outline_plan_payload(plan),
            "created_chapter_count": len(chapters),
            "created_scene_count": scene_count,
        }

    def _require_plan(self, project_id: str, plan_id: str) -> OutlinePlan:
        plan = self.session.get(OutlinePlan, plan_id)
        if plan is None or plan.project_id != project_id:
            raise DomainError("OUTLINE_PLAN_NOT_FOUND", "outline plan not found", status_code=404)
        return plan

    def _latest_plan(self, project_id: str) -> OutlinePlan | None:
        return self.session.execute(
            select(OutlinePlan)
            .where(OutlinePlan.project_id == project_id)
            .order_by(OutlinePlan.version.desc(), OutlinePlan.created_at.desc())
        ).scalars().first()

    def _chapter_payloads(self, project_id: str) -> list[dict[str, Any]]:
        chapters = self.session.execute(
            select(ChapterGoal)
            .where(ChapterGoal.project_id == project_id, ChapterGoal.trashed_flag == 0)
            .order_by(ChapterGoal.chapter_id.asc())
        ).scalars().all()
        return [chapter_payload(self.session, chapter) for chapter in chapters]

    def _reference_profile_payloads(self, project: StoryProject) -> list[dict[str, Any]]:
        profile_ids = list(project.reference_profile_ids_json or [])
        if not profile_ids:
            return []
        profiles = self.session.execute(
            select(ReferenceProfile).where(ReferenceProfile.profile_id.in_(profile_ids))
        ).scalars().all()
        by_id = {profile.profile_id: profile for profile in profiles}
        return [reference_profile_payload(by_id[profile_id]) for profile_id in profile_ids if profile_id in by_id]

    def _next_action(self, project: StoryProject, latest_plan: OutlinePlan | None, *, backtrack_items: list[dict[str, Any]] | None = None) -> str:
        if any(item.get("status") == "pending" for item in (backtrack_items or [])):
            return "resolve_backtrack_items"
        if project.status == PROJECT_STATUS_COMPLETED:
            return "completed"
        if project.status == PROJECT_STATUS_CHAPTER_FINAL_REVIEW:
            return "approve_chapter_final"
        if project.status == PROJECT_STATUS_CHAPTER_RUNNING:
            return "view_chapter_progress"
        if project.status == PROJECT_STATUS_CHAPTER_READY:
            return "run_current_chapter"
        if project.status == PROJECT_STATUS_CHAPTER_BLOCKED:
            return "resolve_blocker"
        if latest_plan and latest_plan.status == PLAN_STATUS_PENDING_REVIEW:
            return "approve_outline_plan"
        return "generate_outline_plan"

    def _next_project_id(self) -> str:
        while True:
            project_id = f"PRJ_{uuid.uuid4().hex[:10].upper()}"
            if self.session.get(StoryProject, project_id) is None:
                return project_id


class OutlinePlannerService:
    def __init__(self, session: Session) -> None:
        self.session = session
        self._prompt_builder = PromptBuilder()

    def generate(self, project_id: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        project = ProjectService(self.session).require_project(project_id)
        version = self._next_version(project.project_id)
        plan = OutlinePlan(
            plan_id=f"outline_plan_{project.project_id}_{version:02d}_{uuid.uuid4().hex[:8]}",
            project_id=project.project_id,
            version=version,
            status=PLAN_STATUS_PENDING_REVIEW,
            plan_json=self._build_plan(project, payload or {}),
        )
        project.status = PROJECT_STATUS_OUTLINE_REVIEW
        self.session.add(plan)
        self.session.flush()
        return {"plan": outline_plan_payload(plan), "project": project_payload(project)}

    def _next_version(self, project_id: str) -> int:
        latest = self.session.execute(
            select(OutlinePlan.version)
            .where(OutlinePlan.project_id == project_id)
            .order_by(OutlinePlan.version.desc())
        ).scalar()
        return int(latest or 0) + 1

    def _build_plan(self, project: StoryProject, payload: dict[str, Any]) -> dict[str, Any]:
        if get_settings().llm_enabled:
            return self._build_llm_plan(project, payload)
        return self._build_local_plan(project, payload)

    def _build_llm_plan(self, project: StoryProject, payload: dict[str, Any]) -> dict[str, Any]:
        chapter_count = _optional_positive_int(payload.get("target_chapter_count")) or project.target_chapter_count or 2
        chapter_count = max(1, min(int(chapter_count), 80))
        reference_safety = list(REFERENCE_SAFETY_RULES)
        snapshot = {
            "project": project_payload(project),
            "target_chapter_count": chapter_count,
            "outline_text": project.outline_text,
            "reference_safety": reference_safety,
            "planning_constraints": {
                "original_only": True,
                "avoid_source_book_names_settings_plot_or_signature_imagery": True,
                "required_scene_fields": [
                    "scene_goal",
                    "beats_json",
                    "exit_change",
                    "hook",
                    "target_length_band",
                    "scene_type",
                ],
            },
        }
        prompt = self._prompt_builder.build(snapshot, "project_outline_plan")
        bundle_hash = hashlib.sha256(canonical_json(snapshot).encode("utf-8")).hexdigest()
        try:
            result = LLMNodeRunner(self.session).run(
                scene_id=f"project_{project.project_id}",
                chapter_id=project.project_id,
                bundle_id=f"project_outline:{project.project_id}",
                bundle_hash=bundle_hash,
                node_id="project_outline_plan",
                step="project_outline_plan",
                prompt=prompt,
                user_prompt=prompt["user_prompt"],
                offline_client_factory=lambda: None,
            )
        except LLMNodeExecutionError as exc:
            raise DomainError(
                "PROJECT_OUTLINE_PLAN_LLM_FAILED",
                exc.message,
                status_code=409,
                details={
                    "llm_call_id": exc.llm_call_id,
                    "node_id": "project_outline_plan",
                    "error_code": exc.error_code,
                    "next_action": "configure_project_outline_plan_route_and_retry",
                    "response_summary": exc.response_summary,
                },
            ) from exc
        structured_output = result.response.structured_output or {}
        return self._normalize_llm_plan(
            project,
            structured_output,
            chapter_count=chapter_count,
            reference_safety=reference_safety,
            llm_call_id=result.llm_call_id,
        )

    def _normalize_llm_plan(
        self,
        project: StoryProject,
        output: dict[str, Any],
        *,
        chapter_count: int,
        reference_safety: list[str],
        llm_call_id: str,
    ) -> dict[str, Any]:
        chapters_payload = output.get("chapters") if isinstance(output.get("chapters"), list) else []
        outline_points = _outline_points(project.outline_text, max(chapter_count, 1))
        chapters: list[dict[str, Any]] = []
        for index in range(1, chapter_count + 1):
            raw_chapter = chapters_payload[index - 1] if index - 1 < len(chapters_payload) and isinstance(chapters_payload[index - 1], dict) else {}
            point = outline_points[index - 1] if index - 1 < len(outline_points) else outline_points[-1]
            chapter_id = str(raw_chapter.get("chapter_id") or f"{project.project_id}_CH{index:02d}").strip()
            scenes = self._normalize_llm_scenes(
                project=project,
                chapter_id=chapter_id,
                chapter_index=index,
                chapter_count=chapter_count,
                point=point,
                raw_scenes=raw_chapter.get("scenes"),
                reference_safety=reference_safety,
            )
            chapters.append(
                {
                    "chapter_id": chapter_id,
                    "title": str(raw_chapter.get("title") or f"Chapter {index:02d}").strip(),
                    "planned_scene_count": len(scenes),
                    "chapter_goal": str(raw_chapter.get("chapter_goal") or _chapter_push(index, chapter_count, point)).strip(),
                    "main_plot_push": _optional_text(raw_chapter.get("main_plot_push")) or _chapter_push(index, chapter_count, point),
                    "emotional_target": _optional_text(raw_chapter.get("emotional_target")) or "Make the pressure visible through action.",
                    "ending_effect": _optional_text(raw_chapter.get("ending_effect")) or "End with a changed choice, cost, or clue.",
                    "must_not": _optional_text(raw_chapter.get("must_not")) or "Do not copy protected source-book expression.",
                    "notes": _optional_text(raw_chapter.get("notes")) or "LLM outline plan normalized by the system.",
                    "writer_brief_json": dict(raw_chapter.get("writer_brief_json") or {}),
                    "scenes": scenes,
                }
            )
        return {
            "source": "llm",
            "node_id": "project_outline_plan",
            "llm_call_id": llm_call_id,
            "project_id": project.project_id,
            "project_title": project.title,
            "outline_text": project.outline_text,
            "reference_safety": _string_list(output.get("reference_safety")) or reference_safety,
            "chapters": chapters,
        }

    def _normalize_llm_scenes(
        self,
        *,
        project: StoryProject,
        chapter_id: str,
        chapter_index: int,
        chapter_count: int,
        point: str,
        raw_scenes: Any,
        reference_safety: list[str],
    ) -> list[dict[str, Any]]:
        scenes_payload = raw_scenes if isinstance(raw_scenes, list) else []
        scene_count = max(1, len(scenes_payload)) if scenes_payload else (3 if chapter_index in {1, chapter_count} else 2)
        fallback_scenes = self._scene_plan(project, chapter_id, point, chapter_index, chapter_count, reference_safety)
        scenes: list[dict[str, Any]] = []
        for scene_index in range(1, scene_count + 1):
            raw_scene = scenes_payload[scene_index - 1] if scene_index - 1 < len(scenes_payload) and isinstance(scenes_payload[scene_index - 1], dict) else {}
            fallback = fallback_scenes[scene_index - 1] if scene_index - 1 < len(fallback_scenes) else fallback_scenes[-1]
            scene_id = str(raw_scene.get("scene_id") or f"{chapter_id}_SC{scene_index:02d}").strip()
            scenes.append(
                {
                    "scene_id": scene_id,
                    "chapter_id": chapter_id,
                    "scene_seq": int(raw_scene.get("scene_seq") or scene_index),
                    "pov_character_id": _optional_text(raw_scene.get("pov_character_id")),
                    "onstage_chars_json": _string_list(raw_scene.get("onstage_chars_json")),
                    "location": _optional_text(raw_scene.get("location")),
                    "scene_goal": str(raw_scene.get("scene_goal") or fallback["scene_goal"]).strip(),
                    "beats_json": _string_list(raw_scene.get("beats_json")) or list(fallback["beats_json"]),
                    "must_include_text": _optional_text(raw_scene.get("must_include_text")) or fallback.get("must_include_text"),
                    "forbidden_text": _optional_text(raw_scene.get("forbidden_text")) or fallback.get("forbidden_text"),
                    "exit_change": _optional_text(raw_scene.get("exit_change")) or fallback.get("exit_change"),
                    "hook": _optional_text(raw_scene.get("hook")) or fallback.get("hook"),
                    "target_length_band": _optional_text(raw_scene.get("target_length_band")) or "medium",
                    "scene_type": _optional_text(raw_scene.get("scene_type")) or "outline_driven",
                    "is_chapter_last": 1 if scene_index == scene_count else 0,
                    "writer_brief_json": {
                        "source": "llm",
                        "node_id": "project_outline_plan",
                        "project_id": project.project_id,
                        "reference_safety": reference_safety,
                        **dict(raw_scene.get("writer_brief_json") or {}),
                    },
                }
            )
        return scenes

    def _build_local_plan(self, project: StoryProject, payload: dict[str, Any]) -> dict[str, Any]:
        chapter_count = _optional_positive_int(payload.get("target_chapter_count")) or project.target_chapter_count or 2
        chapter_count = max(1, min(int(chapter_count), 80))
        outline_points = _outline_points(project.outline_text, chapter_count)
        reference_safety = list(REFERENCE_SAFETY_RULES)
        chapters: list[dict[str, Any]] = []
        for index in range(1, chapter_count + 1):
            point = outline_points[index - 1] if index - 1 < len(outline_points) else outline_points[-1]
            chapter_id = f"{project.project_id}_CH{index:02d}"
            chapter_title = f"第{index:02d}章 {point[:18]}"
            scenes = self._scene_plan(project, chapter_id, point, index, chapter_count, reference_safety)
            chapters.append(
                {
                    "chapter_id": chapter_id,
                    "title": chapter_title,
                    "planned_scene_count": len(scenes),
                    "chapter_goal": f"围绕大纲节点推进：{point}",
                    "main_plot_push": _chapter_push(index, chapter_count, point),
                    "emotional_target": "让主要人物在压力下暴露真实需求，并付出具体代价。",
                    "ending_effect": "以新的信息、行动后果或关系变化收束，并留下下一章钩子。",
                    "must_not": "不得复制参考书原文表达、人物、设定或桥段；不得跳过用户大纲中的硬事实。",
                    "notes": "由项目大纲自动拆解，需先通过结构审核再开写。",
                    "scenes": scenes,
                }
            )
        return {
            "source": "project_outline_plan",
            "project_id": project.project_id,
            "project_title": project.title,
            "outline_text": project.outline_text,
            "reference_safety": reference_safety,
            "chapters": chapters,
        }

    def _scene_plan(
        self,
        project: StoryProject,
        chapter_id: str,
        point: str,
        chapter_index: int,
        chapter_count: int,
        reference_safety: list[str],
    ) -> list[dict[str, Any]]:
        scene_count = 2
        if chapter_index == 1 or chapter_index == chapter_count:
            scene_count = 3
        scenes: list[dict[str, Any]] = []
        for scene_index in range(1, scene_count + 1):
            scene_id = f"{chapter_id}_SC{scene_index:02d}"
            role = _scene_role(scene_index, scene_count)
            scenes.append(
                {
                    "scene_id": scene_id,
                    "chapter_id": chapter_id,
                    "scene_seq": scene_index,
                    "scene_goal": f"{role}：让“{point}”在行动、选择或后果中显形。",
                    "beats_json": [
                        f"承接项目大纲：{point}",
                        f"制造{role}压力，避免解释性旁白。",
                        "用行动或对白推进信息，而不是复述设定。",
                    ],
                    "must_include_text": point,
                    "forbidden_text": "不得复制参考书原文表达、人物、设定或桥段。",
                    "exit_change": "场景结束时至少改变一个信息、关系或行动目标。",
                    "hook": "以未解决的选择、代价或发现推动下一场。",
                    "target_length_band": "medium",
                    "scene_type": "outline_driven",
                    "is_chapter_last": 1 if scene_index == scene_count else 0,
                    "writer_brief_json": {
                        "source": "project_outline_plan",
                        "project_id": project.project_id,
                        "reference_safety": reference_safety,
                    },
                }
            )
        return scenes


class ProjectChapterFlowService:
    def __init__(self, session: Session) -> None:
        self.session = session

    def run_chapter(self, project_id: str, chapter_id: str) -> dict[str, Any]:
        project = ProjectService(self.session).require_project(project_id)
        self._require_project_chapter(project, chapter_id)
        if project.current_chapter_id != chapter_id:
            raise DomainError("PROJECT_CHAPTER_NOT_CURRENT", "only the current chapter can be run from project dashboard")

        project.status = PROJECT_STATUS_CHAPTER_RUNNING
        self.session.flush()
        run_result = ChapterRunnerService(self.session).run_full(chapter_id)
        if run_result.get("status") == "completed":
            project.status = PROJECT_STATUS_CHAPTER_FINAL_REVIEW
        elif run_result.get("status") == "blocked":
            project.status = PROJECT_STATUS_CHAPTER_BLOCKED
        else:
            project.status = PROJECT_STATUS_CHAPTER_READY
        self.session.flush()
        return {
            "project": project_payload(project),
            "run": run_result,
            "review_packet": self.review_packet(project, chapter_id),
        }

    def prepare_chapter_run_job(self, project_id: str, chapter_id: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        body = payload or {}
        project = ProjectService(self.session).require_project(project_id)
        self._require_project_chapter(project, chapter_id)
        if project.current_chapter_id != chapter_id:
            raise DomainError("PROJECT_CHAPTER_NOT_CURRENT", "only the current chapter can be run from project dashboard")

        allow_demo = bool(body.get("allow_demo") or body.get("offline_demo"))
        if not get_settings().llm_enabled and not allow_demo:
            raise DomainError(
                "LLM_DISABLED_FOR_CHAPTER_RUN",
                "LLM is disabled; enable a live model before starting chapter generation, or explicitly run an offline demo.",
                status_code=409,
                details={"retryable": False, "generation_mode": "offline_disabled"},
            )

        run_payload, should_start_worker = ChapterRunnerService(self.session).prepare_full_run(
            chapter_id,
            offline_demo=allow_demo and not get_settings().llm_enabled,
        )
        if run_payload.get("status") in {"pending", "running"}:
            project.status = PROJECT_STATUS_CHAPTER_RUNNING
            next_action = "view_chapter_progress"
        elif run_payload.get("status") == "completed":
            project.status = PROJECT_STATUS_CHAPTER_FINAL_REVIEW
            next_action = "approve_chapter_final"
        elif run_payload.get("status") == "blocked":
            project.status = PROJECT_STATUS_CHAPTER_BLOCKED
            next_action = "resolve_blocker"
        else:
            project.status = PROJECT_STATUS_CHAPTER_READY
            next_action = "run_current_chapter"
        self.session.flush()
        return {
            "project": project_payload(project),
            "run": run_payload,
            "review_packet": self.review_packet(project, chapter_id),
            "next_action": next_action,
            "_start_worker": should_start_worker and run_payload.get("status") == "pending",
        }

    def approve_final(self, project_id: str, chapter_id: str, payload: dict[str, Any] | None = None, *, actor_ref: str = "operator") -> dict[str, Any]:
        body = payload or {}
        project = ProjectService(self.session).require_project(project_id)
        self._require_project_chapter(project, chapter_id)
        if project.current_chapter_id != chapter_id:
            raise DomainError("PROJECT_CHAPTER_NOT_CURRENT", "only the current chapter final can be approved")
        revision_notes = str(body.get("revision_notes") or "").strip()
        if len(revision_notes) > 2000:
            raise DomainError("CHAPTER_APPROVAL_NOTES_TOO_LONG", "revision_notes must be 2000 characters or fewer", status_code=400)

        approved = list(project.approved_chapter_ids_json or [])
        if chapter_id not in approved:
            approved.append(chapter_id)
        project.approved_chapter_ids_json = approved

        next_chapter_id = self._next_chapter_id(project.project_id, chapter_id)
        if next_chapter_id:
            project.current_chapter_id = next_chapter_id
            project.status = PROJECT_STATUS_CHAPTER_READY
        else:
            project.current_chapter_id = None
            project.status = PROJECT_STATUS_COMPLETED
        approval_note = {
            "revision_notes": revision_notes,
            "actor_ref": actor_ref or "operator",
        }
        self.session.add(
            OperationLog(
                event_type="chapter_final_approval",
                object_type="chapter",
                object_ref=chapter_id,
                payload_json={
                    "project_id": project.project_id,
                    "chapter_id": chapter_id,
                    "next_chapter_id": project.current_chapter_id,
                    "project_status": project.status,
                    **approval_note,
                },
            )
        )
        self.session.flush()
        return {
            "project": project_payload(project),
            "next_chapter_id": project.current_chapter_id,
            "approved_chapter_id": chapter_id,
            "approval_note": approval_note,
        }

    def final_review(self, project_id: str, chapter_id: str, payload: dict[str, Any] | None = None, *, actor_ref: str = "operator") -> dict[str, Any]:
        body = payload or {}
        decision = str(body.get("decision") or "").strip() or "approve"
        scene_decisions = body.get("scene_decisions") if isinstance(body.get("scene_decisions"), list) else []
        revision_notes = str(body.get("revision_notes") or "").strip()
        if len(revision_notes) > 2000:
            raise DomainError("CHAPTER_APPROVAL_NOTES_TOO_LONG", "revision_notes must be 2000 characters or fewer", status_code=400)
        project = ProjectService(self.session).require_project(project_id)
        self._require_project_chapter(project, chapter_id)
        if project.current_chapter_id != chapter_id:
            raise DomainError("PROJECT_CHAPTER_NOT_CURRENT", "only the current chapter final can be reviewed")

        requested_revisions = [
            item for item in scene_decisions if isinstance(item, dict) and str(item.get("decision") or "").strip() in {"request_revision", "request_scene_revision"}
        ]
        if not requested_revisions and decision in {"approve", "approve_final", "approved"}:
            return self.approve_final(project_id, chapter_id, {"revision_notes": revision_notes}, actor_ref=actor_ref)
        if not requested_revisions and decision not in {"request_revision", "request_scene_revision", "request_chapter_revision"}:
            raise DomainError("CHAPTER_FINAL_REVIEW_DECISION_INVALID", "final review decision is invalid", status_code=400)

        backtracks = ProjectBacktrackService(self.session)
        created_items = []
        for item in requested_revisions or [{"scene_id": None, "note": revision_notes or "Chapter needs revision before approval."}]:
            scene_id = str(item.get("scene_id") or "").strip() or None
            if scene_id:
                scene = self.session.get(SceneCard, scene_id)
                if scene is None or scene.chapter_id != chapter_id:
                    raise DomainError("PROJECT_REVIEW_SCENE_NOT_FOUND", "scene does not belong to the reviewed chapter", status_code=404)
            note = str(item.get("note") or revision_notes or "Scene needs revision before chapter approval.").strip()
            created_items.append(
                backtracks.ensure_item(
                    project_id=project.project_id,
                    chapter_id=chapter_id,
                    scene_id=scene_id,
                    scope="chapter_final_review_scene" if scene_id else "chapter_final_review",
                    target_ref=scene_id or chapter_id,
                    problem_summary=note,
                    recommended_fix=note,
                    reason_codes=["chapter_final_review"],
                    created_by=actor_ref or "chapter_final_review",
                )
            )
        project.status = PROJECT_STATUS_CHAPTER_BLOCKED
        self.session.add(
            OperationLog(
                event_type="chapter_final_revision_request",
                object_type="chapter",
                object_ref=chapter_id,
                payload_json={
                    "project_id": project.project_id,
                    "chapter_id": chapter_id,
                    "decision": decision,
                    "revision_notes": revision_notes,
                    "scene_decisions": scene_decisions,
                    "backtrack_item_ids": [item.item_id for item in created_items],
                    "actor_ref": actor_ref or "operator",
                },
            )
        )
        self.session.flush()
        return {
            "project": project_payload(project),
            "review_decision": {
                "decision": decision,
                "revision_notes": revision_notes,
                "actor_ref": actor_ref or "operator",
            },
            "backtrack_items": [ProjectBacktrackService.serialize(item) for item in created_items],
        }

    def review_packet(self, project: StoryProject, chapter_id: str | None) -> dict[str, Any] | None:
        if not chapter_id or project.status != PROJECT_STATUS_CHAPTER_FINAL_REVIEW:
            return None
        chapter = self.session.get(ChapterGoal, chapter_id)
        if chapter is None:
            return None
        latest_job = self._latest_job(chapter_id)
        issues_summary = []
        latest_error = (latest_job.result_summary_json or {}).get("latest_error") if latest_job else None
        if latest_error:
            issues_summary.append(latest_error)
        manuscript = ChapterManuscriptService(self.session).manuscript_detail(chapter_id)
        aggregate = manuscript.get("aggregate") or None
        assembled = manuscript.get("assembled") or {}
        if aggregate and str(aggregate.get("content") or ""):
            body = str(aggregate.get("content") or "")
            body_source = "aggregate"
            char_count = int(aggregate.get("char_count") or len(body))
            aggregate_row_id = aggregate.get("row_id")
        else:
            body = str(assembled.get("content") or "")
            body_source = "assembled" if body else "empty"
            char_count = int(assembled.get("char_count") or len(body))
            aggregate_row_id = None
        missing_scene_ids = list(assembled.get("missing_scene_ids") or [])
        completion_status = manuscript.get("completion_status") or "empty"
        body_empty_reason = None
        if not body:
            body_empty_reason = "no_generated_scenes" if completion_status == "empty" else "manuscript_body_empty"
        scene_reviews = self._scene_reviews(chapter.chapter_id)
        return {
            "chapter_id": chapter.chapter_id,
            "chapter_goal": chapter.chapter_goal,
            "body": body,
            "body_source": body_source,
            "char_count": char_count,
            "body_empty_reason": body_empty_reason,
            "completion_status": completion_status,
            "comparison_status": manuscript.get("comparison_status"),
            "missing_scene_ids": missing_scene_ids,
            "missing_scene_labels": self._missing_scene_labels(missing_scene_ids, scene_reviews),
            "scene_coverage": self._scene_coverage(scene_reviews),
            "target_word_count_band": self._target_word_count_band(project),
            "aggregate_row_id": aggregate_row_id,
            "source_safety_scan": manuscript.get("source_safety_scan"),
            "scene_reviews": scene_reviews,
            "issues_summary": issues_summary,
            "run_status": latest_job.status if latest_job else "idle",
            "reference_safety": list(REFERENCE_SAFETY_RULES),
            "small_revision_entry": {
                "writer_room_object_type": "chapter",
                "writer_room_object_id": chapter.chapter_id,
                "deepdesk_object_id": chapter.chapter_id,
            },
        }

    def _scene_reviews(self, chapter_id: str) -> list[dict[str, Any]]:
        scenes = self.session.execute(
            select(SceneCard)
            .where(SceneCard.chapter_id == chapter_id, SceneCard.trashed_flag == 0)
            .order_by(SceneCard.scene_seq.asc(), SceneCard.scene_id.asc())
        ).scalars().all()
        reviews: list[dict[str, Any]] = []
        for scene in scenes:
            state = self.session.get(SceneRunState, scene.scene_id)
            final_row = self.session.get(FinalScene, state.current_final_scene_row_id) if state and state.current_final_scene_row_id else None
            body = final_row.content if final_row is not None else ""
            excerpt = " ".join(str(body or "").split())
            reviews.append(
                {
                    "scene_id": scene.scene_id,
                    "scene_seq": scene.scene_seq,
                    "title": scene.scene_goal or scene.hook or scene.scene_id,
                    "body_excerpt": excerpt[:240],
                    "char_count": len(body or ""),
                    "missing": not bool(body),
                    "issues_summary": [],
                    "current_decision": "pending",
                }
            )
        return reviews

    @staticmethod
    def _scene_coverage(scene_reviews: list[dict[str, Any]]) -> dict[str, Any]:
        total = len(scene_reviews)
        completed = sum(1 for item in scene_reviews if int(item.get("char_count") or 0) > 0)
        return {
            "completed_count": completed,
            "total_count": total,
            "percent": round((completed / total) * 100) if total else 0,
        }

    @staticmethod
    def _missing_scene_labels(missing_scene_ids: list[str], scene_reviews: list[dict[str, Any]]) -> list[str]:
        by_id = {str(item.get("scene_id") or ""): item for item in scene_reviews}
        missing_ids = {str(item or "") for item in missing_scene_ids if str(item or "")}
        for item in scene_reviews:
            if item.get("missing"):
                scene_id = str(item.get("scene_id") or "")
                if scene_id:
                    missing_ids.add(scene_id)
        labels: list[str] = []
        for scene_id in sorted(missing_ids):
            item = by_id.get(scene_id)
            if item is None:
                labels.append(scene_id)
                continue
            seq = item.get("scene_seq")
            title = str(item.get("title") or scene_id).strip() or scene_id
            prefix = f"第 {seq} 场" if seq else "场景"
            labels.append(f"{prefix}：{title}")
        return labels

    @staticmethod
    def _target_word_count_band(project: StoryProject) -> dict[str, Any] | None:
        target_word_count = int(project.target_word_count or 0)
        target_chapter_count = int(project.target_chapter_count or 0)
        if target_word_count <= 0 or target_chapter_count <= 0:
            return None
        per_chapter = max(1, round(target_word_count / target_chapter_count))
        lower = max(1, round(per_chapter * 0.85))
        upper = max(lower, round(per_chapter * 1.15))
        return {
            "target": per_chapter,
            "min": lower,
            "max": upper,
            "label": f"{lower}-{upper} 字",
        }

    def _require_project_chapter(self, project: StoryProject, chapter_id: str) -> ChapterGoal:
        chapter = self.session.get(ChapterGoal, chapter_id)
        if chapter is None or chapter.project_id != project.project_id:
            raise DomainError("PROJECT_CHAPTER_NOT_FOUND", "chapter does not belong to project", status_code=404)
        return chapter

    def _next_chapter_id(self, project_id: str, chapter_id: str) -> str | None:
        chapter_ids = [
            row[0]
            for row in self.session.execute(
                select(ChapterGoal.chapter_id)
                .where(ChapterGoal.project_id == project_id, ChapterGoal.trashed_flag == 0)
                .order_by(ChapterGoal.chapter_id.asc())
            ).all()
        ]
        try:
            index = chapter_ids.index(chapter_id)
        except ValueError:
            return None
        return chapter_ids[index + 1] if index + 1 < len(chapter_ids) else None

    def _latest_job(self, chapter_id: str) -> ChapterRunJob | None:
        return self.session.execute(
            select(ChapterRunJob)
            .where(ChapterRunJob.chapter_id == chapter_id)
            .order_by(ChapterRunJob.created_at.desc(), ChapterRunJob.job_id.desc())
        ).scalars().first()


def start_project_chapter_run_job_worker(project_id: str, chapter_id: str, job_id: str) -> None:
    thread = threading.Thread(
        target=_run_project_chapter_job_worker,
        args=(project_id, chapter_id, job_id),
        daemon=True,
    )
    thread.start()


def _run_project_chapter_job_worker(project_id: str, chapter_id: str, job_id: str) -> None:
    session = SessionLocal()
    try:
        project = ProjectService(session).require_project(project_id)
        if project.current_chapter_id != chapter_id:
            raise DomainError("PROJECT_CHAPTER_NOT_CURRENT", "only the current chapter can be run from project dashboard")
        project.status = PROJECT_STATUS_CHAPTER_RUNNING
        session.commit()

        run_result = ChapterRunnerService(session).run_full(chapter_id)
        project = ProjectService(session).require_project(project_id)
        if run_result.get("status") == "completed":
            project.status = PROJECT_STATUS_CHAPTER_FINAL_REVIEW
        elif run_result.get("status") == "blocked":
            project.status = PROJECT_STATUS_CHAPTER_BLOCKED
        elif run_result.get("status") == "failed":
            project.status = PROJECT_STATUS_CHAPTER_BLOCKED
        else:
            project.status = PROJECT_STATUS_CHAPTER_READY
        session.commit()
    except DomainError as exc:
        session.rollback()
        _mark_project_chapter_job_failed(job_id, project_id, chapter_id, exc.code, exc.message)
    except Exception as exc:  # pragma: no cover - defensive worker boundary
        session.rollback()
        _mark_project_chapter_job_failed(job_id, project_id, chapter_id, "CHAPTER_RUN_JOB_FAILED", str(exc) or "chapter run job failed")
    finally:
        session.close()


def _mark_project_chapter_job_failed(job_id: str, project_id: str, chapter_id: str, error_code: str, error_text: str) -> None:
    session = SessionLocal()
    try:
        job = session.get(ChapterRunJob, job_id)
        if job is not None:
            job.status = "failed"
            job.error_code = error_code
            job.error_text = error_text
            job.finished_at = utcnow()
            summary = dict(job.result_summary_json or {})
            summary["latest_error"] = {"code": error_code, "message": error_text}
            job.result_summary_json = summary
        project = session.get(StoryProject, project_id)
        if project is not None and project.current_chapter_id == chapter_id:
            project.status = PROJECT_STATUS_CHAPTER_BLOCKED
        session.commit()
    finally:
        session.close()


def project_summary_payload(project: StoryProject) -> dict[str, Any]:
    payload = project_payload(project)
    payload.pop("outline_text", None)
    return payload


def project_payload(project: StoryProject) -> dict[str, Any]:
    return {
        "project_id": project.project_id,
        "title": project.title,
        "genre": project.genre,
        "target_word_count": project.target_word_count,
        "target_chapter_count": project.target_chapter_count,
        "outline_text": project.outline_text,
        "planning_mode": getattr(project, "planning_mode", "outline_driven") or "outline_driven",
        "snowflake_schema_version": getattr(project, "snowflake_schema_version", None),
        "status": project.status,
        "active_outline_plan_id": project.active_outline_plan_id,
        "current_chapter_id": project.current_chapter_id,
        "approved_chapter_ids": list(project.approved_chapter_ids_json or []),
        "reference_profile_ids": list(project.reference_profile_ids_json or []),
        "created_at": project.created_at,
        "updated_at": project.updated_at,
    }


def outline_plan_payload(plan: OutlinePlan) -> dict[str, Any]:
    return {
        "plan_id": plan.plan_id,
        "project_id": plan.project_id,
        "version": plan.version,
        "status": plan.status,
        "plan_json": plan.plan_json or {},
        "created_at": plan.created_at,
        "approved_at": plan.approved_at,
    }


def chapter_payload(session: Session, chapter: ChapterGoal) -> dict[str, Any]:
    scenes = session.execute(
        select(SceneCard)
        .where(SceneCard.chapter_id == chapter.chapter_id, SceneCard.trashed_flag == 0)
        .order_by(SceneCard.scene_seq.asc(), SceneCard.scene_id.asc())
    ).scalars().all()
    return {
        "chapter_id": chapter.chapter_id,
        "project_id": chapter.project_id,
        "outline_plan_id": chapter.outline_plan_id,
        "chapter_goal": chapter.chapter_goal,
        "main_plot_push": chapter.main_plot_push,
        "emotional_target": chapter.emotional_target,
        "ending_effect": chapter.ending_effect,
        "must_not": chapter.must_not,
        "planned_scene_count": chapter.planned_scene_count,
        "scenes": [scene_payload(scene) for scene in scenes],
    }


def scene_payload(scene: SceneCard) -> dict[str, Any]:
    return {
        "scene_id": scene.scene_id,
        "chapter_id": scene.chapter_id,
        "project_id": scene.project_id,
        "outline_plan_id": scene.outline_plan_id,
        "scene_seq": scene.scene_seq,
        "scene_goal": scene.scene_goal,
        "beats_json": list(scene.beats_json or []),
        "must_include_text": scene.must_include_text,
        "forbidden_text": scene.forbidden_text,
        "exit_change": scene.exit_change,
        "hook": scene.hook,
        "target_length_band": scene.target_length_band,
        "scene_type": scene.scene_type,
        "is_chapter_last": scene.is_chapter_last,
    }


def reference_profile_payload(profile: ReferenceProfile) -> dict[str, Any]:
    return {
        "profile_id": profile.profile_id,
        "title": profile.title,
        "status": profile.status,
        "profile_json": profile.profile_json or {},
    }


def _outline_points(outline_text: str, chapter_count: int) -> list[str]:
    lines = [
        re.sub(r"^[\s\-\*\d\.、）)]+", "", line).strip()
        for line in str(outline_text or "").splitlines()
        if line.strip()
    ]
    if not lines:
        lines = [
            part.strip()
            for part in re.split(r"[。！？!?；;]\s*", str(outline_text or ""))
            if part.strip()
        ]
    if not lines:
        lines = ["围绕用户大纲推进核心冲突"]
    while len(lines) < chapter_count:
        lines.append(lines[-1])
    return lines[:chapter_count]


def _scene_role(scene_index: int, scene_count: int) -> str:
    if scene_index == 1:
        return "开场承压"
    if scene_index == scene_count:
        return "转折收束"
    return "冲突升级"


def _chapter_push(index: int, chapter_count: int, point: str) -> str:
    if index == 1:
        return f"建立主矛盾和行动入口：{point}"
    if index == chapter_count:
        return f"兑现核心承诺并留下长期余波：{point}"
    return f"升级阻力并改变人物关系：{point}"


def _optional_text(value: Any) -> str | None:
    text = str(value).strip() if value is not None else ""
    return text or None


def _optional_positive_int(value: Any) -> int | None:
    if value in (None, ""):
        return None
    try:
        number = int(value)
    except (TypeError, ValueError):
        return None
    return number if number > 0 else None


def _planning_mode(value: Any) -> str:
    mode = str(value or "").strip()
    if mode == "snowflake":
        return "snowflake"
    return "outline_driven"


def _string_list(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if value in (None, ""):
        return []
    return [str(value).strip()]
