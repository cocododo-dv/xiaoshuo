from __future__ import annotations

import json
import time
import uuid
from dataclasses import dataclass
from typing import Any, Callable, Mapping

from sqlalchemy.orm import Session

from novel_system.db.models import LlmCall, StoryProject
from novel_system.services.errors import DomainError
from novel_system.services.hash_engine import canonical_json, normalize
from novel_system.services.llm_client import (
    LLMClient,
    LLMRequest,
    LLMResponse,
    LLMClientError,
    LLMConfigurationError,
    load_model_routing_config,
)
from novel_system.services.prompt_builder import PromptConfigurationError, load_prompt_templates
from novel_system.services.snowflake_steps import (
    diagnose_scene_detail,
    diagnose_step_pressure,
    get_step_definition,
    merge_step_draft,
    step_completeness,
    step_guidance,
)
from novel_system.services.system_config import load_llm_provider_runtime_configs
from novel_system.settings import get_settings


@dataclass(slots=True)
class WorkspaceLLMResult:
    source: str
    llm_call_id: str | None
    payload: dict[str, Any]


class SnowflakeWorkspaceLLMService:
    def __init__(
        self,
        session: Session,
        *,
        llm_client: Any | None = None,
        routing_config: Any | None = None,
        prompt_templates: dict[str, Any] | None = None,
    ) -> None:
        self.session = session
        self._llm_client = llm_client
        self._routing_config = routing_config
        self._prompt_templates = prompt_templates
        self._provider_configs: dict[str, Any] | None = None
        self._settings = None

    def generate_step(
        self,
        *,
        project: StoryProject,
        step_key: str,
        latest_by_step: Mapping[str, Any],
        fallback_factory: Callable[[], dict[str, Any]],
        adopted_direction: str | None = None,
        focus_scene_refs: list[str] | None = None,
        focus_character_refs: list[str] | None = None,
        draft_override: dict[str, Any] | None = None,
    ) -> WorkspaceLLMResult:
        step_definition = get_step_definition(step_key)
        # draft_override：FE 与上行 PATCH 同源的本地最新规范草稿（service 层已并入
        # 存档、剥 fe_*）——消除「刚编辑还没自动保存上行，模型看不到」的竞态。
        current_source = (
            draft_override
            if draft_override
            else (latest_by_step.get(step_key).artifact_json if latest_by_step.get(step_key) is not None else None)
        )
        current_draft = merge_step_draft(
            step_key,
            current_source,
            latest_by_step=dict(latest_by_step),
        )
        # 单场定向：refs 可以是 row_uid 或 scene_id；解析失败要报错而不是悄悄全量重写
        focus_scene_ids: list[str] = []
        focus_scenes: list[dict[str, Any]] = []
        focus_scene_allowed: set[str] = set()
        if focus_scene_refs:
            refs = set(focus_scene_refs)
            for scene in current_draft.get("scenes") or []:
                if not isinstance(scene, dict):
                    continue
                if {str(scene.get("row_uid") or ""), str(scene.get("scene_id") or "")} & refs:
                    focus_scenes.append(scene)
                    focus_scene_ids.append(str(scene.get("scene_id") or ""))
                    focus_scene_allowed |= {str(scene.get("scene_id") or ""), str(scene.get("row_uid") or "")}
            focus_scene_allowed = {ref for ref in (focus_scene_allowed | refs) if ref}
            if not focus_scenes:
                raise DomainError(
                    "SNOWFLAKE_FOCUS_SCENE_NOT_FOUND",
                    "指定的场景不在当前场景规划草稿里（可能刚被删除或还未保存）——刷新后重试。",
                    status_code=409,
                    details={"focus_scene_refs": focus_scene_refs},
                )
        # 单角色定向（04/06/08 三个角色集合步）：refs 可以是 character_id 或姓名。
        # 06/08 的成员可能还没在本步草稿里立档——用 04 角色摘要表的名册兜底解析，
        # 解析出的种子成员（id/姓名/定位）进焦点上下文，生成后按 character_id 合并。
        focus_character_ids: list[str] = []
        focus_characters: list[dict[str, Any]] = []
        focus_character_allowed: set[str] = set()
        if focus_character_refs:
            refs = {str(ref or "").strip() for ref in focus_character_refs if str(ref or "").strip()}
            matched_refs: set[str] = set()

            def _match_member(member: dict[str, Any]) -> set[str]:
                return {str(member.get("character_id") or ""), str(member.get("display_name") or "").strip()} & refs

            for member in current_draft.get("characters") or []:
                if not isinstance(member, dict):
                    continue
                hit = _match_member(member)
                if hit:
                    focus_characters.append(member)
                    focus_character_ids.append(str(member.get("character_id") or ""))
                    focus_character_allowed |= {str(member.get("character_id") or ""), str(member.get("display_name") or "").strip()}
                    matched_refs |= hit
            if refs - matched_refs and step_key != "character_sheets":
                roster_artifact = latest_by_step.get("character_sheets")
                roster = (getattr(roster_artifact, "artifact_json", None) or {}).get("characters") if roster_artifact is not None else None
                for member in roster or []:
                    if not isinstance(member, dict):
                        continue
                    hit = _match_member(member) - matched_refs
                    if hit:
                        seed = {
                            "character_id": str(member.get("character_id") or ""),
                            "display_name": str(member.get("display_name") or "").strip(),
                            "role": str(member.get("role") or "").strip(),
                        }
                        focus_characters.append(seed)
                        focus_character_ids.append(seed["character_id"])
                        focus_character_allowed |= {seed["character_id"], seed["display_name"]}
                        matched_refs |= hit
            focus_character_allowed = {ref for ref in (focus_character_allowed | refs) if ref}
            if not focus_characters:
                raise DomainError(
                    "SNOWFLAKE_FOCUS_CHARACTER_NOT_FOUND",
                    "指定的角色不在当前名册里（可能刚被删除或还未保存）——刷新后重试。",
                    status_code=409,
                    details={"focus_character_refs": focus_character_refs},
                )
        approved_steps = _approved_step_context(latest_by_step)
        guidance = step_guidance(step_key)
        prompt_payload = {
            "project": _project_prompt_payload(project),
            "step_key": step_key,
            "step_label": step_definition.get("label"),
            "step_english_label": step_definition.get("english_label"),
            "step_description": step_definition.get("description"),
            "step_instruction": guidance.get("instruction"),
            "step_guidance": guidance,
            "step_editor": step_definition.get("editor") or {},
            "approved_steps": approved_steps,
            "current_draft": _sanitize_canonical_draft(current_draft),
            "pressure_rubric": _pressure_rubric(step_key),
            "current_pressure_diagnosis": diagnose_step_pressure(step_key, current_draft),
            "scene_rules": _scene_rules(step_key),
        }
        if adopted_direction:
            prompt_payload["adopted_direction"] = {
                "text": adopted_direction,
                "how_to_use": (
                    # 定向采纳（候选 × 焦点成员）与整步采纳的蓝本用法不同：前者只落到焦点成员
                    "作者已选定这段文字作为定向蓝本：只把它落实到 focus 指定的成员上，"
                    "保留它的核心意象、人物立场与转折；焦点外的成员一律不动、不复述。"
                    if (focus_scenes or focus_characters)
                    else "作者已选定这段文字作为本步的方向蓝本：以它为基调把本步全部字段结构化展开，"
                    "保留它的核心意象、人物立场与转折，不要另起新方向；它没有覆盖到的字段按上游材料补全。"
                ),
            }
        if focus_scenes:
            prompt_payload["focus_scenes"] = {
                "scenes": normalize(focus_scenes),
                "how_to_use": (
                    "本次只深化 focus_scenes 里列出的场景：输出的 scenes 数组只包含这些场景，"
                    "scene_id 必须原样回传（服务端按 scene_id 合并，其余场景保持不动）；"
                    "结合前后场景的挫败/决定衔接（见 current_draft），不要改动场景的类型与顺序。"
                ),
            }
        if focus_characters:
            prompt_payload["focus_characters"] = {
                "characters": normalize(focus_characters),
                "how_to_use": (
                    "本次只深化 focus_characters 里列出的角色：输出的 characters 数组只包含这些角色，"
                    "character_id 必须原样回传（服务端按 character_id 合并，其余角色保持不动）。"
                    "current_draft 里焦点外的角色是已确立的既成事实：只作为一致性参照"
                    "（人物关系、立场、时间线必须与他们吻合），不要改写他们，也不要在输出里复述他们。"
                ),
            }
        fallback_payload = fallback_factory()
        # 集合步（角色×3 / 场景规划）的合并底稿一律用「当前最新草稿」（剥 fe_* 写穿键）：
        # 默认底稿是空骨架 / 从 scene_list 重新播种的骨架，模型没回传的成员会被整体
        # 丢掉——作者手工加的角色、焦点外场景的既有深化都要在这里幸存。
        # scene_list 的「AI 生成整表」保持替换语义：重排整表时不让旧场景残留混排。
        keep_members = step_key in _CHARACTER_COLLECTION_STEPS or step_key == "scene_details"
        merge_base = (
            {key: value for key, value in current_draft.items() if not str(key).startswith("fe_")}
            if keep_members
            else None
        )
        # 焦点定向的服务端硬约束：不管模型是否守约，输出里焦点外的成员一律丢弃，
        # 合并时保持原样——「其余成员不动」不能只靠提示词。
        focus_filter: dict[str, Any] | None = None
        if focus_scenes:
            focus_filter = {"field": "scenes", "id_keys": ("scene_id", "row_uid"), "allowed": focus_scene_allowed}
        elif focus_characters:
            focus_filter = {"field": "characters", "id_keys": ("character_id", "display_name", "name"), "allowed": focus_character_allowed}
        run_kwargs: dict[str, Any] = dict(
            task_key="snowflake_step_generate",
            template_name=f"snowflake_generate_{step_key}",
            project_id=project.project_id,
            step_ref=step_key,
            fallback_payload=fallback_payload,
            normalize_output=lambda output: _normalize_full_step_output(
                step_key,
                output,
                latest_by_step=dict(latest_by_step),
                project_id=project.project_id,
                base_override=merge_base,
                focus_filter=focus_filter,
            ),
        )
        result = self._run_structured_task(prompt_payload=prompt_payload, **run_kwargs)
        if result.source != "llm":
            return result

        # 完备性修复重试（残缺兜底）：模型输出经清洗（丢契约外键）后仍有空字段时，
        # 带着空字段清单再给模型一次机会；只有重试确实更完整才采用，失败保留首版。
        # 单场定向时只盯焦点场景的缺口——焦外场景本来就没让模型动。
        def collect_gaps(payload: dict[str, Any]) -> list[str]:
            gaps = _collect_generation_gaps(step_key, payload)
            if focus_scene_ids:
                focus_set = set(focus_scene_ids)
                gaps = [gap for gap in gaps if gap.split(".", 1)[0] in focus_set]
            elif focus_characters:
                # 角色缺口标签形如 characters[姓名或id].field——只盯焦点角色的缺口
                allowed_labels = {f"characters[{ref}]" for ref in focus_character_allowed}
                gaps = [gap for gap in gaps if gap.split(".", 1)[0] in allowed_labels]
            return gaps

        gaps = collect_gaps(result.payload)
        if not gaps:
            return result
        repair_payload = dict(prompt_payload)
        repair_payload["completeness_repair"] = {
            "empty_fields": gaps[:40],
            "instruction": (
                "The previous attempt left every field listed in empty_fields blank after server-side "
                "sanitization (unknown keys are discarded — use only the canonical keys named in the task). "
                "Regenerate the complete step and make sure each listed field carries substantive, "
                "story-specific content; empty strings and placeholders are defects."
            ),
        }
        try:
            retry = self._run_structured_task(prompt_payload=repair_payload, **run_kwargs)
        except DomainError:
            return result
        if retry.source == "llm" and len(collect_gaps(retry.payload)) < len(gaps):
            return retry
        return result

    # FE-ALIGN G5：构思视图的「生成 3 条候选」——提示词由模板组装。
    # 上下文以后端权威材料为主（approved 各步规范草稿 + 当前步压力诊断），
    # 前端折叠文本降级为「本地未上行编辑」的补充信号。
    def step_candidates(
        self,
        *,
        project: StoryProject,
        step_key: str,
        context_text: str,
        current_draft: str,
        target_chars: int,
        latest_by_step: Mapping[str, Any] | None = None,
    ) -> WorkspaceLLMResult:
        step_definition = get_step_definition(step_key)
        guidance = step_guidance(step_key)
        prompt_payload = {
            "project": _project_prompt_payload(project),
            "step_key": step_key,
            "step_label": step_definition.get("label"),
            "step_english_label": step_definition.get("english_label"),
            "step_description": step_definition.get("description"),
            "step_instruction": guidance.get("instruction"),
            "fe_local_context": context_text,
            "current_draft_text": current_draft,
            "target_chars": target_chars,
        }
        if latest_by_step is not None:
            current_canonical = merge_step_draft(
                step_key,
                latest_by_step.get(step_key).artifact_json if latest_by_step.get(step_key) is not None else None,
                latest_by_step=dict(latest_by_step),
            )
            prompt_payload.update(
                {
                    "approved_steps": _approved_step_context(latest_by_step),
                    "current_canonical_draft": _sanitize_canonical_draft(current_canonical),
                    "pressure_rubric": _pressure_rubric(step_key),
                    "current_pressure_diagnosis": diagnose_step_pressure(step_key, current_canonical),
                }
            )
        return self._run_structured_task(
            task_key="snowflake_step_candidates",
            template_name="snowflake_step_candidates",
            project_id=project.project_id,
            step_ref=step_key,
            prompt_payload=prompt_payload,
            fallback_payload={"candidates": []},
            normalize_output=_normalize_candidates_output,
        )

    def assistant_reply(
        self,
        *,
        project: dict[str, Any],
        step: dict[str, Any],
        message: str,
        approved_context: list[dict[str, Any]],
        latest_by_step: Mapping[str, Any],
        fallback_factory: Callable[[], dict[str, Any]],
        focus_scene_id: str | None = None,
    ) -> WorkspaceLLMResult:
        step_key = str(step.get("step_key") or "book_brief").strip() or "book_brief"
        guidance_payload = step.get("guidance") if isinstance(step.get("guidance"), dict) else {}
        prompt_payload = {
            "project": project,
            "step_key": step_key,
            "step_label": step.get("label"),
            "step_english_label": step.get("english_label"),
            "step_description": step.get("description"),
            "step_instruction": guidance_payload.get("instruction"),
            "step_guidance": guidance_payload,
            "step_editor": step.get("editor") or {},
            "draft": _sanitize_canonical_draft(step.get("draft") if isinstance(step.get("draft"), dict) else {}),
            "message": str(message or "").strip(),
            "approved_context": approved_context,
            "focus_scene_id": focus_scene_id or "",
            "focus_scene": _focus_scene_payload(step, focus_scene_id),
            "pressure_rubric": _pressure_rubric(step_key),
            "current_pressure_diagnosis": diagnose_step_pressure(step_key, step.get("draft") if isinstance(step.get("draft"), dict) else {}),
            "scene_rules": _scene_rules(step_key),
        }
        fallback_payload = fallback_factory()
        return self._run_structured_task(
            task_key="snowflake_workspace_assistant",
            template_name="snowflake_workspace_assistant",
            project_id=str(project.get("project_id") or ""),
            step_ref=step_key,
            prompt_payload=prompt_payload,
            fallback_payload=fallback_payload,
            normalize_output=lambda output: _normalize_assistant_output(
                step_key,
                output,
                latest_by_step=dict(latest_by_step),
                base_draft=step.get("draft") if isinstance(step.get("draft"), dict) else {},
            ),
        )

    def scene_triage_suggestions(
        self,
        *,
        project: dict[str, Any],
        step: dict[str, Any],
        approved_context: list[dict[str, Any]],
    ) -> WorkspaceLLMResult:
        step_key = "scene_details"
        draft = step.get("draft") if isinstance(step.get("draft"), dict) else {}
        guidance_payload = step.get("guidance") if isinstance(step.get("guidance"), dict) else {}
        prompt_payload = {
            "project": project,
            "step_key": step_key,
            "step_label": step.get("label"),
            "step_english_label": step.get("english_label"),
            "step_instruction": guidance_payload.get("instruction"),
            "draft": _sanitize_canonical_draft(draft),
            "approved_context": approved_context,
            "pressure_rubric": _pressure_rubric(step_key),
            "current_pressure_diagnosis": diagnose_step_pressure(step_key, draft),
            "triage_rules": {
                "pass": "The scene has enough pressure and the required trio is present.",
                "maybe": "The scene is salvageable but its pressure, clarity, or required trio is incomplete.",
                "rewrite": "The scene core is too hollow and should be reworked from premise level.",
            },
            "scene_rules": _scene_rules(step_key),
        }
        fallback_payload = {"items": _fallback_triage_items(draft)}
        return self._run_structured_task(
            task_key="snowflake_scene_triage",
            template_name="snowflake_scene_triage_suggest",
            project_id=str(project.get("project_id") or ""),
            step_ref=step_key,
            prompt_payload=prompt_payload,
            fallback_payload=fallback_payload,
            normalize_output=lambda output: _normalize_triage_output(output, draft),
        )

    def _run_structured_task(
        self,
        *,
        task_key: str,
        template_name: str,
        project_id: str,
        step_ref: str,
        prompt_payload: dict[str, Any],
        fallback_payload: dict[str, Any],
        normalize_output: Callable[[dict[str, Any]], dict[str, Any]],
    ) -> WorkspaceLLMResult:
        if not self._llm_enabled():
            return WorkspaceLLMResult(source="fallback", llm_call_id=None, payload=normalize(fallback_payload))

        try:
            task_config = self._task_config(task_key)
            template = self._template(template_name)
        except (KeyError, LLMConfigurationError, PromptConfigurationError) as exc:
            missing_route = isinstance(exc, KeyError)
            if missing_route:
                message = (
                    f"模型已接入，但 LLM 节点路由未配置：{task_key}。"
                    "请到配置环境点击“一键补齐”，或在节点路由中为该节点绑定 provider/model 后重试。"
                )
                next_action = "sync_missing_llm_node_routes"
            else:
                message = (
                    f"snowflake LLM prompt or route is not ready: {task_key}。"
                    "请检查节点路由、提示词模板和模型配置后重试。"
                )
                next_action = "configure_snowflake_node_route_and_prompt_then_retry"
            raise DomainError(
                "SNOWFLAKE_LLM_ROUTE_OR_PROMPT_MISSING",
                message,
                status_code=409,
                details={
                    "node_id": task_key,
                    "template_name": template_name,
                    "error_code": getattr(exc, "code", exc.__class__.__name__),
                    "reason": "missing_node_route" if missing_route else "route_or_prompt_invalid",
                    "next_action": next_action,
                },
            ) from exc

        user_prompt = _render_user_prompt(template, prompt_payload)
        prompt_hash = _prompt_hash(template_name, template.version, template.system_prompt, user_prompt, template.structured_schema)
        llm_call_id = f"llm_call_project_{task_key}_{uuid.uuid4().hex[:12]}"
        started_at = time.perf_counter()
        request = LLMRequest(
            model=task_config.model,
            messages=[
                {"role": "system", "content": template.system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            temperature=task_config.temperature,
            max_output_tokens=task_config.max_output_tokens,
            response_format=task_config.response_format,
            provider=task_config.provider,
            node_id=task_key,
            provider_id=getattr(task_config, "provider_id", None),
            account_id=getattr(task_config, "account_id", None),
            reasoning_level=getattr(task_config, "reasoning_level", "medium"),
            api_mode=getattr(task_config, "api_mode", "responses"),
            credential_mode=getattr(task_config, "credential_mode", None),
            provider_options=getattr(task_config, "provider_options", {}),
            response_schema={"name": template.name, "schema": template.structured_schema},
        )
        request_summary = {
            "task_key": task_key,
            "template_name": template.name,
            "template_version": template.version,
            "step_key": step_ref,
            **normalize(prompt_payload),
        }
        try:
            response = self._client().generate(request)
        except Exception as exc:  # noqa: BLE001
            self._persist_failed_call(
                llm_call_id=llm_call_id,
                project_id=project_id,
                step_ref=step_ref,
                task_key=task_key,
                task_config=task_config,
                request=request,
                request_summary=request_summary,
                prompt_hash=prompt_hash,
                started_at=started_at,
                error_code=getattr(exc, "code", exc.__class__.__name__),
                response_summary=_error_summary(exc),
            )
            raise DomainError(
                "SNOWFLAKE_LLM_CALL_FAILED",
                _llm_failure_message(exc, task_key),
                status_code=409,
                details={
                    "llm_call_id": llm_call_id,
                    "node_id": task_key,
                    "error_code": getattr(exc, "code", exc.__class__.__name__),
                    "next_action": "check_provider_route_model_and_retry",
                    "response_summary": _error_summary(exc),
                },
            ) from exc

        try:
            raw_output = response.structured_output or {}
            if not isinstance(raw_output, dict):
                raise ValueError("structured output must be an object")
            normalized_output = normalize_output(raw_output)
        except Exception as exc:  # noqa: BLE001
            self._persist_failed_call(
                llm_call_id=llm_call_id,
                project_id=project_id,
                step_ref=step_ref,
                task_key=task_key,
                task_config=task_config,
                request=request,
                request_summary=request_summary,
                prompt_hash=prompt_hash,
                started_at=started_at,
                error_code="LLM_RESPONSE_INVALID_SCHEMA",
                response_summary={
                    "message": str(exc),
                    "structured_output": response.structured_output,
                    "request_id": response.request_id,
                },
                response=response,
            )
            raise DomainError(
                "SNOWFLAKE_LLM_RESPONSE_INVALID_SCHEMA",
                str(exc),
                status_code=409,
                details={
                    "llm_call_id": llm_call_id,
                    "node_id": task_key,
                    "error_code": "LLM_RESPONSE_INVALID_SCHEMA",
                    "next_action": "retry_or_adjust_prompt_schema",
                    "structured_output": response.structured_output,
                },
            ) from exc

        self._persist_successful_call(
            llm_call_id=llm_call_id,
            project_id=project_id,
            step_ref=step_ref,
            task_key=task_key,
            request=request,
            request_summary=request_summary,
            prompt_hash=prompt_hash,
            started_at=started_at,
            response=response,
        )
        return WorkspaceLLMResult(source="llm", llm_call_id=llm_call_id, payload=normalized_output)

    def llm_enabled(self) -> bool:
        """公开可用性探针：FE 的「采纳并结构化」用它决定报错而不是落 fallback 版本。"""
        return self._llm_enabled()

    def _llm_enabled(self) -> bool:
        return bool(self._settings_payload().llm_enabled)

    def _settings_payload(self):
        if self._settings is None:
            self._settings = get_settings()
        return self._settings

    def _client(self) -> Any:
        if self._llm_client is not None:
            return self._llm_client
        settings = self._settings_payload()
        return LLMClient(
            provider=settings.llm_provider,
            base_url=settings.llm_base_url,
            api_key=settings.llm_api_key,
            timeout_seconds=settings.llm_timeout_seconds,
            provider_configs=self._runtime_provider_configs(),
        )

    def _runtime_provider_configs(self) -> dict[str, Any]:
        if self._provider_configs is None:
            self._provider_configs = load_llm_provider_runtime_configs()
        return self._provider_configs

    def _routing(self) -> Any:
        if self._routing_config is None:
            self._routing_config = load_model_routing_config()
        return self._routing_config

    def _task_config(self, task_key: str) -> Any:
        routing = self._routing()
        node_routing = getattr(routing, "node_routing", {})
        if isinstance(node_routing, dict) and task_key in node_routing:
            return node_routing[task_key]
        task_routing = getattr(routing, "task_routing", {})
        if task_key in task_routing:
            return task_routing[task_key]
        raise KeyError(task_key)

    def _template(self, template_name: str) -> Any:
        if self._prompt_templates is None:
            self._prompt_templates = load_prompt_templates()
        return self._prompt_templates[template_name]

    def _persist_successful_call(
        self,
        *,
        llm_call_id: str,
        project_id: str,
        step_ref: str,
        task_key: str,
        request: LLMRequest,
        request_summary: dict[str, Any],
        prompt_hash: str,
        started_at: float,
        response: LLMResponse,
    ) -> None:
        self.session.add(
            LlmCall(
                llm_call_id=llm_call_id,
                scope_type="project",
                scope_id=project_id,
                provider=response.provider,
                provider_id=request.provider_id,
                account_id=request.account_id,
                model=response.model,
                node_id=task_key,
                reasoning_level=request.reasoning_level,
                native_reasoning_json=response.native_reasoning,
                credential_mode=request.credential_mode,
                prompt_hash=prompt_hash,
                step=step_ref,
                project_id=project_id or None,
                scene_id=None,
                chapter_id=None,
                request_payload_summary=request_summary,
                response_payload_summary={
                    "request_id": response.request_id,
                    "response_format": response.response_format,
                    "structured_output": response.structured_output,
                },
                prompt_tokens=response.usage.get("input_tokens", 0),
                completion_tokens=response.usage.get("output_tokens", 0),
                total_tokens=response.usage.get("total_tokens", 0),
                latency_ms=int((time.perf_counter() - started_at) * 1000),
                finish_reason=response.finish_reason,
                error_code=None,
            )
        )
        self.session.flush()

    def _persist_failed_call(
        self,
        *,
        llm_call_id: str,
        project_id: str,
        step_ref: str,
        task_key: str,
        task_config: Any,
        request: LLMRequest | None,
        request_summary: dict[str, Any],
        prompt_hash: str,
        started_at: float,
        error_code: str,
        response_summary: dict[str, Any],
        response: LLMResponse | None = None,
    ) -> None:
        self.session.add(
            LlmCall(
                llm_call_id=llm_call_id,
                scope_type="project",
                scope_id=project_id,
                provider=response.provider if response is not None else getattr(task_config, "provider", None),
                provider_id=getattr(request, "provider_id", None) if request is not None else getattr(task_config, "provider_id", None),
                account_id=getattr(request, "account_id", None) if request is not None else getattr(task_config, "account_id", None),
                model=response.model if response is not None else getattr(task_config, "model", None),
                node_id=task_key,
                reasoning_level=getattr(request, "reasoning_level", None) if request is not None else getattr(task_config, "reasoning_level", None),
                native_reasoning_json=response.native_reasoning if response is not None else None,
                credential_mode=getattr(request, "credential_mode", None) if request is not None else getattr(task_config, "credential_mode", None),
                prompt_hash=prompt_hash,
                step=step_ref,
                project_id=project_id or None,
                scene_id=None,
                chapter_id=None,
                request_payload_summary=request_summary,
                response_payload_summary=response_summary,
                prompt_tokens=response.usage.get("input_tokens", 0) if response is not None else 0,
                completion_tokens=response.usage.get("output_tokens", 0) if response is not None else 0,
                total_tokens=response.usage.get("total_tokens", 0) if response is not None else 0,
                latency_ms=int((time.perf_counter() - started_at) * 1000),
                finish_reason=response.finish_reason if response is not None else None,
                error_code=error_code,
            )
        )
        self.session.flush()


def _project_prompt_payload(project: StoryProject) -> dict[str, Any]:
    return {
        "project_id": project.project_id,
        "title": project.title,
        "genre": project.genre,
        "target_word_count": project.target_word_count,
        "target_chapter_count": project.target_chapter_count,
        "outline_text": project.outline_text,
    }


def _sanitize_canonical_draft(draft: dict[str, Any] | None) -> dict[str, Any]:
    """提示上下文净化：剥掉前端写穿缓存的 fe_* 键（脚手架 JSON / 状态 / 历史账本），
    它们与规范字段内容重复且占提示预算；作者自由草稿（fe_text）是真实创作意图，
    以显式键 author_free_draft 保留。"""
    payload = {k: v for k, v in (draft or {}).items() if not str(k).startswith("fe_")}
    free_text = str((draft or {}).get("fe_text") or "").strip()
    if free_text:
        payload["author_free_draft"] = free_text
    return payload


def _approved_step_context(latest_by_step: Mapping[str, Any]) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for step_key, artifact in latest_by_step.items():
        if artifact is None or str(getattr(artifact, "status", "")) not in {"approved", "skipped"}:
            continue
        step_definition = get_step_definition(step_key)
        items.append(
            {
                "step_key": step_key,
                "label": step_definition.get("label"),
                "draft": _sanitize_canonical_draft(
                    merge_step_draft(step_key, getattr(artifact, "artifact_json", None), latest_by_step=dict(latest_by_step))
                ),
            }
        )
    return items


def _scene_rules(step_key: str) -> dict[str, Any] | None:
    if step_key != "scene_details":
        return None
    return {
        "primary_form_field": "primary_form",
        "proactive": ["goal", "conflict", "setback"],
        "reactive": ["reaction", "dilemma", "decision"],
        "follow_up_fields_are_allowed": True,
    }


def _pressure_rubric(step_key: str) -> dict[str, Any]:
    scene_rules = _scene_rules(step_key)
    rubric = {
        "goal": "让每一层雪花都更容易扩展成带目标、阻力、代价和变化的具体场景。",
        "dimensions": [
            "读者承诺：目标读者和类型爽点足够具体，能指导取舍",
            "因果升级：每一层都让下一事件更难、更贵或更不可逆",
            "角色压力：目标、价值、阻力和变化都能看见",
            "场景开放循环：场景层保留主动场景的目标/冲突/挫折，或反应场景的反应/困境/决定",
            "连续性：保留用户项目中已确认的事实、ID、顺序和语言",
        ],
        "repair_priority": [
            "先补缺失的必需结构",
            "把泛泛压力替换成具体阻力和代价",
            "让结尾或决定制造下一层继续展开的需要",
        ],
    }
    if scene_rules is not None:
        rubric["scene_rules"] = scene_rules
    return rubric


def _focus_scene_payload(step: dict[str, Any], focus_scene_id: str | None) -> dict[str, Any] | None:
    scene_id = str(focus_scene_id or "").strip()
    if not scene_id:
        return None
    draft = step.get("draft") if isinstance(step.get("draft"), dict) else {}
    for scene in draft.get("scenes") or []:
        # FE 场景规划以 row_uid 为键，教练单场聚焦允许 row_uid 或 scene_id 指场
        if isinstance(scene, dict) and scene_id in {str(scene.get("scene_id") or "").strip(), str(scene.get("row_uid") or "").strip()}:
            return normalize(scene)
    return {"scene_id": scene_id}


def _render_user_prompt(template: Any, prompt_payload: dict[str, Any]) -> str:
    required = template.structured_schema.get("required") or []
    required_text = ", ".join(str(item) for item in required if isinstance(item, str))
    prompt_json = json.dumps(normalize(prompt_payload), ensure_ascii=False, indent=2)
    return (
        f"{template.task_prompt.strip()}\n\n"
        f"Working payload:\n{prompt_json}\n\n"
        f"Required top-level JSON keys: {required_text or 'follow the provided schema'}.\n"
        "Return only valid JSON. Do not wrap it in markdown fences."
    )


def _prompt_hash(
    template_name: str,
    template_version: str,
    system_prompt: str,
    user_prompt: str,
    structured_schema: dict[str, Any],
) -> str:
    return uuid.uuid5(
        uuid.NAMESPACE_URL,
        canonical_json(
            {
                "template_name": template_name,
                "template_version": template_version,
                "system_prompt": system_prompt,
                "user_prompt": user_prompt,
                "structured_schema": structured_schema,
            }
        ),
    ).hex


def _normalize_candidates_output(output: dict[str, Any]) -> dict[str, Any]:
    """FE-ALIGN G5：候选数组裁剪到原型契约形状（≤4 条；label/tag/notes 限长）。"""
    items = output.get("candidates") if isinstance(output, dict) else None
    normalized: list[dict[str, Any]] = []
    for item in (items or [])[:4]:
        if not isinstance(item, dict):
            continue
        text = str(item.get("text") or "").strip()
        if not text:
            continue
        notes = item.get("notes") if isinstance(item.get("notes"), list) else []
        normalized.append(
            {
                "label": str(item.get("label") or f"方向 {len(normalized) + 1}").strip()[:8],
                "tag": str(item.get("tag") or "AI 候选").strip()[:16],
                "text": text,
                "notes": [str(n).strip()[:10] for n in notes[:3] if str(n).strip()],
            }
        )
    return {"candidates": normalized}


def _normalize_full_step_output(
    step_key: str,
    output: dict[str, Any],
    *,
    latest_by_step: dict[str, Any],
    project_id: str,
    base_override: dict[str, Any] | None = None,
    focus_filter: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if focus_filter and isinstance(output, dict):
        output = _filter_output_to_focus(output, focus_filter)
    base = base_override if base_override is not None else merge_step_draft(step_key, None, latest_by_step=latest_by_step)
    patch = _sanitize_step_patch(step_key, output, latest_by_step=latest_by_step, project_id=project_id, base=base)
    _assert_meaningful_generation_patch(step_key, patch)
    return _merge_patch(base, patch)


def _filter_output_to_focus(output: dict[str, Any], focus_filter: dict[str, Any]) -> dict[str, Any]:
    """焦点定向的服务端硬约束：清洗前先把模型输出过滤到焦点成员——模型即使
    违约复述/改写了焦点外成员，也不让它进合并；全部被过滤掉则明确报错，
    绝不悄悄把定向请求变成全量重写。"""
    field_key = str(focus_filter.get("field") or "")
    id_keys = tuple(focus_filter.get("id_keys") or ())
    allowed = focus_filter.get("allowed") or set()
    members = output.get(field_key)
    if not isinstance(members, list):
        return output
    kept = [
        item
        for item in members
        if isinstance(item, dict) and ({str(item.get(key) or "").strip() for key in id_keys} & allowed)
    ]
    if members and not kept:
        raise ValueError(
            f"focused generation returned no {field_key} matching the requested focus ids; "
            "the model must echo the focus member ids verbatim — retry the request."
        )
    filtered = dict(output)
    filtered[field_key] = kept
    return filtered


def _normalize_assistant_output(
    step_key: str,
    output: dict[str, Any],
    *,
    latest_by_step: dict[str, Any],
    base_draft: dict[str, Any],
) -> dict[str, Any]:
    reply = str(output.get("reply") or "").strip()
    suggestions = _coerce_string_list(output.get("suggestions"))
    candidate_label = str(output.get("candidate_label") or "").strip()
    patch = {}
    if isinstance(output.get("candidate_patch"), dict):
        patch = _sanitize_step_patch(
            step_key,
            output.get("candidate_patch") or {},
            latest_by_step=latest_by_step,
            project_id=_project_id_from_steps(latest_by_step),
            base=base_draft,
        )
    return {
        "step_key": step_key,
        "reply": reply,
        "suggestions": suggestions,
        "candidate_label": candidate_label or None,
        "candidate_patch": patch or None,
    }


def _normalize_triage_output(output: dict[str, Any], base_draft: dict[str, Any]) -> dict[str, Any]:
    base_items = _fallback_triage_items(base_draft)
    updates = {}
    for item in output.get("items") or []:
        if not isinstance(item, dict):
            continue
        scene_id = str(item.get("scene_id") or "").strip()
        if not scene_id:
            continue
        status = str(item.get("status") or "").strip().lower()
        if status not in {"pass", "maybe", "rewrite"}:
            continue
        updates[scene_id] = {
            "status": status,
            "notes": str(item.get("notes") or "").strip(),
            "missing_fields": _coerce_string_list(item.get("missing_fields")),
            "fix_steps": _coerce_string_list(item.get("fix_steps")),
            "repair_patch": _sanitize_scene_repair_patch(item.get("repair_patch") or {}),
        }
    items = []
    for item in base_items:
        scene_id = item["scene_id"]
        update = updates.get(scene_id, {})
        items.append(
            {
                **item,
                "status": update.get("status", item.get("status") or ""),
                "notes": update.get("notes", item.get("notes") or ""),
                "missing_fields": update.get("missing_fields", item.get("missing_fields") or []),
                "fix_steps": update.get("fix_steps", item.get("fix_steps") or []),
                "repair_patch": update.get("repair_patch", item.get("repair_patch") or {}),
            }
        )
    return {"items": items}


_SERVER_ASSIGNED_ITEM_KEYS = {"row_uid", "scene_id", "chapter_id", "chapter_title", "chapter_goal", "scene_seq", "character_id", "display_name"}
_SCENE_LIST_CONTENT_KEYS = ("summary", "pov_character_id", "location", "crucible", "chapter_role")
_CHARACTER_COLLECTION_STEPS = {"character_sheets", "character_synopses", "character_bibles"}


def _collect_generation_gaps(step_key: str, draft: dict[str, Any] | None) -> list[str]:
    """清洗后空字段盘点（修复重试的靶子）。step_completeness 对集合步只看顶层键
    是否非空，而残缺的主形态恰是「characters/scenes 数组在、字段全空」——这里按
    编辑器模板对集合项逐字段下钻（嵌套档案维度以整块全空计），scene_details 的
    逐场缺字段 step_completeness 本身已下钻。"""
    payload = draft if isinstance(draft, dict) else {}
    gaps = [str(field) for field in step_completeness(step_key, payload).get("missing_fields") or []]
    if step_key in _CHARACTER_COLLECTION_STEPS:
        template = _collection_template(step_key, "characters")
        for index, item in enumerate(payload.get("characters") or [], start=1):
            if not isinstance(item, dict):
                continue
            label = str(item.get("display_name") or item.get("character_id") or index)
            for field_key, template_value in template.items():
                if field_key in _SERVER_ASSIGNED_ITEM_KEYS:
                    continue
                value = item.get(field_key)
                if isinstance(template_value, dict):
                    nested = value if isinstance(value, dict) else {}
                    if not any(_has_value(nested_value) for nested_value in nested.values()):
                        gaps.append(f"characters[{label}].{field_key}")
                elif not _has_value(value):
                    gaps.append(f"characters[{label}].{field_key}")
    elif step_key == "scene_list":
        for index, item in enumerate(payload.get("scenes") or [], start=1):
            if not isinstance(item, dict):
                continue
            label = str(item.get("scene_id") or index)
            gaps.extend(
                f"scenes[{label}].{field_key}"
                for field_key in _SCENE_LIST_CONTENT_KEYS
                if not _has_value(item.get(field_key))
            )
    return gaps


def _collection_template(step_key: str, field_key: str) -> dict[str, Any]:
    for field in get_step_definition(step_key).get("editor", {}).get("fields") or []:
        if field.get("key") == field_key:
            template = field.get("template")
            return template if isinstance(template, dict) else {}
    return {}


def _sanitize_step_patch(
    step_key: str,
    patch: dict[str, Any],
    *,
    latest_by_step: dict[str, Any],
    project_id: str,
    base: dict[str, Any],
) -> dict[str, Any]:
    if not isinstance(patch, dict):
        return {}
    step_definition = get_step_definition(step_key)
    result: dict[str, Any] = {}
    for field in step_definition.get("editor", {}).get("fields") or []:
        key = field.get("key")
        if not isinstance(key, str) or key not in patch:
            continue
        value = patch.get(key)
        normalized = _sanitize_field_value(field, value, project_id=project_id, latest_by_step=latest_by_step, base=base)
        if _has_value(normalized):
            result[key] = normalized
    return result


def _assert_meaningful_generation_patch(step_key: str, patch: dict[str, Any]) -> None:
    if step_key != "character_sheets":
        return
    characters = patch.get("characters") if isinstance(patch, dict) else None
    if not isinstance(characters, list) or not characters:
        raise ValueError(
            "character_sheets LLM output is empty: return at least one character with role plus concrete "
            "goal, ambition, values, conflict, epiphany, or summary content."
        )
    if any(_has_meaningful_character_sheet_content(item) for item in characters if isinstance(item, dict)):
        return
    raise ValueError(
        "character_sheets LLM output is too sparse: model returned only IDs/names or blank fields. "
        "Each generated character must include role plus concrete goal, ambition, values, conflict, "
        "epiphany, or summary content."
    )


def _has_meaningful_character_sheet_content(item: dict[str, Any]) -> bool:
    identity_values = {
        str(item.get("character_id") or "").strip(),
        str(item.get("display_name") or "").strip(),
        str(item.get("name") or "").strip(),
    }
    filled_fields = [
        field
        for field in (
            "role",
            "goal",
            "ambition",
            "values",
            "conflict",
            "epiphany",
            "one_sentence_summary",
            "one_paragraph_summary",
        )
        if _has_meaningful_non_identity_value(item.get(field), identity_values)
    ]
    pressure_fields = {
        "goal",
        "ambition",
        "values",
        "conflict",
        "epiphany",
        "one_sentence_summary",
        "one_paragraph_summary",
    }
    return len(filled_fields) >= 2 and any(field in pressure_fields for field in filled_fields)


def _has_meaningful_non_identity_value(value: Any, identity_values: set[str]) -> bool:
    if isinstance(value, list):
        return any(_has_meaningful_non_identity_value(item, identity_values) for item in value)
    if isinstance(value, dict):
        return any(_has_meaningful_non_identity_value(item, identity_values) for item in value.values())
    text = str(value or "").strip()
    return bool(text and text not in identity_values)


def _sanitize_field_value(
    field: dict[str, Any],
    value: Any,
    *,
    project_id: str,
    latest_by_step: dict[str, Any],
    base: dict[str, Any],
) -> Any:
    kind = str(field.get("kind") or "")
    key = str(field.get("key") or "")
    if kind in {"text", "textarea"}:
        return str(value or "").strip()
    if kind in {"list", "paragraphs"}:
        return _coerce_string_list(value)
    if kind == "sentences":
        seed = base.get(key) if isinstance(base.get(key), list) else []
        items = _coerce_string_list(value)
        if seed and len(items) < len(seed):
            items.extend([""] * (len(seed) - len(items)))
        return items[: len(seed)] if seed else items
    if kind == "object":
        nested = {}
        payload = value if isinstance(value, dict) else {}
        for nested_field in field.get("fields") or []:
            nested_key = nested_field.get("key")
            if not isinstance(nested_key, str):
                continue
            if nested_key not in payload:
                continue
            nested[nested_key] = str(payload.get(nested_key) or "").strip()
        return nested
    if kind in {"characters", "character_synopses", "character_bibles"}:
        template = field.get("template") if isinstance(field.get("template"), dict) else {}
        return _sanitize_character_items(
            value,
            template=template,
            project_id=project_id,
            latest_by_step=latest_by_step,
            base_items=base.get(key) if isinstance(base.get(key), list) else [],
        )
    if kind == "scene_list":
        template = field.get("template") if isinstance(field.get("template"), dict) else {}
        return _sanitize_scene_list_items(
            value,
            template=template,
            project_id=project_id,
            base_items=base.get(key) if isinstance(base.get(key), list) else [],
        )
    if kind == "scene_details":
        return _sanitize_scene_detail_items(
            value,
            project_id=project_id,
            base_items=base.get(key) if isinstance(base.get(key), list) else [],
        )
    return None


def _sanitize_character_items(
    value: Any,
    *,
    template: dict[str, Any],
    project_id: str,
    latest_by_step: dict[str, Any],
    base_items: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    existing_by_name = {
        str(item.get("display_name") or "").strip(): str(item.get("character_id") or "").strip()
        for item in base_items
        if isinstance(item, dict) and str(item.get("display_name") or "").strip()
    }
    for step_key in ("character_sheets", "character_bibles", "character_synopses"):
        artifact = latest_by_step.get(step_key)
        if artifact is None:
            continue
        for item in (artifact.artifact_json or {}).get("characters") or []:
            if not isinstance(item, dict):
                continue
            display_name = str(item.get("display_name") or "").strip()
            character_id = str(item.get("character_id") or "").strip()
            if display_name and character_id and display_name not in existing_by_name:
                existing_by_name[display_name] = character_id

    result = []
    for index, raw_item in enumerate(value, start=1):
        if not isinstance(raw_item, dict):
            continue
        item = {}
        display_name = str(raw_item.get("display_name") or raw_item.get("name") or "").strip()
        character_id = str(raw_item.get("character_id") or "").strip()
        if not character_id and display_name:
            character_id = existing_by_name.get(display_name, "")
        if not character_id:
            character_id = f"{project_id}_CHAR{index:02d}"
        item["character_id"] = character_id
        for field_key, template_value in template.items():
            if field_key == "character_id":
                continue
            sanitized = _prune_empty_values(_sanitize_template_value(template_value, raw_item.get(field_key)))
            # 生成/补丁是「补全」语义：空值不落键，_merge_patch 时不清空该成员的既有
            # 内容（与 FE 咨询式补丁一致）——模型部分回传不再抹掉手工填过的字段。
            if _has_value(sanitized):
                item[field_key] = sanitized
        if not item.get("display_name"):
            item["display_name"] = display_name or character_id
        result.append(item)
    return result


def _prune_empty_values(value: Any) -> Any:
    """递归剥掉空叶子（"" / [] / {} / 全空子树），让补丁只携带有内容的键。"""
    if isinstance(value, dict):
        pruned = {key: _prune_empty_values(item) for key, item in value.items()}
        return {key: item for key, item in pruned.items() if _has_value(item)}
    return value


def _sanitize_scene_list_items(
    value: Any,
    *,
    template: dict[str, Any],
    project_id: str,
    base_items: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    result = []
    scene_seq_by_chapter: dict[str, int] = {}
    current_chapter_id = ""
    for index, raw_item in enumerate(value, start=1):
        if not isinstance(raw_item, dict):
            continue
        chapter_id = str(raw_item.get("chapter_id") or current_chapter_id or f"{project_id}_CH01").strip()
        current_chapter_id = chapter_id
        next_seq = scene_seq_by_chapter.get(chapter_id, 0) + 1
        scene_seq = _coerce_int(raw_item.get("scene_seq"), default=next_seq)
        scene_seq_by_chapter[chapter_id] = scene_seq
        scene_id = str(raw_item.get("scene_id") or f"{chapter_id}_SC{scene_seq:02d}").strip()
        item = {
            "scene_id": scene_id,
            "chapter_id": chapter_id,
            "scene_seq": scene_seq,
        }
        for field_key, template_value in template.items():
            if field_key in {"scene_id", "chapter_id", "scene_seq"}:
                continue
            item[field_key] = _sanitize_template_value(template_value, raw_item.get(field_key))
        if not item.get("chapter_title"):
            item["chapter_title"] = chapter_id
        if not item.get("summary"):
            item["summary"] = str(raw_item.get("title") or "").strip()
        scene_type = str(
            raw_item.get("primary_form")
            or raw_item.get("scene_type")
            or raw_item.get("mode")
            or item.get("primary_form")
            or item.get("scene_type")
            or "proactive"
        ).strip().lower()
        scene_type = scene_type if scene_type in {"proactive", "reactive"} else "proactive"
        item["primary_form"] = scene_type
        item["scene_type"] = scene_type
        result.append(item)
    if not result and base_items:
        return normalize(base_items)
    return result


def _sanitize_scene_detail_items(
    value: Any,
    *,
    project_id: str,
    base_items: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    del project_id
    items = value if isinstance(value, list) else []
    base_by_id = {
        str(item.get("scene_id") or ""): normalize(item)
        for item in base_items
        if isinstance(item, dict) and str(item.get("scene_id") or "")
    }
    overlay_by_id = {
        str(item.get("scene_id") or ""): item
        for item in items
        if isinstance(item, dict) and str(item.get("scene_id") or "")
    }
    allowed_keys = {
        "title",
        "summary",
        "scene_type",
        "location",
        "scene_crucible",
        "crucible",
        "goal",
        "conflict",
        "setback",
        "reaction",
        "dilemma",
        "decision",
        "target_length_band",
        "must_include_text",
        "exit_change",
        "hook",
        "triage_status",
        "triage_notes",
        "beats_json",
    }
    result = []
    for base_item in base_items:
        if not isinstance(base_item, dict):
            continue
        scene_id = str(base_item.get("scene_id") or "")
        merged = dict(base_by_id.get(scene_id) or normalize(base_item))
        overlay = overlay_by_id.get(scene_id, {})
        for key in allowed_keys:
            if key not in overlay:
                continue
            if key in {"primary_form", "scene_type"}:
                scene_type = str(
                    overlay.get(key)
                    or merged.get("primary_form")
                    or merged.get("scene_type")
                    or "proactive"
                ).strip().lower()
                scene_type = scene_type if scene_type in {"proactive", "reactive"} else str(merged.get("primary_form") or merged.get("scene_type") or "proactive")
                merged["primary_form"] = scene_type
                merged["scene_type"] = scene_type
            elif key in {"beats_json"}:
                beats = _coerce_string_list(overlay.get(key))
                if beats:
                    merged[key] = beats
            else:
                text = str(overlay.get(key) or "").strip()
                # 补全语义：模型对某键回传空串不清空底稿既有内容
                if text:
                    merged[key] = text
        result.append(merged)
    return result


def _sanitize_template_value(template_value: Any, value: Any) -> Any:
    if isinstance(template_value, dict):
        payload = value if isinstance(value, dict) else {}
        return {
            str(field_key): _sanitize_template_value(nested_template, payload.get(field_key))
            for field_key, nested_template in template_value.items()
        }
    if isinstance(template_value, list):
        return _coerce_string_list(value)
    return str(value or "").strip()


def _merge_patch(base: Any, patch: Any, *, collection_key: str | None = None) -> Any:
    if isinstance(base, dict) and isinstance(patch, dict):
        merged = dict(normalize(base))
        for key, value in patch.items():
            merged[key] = _merge_patch(merged.get(key), value, collection_key=key)
        return merged
    if isinstance(base, list) and isinstance(patch, list):
        id_key = _collection_id_key(collection_key)
        if not id_key:
            return normalize(patch)
        base_items = [normalize(item) for item in base if isinstance(item, dict)]
        patch_items = [normalize(item) for item in patch if isinstance(item, dict)]
        patch_by_id = {
            str(item.get(id_key) or ""): item
            for item in patch_items
            if str(item.get(id_key) or "")
        }
        # 保持底稿成员顺序（名册/场景序即作者语序）：patch 命中的按 id 就地合并，
        # 模型新增的成员追加在尾部——定向补全不打乱其余成员的排列。
        merged_items = []
        seen_ids: set[str] = set()
        for item in base_items:
            item_id = str(item.get(id_key) or "")
            if not item_id:
                continue
            merged_items.append(_merge_patch(item, patch_by_id[item_id]) if item_id in patch_by_id else item)
            seen_ids.add(item_id)
        for item in patch_items:
            item_id = str(item.get(id_key) or "")
            if item_id and item_id not in seen_ids:
                merged_items.append(_merge_patch({}, item))
                seen_ids.add(item_id)
        return merged_items
    return normalize(patch)


def _collection_id_key(collection_key: str | None) -> str | None:
    if collection_key == "characters":
        return "character_id"
    if collection_key == "scenes":
        return "scene_id"
    return None


_FIELD_LABELS = {
    "target_reader": "目标读者",
    "summary": "概括",
    "scenes": "场景",
    "crucible": "坩埚",
    "scene_crucible": "坩埚",
    "goal": "目标",
    "conflict": "冲突",
    "setback": "挫折",
    "reaction": "反应",
    "dilemma": "困境",
    "decision": "决定",
    "exit_change": "离场变化",
    "hook": "钩子",
}

_DIAGNOSTIC_LABELS = {
    "scene_core_empty": "场景核心为空",
    "weak_crucible_pressure": "坩埚压力不足",
    "weak_goal_specificity": "目标不够具体",
    "weak_conflict_escalation": "冲突升级不足",
    "weak_setback_cost": "挫折代价不足",
    "weak_reaction_specificity": "反应不够具体",
    "fake_dilemma": "困境不是真两难",
    "weak_decision_next_goal": "决定没有引出下一目标",
}


def _field_label(value: str) -> str:
    return _FIELD_LABELS.get(str(value or ""), str(value or "字段"))


def _diagnostic_label(value: str) -> str:
    key = str(value or "")
    if key in _DIAGNOSTIC_LABELS:
        return _DIAGNOSTIC_LABELS[key]
    if key.startswith("missing_"):
        return f"缺少{_field_label(key.removeprefix('missing_'))}"
    return key


def _fallback_triage_items(draft: dict[str, Any]) -> list[dict[str, Any]]:
    items = []
    for index, raw_scene in enumerate(draft.get("scenes") or [], start=1):
        if not isinstance(raw_scene, dict):
            continue
        diagnosis = diagnose_scene_detail(raw_scene, index=index)
        scene_type = str(diagnosis.get("primary_form") or diagnosis.get("scene_type") or "proactive").strip().lower() or "proactive"
        status = str(diagnosis.get("recommended_status") or "maybe")
        missing_fields = [str(field) for field in diagnosis.get("missing_fields") or []]
        if status == "rewrite":
            notes = "修复场景压力：场景核心太薄，需要重建前提和坩埚。"
        elif status == "maybe":
            readable_flags = "、".join(_diagnostic_label(flag) for flag in diagnosis.get("pressure_flags") or missing_fields)
            notes = f"修复场景压力：{readable_flags}。"
        else:
            notes = "核心压力清楚，可以继续。"
        items.append(
            {
                "scene_id": str(raw_scene.get("scene_id") or f"scene_{index:02d}"),
                "title": str(raw_scene.get("title") or raw_scene.get("summary") or f"Scene {index:02d}"),
                "primary_form": scene_type,
                "scene_type": scene_type,
                "status": status,
                "notes": notes,
                "missing_fields": missing_fields,
                "fix_steps": diagnosis.get("fix_steps") or _fallback_fix_steps(scene_type, missing_fields, status),
                "repair_patch": _fallback_repair_patch(scene_type, missing_fields),
            }
        )
    return items


def _fallback_fix_steps(scene_type: str, missing_fields: list[str], status: str) -> list[str]:
    if status == "pass":
        return []
    if status == "rewrite":
        return ["围绕具体坩埚和可见压力转折重建这一场。"]
    label = "反应/困境/决定" if scene_type == "reactive" else "目标/冲突/挫折"
    return [f"补齐缺失的{label}字段：{'、'.join(_field_label(field) for field in missing_fields)}。"]


def _fallback_repair_patch(scene_type: str, missing_fields: list[str]) -> dict[str, str]:
    examples = {
        "crucible": "一个具体压力把视角角色困在这里；离开会让损失永久化。",
        "goal": "在场景倒计时结束前，拿到某个具体证据、许可或让步。",
        "conflict": "角色先直接索取，再尝试策略绕路，最后冒险揭露；每一轮都遇到更强阻力。",
        "setback": "角色拿到线索，但代价指向一个他无法失去的人。",
        "reaction": "角色先出现身体和情绪反应，然后才开始分析损害。",
        "dilemma": "一个选择保护关系却埋掉真相，另一个选择暴露真相却烧掉保护。",
        "decision": "角色选择代价更高的路径，并制造下一场的具体目标。",
    }
    required = ["reaction", "dilemma", "decision"] if scene_type == "reactive" else ["goal", "conflict", "setback"]
    keys = ["crucible" if field == "crucible" else field for field in missing_fields if field in {"crucible", *required}]
    return {key: examples[key] for key in keys if key in examples}


def _sanitize_scene_repair_patch(value: Any) -> dict[str, str]:
    if not isinstance(value, dict):
        return {}
    allowed = {
        "title",
        "summary",
        "primary_form",
        "scene_type",
        "location",
        "scene_crucible",
        "crucible",
        "goal",
        "conflict",
        "setback",
        "reaction",
        "dilemma",
        "decision",
        "exit_change",
        "hook",
        "target_length_band",
        "must_include_text",
    }
    return {key: str(value.get(key) or "").strip() for key in allowed if key in value and str(value.get(key) or "").strip()}


def _coerce_string_list(value: Any) -> list[str]:
    if isinstance(value, str):
        return [item.strip() for item in value.splitlines() if item.strip()]
    if not isinstance(value, list):
        return []
    return [str(item).strip() for item in value if str(item).strip()]


def _coerce_int(value: Any, *, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _project_id_from_steps(latest_by_step: Mapping[str, Any]) -> str:
    for artifact in latest_by_step.values():
        project_id = str(getattr(artifact, "project_id", "") or "").strip()
        if project_id:
            return project_id
    return ""


def _error_summary(exc: Exception) -> dict[str, Any]:
    details = getattr(exc, "details", None)
    details = details if isinstance(details, dict) else {}
    retryable = bool(getattr(exc, "retryable", False))
    return {
        "message": str(exc),
        "details": details,
        "retryable": retryable,
    }


def _llm_failure_message(exc: Exception, task_key: str) -> str:
    details = getattr(exc, "details", None)
    details = details if isinstance(details, dict) else {}
    if details.get("next_action") == "switch_provider_api_mode_to_chat_or_use_responses_compatible_provider":
        provider_id = str(details.get("provider_id") or "current provider")
        model = str(details.get("model") or "current model")
        endpoint = str(details.get("endpoint") or "/responses")
        return (
            f"LLM 请求失败：节点 {task_key} 正在用 {provider_id}/{model} 调 Responses API（{endpoint}），"
            "但服务返回 404。这个中转服务大概率只支持 Chat Completions；"
            "请到配置环境把该提供方“调用协议”切换为 chat，保存后点击“一键补齐”，"
            "或改用支持 Responses API 的提供方。"
        )
    return str(exc)


def _has_value(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, list):
        return any(_has_value(item) for item in value)
    if isinstance(value, dict):
        return any(_has_value(item) for item in value.values())
    return True
