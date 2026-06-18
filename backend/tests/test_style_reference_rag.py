"""立项 C — Strategy C(RAG)三粒度向量召回测试。

确定性单测(memory 向量后端):索引构建 / 切句 / scene 聚合 / 三粒度召回 /
确定性 rerank / C 策略注入(红线随注)/ 防漂移随上下文变化 / 优雅退化 / 清理 /
hit 命中。chroma 集成由 WSL 跑(本文件全部用 memory,Windows 安全)。
"""

from __future__ import annotations

from novel_system.services.style_reference import rag
from novel_system.services.style_reference.cleanup import purge_derived_data
from novel_system.services.style_reference.injection import InjectionService
from novel_system.services.style_reference.repository import StyleReferenceRepository
from novel_system.services.vector_store import InMemoryVectorStore

# 参考语料:刻意用区分度高的句子,memory 后端按字符集交集打分可确定性命中。
_PARAGRAPHS = [
    ("p0", "dialogue", "“你来了。”他轻声说，没有回头。"),
    ("p1", "description_env", "窗外的雨下个不停，青灰色的瓦檐滴着水珠。"),
    ("p2", "action", "她猛地推开门，冲进漆黑的走廊，脚步声急促。"),
    ("p3", "psychology", "他心里清楚，这一别也许就是永远，可终究说不出口。"),
    ("p4", "narration", "那一年的冬天格外漫长，雪落了又化，化了又落。"),
]


def _seed_book_with_paragraphs(
    session, *, seed: str, status: str = "active", cloud_policy: str = "allow_full_cloud"
):
    repo = StyleReferenceRepository(session)
    book_id = f"sr_book_{seed}"
    run_id = f"sr_run_{seed}"
    profile_id = f"sr_profile_{seed}"
    repo.create_book(
        book_id=book_id, title="t", source_kind="upload", cloud_policy=cloud_policy,
        text_checksum=f"chk_{seed}", total_chars=200, status="ready", stats_json={},
    )
    repo.create_run(run_id=run_id, book_id=book_id, status="done", phase="done")
    for i, (pid, ptype, text) in enumerate(_PARAGRAPHS):
        repo.create_paragraph(
            paragraph_id=f"{seed}_{pid}", book_id=book_id, paragraph_index=i,
            paragraph_type=ptype, start_offset=0, end_offset=len(text),
            text=text, char_count=len(text), classifier_confidence=0.9,
        )
    profile = repo.create_profile(
        profile_id=profile_id, book_id=book_id, run_id=run_id, title="t",
        status=status,
        profile_json={"narrative_summary": "雨夜离别的克制叙事", "style_features": ["短句"]},
        coverage_json={}, source_finding_ids_json=[],
    )
    session.flush()
    return profile


# --------------------------------------------------------------------------- 纯函数


def test_split_sentences_keeps_punctuation_and_filters_short():
    out = rag.split_sentences("他走了。她问：你来了吗？嗯。", min_chars=3)
    assert out == ["他走了。", "她问：你来了吗？"]  # "嗯。" 过短被滤


def test_aggregate_scenes_windows_by_chars():
    class P:
        def __init__(self, idx, t, txt):
            self.paragraph_index, self.paragraph_type, self.text = idx, t, txt

    paras = [P(0, "narration", "甲" * 400), P(1, "dialogue", "乙" * 400), P(2, "action", "丙" * 100)]
    blocks = rag.aggregate_scenes(paras, target_chars=600)
    # 前两段累加 800≥600 封一块;第三段单独成块(flush 尾部)
    assert len(blocks) == 2
    assert blocks[0]["paragraph_index"] == 0
    assert blocks[1]["paragraph_index"] == 2


# --------------------------------------------------------------------------- 构建 + 召回


