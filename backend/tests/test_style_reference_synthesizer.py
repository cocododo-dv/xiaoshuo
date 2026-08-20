"""ProfileSynthesizer 单测(PR-4)。

参见 plans/style-reference-v1-1-fancy-shannon.md §"测试策略"。
"""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from novel_system.db.session import SessionLocal
from novel_system.services.prompt_builder import PromptTemplate, load_prompt_templates
from novel_system.services.style_reference.errors import LLMRequiredError
from novel_system.services.style_reference.ingest import IngestService
from novel_system.services.style_reference.profile_synthesizer import (
    ProfileSynthesizer,
    SynthesizeError,
    _build_sample_quotes_payload,
    _estimate_synthesis_input_tokens,
    _fit_synthesis_payload_to_budget,
)
from novel_system.services.style_reference.repository import StyleReferenceRepository
from tests.accounted_llm_fakes import AccountedGenerateMixin


SAMPLE_TEXT = """这是一段叙述,介绍清晨场景。

他说:"今天天气真好。"

我心里想着昨日的对话。

记得那年她还在的时候。

雪从天上飘下来。
"""


def test_synthesis_prompt_does_not_anchor_every_profile_to_one_mood() -> None:
    template = load_prompt_templates()["style_ref_synthesize_profile"]

    assert template.version == "2026-08-20.v7"
    assert "冷峻克制的市井白描" not in template.system_prompt
    assert "只有在 finding_summaries 中存在直接对应的 theme finding" in template.system_prompt
    assert "不得扩张成“大量、密集、高频、总是、连续”" in template.system_prompt
    assert "只聚合 payload 实际存在的子维度" in template.task_prompt


def _ingest_with_finding(book_seed: str) -> tuple[str, str]:
    """建一本书 + 一个 run + 若干 finding(模拟 PR-3 抽取后的状态)。"""
    with SessionLocal() as session:
        ingest = IngestService(session, llm_enabled=False)
        result = ingest.ingest_upload(
            raw_bytes=SAMPLE_TEXT.encode("utf-8"),
            file_name=f"book_{book_seed}.txt",
            title="测试书",
            author_label="作者",
            cloud_policy="segments_only",
            rights_declaration={"analysis_rights": True, "send_rights": True},
        )
        book_id = result.book.book_id
        repo = StyleReferenceRepository(session)
        run_id = f"sr_run_{book_seed}"
        repo.create_run(
            run_id=run_id, book_id=book_id, status="done", phase="done"
        )
        # 各 sub_dim 加 1 obs + 1 forbid
        extraction_id = f"sr_ext_{book_seed}"
        repo.create_extraction(
            extraction_id=extraction_id,
            book_id=book_id,
            run_id=run_id,
            layer="language",
            sub_dimension="language.rhetoric",
            raw_payload_json={},
            status="done",
            validation_errors_json=[],
            purpose="extract",
        )
        for kind in ("observation", "forbidden_pattern"):
            repo.create_finding(
                finding_id=f"sr_find_{book_seed}_{kind}",
                book_id=book_id,
                run_id=run_id,
                extraction_id=extraction_id,
                sub_dimension="language.rhetoric",
                finding_kind=kind,
                statement=f"测试 {kind} 描述",
                confidence="high",
                status="pending",
            )
        # 1 个 quote(经 evidence 挂到 observation finding 上——2026-07 起
        # synthesizer 的 quotes 为 run-scoped,未关联 evidence 的引文不进聚合)
        repo.create_quote(
            quote_id=f"sr_quote_{book_seed}",
            book_id=book_id,
            paragraph_id=None,
            span_start=0,
            span_end=20,
            quote_text="他低头看着脚下的路",
            illustrates_dims=["language.rhetoric"],
            extracted_features={"paragraph_type": "narration"},
        )
        repo.create_evidence(
            evidence_id=f"sr_ev_{book_seed}",
            finding_id=f"sr_find_{book_seed}_observation",
            quote_id=f"sr_quote_{book_seed}",
            anchor_kind="paragraph_quote",
            is_synthetic=0,
        )
        session.commit()
        return book_id, run_id


def _fake_llm_with_response(response_dict: dict):
    class _Resp:
        structured_output = response_dict
        text = json.dumps(response_dict, ensure_ascii=False)
        usage = {}
        finish_reason = "stop"
        provider = "fake"
        model = "fake"
        response_format = "json_object"
        request_id = None
        raw_response = {}

    class _Client(AccountedGenerateMixin):
        def generate(self, request):  # noqa: ANN001
            return _Resp()

    return _Client()


