from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from novel_system.db.models import OutlinePlan, SnowflakeArtifact, StoryCharacter, StoryProject, utcnow
from novel_system.services.errors import DomainError
from novel_system.services.project_runtime_invalidation import ProjectRuntimeInvalidationService
from novel_system.services.projects import PLAN_STATUS_PENDING_REVIEW, ProjectService, outline_plan_payload, project_payload

SNOWFLAKE_STEPS = [
    {
        "step_key": "book_brief",
        "label": "读者定位",
        "english_label": "Target Audience",
        "description": "明确你的小说类型和目标读者群体。你写作的核心目标是取悦你的读者——先知道为谁写，再决定写什么。",
    },
    {
        "step_key": "one_sentence_summary",
        "label": "一句话概括",
        "english_label": "One-Sentence Summary",
        "description": "用一句话（最好25字以内）概括整部小说。这是最强营销工具——让人听完就想说「告诉我更多！」",
    },
    {
        "step_key": "one_paragraph_summary",
        "label": "一段话概括",
        "english_label": "One-Paragraph Summary",
        "description": "将一句话扩展为五句话，构建三幕结构与三个关键「灾难」转折点。这确保你的故事有扎实的戏剧骨架。",
    },
    {
        "step_key": "character_sheets",
        "label": "角色摘要表",
        "english_label": "Character Sheets",
        "description": "为每个重要角色创建基础档案。优秀小说由立体角色驱动——角色的价值观冲突产生了你所有的场景冲突。",
    },
    {
        "step_key": "short_synopsis",
        "label": "一页梗概",
        "english_label": "Short Synopsis",
        "description": "将五句话每一句扩展为一段（约100字），形成约500字的故事骨架。这是故事的第一次「填肉」。",
    },
    {
        "step_key": "character_synopses",
        "label": "角色背景故事",
        "english_label": "Character Synopses",
        "description": "为每个重要角色写半页到一页的背景故事。理解角色为何成为这样的人，你才能写出他真实可信的行动。",
    },
    {
        "step_key": "long_synopsis",
        "label": "长篇大纲",
        "english_label": "Long Synopsis",
        "description": "将一页梗概扩展为四到五页详细大纲。这是最接近实际写作的规划阶段。",
        "skippable": True,
    },
    {
        "step_key": "character_bibles",
        "label": "角色全档案",
        "english_label": "Character Bibles",
        "description": "为每个角色创建详尽的「角色圣经」，彻底了解你的角色——他们是真实存在于你脑海中的人。",
    },
    {
        "step_key": "scene_list",
        "label": "场景列表",
        "english_label": "Scene List",
        "description": "列出小说中每一个场景。场景是小说的基本单位——每个场景必须有冲突，必须是一个完整的缩微故事。",
    },
    {
        "step_key": "scene_details",
        "label": "场景规划",
        "english_label": "Scene Planning",
        "description": "为每个场景规划关键信息。主动场景制造紧张，被动场景让读者喘息并期待——两者交替构成故事的引擎。",
    },
]

STEP_INDEX = {step["step_key"]: index for index, step in enumerate(SNOWFLAKE_STEPS)}
GATE_STATUSES = {"approved", "skipped"}


