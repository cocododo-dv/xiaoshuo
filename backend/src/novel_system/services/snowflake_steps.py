from __future__ import annotations

from copy import deepcopy
from typing import Any


SNOWFLAKE_METHOD_VERSION = "2026-04-29.v2"
MATERIALIZATION_REQUIRED_STEPS = [
    "book_brief",
    "one_sentence_summary",
    "one_paragraph_summary",
    "scene_list",
    "scene_details",
]
MATERIALIZATION_WARNING_STEPS = [
    "character_sheets",
    "short_synopsis",
    "character_synopses",
    "long_synopsis",
    "character_bibles",
]
QUALITY_POLICY = {
    "flow_mode": "coach_flexible",
    "optional_steps_skippable_with_reason": True,
    "hard_gate": "materialization",
    "hard_required_steps": MATERIALIZATION_REQUIRED_STEPS,
    "warning_only_steps": MATERIALIZATION_WARNING_STEPS,
}
MATERIALIZATION_REQUIREMENTS = {
    "hard_required_steps": MATERIALIZATION_REQUIRED_STEPS,
    "warning_only_steps": MATERIALIZATION_WARNING_STEPS,
    "hard_blocker_statuses": ["missing", "skipped", "stale", "rewrite"],
}


SNOWFLAKE_STEP_CATALOG: list[dict[str, Any]] = [
    {
        "step_key": "book_brief",
        "label": "读者定位",
        "english_label": "Target Audience",
        "phase": "基础准备",
        "description": "明确你的小说类型和目标读者群体。你写作的核心目标是取悦你的读者——先知道为谁写，再决定写什么。",
        "default_draft": {
            "category": "",
            "target_reader": "",
            "story_kind": "",
            "delight_reason": "",
            "genre_promise": "",
            "expected_reader_emotion": "",
            "safety_rules": [
                "只借鉴抽象风格、结构经验与节奏手法。",
                "不得复制参考文本的人物、设定、桥段或标志性句式。",
            ],
        },
        "editor": {
            "kind": "form",
            "fields": [
                {"key": "category", "kind": "text", "label": "类型"},
                {"key": "target_reader", "kind": "textarea", "label": "目标读者"},
                {"key": "story_kind", "kind": "textarea", "label": "故事类型"},
                {"key": "delight_reason", "kind": "textarea", "label": "读者会沉迷的原因"},
                {"key": "genre_promise", "kind": "textarea", "label": "类型承诺"},
                {"key": "expected_reader_emotion", "kind": "textarea", "label": "期待读者情绪"},
                {"key": "safety_rules", "kind": "list", "label": "安全规则"},
            ],
        },
    },
    {
        "step_key": "one_sentence_summary",
        "label": "一句话概括",
        "english_label": "One-Sentence Summary",
        "phase": "雪花第1步",
        "description": "用一句话（最好25字以内）概括整部小说。这是最强营销工具——让人听完就想说「告诉我更多！」",
        "default_draft": {"summary": ""},
        "editor": {
            "kind": "form",
            "fields": [{"key": "summary", "kind": "textarea", "label": "一句话概括"}],
        },
    },
    {
        "step_key": "one_paragraph_summary",
        "label": "一段话概括",
        "english_label": "One-Paragraph Summary",
        "phase": "雪花第2步",
        "description": "将一句话扩展为五句话，构建三幕结构与三个关键「灾难」转折点。这确保你的故事有扎实的戏剧骨架。",
        "default_draft": {
            "sentences": ["", "", "", "", ""],
            "three_act_check": {
                "first_disaster": "",
                "second_disaster": "",
                "third_disaster": "",
                "ending": "",
            },
            "moral_premise": "",
        },
        "editor": {
            "kind": "form",
            "fields": [
                {"key": "sentences", "kind": "sentences", "label": "五个关键句"},
                {
                    "key": "three_act_check",
                    "kind": "object",
                    "label": "三幕校验",
                    "fields": [
                        {"key": "first_disaster", "kind": "text", "label": "第一次灾难"},
                        {"key": "second_disaster", "kind": "text", "label": "第二次灾难"},
                        {"key": "third_disaster", "kind": "text", "label": "第三次灾难"},
                        {"key": "ending", "kind": "text", "label": "结局"},
                    ],
                },
                {"key": "moral_premise", "kind": "textarea", "label": "主题前提"},
            ],
        },
    },
    {
        "step_key": "character_sheets",
        "label": "角色摘要表",
        "english_label": "Character Sheets",
        "phase": "雪花第3步",
        "description": "为每个重要角色创建基础档案。优秀小说由立体角色驱动——角色的价值观冲突产生了你所有的场景冲突。",
        "default_draft": {"characters": []},
        "editor": {
            "kind": "form",
            "fields": [
                {
                    "key": "characters",
                    "kind": "characters",
                    "label": "角色摘要表",
                    "template": {
                        "character_id": "",
                        "display_name": "",
                        "role": "",
                        "goal": "",
                        "ambition": "",
                        "values": [],
                        "conflict": "",
                        "epiphany": "",
                        "one_sentence_summary": "",
                        "one_paragraph_summary": "",
                    },
                }
            ],
        },
    },
    {
        "step_key": "short_synopsis",
        "label": "一页梗概",
        "english_label": "Short Synopsis",
        "phase": "雪花第4步",
        "description": "将五句话每一句扩展为一段（约100字），形成约500字的故事骨架。这是故事的第一次「填肉」。",
        "default_draft": {"paragraphs": ["", "", "", "", ""]},
        "editor": {
            "kind": "form",
            "fields": [{"key": "paragraphs", "kind": "paragraphs", "label": "段落梗概"}],
        },
    },
    {
        "step_key": "character_synopses",
        "label": "角色背景故事",
        "english_label": "Character Synopses",
        "phase": "雪花第5步",
        "description": "为每个重要角色写半页到一页的背景故事。理解角色为何成为这样的人，你才能写出他真实可信的行动。",
        "default_draft": {"characters": []},
        "editor": {
            "kind": "form",
            "fields": [
                {
                    "key": "characters",
                    "kind": "character_synopses",
                    "label": "角色背景故事",
                    "template": {
                        "character_id": "",
                        "display_name": "",
                        "role": "",
                        "synopsis": "",
                    },
                }
            ],
        },
    },
    {
        "step_key": "long_synopsis",
        "label": "长篇大纲",
        "english_label": "Long Synopsis",
        "phase": "雪花第6步",
        "description": "将一页梗概扩展为四到五页详细大纲。这是最接近实际写作的规划阶段。",
        "default_draft": {"paragraphs": ["", "", "", ""]},
        "editor": {
            "kind": "form",
            "fields": [{"key": "paragraphs", "kind": "paragraphs", "label": "长篇大纲段落"}],
        },
    },
    {
        "step_key": "character_bibles",
        "label": "角色全档案",
        "english_label": "Character Bibles",
        "phase": "雪花第7步",
        "description": "为每个角色创建详尽的「角色圣经」，彻底了解你的角色——他们是真实存在于你脑海中的人。",
        "default_draft": {"characters": []},
        "editor": {
            "kind": "form",
            "fields": [
                {
                    "key": "characters",
                    "kind": "character_bibles",
                    "label": "角色全档案",
                    "template": {
                        "character_id": "",
                        "display_name": "",
                        "role": "",
                        "physical_profile": {
                            "age": "",
                            "height": "",
                            "appearance": "",
                            "style": "",
                        },
                        "personality_profile": {
                            "strongest_trait": "",
                            "weakest_trait": "",
                            "humor": "",
                            "preferences": [],
                        },
                        "environment_profile": {
                            "home": "",
                            "family_background": "",
                            "education": "",
                            "work": "",
                            "relationships": "",
                        },
                        "psychological_profile": {
                            "best_memory": "",
                            "worst_memory": "",
                            "deepest_fear": "",
                            "greatest_hope": "",
                            "philosophy": "",
                            "self_image": "",
                            "public_image": "",
                            "character_arc": "",
                        },
                    },
                }
            ],
        },
    },
    {
        "step_key": "scene_list",
        "label": "场景列表",
        "english_label": "Scene List",
        "phase": "雪花第8步",
        "description": "列出小说中每一个场景。场景是小说的基本单位——每个场景必须有冲突，必须是一个完整的缩微故事。",
        "default_draft": {"scenes": []},
        "editor": {
            "kind": "form",
            "fields": [
                {
                    "key": "scenes",
                    "kind": "scene_list",
                    "label": "场景列表",
                    "template": {
                        "scene_id": "",
                        "chapter_id": "",
                        "chapter_title": "",
                        "chapter_goal": "",
                        "scene_seq": 1,
                        "pov_character_id": "",
                        "summary": "",
                        "primary_form": "proactive",
                        "scene_type": "proactive",
                        "chapter_role": "",
                        "location": "",
                        "crucible": "",
                    },
                }
            ],
        },
    },
    {
        "step_key": "scene_details",
        "label": "场景规划",
        "english_label": "Scene Planning",
        "phase": "雪花第9步",
        "description": "为每个场景规划关键信息。主动场景制造紧张，被动场景让读者喘息并期待——两者交替构成故事的引擎。",
        "default_draft": {"scenes": []},
        "editor": {
            "kind": "form",
            "fields": [
                {
                    "key": "scenes",
                    "kind": "scene_details",
                    "label": "场景规划",
                    "template": {
                        "scene_id": "",
                        "chapter_id": "",
                        "title": "",
                        "summary": "",
                        "primary_form": "proactive",
                        "scene_type": "proactive",
                        "location": "",
                        "scene_crucible": "",
                        "crucible": "",
                        "goal": "",
                        "conflict": "",
                        "setback": "",
                        "reaction": "",
                        "dilemma": "",
                        "decision": "",
                        "target_length_band": "medium",
                        "must_include_text": "",
                        "exit_change": "",
                        "hook": "",
                        "beats_json": [],
                    },
                    "scene_modes": [
                        {
                            "value": "proactive",
                            "label": "主动场景",
                            "fields": [
                                {
                                    "key": "goal",
                                    "kind": "textarea",
                                    "label": "目标",
                                    "hint": "角色想达成什么？（可拍摄/量化）",
                                    "placeholder": "例：在审讯结束前（约2小时内），让警探放弃拘留，拿到离开许可",
                                    "rows": 2,
                                },
                                {
                                    "key": "crucible",
                                    "kind": "textarea",
                                    "label": "坩埚",
                                    "hint": "什么力量将角色困住、无法轻易逃脱？",
                                    "placeholder": "例：审讯室是封闭空间，主角有前科，警探手里有伪造的监控截图，且主角手机已被没收",
                                    "rows": 2,
                                },
                                {
                                    "key": "conflict",
                                    "kind": "textarea",
                                    "label": "冲突过程",
                                    "hint": "写出2-3轮「尝试→受阻」的循环",
                                    "placeholder": "① 提供不在场证明→警探拿出监控截图否定\n② 要求见律师→以「证据收集期」为由拒绝\n③ 故意激怒警探犯程序错误→警探更冷静地追问",
                                    "rows": 4,
                                },
                                {
                                    "key": "setback",
                                    "kind": "textarea",
                                    "label": "挫折",
                                    "hint": "结尾主角比开场更糟——制造「开放循环」迫使读者翻页",
                                    "placeholder": "例：警探宣布以「妨碍司法」拘留48小时——正好是真凶行动的关键窗口期",
                                    "rows": 2,
                                },
                            ],
                        },
                        {
                            "value": "reactive",
                            "label": "反应场景",
                            "fields": [
                                {
                                    "key": "reaction",
                                    "kind": "textarea",
                                    "label": "反应",
                                    "hint": "先情感后理性——用身体/行为呈现，别直说「他很害怕」",
                                    "placeholder": "例：主角发现手在颤抖；脑子里反复回放那段被篡改的视频；连警探说话都听不进去；最后才意识到48小时意味着什么",
                                    "rows": 3,
                                },
                                {
                                    "key": "crucible",
                                    "kind": "textarea",
                                    "label": "坩埚",
                                    "hint": "是什么让角色无法回避这个困境？",
                                    "placeholder": "例：真凶今晚就要行动，主角却被关着，而且没有人相信他的话",
                                    "rows": 2,
                                },
                                {
                                    "key": "dilemma",
                                    "kind": "textarea",
                                    "label": "困境",
                                    "hint": "真正的两难——每个选项都必须付出代价",
                                    "placeholder": "选A：认罪换取假释→永远背负污点，无法再执业，且以后无法追凶\n选B：继续抵抗→今晚真凶得逞，又一条人命，且自己罪名更重",
                                    "rows": 3,
                                },
                                {
                                    "key": "decision",
                                    "kind": "textarea",
                                    "label": "决定",
                                    "hint": "角色最终如何选择？这个决定必须直接引发下一个场景的目标",
                                    "placeholder": "例：决定认罪——但在签字前悄悄发出了一条给记者的暗语短信",
                                    "rows": 2,
                                },
                            ],
                        },
                    ],
                }
            ],
        },
    },
]