def _fake_llm_with_responses(response_dicts: list[dict]):
    class _Client(AccountedGenerateMixin):
        def __init__(self) -> None:
            self.responses = list(response_dicts)
            self.requests = []

        def generate(self, request):  # noqa: ANN001
            self.requests.append(request)
            response_dict = self.responses.pop(0)
            return SimpleNamespace(
                structured_output=response_dict,
                text=json.dumps(response_dict, ensure_ascii=False),
                usage={},
                finish_reason="stop",
                provider="fake",
                model="fake",
                response_format="json_object",
                request_id=None,
                raw_response={},
            )

    return _Client()


# ---------------------------------------------------------------------------
# Cases
# ---------------------------------------------------------------------------


def test_sample_quote_is_selected_from_the_findings_own_evidence() -> None:
    """同一维度有多条引文时，不能把别的 finding 的证据错配过来。"""
    finding = SimpleNamespace(
        finding_id="finding_target",
        sub_dimension="language.rhetoric",
        finding_kind="observation",
        statement="目标观察",
    )
    wrong_quote = SimpleNamespace(
        quote_id="quote_wrong",
        quote_text="同维度但属于另一条观察的引文",
        illustrates_dims=["language.rhetoric"],
    )
    right_quote = SimpleNamespace(
        quote_id="quote_right",
        quote_text="目标观察自己的证据引文",
        illustrates_dims=["language.rhetoric"],
    )
    evidence = SimpleNamespace(
        evidence_id="evidence_target",
        finding_id="finding_target",
        quote_id="quote_right",
        anchor_kind="paragraph_quote",
        is_synthetic=0,
        created_at="2026-01-01T00:00:00Z",
    )

    payload = _build_sample_quotes_payload(
        [finding],
        [wrong_quote, right_quote],
        [evidence],
    )

    assert payload[0]["representative_quote"] == "目标观察自己的证据引文"


def test_synthesize_llm_required_when_disabled() -> None:
    book_id, run_id = _ingest_with_finding("disabled")
    with SessionLocal() as session:
        synth = ProfileSynthesizer(session, llm_client=None, llm_enabled=False)
        with pytest.raises(LLMRequiredError):
            synth.synthesize(book_id, run_id)


def test_synthesize_happy_path() -> None:
    book_id, run_id = _ingest_with_finding("happy")
    client = _fake_llm_with_response(
        {
            "profile_title": "鲁迅风格 v1",
            "narrative_summary": "短句+反讽+冷静叙述,克制情感",
            "style_features": ["善用短句", "反讽点缀", "白描+留白"],
            "narrative_patterns": ["人物对话引出冲突", "环境暗示情绪"],
            "banned_replication_rules": ["禁止堆砌华丽形容词"],
            "calibration_guidance": ["每场景至少一处白描"],
        }
    )
    with SessionLocal() as session:
        synth = ProfileSynthesizer(session, llm_client=client, llm_enabled=True)
        profile = synth.synthesize(book_id, run_id)
        session.commit()

    assert profile.title == "鲁迅风格 v1"
    assert profile.status == "draft"
    pj = profile.profile_json
    # profile_json 4 类应用建议 + narrative_summary + metrics_baseline + scene_samples_index + sub_dimensions
    assert pj["narrative_summary"].startswith("量化基线")
    assert pj["qualitative_summary"] == "短句+反讽+冷静叙述,克制情感"
    assert "metrics_baseline" in pj
    assert "avg_sentence_length" in pj["metrics_baseline"]
    assert "paragraph_mean_chars" in pj["metrics_baseline"]
    assert "paragraphs_per_1k" in pj["metrics_baseline"]
    assert "scene_samples_index" in pj
    assert "sub_dimensions" in pj
    assert pj["style_features"] == ["善用短句", "反讽点缀", "白描+留白"]
    assert pj["banned_replication_rules"] == ["禁止堆砌华丽形容词"]
    # source_finding_ids_json 含所有 finding
    assert len(profile.source_finding_ids_json) == 2


