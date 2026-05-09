from __future__ import annotations

from typing import Any


class SnowflakeWorkspaceAssistantService:
    def reply(
        self,
        *,
        project: dict[str, Any],
        step: dict[str, Any],
        message: str,
        approved_context: list[dict[str, Any]],
        focus_scene_id: str | None = None,
    ) -> dict[str, Any]:
        project_title = str(project.get("title") or "当前项目").strip()
        step_label = str(step.get("label") or step.get("step_key") or "当前步骤").strip()
        draft = step.get("draft") if isinstance(step.get("draft"), dict) else {}
        filled_keys = [key for key, value in draft.items() if _has_value(value)]
        missing_keys = [
            field.get("label") or field.get("key")
            for field in (step.get("editor", {}).get("fields") or [])
            if not _has_value(draft.get(field.get("key")))
        ]
        context_labels = [item.get("label") for item in approved_context if item.get("label")]

        suggestions: list[str] = []
        if filled_keys:
            suggestions.append(f"先保留你已经明确的 {', '.join(filled_keys[:3])}，不要在这一轮把目标说散。")
        if missing_keys:
            suggestions.append(f"优先补齐 {', '.join(missing_keys[:3])}，这样下一步生成会更稳。")
        if context_labels:
            suggestions.append(f"回答时记得和已确认的 {', '.join(context_labels[:2])} 保持一致。")
        if not suggestions:
            suggestions.append("先把这一层最想让读者记住的一件事写得更具体。")

        reply_lines = [
            f"《{project_title}》现在在“{step_label}”这一层，建议继续把这一步写得更尖一点。",
            suggestions[0],
        ]
        trimmed_message = str(message or "").strip()
        if trimmed_message:
            reply_lines.append(f"你刚才提到“{trimmed_message}”，我会优先围绕这个问题收窄表达。")
        if focus_scene_id:
            reply_lines.append(f"当前聚焦场景是 {focus_scene_id}，建议先修它的结构缺口再继续物化。")
        if len(suggestions) > 1:
            reply_lines.append(suggestions[1])
        return {
            "step_key": step.get("step_key"),
            "reply": " ".join(reply_lines),
            "suggestions": suggestions,
            "source": "fallback",
            "llm_call_id": None,
            "candidate_label": None,
            "candidate_patch": None,
        }


def _has_value(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, (list, tuple, set)):
        return any(_has_value(item) for item in value)
    if isinstance(value, dict):
        return any(_has_value(item) for item in value.values())
    return True