for _step_definition in SNOWFLAKE_STEP_CATALOG:
    _required_for_materialization = _step_definition["step_key"] in MATERIALIZATION_REQUIRED_STEPS
    _step_definition["required_for_materialization"] = _required_for_materialization
    _step_definition["skippable"] = not _required_for_materialization

STEP_ORDER = {step["step_key"]: index for index, step in enumerate(SNOWFLAKE_STEP_CATALOG)}

_DEFAULT_GUIDANCE = {
    "instruction": "先写出当前层的可用版本，再根据后续发现回修前面的层级。",
    "checklist": ["保持具体", "保留代价", "让下一层能继续展开"],
    "rubric": {},
    "required_for_materialization": False,
    "timebox_minutes": 60,
    "source": "snowflake_method_summary",
}

_REFERENCE_STEP_INSTRUCTIONS: dict[str, str] = {
    "book_brief": (
        "回答以下三个问题：\n\n"
        "① 我的故事类型/流派是什么？\n"
        "② 这类故事的魅力在哪里？为何读者会喜欢？\n"
        "③ 我理想中的读者是谁？他们的特征是？"
    ),
    "one_sentence_summary": (
        "格式参考：\n"
        "「一位[有特点的角色]必须[完成某个目标]，但[核心障碍阻拦着他]。」\n\n"
        "要求：\n"
        "① 不超过25字\n"
        "② 突出主角独特性\n"
        "③ 明确故事核心目标\n"
        "④ 制造悬念，不透露结局"
    ),
    "one_paragraph_summary": (
        "五句话对应五个结构节点：\n\n"
        "第①句：背景与主角登场\n"
        "第②句：第一灾难→第一幕终点（主角被迫卷入，无法回头）\n"
        "第③句：第二灾难→第二幕中点（世界观被打碎，开始改变）\n"
        "第④句：第三灾难→第二幕终点（局势失控，逼向终局）\n"
        "第⑤句：第三幕→决战与收尾"
    ),
    "character_sheets": (
        "每个角色包含：\n\n"
        "• 角色定位：主角/反派/导师/伙伴...\n"
        "• 具体目标：这个故事里他要达成什么？\n"
        "• 抽象野心：他人生最深处渴望什么？\n"
        "• 核心价值观：「没有什么比___更重要」（写3条，互相有张力）\n"
        "• 阻碍：什么阻止他实现目标？\n"
        "• 顿悟：故事结束时他学到/改变了什么？\n\n"
        "⚠️ 每个角色都是自己故事的主角，包括反派。"
    ),
    "short_synopsis": (
        "将第2步的五句话各自扩展为一段：\n\n"
        "第1段：世界观细节、主角背景、初始状态与内心冲突\n"
        "第2段：触发事件，第一灾难的具体过程与影响\n"
        "第3段：第二幕挣扎，第二灾难如何改变主角认知\n"
        "第4段：局势升级，第三灾难如何将所有人逼向绝境\n"
        "第5段：高潮决战走向，主角命运，故事如何收尾"
    ),
    "character_synopses": (
        "每个角色的背景故事包含：\n\n"
        "• 成长经历：哪些关键事件塑造了他的性格？\n"
        "• 内心世界：他真正渴望的是什么？为何渴望？\n"
        "• 在故事中的作用：他如何推动主线剧情？\n"
        "• 与其他角色的关系纠葛\n\n"
        "⚠️ 特别提示：给反派足够的理解——他相信自己是对的。"
    ),
    "long_synopsis": (
        "将第4步的每一段扩展为约400字的一页：\n\n"
        "• 加入具体的场景设定（时间、地点、氛围）\n"
        "• 详细的角色行动与反应\n"
        "• 关键对话的要点提示\n"
        "• 情感变化的节点\n"
        "• 次要情节线的穿插"
    ),
    "character_bibles": (
        "每个角色全档案包含四个维度：\n\n"
        "【外貌信息】年龄、身高体重、外貌特征、着装风格\n"
        "【性格信息】幽默感、性格类型、爱好偏好\n"
        "【环境信息】家庭背景、教育、工作、重要人际关系\n"
        "【心理信息】最好/最坏的童年记忆、性格优缺点、最大希望与恐惧、人生哲学、「他人眼中的他」vs「他自己眼中的他」"
    ),
    "scene_list": (
        "场景列表格式：\n\n"
        "「编号 | 类型（主动/被动）| 视角人物 | 地点/时间 | 坩埚（困住角色的力量）| 结果/转变」\n\n"
        "⚠️ 铁律三条：\n"
        "① 每个场景必须包含冲突（内部或外部）\n"
        "② 没有冲突的场景→删除\n"
        "③ 主动场景（目标→冲突→挫折）和被动场景（反应→困境→决定）交替出现，形成呼吸节奏"
    ),
    "scene_details": (
        "【主动场景】\n"
        "目标：角色想达成什么？要具体可拍摄/量化\n"
        "坩埚：什么力量将角色困在这个处境里？\n"
        "冲突：多轮尝试→受阻的循环\n"
        "挫折：结尾比开场更糟，制造「开放循环」迫使读者翻页\n\n"
        "【反应场景】\n"
        "反应：情感先于理性——用身体/行为呈现，别直说「他很害怕」\n"
        "困境：真正的两难——每个选项都有代价\n"
        "决定：必须决断，决定引发下一个目标\n\n"
        "主动→被动→主动→被动……是故事前进的引擎。"
    ),
}