class SnowflakePlannerService:
    def __init__(self, session: Session) -> None:
        self.session = session

    def state(self, project_id: str) -> dict[str, Any]:
        project = ProjectService(self.session).require_project(project_id)
        latest_by_step = self._latest_by_step(project_id)
        current_step_key = self._current_step_key(latest_by_step)
        return {
            "project": project_payload(project),
            "steps": [
                {
                    **step,
                    "index": index,
                    "artifact": artifact_payload(latest_by_step.get(step["step_key"]))
                    if latest_by_step.get(step["step_key"])
                    else None,
                    "gate_satisfied": self._gate_satisfied(step["step_key"], latest_by_step),
                }
                for index, step in enumerate(SNOWFLAKE_STEPS)
            ],
            "current_step_key": current_step_key,
            "blocking_reason": None if current_step_key else None,
            "next_action": "generate_snowflake_step" if current_step_key else "materialize_outline_plan",
            "ready_to_materialize": current_step_key is None,
        }

    def generate(
        self,
        project_id: str,
        step_key: str,
        payload: dict[str, Any] | None = None,
        *,
        artifact_json_override: dict[str, Any] | None = None,
        llm_call_id: str | None = None,
        generation_source: str | None = None,
    ) -> dict[str, Any]:
        project = ProjectService(self.session).require_project(project_id)
        body = payload or {}
        self._require_step(step_key)
        latest_by_step = self._latest_by_step(project_id)
        self._require_previous_gates(step_key, latest_by_step)

        if body.get("skip"):
            artifact_json = self._skip_artifact(step_key, body)
            status = "skipped"
            approved_at = utcnow()
        else:
            artifact_json = artifact_json_override or self._build_artifact_json(project, step_key, latest_by_step)
            status = "pending_review"
            approved_at = None

        artifact = SnowflakeArtifact(
            artifact_id=f"snowflake_{project_id}_{step_key}_{uuid.uuid4().hex[:10]}",
            project_id=project_id,
            step_key=step_key,
            version=self._next_version(project_id, step_key),
            status=status,
            artifact_json=artifact_json,
            input_refs_json=self._input_refs(step_key, latest_by_step),
            diagnosis_json=self._diagnosis(step_key, artifact_json, status, generation_source=generation_source),
            llm_call_id=llm_call_id,
            approved_at=approved_at,
        )
        self.session.add(artifact)
        if status == "skipped":
            self._supersede_same_step(artifact)
            self._mark_downstream_stale(artifact)
        self.session.flush()
        return {"artifact": artifact_payload(artifact), "state": self.state(project_id)}

    def update_artifact(self, project_id: str, artifact_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        artifact = self._require_artifact(project_id, artifact_id)
        if artifact.status not in {"pending_review", "approved", "skipped"}:
            raise DomainError("SNOWFLAKE_ARTIFACT_NOT_EDITABLE", "artifact cannot be edited in its current status")
        artifact.artifact_json = dict(payload.get("artifact_json") or artifact.artifact_json or {})
        if "diagnosis_json" in payload:
            artifact.diagnosis_json = dict(payload.get("diagnosis_json") or {})
        else:
            artifact.diagnosis_json = self._diagnosis(artifact.step_key, artifact.artifact_json, artifact.status)
        self.session.flush()
        return {"artifact": artifact_payload(artifact), "state": self.state(project_id)}

    def approve(self, project_id: str, artifact_id: str) -> dict[str, Any]:
        artifact = self._require_artifact(project_id, artifact_id)
        if artifact.status == "approved":
            return {"artifact": artifact_payload(artifact), "state": self.state(project_id)}
        if artifact.status == "skipped":
            return {"artifact": artifact_payload(artifact), "state": self.state(project_id)}
        if artifact.status != "pending_review":
            raise DomainError("SNOWFLAKE_ARTIFACT_NOT_APPROVABLE", "artifact cannot be approved")

        latest_by_step = self._latest_by_step(project_id)
        previous_artifact = self._latest_approved_artifact(project_id, artifact.step_key, exclude_artifact_id=artifact.artifact_id)
        self._require_previous_gates(artifact.step_key, latest_by_step, allow_self=artifact.artifact_id)
        self._supersede_same_step(artifact)

        artifact.status = "approved"
        artifact.approved_at = utcnow()
        self._mark_downstream_stale(artifact)
        self._sync_characters(artifact)
        impact = ProjectRuntimeInvalidationService(self.session).invalidate_for_snowflake_step(
            project_id,
            artifact.step_key,
            previous_payload=previous_artifact.artifact_json if previous_artifact is not None else None,
            current_payload=artifact.artifact_json,
        )
        self.session.flush()
        return {"artifact": artifact_payload(artifact), "state": self.state(project_id), "impact": impact}

    def materialize_outline_plan(self, project_id: str) -> dict[str, Any]:
        project = ProjectService(self.session).require_project(project_id)
        latest_by_step = self._latest_by_step(project_id)
        if self._current_step_key(latest_by_step) is not None:
            raise DomainError(
                "SNOWFLAKE_NOT_READY",
                "all required snowflake steps must be approved before materializing an outline plan",
                status_code=409,
            )
        scene_list = latest_by_step.get("scene_list")
        scene_details = latest_by_step.get("scene_details")
        if scene_list is None or scene_details is None:
            raise DomainError("SNOWFLAKE_SCENES_REQUIRED", "scene list and details are required", status_code=409)

        plan = OutlinePlan(
            plan_id=f"outline_plan_{project.project_id}_{self._next_plan_version(project.project_id):02d}_{uuid.uuid4().hex[:8]}",
            project_id=project.project_id,
            version=self._next_plan_version(project.project_id),
            status=PLAN_STATUS_PENDING_REVIEW,
            plan_json=self._build_outline_plan(project, scene_list.artifact_json, scene_details.artifact_json),
        )
        project.status = "outline_review"
        self.session.add(plan)
        self.session.flush()
        return {"plan": outline_plan_payload(plan), "project": project_payload(project)}

    def _build_outline_plan(
        self,
        project: StoryProject,
        scene_list_json: dict[str, Any],
        scene_details_json: dict[str, Any],
    ) -> dict[str, Any]:
        detail_by_id = {
            str(scene.get("scene_id")): scene
            for scene in scene_details_json.get("scenes", [])
            if isinstance(scene, dict) and scene.get("scene_id")
        }
        chapters: dict[str, dict[str, Any]] = {}
        for item in scene_list_json.get("scenes", []):
            if not isinstance(item, dict):
                continue
            chapter_id = str(item.get("chapter_id") or f"{project.project_id}_CH01")
            chapter = chapters.setdefault(
                chapter_id,
                {
                    "chapter_id": chapter_id,
                    "title": item.get("chapter_title") or chapter_id,
                    "planned_scene_count": 0,
                    "chapter_goal": item.get("chapter_goal") or f"推进雪花法场景：{item.get('summary') or project.title}",
                    "main_plot_push": item.get("chapter_goal") or "按雪花场景列表推进主线。",
                    "emotional_target": "让人物目标、阻碍和代价在行动中显形。",
                    "ending_effect": "用新的选择、代价或信息推动下一章。",
                    "must_not": "不得复制参考书原文表达、人物、设定或桥段。",
                    "notes": "由雪花法场景列表物化，需确认后进入逐章运行。",
                    "writer_brief_json": {
                        "source": "snowflake_method",
                        "chapter_role": item.get("chapter_role") or "",
                    },
                    "scenes": [],
                },
            )
            scene_id = str(item.get("scene_id") or f"{chapter_id}_SC{len(chapter['scenes']) + 1:02d}")
            detail = detail_by_id.get(scene_id, {})
            scene_type = str(
                detail.get("primary_form")
                or detail.get("scene_type")
                or detail.get("scene_kind")
                or item.get("primary_form")
                or item.get("scene_type")
                or "proactive"
            )
            writer_brief = _scene_writer_brief(scene_type, detail)
            chapter["scenes"].append(
                {
                    "scene_id": scene_id,
                    "chapter_id": chapter_id,
                    "scene_seq": int(item.get("scene_seq") or len(chapter["scenes"]) + 1),
                    "pov_character_id": item.get("pov_character_id") or detail.get("pov_character_id"),
                    "onstage_chars_json": item.get("onstage_chars_json") or detail.get("onstage_chars_json") or [],
                    "location": detail.get("location") or item.get("location"),
                    "scene_goal": detail.get("summary") or item.get("summary") or item.get("scene_goal") or chapter["chapter_goal"],
                    "beats_json": detail.get("beats_json") or _beats_from_detail(scene_type, detail),
                    "must_include_text": detail.get("must_include_text") or item.get("summary") or project.outline_text[:120],
                    "forbidden_text": "不得复制参考书原文表达、人物、设定或桥段。",
                    "exit_change": detail.get("exit_change") or "场景结束时至少改变一个信息、关系或行动目标。",
                    "hook": detail.get("hook") or "以未解决的选择、代价或发现推动下一场。",
                    "target_length_band": detail.get("target_length_band") or "medium",
                    "primary_form": scene_type,
                    "scene_type": scene_type,
                    "is_chapter_last": 0,
                    "writer_brief_json": writer_brief,
                }
            )

        chapter_list = sorted(chapters.values(), key=lambda chapter: chapter["chapter_id"])
        for chapter in chapter_list:
            chapter["scenes"] = sorted(chapter["scenes"], key=lambda scene: (scene["scene_seq"], scene["scene_id"]))
            chapter["planned_scene_count"] = len(chapter["scenes"])
            if chapter["scenes"]:
                chapter["scenes"][-1]["is_chapter_last"] = 1

        return {
            "source": "snowflake_method",
            "project_id": project.project_id,
            "project_title": project.title,
            "outline_text": project.outline_text,
            "reference_safety": [
                "参考书只进入抽象风格画像，不复制原文表达。",
                "不得复刻参考书人物、设定、桥段、特殊意象或标志性句式。",
                "运行时只使用节奏、句法、叙事手法、结构技巧和禁复刻规则。",
            ],
            "chapters": chapter_list,
        }

    def _latest_by_step(self, project_id: str) -> dict[str, SnowflakeArtifact]:
        rows = self.session.execute(
            select(SnowflakeArtifact)
            .where(SnowflakeArtifact.project_id == project_id)
            .order_by(SnowflakeArtifact.version.asc(), SnowflakeArtifact.created_at.asc())
        ).scalars().all()
        latest: dict[str, SnowflakeArtifact] = {}
        for row in rows:
            if row.status == "superseded":
                continue
            latest[row.step_key] = row
        return latest

    def _current_step_key(self, latest_by_step: dict[str, SnowflakeArtifact]) -> str | None:
        for step in SNOWFLAKE_STEPS:
            if not self._gate_satisfied(step["step_key"], latest_by_step):
                return step["step_key"]
        return None

    def _gate_satisfied(self, step_key: str, latest_by_step: dict[str, SnowflakeArtifact]) -> bool:
        artifact = latest_by_step.get(step_key)
        return artifact is not None and artifact.status in GATE_STATUSES

    def _require_step(self, step_key: str) -> None:
        if step_key not in STEP_INDEX:
            raise DomainError("SNOWFLAKE_STEP_NOT_FOUND", "unknown snowflake step", status_code=404)

    def _require_previous_gates(
        self,
        step_key: str,
        latest_by_step: dict[str, SnowflakeArtifact],
        *,
        allow_self: str | None = None,
    ) -> None:
        step_index = STEP_INDEX[step_key]
        for prior in SNOWFLAKE_STEPS[:step_index]:
            artifact = latest_by_step.get(prior["step_key"])
            if allow_self and artifact and artifact.artifact_id == allow_self:
                continue
            if artifact is None or artifact.status not in GATE_STATUSES:
                raise DomainError(
                    "SNOWFLAKE_PREVIOUS_STEP_REQUIRED",
                    "previous snowflake steps must be approved first",
                    status_code=409,
                )

    def _next_version(self, project_id: str, step_key: str) -> int:
        latest = self.session.execute(
            select(SnowflakeArtifact.version)
            .where(SnowflakeArtifact.project_id == project_id, SnowflakeArtifact.step_key == step_key)
            .order_by(SnowflakeArtifact.version.desc())
        ).scalar()
        return int(latest or 0) + 1

    def _next_plan_version(self, project_id: str) -> int:
        latest = self.session.execute(
            select(OutlinePlan.version)
            .where(OutlinePlan.project_id == project_id)
            .order_by(OutlinePlan.version.desc())
        ).scalar()
        return int(latest or 0) + 1

    def _input_refs(self, step_key: str, latest_by_step: dict[str, SnowflakeArtifact]) -> dict[str, Any]:
        step_index = STEP_INDEX[step_key]
        refs = {}
        for prior in SNOWFLAKE_STEPS[:step_index]:
            artifact = latest_by_step.get(prior["step_key"])
            if artifact and artifact.status in GATE_STATUSES:
                refs[prior["step_key"]] = artifact.artifact_id
        return refs

    def _require_artifact(self, project_id: str, artifact_id: str) -> SnowflakeArtifact:
        artifact = self.session.get(SnowflakeArtifact, artifact_id)
        if artifact is None or artifact.project_id != project_id:
            raise DomainError("SNOWFLAKE_ARTIFACT_NOT_FOUND", "snowflake artifact not found", status_code=404)
        return artifact

    def _latest_approved_artifact(
        self,
        project_id: str,
        step_key: str,
        *,
        exclude_artifact_id: str,
    ) -> SnowflakeArtifact | None:
        return self.session.execute(
            select(SnowflakeArtifact)
            .where(
                SnowflakeArtifact.project_id == project_id,
                SnowflakeArtifact.step_key == step_key,
                SnowflakeArtifact.artifact_id != exclude_artifact_id,
                SnowflakeArtifact.status.in_(["approved", "skipped"]),
            )
            .order_by(SnowflakeArtifact.version.desc(), SnowflakeArtifact.created_at.desc())
        ).scalars().first()

    def _supersede_same_step(self, artifact: SnowflakeArtifact) -> None:
        rows = self.session.execute(
            select(SnowflakeArtifact).where(
                SnowflakeArtifact.project_id == artifact.project_id,
                SnowflakeArtifact.step_key == artifact.step_key,
                SnowflakeArtifact.artifact_id != artifact.artifact_id,
                SnowflakeArtifact.status.in_(["approved", "skipped"]),
            )
        ).scalars().all()
        for row in rows:
            row.status = "superseded"

    def _mark_downstream_stale(self, artifact: SnowflakeArtifact) -> None:
        step_index = STEP_INDEX[artifact.step_key]
        downstream_keys = [step["step_key"] for step in SNOWFLAKE_STEPS[step_index + 1 :]]
        if not downstream_keys:
            return
        rows = self.session.execute(
            select(SnowflakeArtifact).where(
                SnowflakeArtifact.project_id == artifact.project_id,
                SnowflakeArtifact.step_key.in_(downstream_keys),
                SnowflakeArtifact.status.in_(["pending_review", "approved", "skipped"]),
            )
        ).scalars().all()
        for row in rows:
            row.status = "stale"

    def _sync_characters(self, artifact: SnowflakeArtifact) -> None:
        if artifact.step_key not in {"character_sheets", "character_bibles"}:
            return
        characters = artifact.artifact_json.get("characters") or []
        for index, item in enumerate(characters, start=1):
            if not isinstance(item, dict):
                continue
            display_name = str(item.get("display_name") or item.get("name") or f"角色{index}").strip()
            character_id = str(item.get("character_id") or f"{artifact.project_id}_CHAR{index:02d}").strip()
            row = self.session.get(StoryCharacter, character_id)
            if row is None:
                row = StoryCharacter(
                    character_id=character_id,
                    project_id=artifact.project_id,
                    display_name=display_name,
                    role=item.get("role"),
                    summary_json={},
                    bible_json={},
                    status="approved",
                )
                self.session.add(row)
            row.display_name = display_name
            row.role = item.get("role") or row.role
            row.status = "approved"
            if artifact.step_key == "character_sheets":
                row.summary_json = item
            else:
                row.bible_json = item

    def _skip_artifact(self, step_key: str, payload: dict[str, Any]) -> dict[str, Any]:
        self._require_step(step_key)
        if not SNOWFLAKE_STEPS[STEP_INDEX[step_key]].get("skippable"):
            raise DomainError("SNOWFLAKE_STEP_NOT_SKIPPABLE", "this snowflake step cannot be skipped", status_code=400)
        reason = str(payload.get("skip_reason") or "").strip()
        if not reason:
            raise DomainError("SNOWFLAKE_SKIP_REASON_REQUIRED", "skip_reason is required", status_code=400)
        return {"skipped": True, "skip_reason": reason}

    def _diagnosis(self, step_key: str, artifact_json: dict[str, Any], status: str) -> dict[str, Any]:
        if status == "skipped":
            return {"severity": "info", "message": "此步骤已记录跳过原因，可继续下一步。"}
        if not artifact_json:
            return {"severity": "warning", "message": "候选内容为空。"}
        return {"severity": "info", "message": "候选已生成，作者确认后进入下一层雪花。"}

    def _diagnosis(
        self,
        step_key: str,
        artifact_json: dict[str, Any],
        status: str,
        *,
        generation_source: str | None = None,
    ) -> dict[str, Any]:
        del step_key
        if status == "skipped":
            return {
                "severity": "info",
                "message": "step skipped with an explicit author reason",
                "generation_source": generation_source or "skip",
            }
        if not artifact_json:
            return {
                "severity": "warning",
                "message": "generated candidate is empty",
                "generation_source": generation_source or "fallback",
            }
        return {
            "severity": "info",
            "message": "candidate generated and waiting for author approval",
            "generation_source": generation_source or "fallback",
        }

    def _build_artifact_json(
        self,
        project: StoryProject,
        step_key: str,
        latest_by_step: dict[str, SnowflakeArtifact],
    ) -> dict[str, Any]:
        outline_lines = _outline_lines(project.outline_text)
        return _build_outline_based_artifact(project, step_key, latest_by_step, outline_lines)
        if step_key == "book_brief":
            return {
                "category": project.genre or "长篇小说",
                "target_reader": f"喜欢{project.genre or '类型小说'}、人物选择和层层揭示的读者",
                "story_kind": "以行动、代价和真相揭露推动的长篇故事",
                "delight_reason": "读者会期待主角不断接近真相，同时承担越来越具体的关系代价。",
                "genre_promise": "以调查推进真相，以关系代价放大抉择。",
                "expected_reader_emotion": "读者应持续感到压力、怀疑和必须立刻翻页的未完成感。",
                "safety_rules": [
                    "参考书只能提供抽象风格与结构经验，不得复制原文表达。",
                    "不得借用参考书的人物、设定、桥段、标志性意象或句式。",
                ],
            }
        if step_key == "one_sentence_summary":
            return {
                "summary": "一名被旧信召回雨城的女人追查十年前旧案，却发现真相会撕开自己的家族。"
            }
        if step_key == "one_paragraph_summary":
            return {
                "sentences": [
                    "林岚收到来自十年前的信，被迫回到雨城面对旧案和家族裂缝。",
                    "她发现第一条线索指向亲人，决定留下调查。",
                    "调查中途，她原本相信的记忆被推翻，也必须改变只求自保的想法。",
                    "当关键证人失踪，幕后人逼她沉默，她和对手都走向最后摊牌。",
                    "林岚公开真相，失去安全的家庭幻象，却获得重新生活的自由。",
                ],
                "three_act_check": {
                    "first_disaster": "旧信证明旧案并未结束。",
                    "second_disaster": "家族成员可能参与掩盖真相。",
                    "third_disaster": "证人失踪，主角被迫公开对抗。",
                    "ending": "公开真相，承受代价。",
                },
                "moral_premise": "保护不是沉默，真正的保护要允许代价和真相同时被看见。",
            }
        if step_key == "character_sheets":
            return {"characters": _base_characters(project.project_id)}
        if step_key == "short_synopsis":
            return {
                "paragraphs": [
                    "林岚收到一封迟到十年的信，雨城旧案重新浮出水面。她原想只确认信件来源就离开，却发现信中细节只有家里人才知道。",
                    "她追查旧案时与陈渡重新合作，线索不断指向家族内部。林岚越想保护现有生活，越发现沉默本身就是当年悲剧的延续。",
                    "证人失踪后，沈确逼她在家族体面和公开真相之间选择。林岚最终公布证据，付出亲情破裂的代价，也结束了旧案制造的长期恐惧。",
                ]
            }
        if step_key == "character_synopses":
            return {
                "characters": [
                    {
                        **character,
                        "synopsis": f"{character['display_name']}围绕旧案不断被迫选择，个人目标与家族真相发生冲突。",
                    }
                    for character in _base_characters(project.project_id)
                ]
            }
        if step_key == "long_synopsis":
            short = latest_by_step.get("short_synopsis")
            paragraphs = list((short.artifact_json if short else {}).get("paragraphs") or [])
            return {"paragraphs": paragraphs + ["最后的公开行动让雨城旧案从私人伤口变成公共真相。"]}
        if step_key == "character_bibles":
            return {
                "characters": [
                    {
                        **character,
                        "age": 32 if index == 1 else 35 + index,
                        "home": "雨城旧城区",
                        "strongest_trait": "能在压力下快速行动",
                        "weakest_trait": "习惯把痛苦解释成自己的责任",
                        "deepest_fear": "真相会证明自己一直爱错了人",
                        "how_character_changes": "从逃避评价变成愿意承担公开真相的代价",
                    }
                    for index, character in enumerate(_base_characters(project.project_id), start=1)
                ]
            }
        if step_key == "scene_list":
            return {"scenes": _scene_list(project, outline_lines)}
        if step_key == "scene_details":
            scene_list = latest_by_step.get("scene_list")
            scenes = list((scene_list.artifact_json if scene_list else {}).get("scenes") or _scene_list(project, outline_lines))
            return {"scenes": [_scene_detail(scene, index) for index, scene in enumerate(scenes, start=1)]}
        raise DomainError("SNOWFLAKE_STEP_NOT_FOUND", "unknown snowflake step", status_code=404)


def _build_outline_based_artifact(
    project: StoryProject,
    step_key: str,
    latest_by_step: dict[str, Any],
    outline_lines: list[str],
) -> dict[str, Any]:
    lines = _ensure_outline_lines(project, outline_lines)
    zh = _looks_chinese(" ".join([project.title or "", project.genre or "", *lines]))
    lead = "主角" if zh else "the protagonist"
    opposition = lines[1] if len(lines) > 1 else lines[0]
    final_pressure = lines[-1]
    title = str(project.title or ("未命名小说" if zh else "Untitled Novel")).strip()
    genre = str(project.genre or ("长篇小说" if zh else "Novel")).strip()

    if step_key == "book_brief":
        if zh:
            return {
                "category": genre,
                "target_reader": f"喜欢{genre}、具体压力、人物选择和代价递增的读者。",
                "story_kind": f"围绕《{title}》展开的故事：{lines[0]}，但{final_pressure}",
                "delight_reason": "读者会持续追问下一步行动，因为每个线索都带来新的阻力、代价或关系变化。",
                "genre_promise": f"以{genre}的阅读快感推进，保留项目大纲中的事实和语言。",
                "expected_reader_emotion": "紧张、好奇、担心人物付出代价，并愿意继续翻页。",
                "safety_rules": [
                    "参考材料只抽象方法、节奏和结构。",
                    "不复制参考文本的人物、设定、桥段或标志性表达。",
                ],
            }
        return {
            "category": genre,
            "target_reader": f"Readers who want {genre}, concrete pressure, costly choices, and escalating reveals.",
            "story_kind": f"A {genre} shaped by this outline: {lines[0]}, but {final_pressure}.",
            "delight_reason": "Each clue, choice, or reversal should create a new cost or relationship change.",
            "genre_promise": f"Deliver the {genre} pleasure while preserving the project's own facts and language.",
            "expected_reader_emotion": "Curiosity, pressure, concern for the cost, and a strong need to keep reading.",
            "safety_rules": [
                "Use reference materials only for abstract craft, rhythm, and structure.",
                "Do not copy source characters, settings, plot beats, or signature phrasing.",
            ],
        }

    if step_key == "one_sentence_summary":
        if zh:
            return {"summary": f"{lead}必须处理“{lines[0]}”，但“{final_pressure}”让每一步都付出更高代价。"}
        return {"summary": f"In {title}, {lead} must face {lines[0]}, but {final_pressure}."}

    if step_key == "one_paragraph_summary":
        spine = _five_spine(lines)
        if zh:
            sentences = [
                f"{spine[0]}迫使{lead}进入无法回避的处境。",
                f"{spine[1]}制造第一次不可逆转的代价。",
                f"{spine[2]}改变{lead}对局面的判断。",
                f"{spine[3]}把所有人推向更公开、更危险的冲突。",
                f"{spine[4]}让结局必须在真相、关系和代价之间完成选择。",
            ]
            return {
                "sentences": sentences,
                "three_act_check": {
                    "first_disaster": sentences[1],
                    "second_disaster": sentences[2],
                    "third_disaster": sentences[3],
                    "ending": sentences[4],
                },
                "moral_premise": "逃避代价只会扩大伤害；承担选择才可能结束伤害。",
            }
        sentences = [
            f"{spine[0]} forces {lead} into a problem that cannot be ignored.",
            f"{spine[1]} creates the first irreversible cost.",
            f"{spine[2]} changes what {lead} believes about the situation.",
            f"{spine[3]} pushes the conflict into a more public and dangerous stage.",
            f"{spine[4]} forces the ending to choose between truth, relationship, and cost.",
        ]
        return {
            "sentences": sentences,
            "three_act_check": {
                "first_disaster": sentences[1],
                "second_disaster": sentences[2],
                "third_disaster": sentences[3],
                "ending": sentences[4],
            },
            "moral_premise": "Avoiding cost preserves harm; choosing with cost creates change.",
        }

    if step_key == "character_sheets":
        return {"characters": _outline_characters(project, lines, zh=zh)}

    if step_key == "short_synopsis":
        return {"paragraphs": _synopsis_paragraphs(lines, zh=zh, count=5)}

    if step_key == "character_synopses":
        return {
            "characters": [
                {
                    **character,
                    "synopsis": (
                        f"{character['display_name']} is pressured by {lines[0]} and must act while {final_pressure} changes the cost."
                        if not zh
                        else f"{character['display_name']}被“{lines[0]}”卷入压力，并在“{final_pressure}”带来的代价中做选择。"
                    ),
                }
                for character in _outline_characters(project, lines, zh=zh)
            ]
        }

    if step_key == "long_synopsis":
        short = latest_by_step.get("short_synopsis")
        paragraphs = list((short.artifact_json if short else {}).get("paragraphs") or _synopsis_paragraphs(lines, zh=zh, count=5))
        return {"paragraphs": paragraphs + _synopsis_paragraphs(lines[::-1], zh=zh, count=max(0, 4 - len(paragraphs)))}

    if step_key == "character_bibles":
        return {"characters": [_outline_character_bible(character, lines, zh=zh) for character in _outline_characters(project, lines, zh=zh)]}

    if step_key == "scene_list":
        return {"scenes": _outline_scene_list(project, lines, zh=zh)}

    if step_key == "scene_details":
        scene_list = latest_by_step.get("scene_list")
        scenes = list((scene_list.artifact_json if scene_list else {}).get("scenes") or _outline_scene_list(project, lines, zh=zh))
        return {"scenes": [_outline_scene_detail(scene, index, lines, zh=zh) for index, scene in enumerate(scenes, start=1)]}

    raise DomainError("SNOWFLAKE_STEP_NOT_FOUND", "unknown snowflake step", status_code=404)


def artifact_payload(artifact: SnowflakeArtifact | None) -> dict[str, Any] | None:
    if artifact is None:
        return None
    return {
        "artifact_id": artifact.artifact_id,
        "project_id": artifact.project_id,
        "step_key": artifact.step_key,
        "version": artifact.version,
        "status": artifact.status,
        "artifact_json": artifact.artifact_json or {},
        "input_refs_json": artifact.input_refs_json or {},
        "diagnosis_json": artifact.diagnosis_json or {},
        "llm_call_id": artifact.llm_call_id,
        "approved_at": artifact.approved_at,
        "created_at": artifact.created_at,
        "updated_at": artifact.updated_at,
    }


def _ensure_outline_lines(project: StoryProject, outline_lines: list[str]) -> list[str]:
    lines = [str(line or "").strip() for line in outline_lines if str(line or "").strip()]
    if lines:
        return lines
    title = str(project.title or "").strip()
    return [title or "The protagonist faces a costly change."]


def _looks_chinese(text: str) -> bool:
    cjk_count = sum(1 for char in str(text or "") if "\u4e00" <= char <= "\u9fff")
    return cjk_count >= 4


def _five_spine(lines: list[str]) -> list[str]:
    spine = [str(line or "").strip() for line in lines if str(line or "").strip()]
    while len(spine) < 5:
        spine.append(spine[-1] if spine else "A costly pressure turn")
    return spine[:5]


def _synopsis_paragraphs(lines: list[str], *, zh: bool, count: int) -> list[str]:
    spine = _five_spine(lines)
    paragraphs = []
    for index in range(count):
        point = spine[index % len(spine)]
        next_point = spine[(index + 1) % len(spine)]
        if zh:
            paragraphs.append(
                f"{point}。这一段必须把人物行动、阻力和代价写清楚，并让“{next_point}”成为下一段不得不发生的压力。"
            )
        else:
            paragraphs.append(
                f"{point}. This section turns the outline point into action, opposition, and cost, making {next_point} the next necessary pressure."
            )
    return paragraphs


def _outline_characters(project: StoryProject, lines: list[str], *, zh: bool) -> list[dict[str, Any]]:
    names = [("主角", "主角"), ("盟友", "盟友"), ("对手", "对手")] if zh else [
        ("Lead", "lead"),
        ("Ally", "ally"),
        ("Opposition", "opposition"),
    ]
    goal = lines[0]
    pressure = lines[1] if len(lines) > 1 else lines[0]
    cost = lines[-1]
    result = []
    for index, (display_name, role) in enumerate(names, start=1):
        character_id = f"{project.project_id}_CHAR{index:02d}"
        if zh:
            item = {
                "character_id": character_id,
                "display_name": display_name,
                "role": role,
                "goal": f"围绕“{goal}”采取行动",
                "ambition": f"在《{project.title}》中守住最重要的关系或信念",
                "values": ["真相比安全更重要", "保护也必须承担代价"],
                "conflict": f"“{pressure}”让目标和关系发生冲突",
                "epiphany": f"必须在“{cost}”面前做出有代价的选择",
                "one_sentence_summary": f"{display_name}必须处理“{goal}”，但“{cost}”改变了代价。",
                "one_paragraph_summary": f"{display_name}从“{goal}”进入故事，被“{pressure}”持续阻挡，最终必须面对“{cost}”。",
            }
        else:
            item = {
                "character_id": character_id,
                "display_name": display_name,
                "role": role,
                "goal": f"Act on {goal}",
                "ambition": f"Protect the central relationship or belief inside {project.title}",
                "values": ["truth over safety", "protection must carry a cost"],
                "conflict": f"{pressure} puts the goal and relationship at odds",
                "epiphany": f"The character must choose under the cost of {cost}",
                "one_sentence_summary": f"{display_name} must act on {goal}, but {cost} changes the price.",
                "one_paragraph_summary": f"{display_name} enters through {goal}, is blocked by {pressure}, and must finally face {cost}.",
            }
        result.append(item)
    return result


def _outline_character_bible(character: dict[str, Any], lines: list[str], *, zh: bool) -> dict[str, Any]:
    cost = lines[-1]
    home = lines[0]
    if zh:
        return {
            **character,
            "physical_profile": {"age": "", "height": "", "appearance": f"外貌应服务于“{home}”带来的生活压力", "style": ""},
            "personality_profile": {
                "strongest_trait": "能在压力下行动",
                "weakest_trait": "容易把沉默误认为保护",
                "humor": "",
                "preferences": [],
            },
            "environment_profile": {"home": home, "family_background": "", "education": "", "work": "", "relationships": ""},
            "psychological_profile": {
                "best_memory": "",
                "worst_memory": "",
                "deepest_fear": f"{cost}会摧毁现有关系",
                "greatest_hope": "真相和关系可以同时被修复",
                "philosophy": "选择必须承担代价",
                "self_image": "",
                "public_image": "",
                "character_arc": f"从回避代价变成愿意面对“{cost}”。",
            },
        }
    return {
        **character,
        "physical_profile": {"age": "", "height": "", "appearance": f"Appearance should reflect the pressure of {home}", "style": ""},
        "personality_profile": {
            "strongest_trait": "Acts under pressure",
            "weakest_trait": "Mistakes silence for protection",
            "humor": "",
            "preferences": [],
        },
        "environment_profile": {"home": home, "family_background": "", "education": "", "work": "", "relationships": ""},
        "psychological_profile": {
            "best_memory": "",
            "worst_memory": "",
            "deepest_fear": f"{cost} will destroy the current relationships",
            "greatest_hope": "Truth and relationship can both be repaired",
            "philosophy": "Every meaningful choice carries a cost",
            "self_image": "",
            "public_image": "",
            "character_arc": f"Moves from avoiding cost to facing {cost}.",
        },
    }


def _outline_scene_list(project: StoryProject, lines: list[str], *, zh: bool) -> list[dict[str, Any]]:
    chapter_count = max(1, min(project.target_chapter_count or len(lines) or 2, 4))
    spine = list(lines)
    while len(spine) < chapter_count:
        spine.append(spine[-1])
    scenes: list[dict[str, Any]] = []
    for chapter_index in range(1, chapter_count + 1):
        chapter_id = f"{project.project_id}_CH{chapter_index:02d}"
        chapter_point = spine[chapter_index - 1]
        for scene_index in range(1, 3):
            primary_form = "proactive" if scene_index == 1 else "reactive"
            summary = (
                f"{'行动' if scene_index == 1 else '反应'}：{chapter_point}"
                if zh
                else f"{'Action' if scene_index == 1 else 'Reaction'}: {chapter_point}"
            )
            scenes.append(
                {
                    "scene_id": f"{chapter_id}_SC{scene_index:02d}",
                    "chapter_id": chapter_id,
                    "chapter_title": f"{'第' + str(chapter_index) + '章' if zh else 'Chapter ' + str(chapter_index)}: {chapter_point[:36]}",
                    "chapter_goal": f"{'推进' if zh else 'Advance'}: {chapter_point}",
                    "scene_seq": scene_index,
                    "pov_character_id": f"{project.project_id}_CHAR01",
                    "onstage_chars_json": [f"{project.project_id}_CHAR01", f"{project.project_id}_CHAR02"],
                    "summary": summary,
                    "primary_form": primary_form,
                    "scene_type": primary_form,
                    "chapter_role": "承压" if scene_index == 1 and zh else "转向" if zh else ("pressure" if scene_index == 1 else "turn"),
                    "location": chapter_point,
                    "crucible": f"{chapter_point} cannot be avoided without locking in a bigger loss.",
                }
            )
    return scenes


def _outline_scene_detail(scene: dict[str, Any], index: int, lines: list[str], *, zh: bool) -> dict[str, Any]:
    primary_form = str(scene.get("primary_form") or scene.get("scene_type") or ("proactive" if index % 2 else "reactive")).strip().lower()
    if primary_form not in {"proactive", "reactive"}:
        primary_form = "proactive"
    summary = str(scene.get("summary") or lines[(index - 1) % len(lines)]).strip()
    base = {
        **scene,
        "primary_form": primary_form,
        "scene_type": primary_form,
        "location": scene.get("location") or summary,
        "target_length_band": scene.get("target_length_band") or "medium",
        "must_include_text": scene.get("must_include_text") or summary,
        "exit_change": scene.get("exit_change") or (f"{summary} leaves a new cost, clue, or relationship shift."),
        "hook": scene.get("hook") or (f"The result of {summary} forces the next move."),
        "triage_status": str(scene.get("triage_status") or "").strip(),
        "triage_notes": str(scene.get("triage_notes") or "").strip(),
    }
    if primary_form == "reactive":
        base.update(
            {
                "scene_crucible": scene.get("scene_crucible") or scene.get("crucible") or f"Retreating after {summary} would make the previous loss permanent.",
                "crucible": scene.get("crucible") or scene.get("scene_crucible") or f"Retreating after {summary} would make the previous loss permanent.",
                "reaction": scene.get("reaction") or f"The POV character absorbs the emotional damage from {summary} before analysis.",
                "dilemma": scene.get("dilemma") or f"One choice protects a relationship but buries the truth; the other exposes truth but costs safety.",
                "decision": scene.get("decision") or f"The POV character chooses the costly next action that follows from {summary}.",
                "beats_json": scene.get("beats_json") or ["reaction", "dilemma", "decision"],
            }
        )
    else:
        base.update(
            {
                "scene_crucible": scene.get("scene_crucible") or scene.get("crucible") or f"The goal inside {summary} is trapped by a clock, relationship cost, or irreversible loss.",
                "crucible": scene.get("crucible") or scene.get("scene_crucible") or f"The goal inside {summary} is trapped by a clock, relationship cost, or irreversible loss.",
                "goal": scene.get("goal") or f"Secure a concrete result from {summary} before the chance closes.",
                "conflict": scene.get("conflict") or f"The character tries a direct move, a workaround, and a risky reveal; each meets stronger resistance.",
                "setback": scene.get("setback") or f"The character gains something from {summary}, but the cost creates a worse and more personal problem.",
                "beats_json": scene.get("beats_json") or ["goal", "conflict", "setback"],
            }
        )
    return base


def _base_characters(project_id: str) -> list[dict[str, Any]]:
    return [
        {
            "character_id": f"{project_id}_CHAR01",
            "display_name": "林岚",
            "role": "主角",
            "goal": "查清十年前旧案与旧信来源",
            "ambition": "摆脱被家族评价束缚的人生",
            "values": ["没有什么比真相更重要", "没有什么比保护所爱的人更重要"],
            "conflict": "真相会伤害她想保护的家人。",
            "epiphany": "真正的保护不是沉默，而是让代价被看见。",
            "one_sentence_summary": "一名回到雨城的女人追查旧案，却发现真相来自家族内部。",
            "one_paragraph_summary": "林岚收到旧信后回城调查，逐步发现家族参与掩盖旧案；她在关系与真相之间挣扎，最终选择公开证据。",
        },
        {
            "character_id": f"{project_id}_CHAR02",
            "display_name": "陈渡",
            "role": "盟友",
            "goal": "帮助林岚恢复旧案证据链",
            "ambition": "证明自己当年没有背弃朋友",
            "values": ["没有什么比兑现承诺更重要", "没有什么比证据更重要"],
            "conflict": "他掌握的信息会让林岚重新受伤。",
            "epiphany": "陪伴不是替人决定，而是把选择交还给她。",
            "one_sentence_summary": "一名旧友试图补上迟到十年的证据，却必须面对自己的沉默。",
            "one_paragraph_summary": "陈渡协助调查旧信与旧案，既提供证据也制造新的不信任，最终学会让林岚自己做选择。",
        },
        {
            "character_id": f"{project_id}_CHAR03",
            "display_name": "沈确",
            "role": "对手",
            "goal": "阻止旧案真相公开",
            "ambition": "维持雨城体面和家族秩序",
            "values": ["没有什么比秩序更重要", "没有什么比保住体面更重要"],
            "conflict": "林岚的调查不断逼近他保护的秘密。",
            "epiphany": "",
            "one_sentence_summary": "一名守旧秩序的人不惜继续制造伤害，也要让旧案保持沉默。",
            "one_paragraph_summary": "沈确操控旧案相关证据，试图逼退林岚，但他的阻拦反而让真相更快浮出水面。",
        },
    ]


def _outline_lines(outline_text: str) -> list[str]:
    lines = [line.strip(" -\t\r\n.。") for line in str(outline_text or "").splitlines() if line.strip()]
    return lines or ["旧信把主角带回雨城", "旧案牵出家族秘密", "主角公开真相"]


def _scene_list(project: StoryProject, outline_lines: list[str]) -> list[dict[str, Any]]:
    chapter_count = max(1, min(project.target_chapter_count or len(outline_lines) or 2, 4))
    while len(outline_lines) < chapter_count:
        outline_lines.append(outline_lines[-1])
    scenes: list[dict[str, Any]] = []
    for chapter_index in range(1, chapter_count + 1):
        chapter_id = f"{project.project_id}_CH{chapter_index:02d}"
        chapter_point = outline_lines[chapter_index - 1]
        for scene_index in range(1, 3):
            scenes.append(
                {
                    "scene_id": f"{chapter_id}_SC{scene_index:02d}",
                    "chapter_id": chapter_id,
                    "chapter_title": f"第{chapter_index:02d}章 {chapter_point[:16]}",
                    "chapter_goal": f"推进大纲节点：{chapter_point}",
                    "scene_seq": scene_index,
                    "pov_character_id": f"{project.project_id}_CHAR01",
                    "onstage_chars_json": [f"{project.project_id}_CHAR01", f"{project.project_id}_CHAR02"],
                    "summary": f"{'打开局面' if scene_index == 1 else '制造转折'}：{chapter_point}",
                    "scene_type": "proactive" if scene_index == 1 else "reactive",
                    "chapter_role": "承压" if scene_index == 1 else "转向",
                }
            )
    return scenes


def _scene_detail(scene: dict[str, Any], index: int) -> dict[str, Any]:
    scene_type = str(scene.get("scene_type") or ("proactive" if index % 2 else "reactive"))
    base = {
        **scene,
        "scene_type": scene_type,
        "location": "雨城旧街",
        "target_length_band": "medium",
        "must_include_text": scene.get("summary"),
        "exit_change": "林岚得到新证据，但必须付出关系代价。",
        "hook": "新的证据指向更亲近的人。",
    }
    if scene_type == "reactive":
        base.update(
            {
                "scene_crucible": "如果人物在这一刻退缩，上一场 setback 带来的损失就会扩大并冻结后续行动。",
                "reaction": "林岚被上一场的发现击中，短暂失去判断。",
                "dilemma": "她不能退回安全生活，也不能立刻公开未证实的线索。",
                "decision": "她决定冒险去见掌握时间线的人。",
                "beats_json": ["情绪反应", "两难选择", "做出下一步决定"],
            }
        )
    else:
        base.update(
            {
                "scene_crucible": "人物越接近眼前目标，就越接近会让她付出代价的阻力源。",
                "goal": "林岚要确认旧信与旧案的直接关联。",
                "conflict": "相关人物回避证据，并用家族关系压她停手。",
                "setback": "她拿到线索，却发现线索指向自己的家人。",
                "beats_json": ["带着目标进入场景", "遭遇阻碍", "以代价或坏消息收束"],
            }
        )
    return base


def _scene_detail(scene: dict[str, Any], index: int) -> dict[str, Any]:
    scene_type = str(scene.get("scene_type") or ("proactive" if index % 2 else "reactive")).strip() or "proactive"
    base = {
        **scene,
        "scene_type": scene_type,
        "location": scene.get("location") or "rain city old street",
        "target_length_band": scene.get("target_length_band") or "medium",
        "must_include_text": scene.get("must_include_text") or scene.get("summary"),
        "exit_change": scene.get("exit_change") or "The scene should leave a visible cost or new pressure.",
        "hook": scene.get("hook") or "End with a pull that forces the next scene.",
        "triage_status": str(scene.get("triage_status") or "").strip(),
        "triage_notes": str(scene.get("triage_notes") or "").strip(),
    }
    if scene_type == "reactive":
        base.update(
            {
                "scene_crucible": scene.get("scene_crucible")
                or scene.get("crucible")
                or "If the character retreats here, the previous setback hardens into loss.",
                "crucible": scene.get("crucible")
                or scene.get("scene_crucible")
                or "If the character retreats here, the previous setback hardens into loss.",
                "reaction": scene.get("reaction") or "The protagonist reels from the last blow.",
                "dilemma": scene.get("dilemma") or "Every available move now carries a cost.",
                "decision": scene.get("decision") or "The protagonist commits to the next risky move.",
                "beats_json": scene.get("beats_json") or ["reaction", "dilemma", "decision"],
            }
        )
    else:
        base.update(
            {
                "scene_crucible": scene.get("scene_crucible")
                or scene.get("crucible")
                or "The closer the protagonist moves toward the goal, the closer the price gets.",
                "crucible": scene.get("crucible")
                or scene.get("scene_crucible")
                or "The closer the protagonist moves toward the goal, the closer the price gets.",
                "goal": scene.get("goal") or "The protagonist enters with a concrete objective.",
                "conflict": scene.get("conflict") or "People, information, or the setting block that objective.",
                "setback": scene.get("setback") or "The scene ends with loss, cost, or a harder problem.",
                "beats_json": scene.get("beats_json") or ["goal", "conflict", "setback"],
            }
        )
    return base


def _scene_writer_brief(scene_type: str, detail: dict[str, Any]) -> dict[str, Any]:
    if scene_type == "reactive":
        return {
            "source": "snowflake_method",
            "scene_form": "reactive",
            "scene_crucible": detail.get("scene_crucible") or detail.get("crucible") or "人物此刻如果退缩，就会失去继续推进故事的能力。",
            "reaction": detail.get("reaction") or "人物对上一场后果产生情绪反应。",
            "dilemma": detail.get("dilemma") or "人物面对两个都要付出代价的选择。",
            "decision": detail.get("decision") or "人物做出推动下一场的决定。",
            "must_reveal": detail.get("decision") or "",
            "must_withhold": "不要一次解释完上一场 setback 的全部意义。",
            "expected_reader_emotion": "让读者感到人物在痛苦之后仍被迫继续行动。",
            "timebox": detail.get("target_length_band") or "medium",
            "next_scene_pull": detail.get("hook") or "",
        }
    return {
        "source": "snowflake_method",
        "scene_form": "proactive",
        "scene_crucible": detail.get("scene_crucible") or detail.get("crucible") or "人物为了得到目标，必须穿过会伤到她的阻力源。",
        "goal": detail.get("goal") or "人物带着具体目标进入场景。",
        "conflict": detail.get("conflict") or "目标被人物、信息或环境阻碍。",
        "setback": detail.get("setback") or "场景以坏消息、代价或新问题收束。",
        "must_reveal": detail.get("setback") or "",
        "must_withhold": "不要提前解释完整背景，只揭示当前场景必需的信息。",
        "expected_reader_emotion": "让读者感到人物主动出击却被阻力持续抬高代价。",
        "timebox": detail.get("target_length_band") or "medium",
        "next_scene_pull": detail.get("hook") or "",
    }


def _beats_from_detail(scene_type: str, detail: dict[str, Any]) -> list[str]:
    keys = ["reaction", "dilemma", "decision"] if scene_type == "reactive" else ["goal", "conflict", "setback"]
    return [str(detail.get(key) or "").strip() for key in keys if str(detail.get(key) or "").strip()]