def test_build_rag_index_creates_three_granularities(session):
    profile = _seed_book_with_paragraphs(session, seed="b1")
    store = InMemoryVectorStore()
    counts = rag.build_rag_index(session, profile, vector_store=store)
    assert counts["paragraph"] == len(_PARAGRAPHS)
    assert counts["sentence"] >= len(_PARAGRAPHS)  # 每段至少一句
    assert counts["scene"] >= 1
    for gran in rag.GRANULARITIES:
        assert store.collection_exists(rag.rag_collection_name(profile.profile_id, gran))


def test_retrieve_per_granularity_hits_relevant(session):
    profile = _seed_book_with_paragraphs(session, seed="b2")
    store = InMemoryVectorStore()
    rag.build_rag_index(session, profile, vector_store=store)
    retriever = rag.RagRetriever(session, vector_store=store)
    # query 取自 p2(动作段)文字 → 该段应在 paragraph 粒度命中 top1
    per = retriever.retrieve_per_granularity(profile.profile_id, "她推开门冲进漆黑的走廊")
    assert set(per.keys()) == set(rag.GRANULARITIES)
    para_texts = [s.text for s in per["paragraph"]]
    assert any("推开门" in t for t in para_texts)


def test_retrieve_merges_dedupes_and_caps(session):
    profile = _seed_book_with_paragraphs(session, seed="b3")
    store = InMemoryVectorStore()
    rag.build_rag_index(session, profile, vector_store=store)
    retriever = rag.RagRetriever(session, vector_store=store)
    out = retriever.retrieve(profile.profile_id, "雨夜走廊离别", inject_max=4)
    assert 0 < len(out) <= 4
    texts = [s.text for s in out]
    assert len(texts) == len(set(texts))  # 去重


def test_retrieve_empty_query_returns_nothing(session):
    profile = _seed_book_with_paragraphs(session, seed="b4")
    store = InMemoryVectorStore()
    rag.build_rag_index(session, profile, vector_store=store)
    retriever = rag.RagRetriever(session, vector_store=store)
    assert retriever.retrieve(profile.profile_id, "   ") == []


def test_retrieve_deterministic(session):
    profile = _seed_book_with_paragraphs(session, seed="b5")
    store = InMemoryVectorStore()
    rag.build_rag_index(session, profile, vector_store=store)
    retriever = rag.RagRetriever(session, vector_store=store)
    q = "推开门冲进走廊"
    first = [s.snippet_id for s in retriever.retrieve(profile.profile_id, q)]
    second = [s.snippet_id for s in retriever.retrieve(profile.profile_id, q)]
    assert first == second


# --------------------------------------------------------------------------- 渲染


def test_render_rag_block_labels_and_red_line_contract(session):
    profile = _seed_book_with_paragraphs(session, seed="b6")
    store = InMemoryVectorStore()
    rag.build_rag_index(session, profile, vector_store=store)
    retriever = rag.RagRetriever(session, vector_store=store)
    snippets = retriever.retrieve(profile.profile_id, "雨夜推开门离别")
    block = rag.render_rag_block(snippets)
    assert block.startswith("[风格检索样例]")
    assert "严禁照抄" in block


def test_render_rag_block_empty_on_no_snippets():
    assert rag.render_rag_block([]) == ""


# --------------------------------------------------------------------------- 删除/清理


def test_delete_rag_index_removes_collections(session):
    profile = _seed_book_with_paragraphs(session, seed="b7")
    store = InMemoryVectorStore()
    rag.build_rag_index(session, profile, vector_store=store)
    rag.delete_rag_index(profile.profile_id, vector_store=store)
    for gran in rag.GRANULARITIES:
        assert not store.collection_exists(rag.rag_collection_name(profile.profile_id, gran))


# --------------------------------------------------------------------------- C 策略注入(env memory 后端)


def _bind_c_strategy(session, profile, *, project_id):
    repo = StyleReferenceRepository(session)
    repo.create_binding(
        binding_id=f"bind_{profile.profile_id}", profile_id=profile.profile_id,
        scope="project", scope_ref_id=project_id,
        task_type="scene_generation", strategy="C", config_json={}, status="active",
    )
    session.flush()