def test_synthesize_filters_reference_prose_from_generation_profile_fields() -> None:
    book_id, run_id = _ingest_with_finding("source_filter")
    copied = "这是一段叙述,介绍清晨场景。"
    with SessionLocal() as session:
        repo = StyleReferenceRepository(session)
        forbidden = repo.get_finding("sr_find_source_filter_forbidden_pattern")
        forbidden.statement = copied
        session.commit()

    client = _fake_llm_with_response(
        {
            "profile_title": "安全画像",
            "narrative_summary": copied,
            "style_features": [copied, "用动作承担解释，减少抽象判断"],
            "narrative_patterns": [copied, "转折前先释放可见线索"],
            "banned_replication_rules": [copied, "不复用专名和独特意象"],
            "calibration_guidance": [copied, "若解释过多就改回动作"],
        }
    )
    with SessionLocal() as session:
        profile = ProfileSynthesizer(
            session,
            llm_client=client,
            llm_enabled=True,
        ).synthesize(book_id, run_id)
        session.commit()

    payload = profile.profile_json
    serialized_generation_fields = json.dumps(
        {
            "summary": payload["narrative_summary"],
            "features": payload["style_features"],
            "patterns": payload["narrative_patterns"],
            "rules": payload["banned_replication_rules"],
            "calibration": payload["calibration_guidance"],
            "forbidden": payload["generation_safe_forbidden_findings"],
        },
        ensure_ascii=False,
    )
    assert copied not in serialized_generation_fields
    assert payload["style_features"] == ["用动作承担解释，减少抽象判断"]
    assert payload["narrative_patterns"] == ["转折前先释放可见线索"]
    assert payload["source_overlap_filter"]["summary_replaced"] is True
    assert payload["source_overlap_filter"]["dropped_forbidden_finding_count"] == 1


def test_synthesize_pydantic_validation_failure() -> None:
    book_id, run_id = _ingest_with_finding("pyderr")
    # LLM 返回缺 narrative_summary,Pydantic min_length=1 不通过
    client = _fake_llm_with_response(
        {
            "profile_title": "x",
            "narrative_summary": "",  # 违反 min_length=1
            "style_features": [],
            "narrative_patterns": [],
            "banned_replication_rules": [],
        }
    )
    with SessionLocal() as session:
        synth = ProfileSynthesizer(session, llm_client=client, llm_enabled=True)
        with pytest.raises(SynthesizeError):
            synth.synthesize(book_id, run_id)


def test_synthesize_retries_one_invalid_empty_profile_then_succeeds() -> None:
    book_id, run_id = _ingest_with_finding("retryempty")
    client = _fake_llm_with_responses(
        [
            {
                "profile_title": "",
                "narrative_summary": "",
                "style_features": [],
                "narrative_patterns": [],
                "banned_replication_rules": [],
                "calibration_guidance": [],
            },
            {
                "profile_title": "克制叙事",
                "narrative_summary": "以动作和节奏推进信息，减少直接判断。",
                "style_features": ["用短句承接动作变化"],
                "narrative_patterns": ["转折前先释放可见线索"],
                "banned_replication_rules": [],
                "calibration_guidance": ["若解释过多，改回人物动作"],
            },
        ]
    )

    with SessionLocal() as session:
        profile = ProfileSynthesizer(
            session,
            llm_client=client,
            llm_enabled=True,
        ).synthesize(book_id, run_id)
        session.commit()

    assert len(client.requests) == 2
    assert "validation_retry" in client.requests[1].messages[-1]["content"]
    assert profile.profile_json["synthesis_attempts"]["attempt_count"] == 2
    assert profile.profile_json["synthesis_attempts"]["retried"] is True
    assert (
        profile.profile_json["synthesis_attempts"]["first_failure"]["reason_code"]
        == "invalid_or_empty_profile"
    )


def test_synthesize_retries_profile_with_broken_unicode_then_succeeds() -> None:
    book_id, run_id = _ingest_with_finding("retryunicode")
    client = _fake_llm_with_responses(
        [
            {
                "profile_title": "损坏画像",
                "narrative_summary": "减少文言词造成的阅读隔�0。",
                "style_features": ["使用具体动作"],
                "narrative_patterns": ["转折前先释放线索"],
                "banned_replication_rules": [],
                "calibration_guidance": [],
            },
            {
                "profile_title": "有效画像",
                "narrative_summary": "用具体动作推进信息，语域保持清楚。",
                "style_features": ["使用具体动作"],
                "narrative_patterns": ["转折前先释放线索"],
                "banned_replication_rules": [],
                "calibration_guidance": ["偏离时减少解释"],
            },
        ]
    )

    with SessionLocal() as session:
        profile = ProfileSynthesizer(
            session,
            llm_client=client,
            llm_enabled=True,
        ).synthesize(book_id, run_id)
        session.commit()

    attempts = profile.profile_json["synthesis_attempts"]
    assert len(client.requests) == 2
    assert attempts["attempt_count"] == 2
    assert attempts["first_failure"]["reason_code"] == "profile_text_integrity_invalid"
    assert attempts["first_failure"]["violations"] == [
        "narrative_summary:replacement_character"
    ]
    assert "�" not in json.dumps(profile.profile_json, ensure_ascii=False)