_REFERENCE_GUIDANCE_TIMEBOX = {
    "long_synopsis": 120,
    "scene_list": 180,
    "scene_details": 180,
}

_STEP_GUIDANCE = {
    step_key: {
        "instruction": instruction,
        "checklist": [],
        "timebox_minutes": _REFERENCE_GUIDANCE_TIMEBOX.get(step_key, 60),
        "source": "snowflake_method_summary",
    }
    for step_key, instruction in _REFERENCE_STEP_INSTRUCTIONS.items()
}

_GUIDANCE_CHECKLIST = {
    "book_brief": [
        "写出具体读者承诺，而不是只写宽泛类型。",
        "把类型爽点和压力、阻力、代价、情绪连起来。",
        "安全规则只允许借鉴抽象技法，不复制文本或桥段。",
    ],
    "one_sentence_summary": [
        "在一句因果句里保留主角、目标、阻力和代价。",
        "足够具体，后续场景能据此判断取舍。",
        "除非项目本身需要，否则不要提前交代完整结局。",
    ],
    "one_paragraph_summary": [
        "五句分别承担开局、三次递进转折和结局方向。",
        "每次转折都改变主角下一步能做什么。",
        "灾难链能扩展为场景，不需要重新发明前提。",
    ],
    "scene_list": [
        "保持场景 ID、章节顺序和 POV 连续。",
        "每个场景都有职责：施压、受阻、结果或转向。",
        "场景摘要具体到足以进入下一轮规划。",
    ],
    "scene_details": [
        "每场先选主形态：主动场景或反应场景。",
        "主动场景有目标、冲突、挫折；反应场景有反应、困境、决定。",
        "如果同一场兼有行动和反应，后续字段可以保留为补充。",
    ],
}

