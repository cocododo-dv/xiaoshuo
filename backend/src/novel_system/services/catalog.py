"""FE-ALIGN Phase 3: 目录统一 —— ChapterGoal/SceneCard 之上的章节/场景树服务。

`GET/PATCH /api/v2/projects/{id}/catalog…` 的服务层；雪花物化（approve_outline_plan）
创建的行与本服务读写的是同一批行（护栏测试 test_catalog_single_source.py）。

约定：
- 章顺序 = display_order（混合 chapter_id 格式下不能依赖字典序；缺号惰性补齐）。
- 场景顺序 = 既有 scene_seq（与 v1 scene-order 端点同一套逻辑，不另建列）。
- 章标题写 narrative_json["title"]；读取回退 writer_brief_json.chapter_title →
  writer_brief_json.title → chapter_goal 首行。
- slug 不入库：章 slug = "ch"+序号两位，场景 slug = 章slug+"s"+scene_seq（原型
  ch08s3 格式，⌘K/深链/写作器历史 id 都用它）。
- C4 裁决：scene brief 按 kind 返回 GCS（proactive）或 RDD（reactive），
  前端 store 适配层负责映射到视图槽位。
"""
from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from novel_system.db.models import AuthorDraft, ChapterGoal, SceneCard, StoryCharacter, StoryProject
from novel_system.services.errors import DomainError
from novel_system.services.projects import ProjectService

CHAPTER_STATES = ("planned", "todo", "writing", "draft", "review", "approved")
SCENE_STATES = ("todo", "writing", "done")

# narrative_json 里由目录 API 维护的字段（形状抄 design/ws-catalog.jsx 章节对象）
NARRATIVE_FIELDS = (
    "title",
    "act",
    "tension",
    "pov",
    "time_label",
    "place",
    "entry",
    "exit",
    "align",
    "promise",
    "drama",
    "threads",
    "notes",
)

SCENE_BRIEF_GCS = ("goal", "conflict", "setback")
SCENE_BRIEF_RDD = ("reaction", "dilemma", "decision")


def scene_kind(scene: SceneCard) -> str:
    brief = dict(scene.writer_brief_json or {})
    raw = str(brief.get("primary_form") or scene.scene_type or "proactive").strip().lower()
    return "reactive" if raw.startswith("react") or raw == "反应" else "proactive"


def chapter_title(chapter: ChapterGoal) -> str:
    narrative = dict(chapter.narrative_json or {})
    if str(narrative.get("title") or "").strip():
        return str(narrative["title"]).strip()
    brief = dict(chapter.writer_brief_json or {})
    for key in ("chapter_title", "title"):
        if str(brief.get(key) or "").strip():
            return str(brief[key]).strip()
    goal = str(chapter.chapter_goal or "").strip()
    return (goal.splitlines()[0][:24] if goal else "") or chapter.chapter_id


def scene_title(scene: SceneCard) -> str:
    brief = dict(scene.writer_brief_json or {})
    if str(brief.get("title") or "").strip():
        return str(brief["title"]).strip()
    return str(scene.scene_goal or "").strip() or scene.scene_id