def test_synthesis_payload_budget_keeps_sub_dimension_coverage() -> None:
    dimensions = [f"layer.dimension_{index:02d}" for index in range(16)]
    rows = [
        {
            "sub_dimension": dimension,
            "finding_kind": kind,
            "statement": f"{dimension} 的可执行风格机制" + "具体动作节奏" * 12,
            "confidence": "high" if item_index == 0 else "medium",
            "status": "approved" if item_index == 0 else "pending",
            "evidence_count": 2,
        }
        for dimension in dimensions
        for kind in ("observation", "forbidden_pattern")
        for item_index in range(2)
    ]
    metrics = {
        f"metric_{index:02d}": {"mean": float(index), "std": 0.1}
        for index in range(40)
    }
    template = PromptTemplate(
        name="style_ref_synthesize_profile",
        version="test",
        input_token_budget=5000,
        system_prompt="聚合经过验证的抽象风格机制。",
        task_prompt="覆盖各个子维度后输出结构化画像。",
        structured_schema={
            "type": "object",
            "additionalProperties": False,
            "required": ["profile_title"],
            "properties": {"profile_title": {"type": "string"}},
        },
    )
    payload = {
        "book_title": "测试书",
        "sub_dimensions": {dimension: {} for dimension in dimensions},
        "metrics_baseline": metrics,
        "finding_summaries": rows,
    }

    fitted, audit = _fit_synthesis_payload_to_budget(payload, template)

    assert _estimate_synthesis_input_tokens(template, fitted) <= 5000
    assert audit["estimated_after"] <= audit["target_input_tokens"]
    assert audit["finding_count_after"] < audit["finding_count_before"]
    assert set(audit["covered_sub_dimensions"]) == set(dimensions)
    assert all(audit["selected_by_dimension"][dimension] >= 1 for dimension in dimensions)
    assert all(
        {"confidence", "status", "evidence_count"}.issubset(row)
        for row in fitted["finding_summaries"]
    )
    selected_counts = list(audit["selected_by_dimension"].values())
    assert max(selected_counts) - min(selected_counts) <= 1


def test_synthesize_rejects_empty_style_features() -> None:
    """style_features / narrative_patterns 是注入素材,为空的 Profile 必须硬失败。

    banned_replication_rules / calibration_guidance 保持宽松(合法可为空)。
    """
    book_id, run_id = _ingest_with_finding("emptyfeat")
    client = _fake_llm_with_response(
        {
            "profile_title": "t",
            "narrative_summary": "其余字段全部合法的画像简述",
            "style_features": [],  # 违反 min_length=1
            "narrative_patterns": ["p"],
            "banned_replication_rules": [],
            "calibration_guidance": [],
        }
    )
    with SessionLocal() as session:
        synth = ProfileSynthesizer(session, llm_client=client, llm_enabled=True)
        with pytest.raises(SynthesizeError):
            synth.synthesize(book_id, run_id)


def test_synthesize_excludes_rejected_findings() -> None:
    """PR-23 — rejected finding 不进 LLM 聚合 payload,也不进 source_finding_ids_json。"""
    book_id, run_id = _ingest_with_finding("rej")
    rejected_statement = "被驳回的观察描述不应出现在聚合里"
    with SessionLocal() as session:
        repo = StyleReferenceRepository(session)
        repo.create_finding(
            finding_id="sr_find_rej_rejected",
            book_id=book_id,
            run_id=run_id,
            extraction_id="sr_ext_rej",
            sub_dimension="language.rhetoric",
            finding_kind="observation",
            statement=rejected_statement,
            confidence="high",
            status="rejected",
        )
        session.commit()

    captured: list[str] = []
    response_dict = {
        "profile_title": "t",
        "narrative_summary": "s",
        "style_features": ["f"],
        "narrative_patterns": ["p"],
        "banned_replication_rules": ["b"],
    }

    class _Resp:
        structured_output = response_dict
        text = json.dumps(response_dict, ensure_ascii=False)
        usage = {}
        finish_reason = "stop"
        provider = "fake"
        model = "fake"
        response_format = "json_object"
        request_id = None
        raw_response = {}

    class _CapturingClient(AccountedGenerateMixin):
        def generate(self, request):  # noqa: ANN001
            captured.append(request.messages[-1]["content"])
            return _Resp()

    with SessionLocal() as session:
        synth = ProfileSynthesizer(session, llm_client=_CapturingClient(), llm_enabled=True)
        profile = synth.synthesize(book_id, run_id)
        session.commit()

    # rejected statement 不进 finding_summaries；画像聚合也不再重复发送证据原文。
    assert captured and rejected_statement not in captured[0]
    assert "finding_summaries" in captured[0]
    assert "他低头看着脚下的路" not in captured[0]
    # finding_id 不在 source_finding_ids_json;原 2 条 pending finding 保留
    assert "sr_find_rej_rejected" not in profile.source_finding_ids_json
    assert len(profile.source_finding_ids_json) == 2