_GUIDANCE_RUBRIC = {
    "读者承诺": "后续生成选择能否依据这条承诺被接受或否决？",
    "因果压力": "这一层是否让下一事件更难、更贵或更不可逆？",
    "角色压力": "目标、价值、阻力和变化是否能在页面上看见？",
    "场景可写性": "结果能否变成一个有目标、阻力、代价和转折的具体场景？",
    "连续性": "是否保留项目语言、已确认事实、ID 和顺序？",
}

for _step_key, _guidance in _STEP_GUIDANCE.items():
    _guidance["checklist"] = _GUIDANCE_CHECKLIST.get(
        _step_key,
        [
            "保留已确认事实、ID、顺序和项目语言。",
            "补入具体压力或代价，不只做解释性扩写。",
            "让下一层雪花更容易继续写。",
        ],
    )
    _guidance["rubric"] = deepcopy(_GUIDANCE_RUBRIC)
    _guidance["required_for_materialization"] = _step_key in MATERIALIZATION_REQUIRED_STEPS

_FIELD_HELP: dict[str, dict[str, str]] = {
    "category": {"hint": "故事所属类型或货架位置。", "placeholder": "都市悬疑 / 奇幻冒险 / 现实情感"},
    "target_reader": {"hint": "谁会被这个故事稳定取悦。", "placeholder": "喜欢旧案、关系代价和持续反转的读者。"},
    "story_kind": {"hint": "这到底是哪一种故事体验。", "placeholder": "一个人物在压力下追查真相并付出关系代价的故事。"},
    "delight_reason": {"hint": "读者继续翻页的核心原因。", "placeholder": "每个线索都让真相更近，也让主角付出更多。"},
    "genre_promise": {"hint": "类型给读者的承诺。", "placeholder": "调查推进真相，关系代价放大抉择。"},
    "expected_reader_emotion": {"hint": "希望读者持续感到什么。", "placeholder": "压力、怀疑、心疼和必须继续读的未完成感。"},
    "summary": {"hint": "压缩主角、目标、阻力和代价。", "placeholder": "一名回城女子追查旧案，却发现真相会撕开家族。"},
    "sentences": {"hint": "五句分别承载开局、三次灾难和结局。", "placeholder": "每行一句，保持因果递进。"},
    "paragraphs": {"hint": "把上一层的每个节点扩成一段。", "placeholder": "围绕一个结构节点展开行动、阻力和代价。"},
    "characters": {"hint": "每个重要人物都是自己故事里的主角。", "placeholder": "先添加主角、盟友、对手。"},
    "scenes": {"hint": "每个场景都要推动信息、关系或行动目标变化。", "placeholder": "按章节顺序列出场景。"},
    "scene_crucible": {"hint": "困住人物、让他们不能轻易退出的力量。", "placeholder": "退缩会让上一场损失固化，继续行动又会付出新代价。"},
    "crucible": {"hint": "困住人物、让他们不能轻易退出的力量。", "placeholder": "退缩会让上一场损失固化，继续行动又会付出新代价。"},
    "goal": {"hint": "主动场景里可被拍出来的具体目标。", "placeholder": "在审讯结束前拿到离开许可。"},
    "conflict": {"hint": "多轮尝试和受阻，不只是一次拒绝。", "placeholder": "提出证据被否定；要求见律师被拖延；激怒对方反而暴露新风险。"},
    "setback": {"hint": "结尾让人物比开场更糟，或赢了但付出代价。", "placeholder": "拿到线索，却发现线索指向最亲近的人。"},
    "reaction": {"hint": "先身体和情绪，后理性分析。", "placeholder": "手发抖、反复回想上一场坏消息，随后才意识到真正损失。"},
    "dilemma": {"hint": "两个选择都要付出真实代价。", "placeholder": "公开会伤害家人；沉默会让真相再次被掩埋。"},
    "decision": {"hint": "必须触发下一场的新目标。", "placeholder": "决定去见掌握时间线的人。"},
    "moral_premise": {"hint": "人物误信什么，又会学会什么。", "placeholder": "沉默不能保护人，承担代价才可能结束伤害。"},
}


def list_step_definitions() -> list[dict[str, Any]]:
    return deepcopy(SNOWFLAKE_STEP_CATALOG)


def get_step_definition(step_key: str) -> dict[str, Any]:
    for step in SNOWFLAKE_STEP_CATALOG:
        if step["step_key"] == step_key:
            return deepcopy(step)
    raise KeyError(step_key)


def editor_payload(step_key: str) -> dict[str, Any]:
    editor = deepcopy(get_step_definition(step_key)["editor"])
    _enrich_editor_fields(editor.get("fields") or [])
    return editor


def step_guidance(step_key: str) -> dict[str, Any]:
    return deepcopy(_STEP_GUIDANCE.get(step_key) or _DEFAULT_GUIDANCE)


def step_completeness(step_key: str, draft: dict[str, Any] | None) -> dict[str, Any]:
    payload = draft if isinstance(draft, dict) else {}
    missing_fields = _missing_fields_for_step(step_key, payload)
    total_count = _total_fields_for_step(step_key, payload)
    filled_count = max(0, total_count - len(missing_fields))
    return {
        "filled_count": filled_count,
        "total_count": total_count,
        "missing_fields": missing_fields,
    }