def test_c_strategy_injects_rag_block_with_red_line(session):
    # 用 env memory 后端(conftest 设 NOVEL_SYSTEM_VECTOR_BACKEND=memory),
    # 与 InjectionService._render_rag 内部 get_vector_store() 一致。
    profile = _seed_book_with_paragraphs(session, seed="cinj")
    rag.build_rag_index(session, profile)  # 不传 store → 写入 env 后端
    _bind_c_strategy(session, profile, project_id="proj_cinj")
    svc = InjectionService(session)
    svc.context_text = "她推开门冲进漆黑的走廊，脚步声急促"
    frags = svc.fragments_for("proj_cinj", "scene_generation")
    assert frags.rag_block  # C 真召回非空
    prefix = frags.to_system_prompt_prefix()
    assert "风格检索样例" in prefix
    assert "严格禁止" in prefix or "严禁" in prefix  # 红线段随注


def test_c_strategy_drift_changes_snippets_with_context(session):
    profile = _seed_book_with_paragraphs(session, seed="cdrift")
    rag.build_rag_index(session, profile)
    _bind_c_strategy(session, profile, project_id="proj_cdrift")
    svc = InjectionService(session)
    svc.context_text = "窗外的雨下个不停，青灰色的瓦檐"  # 偏 description_env
    block_env = svc.fragments_for("proj_cdrift", "scene_generation").rag_block
    svc2 = InjectionService(session)
    svc2.context_text = "她猛地推开门，冲进漆黑的走廊"   # 偏 action
    block_act = svc2.fragments_for("proj_cdrift", "scene_generation").rag_block
    assert block_env and block_act
    assert block_env != block_act  # 召回随上下文变化(防漂移真实生效)


def test_c_strategy_degrades_gracefully_without_index(session):
    # 不建索引 → C 无 rag_block,但 positive/forbidden 仍在,不报错
    profile = _seed_book_with_paragraphs(session, seed="cdeg")
    _bind_c_strategy(session, profile, project_id="proj_cdeg")
    svc = InjectionService(session)
    svc.context_text = "任意上下文"
    frags = svc.fragments_for("proj_cdeg", "scene_generation")
    assert frags.rag_block == ""
    assert frags.positive_block  # 仍注入抽象正向特征


def test_purge_derived_data_deletes_rag_index(session):
    profile = _seed_book_with_paragraphs(session, seed="cpurge")
    rag.build_rag_index(session, profile)
    from novel_system.services.vector_store import get_vector_store

    store = get_vector_store()
    assert store.collection_exists(rag.rag_collection_name(profile.profile_id, "paragraph"))
    purge_derived_data(session, "sr_book_cpurge")
    assert not store.collection_exists(rag.rag_collection_name(profile.profile_id, "paragraph"))


# --------------------------------------------------------------------------- 审查补强:退化路径 / 红线契约 / 隐私


def test_c_strategy_local_only_skips_rag(session):
    # 附录 B — local_only 的书:RAG 原文片段不得送往云端 LLM,C 跳过 RAG;
    # 但抽象正向特征(positive)仍注入。
    profile = _seed_book_with_paragraphs(session, seed="clocal", cloud_policy="local_only")
    rag.build_rag_index(session, profile)
    _bind_c_strategy(session, profile, project_id="proj_clocal")
    svc = InjectionService(session)
    svc.context_text = "她推开门冲进漆黑的走廊"
    frags = svc.fragments_for("proj_clocal", "scene_generation")
    assert frags.rag_block == ""       # local_only:原文不注入
    assert frags.positive_block        # 抽象特征仍注入


def test_c_strategy_inactive_profile_no_injection(session):
    # profile 非 active(draft)→ binding 解析返回空 fragments(退化路径)
    profile = _seed_book_with_paragraphs(session, seed="cinact", status="draft")
    rag.build_rag_index(session, profile)
    _bind_c_strategy(session, profile, project_id="proj_cinact")
    svc = InjectionService(session)
    svc.context_text = "她推开门"
    frags = svc.fragments_for("proj_cinact", "scene_generation")
    assert frags.rag_block == "" and frags.positive_block == ""
    assert frags.to_system_prompt_prefix() == ""