def test_synthesize_scene_samples_index_buckets_by_paragraph_type() -> None:
    """scene_samples_index 按段落表实测类型分桶;合成反例/负空间/无段落锚点不入索引。

    2026-07 起 quotes 为 run-scoped(仅本 run findings 经 evidence 关联的引文),
    故本用例把每条 quote 经 evidence 挂到 run 的 finding 上——与真实抽取管线一致
    (extractor 落库时 quote 总是伴随 evidence 行)。
    """
    book_id, run_id = _ingest_with_finding("buckets")
    with SessionLocal() as session:
        repo = StyleReferenceRepository(session)
        paras = repo.list_paragraphs(book_id)
        assert len(paras) >= 2
        p_dlg, p_env = paras[0], paras[1]
        p_dlg.paragraph_type = "dialogue"
        p_env.paragraph_type = "description_env"
        obs_finding = f"sr_find_buckets_observation"
        fp_finding = f"sr_find_buckets_forbidden_pattern"
        # 真实原文引文(带 anchor_kind)→ 按段落表类型分桶
        repo.create_quote(
            quote_id="sr_quote_dlg_buckets",
            book_id=book_id,
            paragraph_id=p_dlg.paragraph_id,
            span_start=0,
            span_end=10,
            quote_text="对话引文",
            illustrates_dims=[],
            extracted_features={"anchor_kind": "paragraph_quote"},
        )
        repo.create_evidence(
            evidence_id="sr_ev_dlg_buckets",
            finding_id=obs_finding,
            quote_id="sr_quote_dlg_buckets",
            anchor_kind="paragraph_quote",
            is_synthetic=0,
        )
        # legacy 行(无 anchor_kind)→ 默认按 paragraph_quote 处理,仍按段落表分桶
        repo.create_quote(
            quote_id="sr_quote_env_buckets",
            book_id=book_id,
            paragraph_id=p_env.paragraph_id,
            span_start=0,
            span_end=10,
            quote_text="环境引文",
            illustrates_dims=[],
            extracted_features={},
        )
        repo.create_evidence(
            evidence_id="sr_ev_env_buckets",
            finding_id=obs_finding,
            quote_id="sr_quote_env_buckets",
            anchor_kind="paragraph_quote",
            is_synthetic=0,
        )
        # 合成反例:与原作风格相悖,不能作为风格样例进 few-shot 索引
        repo.create_quote(
            quote_id="sr_quote_syn_buckets",
            book_id=book_id,
            paragraph_id=None,
            span_start=0,
            span_end=10,
            quote_text="(反例)天是那样蓝",
            illustrates_dims=[],
            extracted_features={"anchor_kind": "counter_example"},
        )
        repo.create_evidence(
            evidence_id="sr_ev_syn_buckets",
            finding_id=fp_finding,
            quote_id="sr_quote_syn_buckets",
            anchor_kind="counter_example",
            is_synthetic=1,
        )
        session.commit()

    client = _fake_llm_with_response(
        {
            "profile_title": "t",
            "narrative_summary": "s",
            "style_features": ["f"],
            "narrative_patterns": ["p"],
            "banned_replication_rules": ["b"],
        }
    )
    with SessionLocal() as session:
        synth = ProfileSynthesizer(session, llm_client=client, llm_enabled=True)
        profile = synth.synthesize(book_id, run_id)
        session.commit()
    index = profile.profile_json["scene_samples_index"]
    assert "sr_quote_dlg_buckets" in index.get("dialogue", [])
    assert "sr_quote_env_buckets" in index.get("description_env", [])
    flat = [qid for ids in index.values() for qid in ids]
    assert "sr_quote_syn_buckets" not in flat
    # helper 里 paragraph_id=None 的旧式 quote 同样不入索引
    assert "sr_quote_buckets" not in flat