def diagnose_step_pressure(step_key: str, draft: dict[str, Any] | None) -> dict[str, Any]:
    payload = draft if isinstance(draft, dict) else {}
    if step_key == "scene_details":
        return _diagnose_scene_step_pressure(step_key, payload)

    completeness = step_completeness(step_key, payload)
    missing_fields = completeness.get("missing_fields") or []
    flags = [f"missing_{_flag_key(field)}" for field in missing_fields]
    strengths: list[str] = []
    fix_steps: list[str] = []

    if step_key == "book_brief":
        target_reader = _text(payload.get("target_reader"))
        story_kind = _text(payload.get("story_kind"))
        delight_reason = _text(payload.get("delight_reason"))
        genre_promise = _text(payload.get("genre_promise"))
        expected_emotion = _text(payload.get("expected_reader_emotion"))
        if _looks_generic(target_reader):
            flags.append("reader_promise_too_generic")
            fix_steps.append("把目标读者收窄成可感知的读者承诺，不要只写宽泛类型。")
        else:
            strengths.append("目标读者已经能作为可用读者承诺")
        if _looks_generic(story_kind) or _looks_generic(delight_reason) or _looks_generic(genre_promise):
            flags.append("story_pressure_too_generic")
            fix_steps.append("把故事类型、爽点和类型承诺落到具体压力、阻力与代价上。")
        else:
            strengths.append("故事压力和类型承诺已经连上")
        if _looks_generic(expected_emotion):
            flags.append("reader_emotion_missing")
            fix_steps.append("写清楚读者在压力升级中持续感到的情绪。")
    elif step_key == "one_sentence_summary":
        summary = _text(payload.get("summary"))
        if _looks_generic(summary) or not _has_pressure_turn(summary):
            flags.append("logline_lacks_pressure_turn")
            fix_steps.append("把主角、目标、阻力和代价压缩进一句因果句。")
        else:
            strengths.append("一句话已经带出可用的压力转折")
    elif step_key == "one_paragraph_summary":
        sentences = [_text(item) for item in payload.get("sentences") or [] if _text(item)]
        if len(sentences) < 5:
            flags.append("five_sentence_spine_incomplete")
            fix_steps.append("补齐五句话：开局、三次灾难和结局方向。")
        disaster_text = " ".join(str(item or "") for item in (payload.get("three_act_check") or {}).values())
        if _looks_generic(disaster_text) or not _has_pressure_turn(disaster_text):
            flags.append("disaster_chain_too_soft")
            fix_steps.append("让每次灾难都迫使承诺、价值转变或不可逆升级。")
        else:
            strengths.append("三幕灾难链已经有可见压力")
    elif step_key in {"character_sheets", "character_synopses", "character_bibles"}:
        characters = [item for item in payload.get("characters") or [] if isinstance(item, dict)]
        if not characters:
            flags.append("character_pressure_missing")
            fix_steps.append("至少补入主角、对手/阻力，以及一个能承载压力的盟友或映照角色。")
        for index, character in enumerate(characters[:4], start=1):
            label = _text(character.get("display_name") or character.get("name") or f"character_{index}")
            pressure_text = " ".join(
                _text(character.get(key))
                for key in ("goal", "ambition", "conflict", "epiphany", "synopsis", "deepest_fear", "how_character_changes")
            )
            if _looks_generic(pressure_text) or not _has_pressure_turn(pressure_text):
                flags.append(f"{_flag_key(label)}_pressure_too_soft")
            else:
                strengths.append(f"{label} 已经有目标、冲突和变化压力")
        if characters and not any(item.startswith("至少补入") for item in fix_steps):
            fix_steps.append("把薄弱角色的具体目标、阻挡力量、价值冲突和变化再压实。")
    elif step_key in {"short_synopsis", "long_synopsis"}:
        paragraphs = [_text(item) for item in payload.get("paragraphs") or [] if _text(item)]
        if not paragraphs:
            flags.append("synopsis_missing")
            fix_steps.append("把上一层扩成因果相连的压力节点。")
        elif not _has_pressure_turn(" ".join(paragraphs)):
            flags.append("synopsis_lacks_escalation")
            fix_steps.append("加入可见反转、上升代价，以及会改变下一段目标的转向。")
        else:
            strengths.append("梗概已经包含压力升级")
    elif step_key == "scene_list":
        scenes = [item for item in payload.get("scenes") or [] if isinstance(item, dict)]
        if not scenes:
            flags.append("scene_list_missing")
            fix_steps.append("按顺序列出具体场景，并让每场都有视角压力和结果/变化。")
        weak_scenes = [
            str(scene.get("scene_id") or index)
            for index, scene in enumerate(scenes, start=1)
            if _looks_generic(_text(scene.get("summary"))) or _looks_generic(_text(scene.get("chapter_role")))
        ]
        if weak_scenes:
            flags.append("scene_jobs_too_generic")
            fix_steps.append("给每个场景明确职责：什么改变、谁在阻挡、为什么下一场必须发生。")
        if scenes and not weak_scenes:
            strengths.append("场景列表已经有可用职责")

    for missing_field in missing_fields[:3]:
        fix_steps.append(f"补齐必填字段：{_field_display_label(missing_field)}。")

    return _pressure_result(step_key, flags=flags, fix_steps=fix_steps, strengths=strengths)


def merge_step_draft(
    step_key: str,
    artifact_json: dict[str, Any] | None,
    *,
    latest_by_step: dict[str, Any] | None = None,
) -> dict[str, Any]:
    draft = default_step_draft(step_key, latest_by_step=latest_by_step)
    payload = artifact_json or {}
    if not isinstance(payload, dict):
        return draft
    return _normalize_step_draft(step_key, _merge_dicts(draft, payload))


def default_step_draft(step_key: str, *, latest_by_step: dict[str, Any] | None = None) -> dict[str, Any]:
    step = get_step_definition(step_key)
    draft = deepcopy(step.get("default_draft") or {})
    if step_key == "scene_details":
        scene_list_artifact = (latest_by_step or {}).get("scene_list")
        scenes = []
        if scene_list_artifact is not None:
            scenes = list((scene_list_artifact.artifact_json or {}).get("scenes") or [])
        if scenes:
            draft["scenes"] = [_scene_detail_seed(scene, index) for index, scene in enumerate(scenes, start=1)]
    return _normalize_step_draft(step_key, draft)


def _normalize_step_draft(step_key: str, draft: dict[str, Any]) -> dict[str, Any]:
    payload = deepcopy(draft if isinstance(draft, dict) else {})
    if step_key == "short_synopsis":
        paragraphs = _coerce_string_list(payload.get("paragraphs"))
        while len(paragraphs) < 5:
            paragraphs.append("")
        payload["paragraphs"] = paragraphs[:5]
    elif step_key == "character_bibles":
        payload["characters"] = [_normalize_character_bible(item) for item in payload.get("characters") or [] if isinstance(item, dict)]
    elif step_key in {"scene_list", "scene_details"}:
        payload["scenes"] = [_normalize_scene_item(item, index=index) for index, item in enumerate(payload.get("scenes") or [], start=1) if isinstance(item, dict)]
    return payload


def _normalize_character_bible(item: dict[str, Any]) -> dict[str, Any]:
    template_field = next(
        field
        for field in get_step_definition("character_bibles")["editor"]["fields"]
        if field.get("key") == "characters"
    )
    template = deepcopy(template_field.get("template") or {})
    normalized = _merge_dicts(template, item)

    physical = normalized.setdefault("physical_profile", {})
    personality = normalized.setdefault("personality_profile", {})
    environment = normalized.setdefault("environment_profile", {})
    psychological = normalized.setdefault("psychological_profile", {})
    if isinstance(physical, dict):
        physical["age"] = str(item.get("age") or physical.get("age") or "").strip()
    if isinstance(personality, dict):
        personality["strongest_trait"] = str(item.get("strongest_trait") or personality.get("strongest_trait") or "").strip()
        personality["weakest_trait"] = str(item.get("weakest_trait") or personality.get("weakest_trait") or "").strip()
    if isinstance(environment, dict):
        environment["home"] = str(item.get("home") or environment.get("home") or "").strip()
    if isinstance(psychological, dict):
        psychological["deepest_fear"] = str(item.get("deepest_fear") or psychological.get("deepest_fear") or "").strip()
        psychological["character_arc"] = str(item.get("how_character_changes") or psychological.get("character_arc") or "").strip()
    return normalized