def test_c_strategy_degrades_when_vector_store_unavailable(session, monkeypatch):
    # 向量后端不可用(_resolve_store 返 None,如 Windows 原生 chroma)→ rag_block 空,
    # 但 positive 仍注入,不报错。
    profile = _seed_book_with_paragraphs(session, seed="cunavail")
    rag.build_rag_index(session, profile)
    _bind_c_strategy(session, profile, project_id="proj_cunavail")
    monkeypatch.setattr(rag, "_resolve_store", lambda vs: None)
    svc = InjectionService(session)
    svc.context_text = "她推开门冲进漆黑的走廊"
    frags = svc.fragments_for("proj_cunavail", "scene_generation")
    assert frags.rag_block == ""
    assert frags.positive_block


def test_anti_plagiarism_attached_when_rag_present(session):
    # 红线契约:rag_block 非空 ⟹ anti_plagiarism_block 非空(直接断言字段,非仅 prefix 子串)
    profile = _seed_book_with_paragraphs(session, seed="credline")
    rag.build_rag_index(session, profile)
    _bind_c_strategy(session, profile, project_id="proj_credline")
    svc = InjectionService(session)
    svc.context_text = "她推开门冲进漆黑的走廊"
    frags = svc.fragments_for("proj_credline", "scene_generation")
    assert frags.rag_block
    assert frags.anti_plagiarism_block
    # 拼装顺序:红线段在所有风格块之后(prefix 尾部)
    prefix = frags.to_system_prompt_prefix()
    assert prefix.index("风格检索样例") < prefix.index("严格禁止")


def test_anti_plagiarism_omitted_when_all_blocks_empty(session):
    # 所有风格块全空 ⟹ 红线段不输出,整体 no-op
    repo = StyleReferenceRepository(session)
    repo.create_book(
        book_id="sr_book_empty", title="t", source_kind="upload",
        cloud_policy="allow_full_cloud", text_checksum="chk_empty",
        total_chars=0, status="ready", stats_json={},
    )
    repo.create_run(run_id="sr_run_empty", book_id="sr_book_empty", status="done", phase="done")
    profile = repo.create_profile(
        profile_id="sr_profile_empty", book_id="sr_book_empty", run_id="sr_run_empty",
        title="t", status="active", profile_json={}, coverage_json={}, source_finding_ids_json=[],
    )
    session.flush()
    _bind_c_strategy(session, profile, project_id="proj_empty")
    svc = InjectionService(session)
    frags = svc.fragments_for("proj_empty", "scene_generation")
    assert frags.rag_block == "" and frags.positive_block == "" and frags.anti_plagiarism_block == ""
    assert frags.to_system_prompt_prefix() == ""


def test_drift_retrieve_snippet_sets_differ_by_context(session):
    # 强化防漂移断言:不同 context 召回的 snippet **id 集合**确实不同(非仅字符串不等)
    profile = _seed_book_with_paragraphs(session, seed="driftids")
    store = InMemoryVectorStore()
    rag.build_rag_index(session, profile, vector_store=store)
    r = rag.RagRetriever(session, vector_store=store)
    env_ids = {s.snippet_id for s in r.retrieve(profile.profile_id, "窗外的雨青灰色瓦檐滴水珠")}
    act_ids = {s.snippet_id for s in r.retrieve(profile.profile_id, "她推开门冲进漆黑走廊脚步急促")}
    assert env_ids and act_ids
    assert env_ids != act_ids


def test_retrieve_inject_max_zero_returns_empty(session):
    profile = _seed_book_with_paragraphs(session, seed="cap0")
    store = InMemoryVectorStore()
    rag.build_rag_index(session, profile, vector_store=store)
    r = rag.RagRetriever(session, vector_store=store)
    assert r.retrieve(profile.profile_id, "推开门", inject_max=0) == []