class CatalogService:
    def __init__(self, session: Session) -> None:
        self.session = session
        self._projects = ProjectService(session)

    # ---------- 读 ----------

    def catalog(self, project_id: str) -> dict[str, Any]:
        project = self._projects.require_project(project_id)
        chapters = self.chapter_rows(project_id)
        return {
            "project_id": project_id,
            "chapters": [
                self.chapter_payload(project, chapter, index)
                for index, chapter in enumerate(chapters)
            ],
        }

    def chapter_rows(self, project_id: str) -> list[ChapterGoal]:
        rows = list(
            self.session.execute(
                select(ChapterGoal).where(
                    ChapterGoal.project_id == project_id, ChapterGoal.trashed_flag == 0
                )
            ).scalars().all()
        )
        # 缺 display_order 的行（雪花物化/旧数据）按 chapter_id 字典序惰性补号
        rows.sort(key=lambda c: (c.display_order is None, c.display_order or 0, c.chapter_id))
        dirty = False
        for index, chapter in enumerate(rows, start=1):
            if chapter.display_order != index:
                chapter.display_order = index
                dirty = True
        if dirty:
            self.session.flush()
        return rows

    def scene_rows(self, chapter_id: str) -> list[SceneCard]:
        return list(
            self.session.execute(
                select(SceneCard)
                .where(SceneCard.chapter_id == chapter_id, SceneCard.trashed_flag == 0)
                .order_by(SceneCard.scene_seq.asc(), SceneCard.scene_id.asc())
            ).scalars().all()
        )

    def chapter_payload(
        self, project: StoryProject, chapter: ChapterGoal, index: int
    ) -> dict[str, Any]:
        narrative = dict(chapter.narrative_json or {})
        slug = f"ch{index + 1:02d}"
        scenes = self.scene_rows(chapter.chapter_id)
        words_cur = sum(int(s.words_current or 0) for s in scenes)
        return {
            "chapter_id": chapter.chapter_id,
            "slug": slug,
            "no": f"{index + 1:02d}",
            "title": chapter_title(chapter),
            "state": str(chapter.state or "planned"),
            "current": chapter.chapter_id == project.current_chapter_id,
            "words": {"cur": words_cur, "target": chapter.words_target},
            "act": narrative.get("act"),
            "tension": narrative.get("tension"),
            "pov": narrative.get("pov"),
            "time_label": narrative.get("time_label"),
            "place": narrative.get("place"),
            "entry": narrative.get("entry"),
            "exit": narrative.get("exit"),
            "align": narrative.get("align"),
            "promise": narrative.get("promise"),
            "drama": dict(narrative.get("drama") or {}),
            "threads": list(narrative.get("threads") or []),
            "scenes": [self.scene_payload(scene, chapter_slug=slug) for scene in scenes],
        }

    def scene_payload(self, scene: SceneCard, *, chapter_slug: str) -> dict[str, Any]:
        kind = scene_kind(scene)
        brief_json = dict(scene.writer_brief_json or {})
        keys = SCENE_BRIEF_GCS if kind == "proactive" else SCENE_BRIEF_RDD
        pov_id = str(scene.pov_character_id or "")
        pov_name = ""
        if pov_id:
            character = self.session.get(StoryCharacter, pov_id)
            pov_name = character.display_name if character is not None else ""
        return {
            "scene_id": scene.scene_id,
            "chapter_id": scene.chapter_id,
            "slug": f"{chapter_slug}s{scene.scene_seq}",
            "seq": scene.scene_seq,
            "title": scene_title(scene),
            "kind": kind,
            "state": str(scene.state or "todo"),
            "words": int(scene.words_current or 0),
            "brief": {"kind": kind, **{key: str(brief_json.get(key) or "") for key in keys}},
            "pov_character_id": pov_id,
            "pov_character_name": pov_name,
        }

    # ---------- 写 ----------

    def update_chapter(self, project_id: str, chapter_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        project = self._projects.require_project(project_id)
        chapter = self._require_chapter(project_id, chapter_id)
        body = payload or {}
        if "state" in body:
            state = str(body["state"] or "").strip()
            if state not in CHAPTER_STATES:
                raise DomainError("CATALOG_STATE_INVALID", f"chapter state must be one of {CHAPTER_STATES}", status_code=400)
            chapter.state = state
        if "words_target" in body:
            value = body["words_target"]
            chapter.words_target = int(value) if value not in (None, "") else None
        narrative = dict(chapter.narrative_json or {})
        for key in NARRATIVE_FIELDS:
            if key in body:
                narrative[key] = body[key]
        chapter.narrative_json = narrative
        if body.get("current"):
            project.current_chapter_id = chapter.chapter_id
        self.session.flush()
        chapters = self.chapter_rows(project_id)
        index = next(i for i, c in enumerate(chapters) if c.chapter_id == chapter_id)
        return {"chapter": self.chapter_payload(project, chapter, index)}

    def create_chapter(self, project_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        project = self._projects.require_project(project_id)
        body = payload or {}
        existing = self.chapter_rows(project_id)
        title = str(body.get("title") or "").strip() or f"第 {len(existing) + 1} 章"
        # 空目录首章立为在写章（抄 WsCatalog.addChapter 语义）；调用方也可显式传 state/current
        is_first = not existing
        state = str(body.get("state") or ("writing" if is_first else "planned"))
        if state not in CHAPTER_STATES:
            raise DomainError("CATALOG_STATE_INVALID", f"chapter state must be one of {CHAPTER_STATES}", status_code=400)
        chapter = ChapterGoal(
            chapter_id=f"{project_id}_CH_{uuid.uuid4().hex[:8]}",
            project_id=project_id,
            planned_scene_count=0,
            chapter_goal=title,
            state=state,
            words_target=int(body["words_target"]) if body.get("words_target") else None,
            display_order=len(existing) + 1,
            narrative_json={"title": title, **{k: body[k] for k in NARRATIVE_FIELDS if k in body and k != "title"}},
            writer_brief_json={"source": "catalog_api", "title": title},
        )
        self.session.add(chapter)
        self.session.flush()
        if is_first or body.get("current", True):
            project.current_chapter_id = chapter.chapter_id
        # 默认带一个开场场景（抄 addChapter：scenes=[开场]）；传 with_scene=False 可跳过
        if body.get("with_scene", True):
            self._insert_scene(
                chapter,
                position=0,
                title=str(body.get("scene_title") or "开场"),
                kind="proactive",
                state="writing" if is_first else "todo",
                brief={"goal": title},
            )
        self.session.flush()
        chapters = self.chapter_rows(project_id)
        index = next(i for i, c in enumerate(chapters) if c.chapter_id == chapter.chapter_id)
        return {"chapter": self.chapter_payload(project, chapter, index)}

    def update_scene(self, project_id: str, scene_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        scene = self._require_scene(project_id, scene_id)
        body = payload or {}
        brief = dict(scene.writer_brief_json or {})
        if "title" in body:
            brief["title"] = str(body["title"] or "").strip()
        if "kind" in body:
            kind = "reactive" if str(body["kind"]).strip().lower() in {"reactive", "反应"} else "proactive"
            scene.scene_type = kind
            brief["primary_form"] = kind
        if "state" in body:
            state = str(body["state"] or "").strip()
            if state not in SCENE_STATES:
                raise DomainError("CATALOG_STATE_INVALID", f"scene state must be one of {SCENE_STATES}", status_code=400)
            scene.state = state
        for key in (*SCENE_BRIEF_GCS, *SCENE_BRIEF_RDD):
            if key in body:
                brief[key] = str(body[key] or "")
        nested = body.get("brief")
        if isinstance(nested, dict):
            for key in (*SCENE_BRIEF_GCS, *SCENE_BRIEF_RDD):
                if key in nested:
                    brief[key] = str(nested[key] or "")
        # POV 角色:按 id 选既有角色,或按名 find-or-create(让冷启动作品无需走完整雪花
        # 物化即可设 pov,解执行契约的 pov_character_id 硬阻断);空串显式清空。
        if "pov_character_id" in body or "pov_character_name" in body:
            pov_id = str(body.get("pov_character_id") or "").strip()
            pov_name = str(body.get("pov_character_name") or "").strip()
            if pov_id:
                character = self.session.get(StoryCharacter, pov_id)
                if character is None or character.project_id != project_id:
                    raise DomainError("CATALOG_POV_CHARACTER_NOT_FOUND", "pov character not found in project", status_code=400)
                scene.pov_character_id = pov_id
            elif pov_name:
                scene.pov_character_id = self._find_or_create_character(project_id, pov_name).character_id
            else:
                scene.pov_character_id = None
        scene.writer_brief_json = brief
        self.session.flush()
        return {"scene": self._scene_payload_with_slug(scene)}

    def _find_or_create_character(self, project_id: str, display_name: str) -> StoryCharacter:
        existing = self.session.execute(
            select(StoryCharacter).where(
                StoryCharacter.project_id == project_id,
                StoryCharacter.display_name == display_name,
            )
        ).scalars().first()
        if existing is not None:
            return existing
        character = StoryCharacter(
            character_id=f"CHAR_{uuid.uuid4().hex[:10].upper()}",
            project_id=project_id,
            display_name=display_name,
        )
        self.session.add(character)
        self.session.flush()
        return character

    def create_scene(self, project_id: str, chapter_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        chapter = self._require_chapter(project_id, chapter_id)
        body = payload or {}
        scenes = self.scene_rows(chapter_id)
        at = body.get("at")
        position = int(at) if at is not None else len(scenes)
        position = max(0, min(position, len(scenes)))
        kind = "reactive" if str(body.get("kind") or "").strip().lower() in {"reactive", "反应"} else "proactive"
        state = str(body.get("state") or "todo")
        if state not in SCENE_STATES:
            raise DomainError("CATALOG_STATE_INVALID", f"scene state must be one of {SCENE_STATES}", status_code=400)
        brief_keys = SCENE_BRIEF_GCS if kind == "proactive" else SCENE_BRIEF_RDD
        brief = {key: str(body.get(key) or "") for key in brief_keys if body.get(key)}
        nested = body.get("brief")
        if isinstance(nested, dict):
            for key in (*SCENE_BRIEF_GCS, *SCENE_BRIEF_RDD):
                if key in nested:
                    brief[key] = str(nested[key] or "")
        scene = self._insert_scene(
            chapter,
            position=position,
            title=str(body.get("title") or "").strip() or "新场景",
            kind=kind,
            state=state,
            brief=brief,
        )
        self.session.flush()
        return {"scene": self._scene_payload_with_slug(scene)}

    def move_scene(self, project_id: str, scene_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        scene = self._require_scene(project_id, scene_id)
        body = payload or {}
        if "to" not in body:
            raise DomainError("CATALOG_MOVE_INVALID", "target position 'to' is required", status_code=400)
        scenes = self.scene_rows(scene.chapter_id)
        ids = [s.scene_id for s in scenes]
        from_index = ids.index(scene.scene_id)
        to_index = max(0, min(int(body["to"]), len(scenes) - 1))
        ordered = list(scenes)
        ordered.insert(to_index, ordered.pop(from_index))
        self._renumber(ordered)
        self.session.flush()
        chapter = self.session.get(ChapterGoal, scene.chapter_id)
        project = self._projects.require_project(project_id)
        chapters = self.chapter_rows(project_id)
        index = next(i for i, c in enumerate(chapters) if c.chapter_id == chapter.chapter_id)
        return {"chapter": self.chapter_payload(project, chapter, index)}

    def import_catalog(self, project_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        """一次性迁移入口（admin 保护）：localStorage 旧目录 → 后端行。仅允许空目录导入。"""
        project = self._projects.require_project(project_id)
        if self.chapter_rows(project_id):
            raise DomainError(
                "CATALOG_NOT_EMPTY",
                "catalog import is only allowed into an empty catalog",
                status_code=409,
            )
        chapters = list((payload or {}).get("chapters") or [])
        if not chapters:
            raise DomainError("CATALOG_IMPORT_EMPTY", "chapters are required", status_code=400)
        created_scenes = 0
        for order, item in enumerate(chapters, start=1):
            title = str(item.get("title") or f"第 {order} 章").strip()
            state = str(item.get("state") or "planned")
            chapter = ChapterGoal(
                chapter_id=f"{project_id}_CH_{uuid.uuid4().hex[:8]}",
                project_id=project_id,
                planned_scene_count=len(item.get("scenes") or []),
                chapter_goal=title,
                state=state if state in CHAPTER_STATES else "planned",
                words_target=int((item.get("words") or {}).get("target") or 0) or None,
                display_order=order,
                narrative_json={
                    "title": title,
                    "act": item.get("act"),
                    "tension": item.get("tension"),
                    "pov": item.get("pov"),
                    "time_label": item.get("time"),
                    "place": item.get("place"),
                    "entry": item.get("entry"),
                    "exit": item.get("exit"),
                    "align": item.get("align"),
                    "promise": item.get("promise"),
                    "drama": dict(item.get("drama") or {}),
                    "threads": list(item.get("threads") or []),
                },
                writer_brief_json={"source": "catalog_import", "title": title},
            )
            self.session.add(chapter)
            self.session.flush()
            if item.get("current"):
                project.current_chapter_id = chapter.chapter_id
            scenes_in = list(item.get("scenes") or [])
            # 旧目录的字数挂在章级（words.cur），场景级缺失时把差额摊给零字数场景，
            # 保证 rollup（章字数 = Σ场景字数）不丢数据。
            chapter_cur = int((item.get("words") or {}).get("cur") or 0)
            scene_words = [int(sc.get("words") or 0) for sc in scenes_in]
            shortfall = chapter_cur - sum(scene_words)
            zero_slots = [i for i, w in enumerate(scene_words) if w == 0]
            if scenes_in and shortfall > 0:
                slots = zero_slots or [len(scenes_in) - 1]
                base, remainder = divmod(shortfall, len(slots))
                for j, i in enumerate(slots):
                    scene_words[i] += base + (remainder if j == len(slots) - 1 else 0)
            for seq, sc in enumerate(scenes_in, start=1):
                kind = "reactive" if str(sc.get("kind") or "").strip() in {"反应", "reactive"} else "proactive"
                s_state = str(sc.get("state") or "todo")
                scene = SceneCard(
                    scene_id=f"{chapter.chapter_id}_SC{seq:02d}",
                    chapter_id=chapter.chapter_id,
                    project_id=project_id,
                    scene_seq=seq,
                    scene_goal=str(sc.get("title") or "").strip() or f"场景 {seq}",
                    scene_type=kind,
                    state=s_state if s_state in SCENE_STATES else ("writing" if s_state == "active" else "todo"),
                    words_current=scene_words[seq - 1],
                    is_chapter_last=1 if seq == len(scenes_in) else 0,
                    writer_brief_json={
                        "source": "catalog_import",
                        "title": str(sc.get("title") or "").strip(),
                        "primary_form": kind,
                        **(
                            {"goal": str(sc.get("goal") or ""), "conflict": str(sc.get("obstacle") or ""), "setback": str(sc.get("turn") or "")}
                            if kind == "proactive"
                            else {"reaction": str(sc.get("goal") or ""), "dilemma": str(sc.get("obstacle") or ""), "decision": str(sc.get("turn") or "")}
                        ),
                    },
                )
                self.session.add(scene)
                created_scenes += 1
        self.session.flush()
        return {"created_chapter_count": len(chapters), "created_scene_count": created_scenes}

    # ---------- 字数 rollup（正文保存埋点用） ----------

    def words_rollup(self, scene: SceneCard) -> dict[str, Any]:
        chapter_words = sum(
            int(s.words_current or 0) for s in self.scene_rows(scene.chapter_id)
        )
        return {
            "scene_id": scene.scene_id,
            "scene_words": int(scene.words_current or 0),
            "chapter_id": scene.chapter_id,
            "chapter_words": chapter_words,
        }

    # ---------- internals ----------

    def _require_chapter(self, project_id: str, chapter_id: str) -> ChapterGoal:
        chapter = self.session.get(ChapterGoal, chapter_id)
        if chapter is None or chapter.trashed_flag == 1 or chapter.project_id != project_id:
            raise DomainError("CHAPTER_NOT_FOUND", "chapter not found in project", status_code=404)
        return chapter

    def _require_scene(self, project_id: str, scene_id: str) -> SceneCard:
        scene = self.session.get(SceneCard, scene_id)
        if scene is None or scene.trashed_flag == 1:
            raise DomainError("SCENE_NOT_FOUND", "scene not found", status_code=404)
        owner = scene.project_id
        if not owner:
            chapter = self.session.get(ChapterGoal, scene.chapter_id)
            owner = chapter.project_id if chapter else None
        if owner != project_id:
            raise DomainError("SCENE_NOT_FOUND", "scene not found in project", status_code=404)
        return scene

    def _scene_payload_with_slug(self, scene: SceneCard) -> dict[str, Any]:
        chapter = self.session.get(ChapterGoal, scene.chapter_id)
        project = self._projects.require_project(chapter.project_id)
        chapters = self.chapter_rows(chapter.project_id)
        index = next(i for i, c in enumerate(chapters) if c.chapter_id == chapter.chapter_id)
        return self.scene_payload(scene, chapter_slug=f"ch{index + 1:02d}")

    def _insert_scene(
        self,
        chapter: ChapterGoal,
        *,
        position: int,
        title: str,
        kind: str,
        state: str,
        brief: dict[str, Any],
    ) -> SceneCard:
        scenes = self.scene_rows(chapter.chapter_id)
        seq_base = max((int(s.scene_seq or 0) for s in self._all_chapter_scenes(chapter.chapter_id)), default=0)
        scene = SceneCard(
            scene_id=f"{chapter.chapter_id}_SC_{uuid.uuid4().hex[:8]}",
            chapter_id=chapter.chapter_id,
            project_id=chapter.project_id,
            scene_seq=seq_base + 1,
            scene_goal=title,
            scene_type=kind,
            state=state,
            words_current=0,
            writer_brief_json={"source": "catalog_api", "title": title, "primary_form": kind, **brief},
        )
        self.session.add(scene)
        self.session.flush()
        ordered = list(scenes)
        ordered.insert(max(0, min(position, len(ordered))), scene)
        self._renumber(ordered)
        chapter.planned_scene_count = len(ordered)
        return scene

    def _all_chapter_scenes(self, chapter_id: str) -> list[SceneCard]:
        return list(
            self.session.execute(
                select(SceneCard).where(SceneCard.chapter_id == chapter_id)
            ).scalars().all()
        )

    @staticmethod
    def _renumber(ordered: list[SceneCard]) -> None:
        for index, scene in enumerate(ordered, start=1):
            scene.scene_seq = index
            scene.is_chapter_last = 1 if index == len(ordered) else 0