def _normalize_scene_item(item: dict[str, Any], *, index: int) -> dict[str, Any]:
    normalized = deepcopy(item)
    primary_form = str(
        normalized.get("primary_form")
        or normalized.get("scene_type")
        or ("proactive" if index % 2 else "reactive")
    ).strip().lower()
    if primary_form not in {"proactive", "reactive"}:
        primary_form = "proactive"
    normalized["primary_form"] = primary_form
    normalized["scene_type"] = primary_form
    normalized.setdefault("crucible", normalized.get("scene_crucible") or "")
    normalized.setdefault("scene_crucible", normalized.get("crucible") or "")
    if "beats_json" in normalized:
        normalized["beats_json"] = _coerce_string_list(normalized.get("beats_json"))
    return normalized


def extract_scene_triage_items(scene_details_draft: dict[str, Any] | None) -> list[dict[str, Any]]:
    if not isinstance(scene_details_draft, dict):
        return []
    items: list[dict[str, Any]] = []
    for index, scene in enumerate(scene_details_draft.get("scenes") or [], start=1):
        if not isinstance(scene, dict):
            continue
        scene_id = str(scene.get("scene_id") or "").strip()
        if not scene_id:
            continue
        diagnosis = diagnose_scene_detail(scene, index=index)
        manual_status = _coerce_triage_status(scene.get("triage_status"))
        effective_status = manual_status or diagnosis["recommended_status"]
        manual_missing_fields = _coerce_string_list(scene.get("triage_missing_fields"))
        manual_fix_steps = _coerce_string_list(scene.get("triage_fix_steps"))
        items.append(
            {
                "scene_id": scene_id,
                "title": str(scene.get("title") or scene.get("summary") or f"场景 {index:02d}").strip(),
                "primary_form": str(scene.get("primary_form") or scene.get("scene_type") or "proactive").strip() or "proactive",
                "scene_type": str(scene.get("primary_form") or scene.get("scene_type") or "proactive").strip() or "proactive",
                "status": manual_status,
                "notes": str(scene.get("triage_notes") or "").strip(),
                "recommended_status": diagnosis["recommended_status"],
                "effective_status": effective_status,
                "score": diagnosis["score"],
                "pressure_flags": diagnosis["pressure_flags"],
                "missing_fields": manual_missing_fields or diagnosis["missing_fields"],
                "fix_steps": manual_fix_steps or diagnosis["fix_steps"],
                "blocking": effective_status == "rewrite",
                "manual_override": bool(manual_status and manual_status != diagnosis["recommended_status"]),
            }
        )
    return items


def apply_scene_triage(
    scene_details_draft: dict[str, Any] | None,
    items: list[dict[str, Any]] | None,
) -> dict[str, Any]:
    draft = merge_step_draft("scene_details", scene_details_draft)
    updates = {
        str(item.get("scene_id") or "").strip(): {
            "triage_status": str(item.get("status") or "").strip(),
            "triage_notes": str(item.get("notes") or "").strip(),
            "triage_missing_fields": _coerce_string_list(item.get("missing_fields")),
            "triage_fix_steps": _coerce_string_list(item.get("fix_steps")),
        }
        for item in items or []
        if str(item.get("scene_id") or "").strip()
    }
    for scene in draft.get("scenes") or []:
        if not isinstance(scene, dict):
            continue
        update = updates.get(str(scene.get("scene_id") or "").strip())
        if not update:
            continue
        scene["triage_status"] = update["triage_status"]
        scene["triage_notes"] = update["triage_notes"]
        scene["triage_missing_fields"] = update["triage_missing_fields"]
        scene["triage_fix_steps"] = update["triage_fix_steps"]
    return draft


def _scene_detail_seed(scene: dict[str, Any], index: int) -> dict[str, Any]:
    scene_type = str(scene.get("primary_form") or scene.get("scene_type") or ("proactive" if index % 2 else "reactive")).strip().lower() or "proactive"
    if scene_type not in {"proactive", "reactive"}:
        scene_type = "proactive"
    base = {
        "scene_id": scene.get("scene_id") or "",
        "chapter_id": scene.get("chapter_id") or "",
        "title": scene.get("summary") or f"场景 {index:02d}",
        "summary": scene.get("summary") or "",
        "primary_form": scene_type,
        "scene_type": scene_type,
        "location": scene.get("location") or "",
        "crucible": scene.get("crucible") or scene.get("scene_crucible") or "",
        "scene_crucible": "",
        "goal": "",
        "conflict": "",
        "setback": "",
        "reaction": "",
        "dilemma": "",
        "decision": "",
        "triage_status": "",
        "triage_notes": "",
        "triage_missing_fields": [],
        "triage_fix_steps": [],
    }
    return base


def _enrich_editor_fields(fields: list[dict[str, Any]]) -> None:
    for field in fields:
        key = str(field.get("key") or "")
        help_text = _FIELD_HELP.get(key)
        if help_text:
            field.setdefault("hint", help_text["hint"])
            field.setdefault("placeholder", help_text["placeholder"])
        if isinstance(field.get("fields"), list):
            _enrich_editor_fields(field["fields"])
        for mode in field.get("scene_modes") or []:
            if isinstance(mode.get("fields"), list):
                _enrich_editor_fields(mode["fields"])


def _missing_fields_for_step(step_key: str, draft: dict[str, Any]) -> list[str]:
    if step_key == "scene_details":
        scenes = draft.get("scenes") if isinstance(draft.get("scenes"), list) else []
        if not scenes:
            return ["scenes"]
        missing: list[str] = []
        for index, scene in enumerate(scenes, start=1):
            if not isinstance(scene, dict):
                missing.append(f"scenes[{index}]")
                continue
            scene_missing = _missing_scene_detail_fields(scene)
            missing.extend(f"{scene.get('scene_id') or index}.{field}" for field in scene_missing)
        return missing

    fields = get_step_definition(step_key).get("editor", {}).get("fields") or []
    missing = []
    for field in fields:
        key = str(field.get("key") or "")
        if key and not _has_value(draft.get(key)):
            missing.append(key)
    return missing


def _total_fields_for_step(step_key: str, draft: dict[str, Any]) -> int:
    if step_key == "scene_details":
        scenes = draft.get("scenes") if isinstance(draft.get("scenes"), list) else []
        if not scenes:
            return 1
        total = 0
        for scene in scenes:
            if not isinstance(scene, dict):
                total += 1
                continue
            scene_type = str(scene.get("primary_form") or scene.get("scene_type") or "proactive").strip().lower()
            total += 4 if scene_type in {"proactive", "reactive"} else 1
        return total
    return len(get_step_definition(step_key).get("editor", {}).get("fields") or [])


def _diagnose_scene_step_pressure(step_key: str, draft: dict[str, Any]) -> dict[str, Any]:
    scenes = [scene for scene in draft.get("scenes") or [] if isinstance(scene, dict)]
    if not scenes:
        return _pressure_result(
            step_key,
            flags=["missing_scenes"],
            fix_steps=["物化前先补出场景规划，让每场都有压力和可见转折。"],
            strengths=[],
        )
    diagnoses = [diagnose_scene_detail(scene, index=index) for index, scene in enumerate(scenes, start=1)]
    flags = _unique(flag for diagnosis in diagnoses for flag in diagnosis.get("pressure_flags") or [])
    fix_steps = _unique(step for diagnosis in diagnoses for step in diagnosis.get("fix_steps") or [])
    strengths = []
    pass_count = sum(1 for diagnosis in diagnoses if diagnosis.get("recommended_status") == "pass")
    if pass_count:
        strengths.append(f"{pass_count} 场已经具备完整压力结构")
    score = round(sum(int(diagnosis.get("score") or 0) for diagnosis in diagnoses) / len(diagnoses))
    status = "rewrite" if any(diagnosis.get("recommended_status") == "rewrite" for diagnosis in diagnoses) else "maybe" if flags else "pass"
    return {
        "step_key": step_key,
        "pressure_score": max(0, min(100, score)),
        "pressure_status": status,
        "pressure_flags": flags,
        "fix_steps": fix_steps,
        "strengths": strengths,
        "score": max(0, min(100, score)),
        "status": status,
        "gaps": flags,
        "next_actions": fix_steps,
        "hard_blockers": _hard_blockers_from_flags(flags),
    }


def _missing_scene_detail_fields(scene: dict[str, Any]) -> list[str]:
    scene_type = str(scene.get("primary_form") or scene.get("scene_type") or "proactive").strip().lower()
    required = ["reaction", "dilemma", "decision"] if scene_type == "reactive" else ["goal", "conflict", "setback"]
    missing = []
    if not _has_value(scene.get("scene_crucible") or scene.get("crucible")):
        missing.append("crucible")
    missing.extend(key for key in required if not _has_value(scene.get(key)))
    return missing


def diagnose_scene_detail(scene: dict[str, Any], *, index: int = 1) -> dict[str, Any]:
    payload = scene if isinstance(scene, dict) else {}
    scene_type = str(payload.get("primary_form") or payload.get("scene_type") or "proactive").strip().lower()
    if scene_type not in {"proactive", "reactive"}:
        scene_type = "proactive"
    required = ["reaction", "dilemma", "decision"] if scene_type == "reactive" else ["goal", "conflict", "setback"]
    missing_fields = _missing_scene_detail_fields(payload)
    total_fields = len(required) + 1
    filled_fields = max(0, total_fields - len(missing_fields))
    pressure_flags = [f"missing_{field}" for field in missing_fields]
    scene_core_empty = not _has_value(payload.get("title")) and not _has_value(payload.get("summary"))
    if scene_core_empty and all(field in missing_fields for field in required):
        pressure_flags.append("scene_core_empty")
    weak_flags = _weak_scene_pressure_flags(payload, scene_type)
    pressure_flags.extend(flag for flag in weak_flags if flag not in pressure_flags)

    score = round((filled_fields / total_fields) * 100) if total_fields else 0
    if scene_core_empty:
        score = max(0, score - 10)
    if weak_flags:
        score = max(0, score - min(45, len(weak_flags) * 14))

    if "scene_core_empty" in pressure_flags or score < 40:
        recommended_status = "rewrite"
    elif missing_fields or weak_flags:
        recommended_status = "maybe"
    else:
        recommended_status = "pass"

    return {
        "scene_id": str(payload.get("scene_id") or f"scene_{index:02d}"),
        "primary_form": scene_type,
        "scene_type": scene_type,
        "recommended_status": recommended_status,
        "score": score,
        "missing_fields": missing_fields,
        "pressure_flags": pressure_flags,
        "fix_steps": _diagnostic_fix_steps(scene_type, missing_fields, recommended_status, pressure_flags=pressure_flags),
    }


def _weak_scene_pressure_flags(scene: dict[str, Any], scene_type: str) -> list[str]:
    flags: list[str] = []
    crucible = _text(scene.get("scene_crucible") or scene.get("crucible"))
    if crucible and _looks_generic(crucible):
        flags.append("weak_crucible_pressure")
    if scene_type == "reactive":
        reaction = _text(scene.get("reaction"))
        dilemma = _text(scene.get("dilemma"))
        decision = _text(scene.get("decision"))
        if reaction and _looks_generic(reaction):
            flags.append("weak_reaction_specificity")
        if dilemma and (_looks_generic(dilemma) or not _has_true_choice_cost(dilemma)):
            flags.append("fake_dilemma")
        if decision and (_looks_generic(decision) or not _points_to_next_goal(decision)):
            flags.append("weak_decision_next_goal")
        return flags

    conflict = _text(scene.get("conflict"))
    setback = _text(scene.get("setback"))
    goal = _text(scene.get("goal"))
    if goal and _looks_generic(goal):
        flags.append("weak_goal_specificity")
    if conflict and (_looks_generic(conflict) or not _has_escalating_conflict(conflict)):
        flags.append("weak_conflict_escalation")
    if setback and (_looks_generic(setback) or not _has_cost_or_reversal(setback)):
        flags.append("weak_setback_cost")
    return flags


def _diagnostic_fix_steps(
    scene_type: str,
    missing_fields: list[str],
    recommended_status: str,
    *,
    pressure_flags: list[str] | None = None,
) -> list[str]:
    if recommended_status == "pass":
        return []
    if recommended_status == "rewrite":
        return [
            "围绕具体坩埚重建这一场：谁被困住、被什么压力困住、结尾发生什么变化。",
            "开写前先选一种结构：主动场景用目标/冲突/挫折，反应场景用反应/困境/决定。",
        ]
    if scene_type == "reactive":
        labels = {
            "crucible": "写清楚角色为什么躲不开这个困境。",
            "reaction": "先补身体或情绪反应，再进入理性分析。",
            "dilemma": "把选择改成真正的两难，两边都有代价。",
            "decision": "用一个能制造下一场目标的决定收尾。",
        }
    else:
        labels = {
            "crucible": "写清楚什么力量把角色困在这个压力里。",
            "goal": "让场景目标具体、可见、可判断是否达成。",
            "conflict": "补出多轮升级的尝试与受阻，而不是一次拒绝。",
            "setback": "结尾要比开场更糟，或让胜利带上具体代价。",
        }
    steps = [labels[field] for field in missing_fields if field in labels]
    weak_labels = {
        "weak_crucible_pressure": "把坩埚具体化：写出困住角色的陷阱、倒计时、社会代价或不可逆损失。",
        "weak_goal_specificity": "让场景目标在页面上可见、可检验。",
        "weak_conflict_escalation": "把冲突改成多轮尝试和更强阻力。",
        "weak_setback_cost": "让结尾变糟，或让表面胜利带上具体代价。",
        "weak_reaction_specificity": "用身体反应、行为或迟来的意识替代直接说情绪。",
        "fake_dilemma": "重写困境，让两个选项都有真实且明确的代价。",
        "weak_decision_next_goal": "让决定触发下一场的具体目标。",
    }
    steps.extend(weak_labels[flag] for flag in pressure_flags or [] if flag in weak_labels)
    return _unique(steps)


def _pressure_result(step_key: str, *, flags: list[str], fix_steps: list[str], strengths: list[str]) -> dict[str, Any]:
    unique_flags = _unique(flags)
    unique_fix_steps = _unique(fix_steps)
    unique_strengths = _unique(strengths)
    score = max(0, min(100, 100 - len(unique_flags) * 12))
    critical_flags = {"missing_scenes", "scene_core_empty", "character_pressure_missing", "synopsis_missing", "scene_list_missing"}
    if any(flag in critical_flags for flag in unique_flags) and score > 45:
        score = 44
    status = "rewrite" if score < 45 else "maybe" if unique_flags else "pass"
    return {
        "step_key": step_key,
        "pressure_score": score,
        "pressure_status": status,
        "pressure_flags": unique_flags,
        "fix_steps": unique_fix_steps,
        "strengths": unique_strengths,
        "score": score,
        "status": status,
        "gaps": unique_flags,
        "next_actions": unique_fix_steps,
        "hard_blockers": _hard_blockers_from_flags(unique_flags),
    }


def _hard_blockers_from_flags(flags: list[str]) -> list[str]:
    critical_flags = {"missing_scenes", "scene_core_empty", "scene_list_missing"}
    blockers = [
        flag
        for flag in flags
        if flag in critical_flags or flag.startswith("missing_")
    ]
    return _unique(blockers)


_FIELD_DISPLAY_LABELS = {
    "category": "类型",
    "target_reader": "目标读者",
    "story_kind": "故事类型",
    "delight_reason": "读者沉迷原因",
    "genre_promise": "类型承诺",
    "expected_reader_emotion": "期待读者情绪",
    "summary": "概括",
    "sentences": "五句骨架",
    "three_act_check": "三幕校验",
    "moral_premise": "主题前提",
    "paragraphs": "段落梗概",
    "characters": "角色",
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
    "target_length_band": "目标篇幅",
}


def _field_display_label(key: str) -> str:
    return _FIELD_DISPLAY_LABELS.get(str(key or ""), str(key or "字段"))


def _text(value: Any) -> str:
    return str(value or "").strip()


def _flag_key(value: str) -> str:
    return "".join(char.lower() if char.isalnum() else "_" for char in str(value or "")).strip("_") or "field"


def _looks_generic(value: str) -> bool:
    text = _text(value)
    if not text:
        return True
    if len(text) < 28:
        return True
    generic_fragments = {
        "a mystery",
        "a story",
        "they argue",
        "she decides",
        "he decides",
        "she is upset",
        "feels bad",
        "stay or leave",
        "喜欢 mysteries",
        "喜欢故事",
        "一段故事",
    }
    lowered = text.lower()
    return any(fragment in lowered for fragment in generic_fragments)


def _has_pressure_turn(value: str) -> bool:
    lowered = _text(value).lower()
    markers = [
        "but",
        "yet",
        "cost",
        "risk",
        "lose",
        "force",
        "阻",
        "却",
        "但是",
        "代价",
        "失去",
        "逼",
        "风险",
        "冲突",
        "挫折",
        "灾难",
    ]
    return any(marker in lowered for marker in markers)


def _has_escalating_conflict(value: str) -> bool:
    text = _text(value)
    lowered = text.lower()
    if len(text) >= 60:
        return True
    markers = ["→", ";", "；", "first", "then", "again", "each", "stronger", "tries", "attempt", "resist", "阻", "更", "升级", "尝试"]
    return sum(1 for marker in markers if marker in lowered) >= 2


def _has_cost_or_reversal(value: str) -> bool:
    lowered = _text(value).lower()
    cost_markers = [
        "but",
        "yet",
        "cost",
        "lose",
        "worse",
        "expose",
        "implicate",
        "risk",
        "debt",
        "却",
        "但是",
        "代价",
        "失去",
        "暴露",
        "牵连",
        "更糟",
        "风险",
    ]
    return any(marker in lowered for marker in cost_markers)


def _has_true_choice_cost(value: str) -> bool:
    lowered = _text(value).lower()
    has_choice = any(
        marker in lowered
        for marker in [" or ", "或", "选a", "选b", "choice", "choose", "one choice", "the other", "一边", "另一边", "要么"]
    )
    has_cost = any(
        marker in lowered
        for marker in ["cost", "means", "lose", "burn", "harm", "expose", "代价", "意味着", "失去", "伤害", "暴露", "牺牲"]
    )
    return has_choice and has_cost


def _points_to_next_goal(value: str) -> bool:
    lowered = _text(value).lower()
    action_markers = [
        "go",
        "send",
        "call",
        "meet",
        "find",
        "ask",
        "steal",
        "confront",
        "next",
        "去",
        "发",
        "见",
        "找",
        "问",
        "偷",
        "对峙",
        "下一",
    ]
    return any(marker in lowered for marker in action_markers)


def _unique(values: Any) -> list[Any]:
    result = []
    seen = set()
    for value in values:
        marker = str(value)
        if not marker or marker in seen:
            continue
        seen.add(marker)
        result.append(value)
    return result


def _coerce_string_list(value: Any) -> list[str]:
    if isinstance(value, str):
        return [item.strip() for item in value.splitlines() if item.strip()]
    if not isinstance(value, list):
        return []
    return [str(item).strip() for item in value if str(item).strip()]


def _coerce_triage_status(value: Any) -> str:
    status = str(value or "").strip().lower()
    return status if status in {"pass", "maybe", "rewrite"} else ""


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


def _merge_dicts(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    merged = deepcopy(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _merge_dicts(merged[key], value)
        else:
            merged[key] = deepcopy(value)
    return merged
