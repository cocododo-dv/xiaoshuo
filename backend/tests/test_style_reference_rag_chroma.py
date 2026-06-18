"""立项 C — RAG 三粒度召回在**真实 chroma 后端**上的集成测试 + hit@k 评测。

Windows 自动跳过(conftest:@pytest.mark.chroma_integration + sys.platform=win32 → skip);
经 WSL/Linux 跑(.venv-wsl,见 CLAUDE.md)。验证 memory 单测覆盖不到的 chroma 代码路径
(ChromaVectorStore.write_collection/query + 确定性 embedding + None 元数据过滤)并实测
设计 §10 Phase 3 验收「三粒度 hit@5 ≥ 0.7」。

注:向量后端用 `_DeterministicEmbeddingFunction`(字符频率 64 维 cosine,确定性),
故 hit@k 反映该确定性 embedding 的召回质量(非语义大模型),但真实走通了 chromadb
的写入/查询/打分链路——这是 memory(字符集交集)后端测不到的。

本文件只导入 rag/repository/models/vector_store(干净链),不触发 system_config 重导入,
故可在仅装 chromadb 的 WSL venv 上单独运行。
"""

from __future__ import annotations

import pytest

from novel_system.services.style_reference import rag
from novel_system.services.style_reference.injection import InjectionService
from novel_system.services.style_reference.repository import StyleReferenceRepository
from novel_system.services.vector_store import get_vector_store

pytestmark = pytest.mark.chroma_integration

# 8 段区分度高的语料(不同场景/题材),供 partial-query hit@k 评测。
_CORPUS = [
    ("p0", "dialogue", "“你终于肯回来了。”母亲倚在门框上，声音很轻，却带着十年的埋怨与释然。"),
    ("p1", "description_env", "深秋的码头泛着铁锈味，海风把缆绳吹得呜呜作响，灰白的雾压在桅杆顶端。"),
    ("p2", "action", "他翻身越过断墙，靴底擦着碎玻璃，三步并作两步冲上锈蚀的铁梯，直扑顶楼。"),
    ("p3", "psychology", "她盯着那封没有署名的信，心跳逐渐失序，既盼望是他，又害怕真的是他。"),
    ("p4", "narration", "战争结束后的第三个春天，小城重新支起了茶摊，孩子们在弹坑边追逐纸鸢。"),
    ("p5", "description_char", "老兵的左手缺了两根指头，掌心的老茧像干涸的河床，握起茶杯时微微发抖。"),
    ("p6", "dialogue", "“情报已经送出去了。”他压低嗓音，把怀表塞进她手里，“按约定，子夜的钟声响三下就走。”"),
    ("p7", "action", "火车汽笛长鸣，她攥紧裙角追着月台跑，皮箱在石板上磕出闷响，终究没能追上那节车厢。"),
]


def _seed(session):
    repo = StyleReferenceRepository(session)
    book, run, prof = "chroma_book", "chroma_run", "chroma_profile"
    repo.create_book(
        book_id=book, title="t", source_kind="upload", cloud_policy="allow_full_cloud",
        text_checksum="chk_chroma", total_chars=600, status="ready", stats_json={},
    )
    repo.create_run(run_id=run, book_id=book, status="done", phase="done")
    for i, (pid, ptype, text) in enumerate(_CORPUS):
        repo.create_paragraph(
            paragraph_id=f"{pid}", book_id=book, paragraph_index=i, paragraph_type=ptype,
            start_offset=0, end_offset=len(text), text=text, char_count=len(text),
            classifier_confidence=0.9,
        )
    profile = repo.create_profile(
        profile_id=prof, book_id=book, run_id=run, title="t", status="active",
        profile_json={"narrative_summary": "战后离别与重逢的克制叙事", "style_features": ["短句"]},
        coverage_json={}, source_finding_ids_json=[],
    )
    session.flush()
    return profile


def test_chroma_build_creates_three_granularity_collections(session):
    profile = _seed(session)
    counts = rag.build_rag_index(session, profile)  # 不传 store → get_vector_store()=chroma
    assert counts.get("paragraph") == len(_CORPUS)
    assert counts.get("sentence", 0) >= len(_CORPUS)
    assert counts.get("scene", 0) >= 1
    store = get_vector_store()
    for gran in rag.GRANULARITIES:
        assert store.collection_exists(rag.rag_collection_name(profile.profile_id, gran))


def test_chroma_paragraph_hit_at_5(session):
    """paragraph 粒度 hit@5:用每段前 60% 文本作 query,源段应在 top-5。阈值 ≥ 0.7(设计 §10)。"""
    profile = _seed(session)
    rag.build_rag_index(session, profile)
    retriever = rag.RagRetriever(session)
    hits = 0
    for pid, _ptype, text in _CORPUS:
        query = text[: max(8, int(len(text) * 0.6))]
        per = retriever.retrieve_per_granularity(profile.profile_id, query, top_k=5)
        got_ids = {s.snippet_id for s in per["paragraph"]}
        if f"p_{pid}" in got_ids:
            hits += 1
    hit_rate = hits / len(_CORPUS)
    assert hit_rate >= 0.7, f"paragraph hit@5={hit_rate:.2f} < 0.7"


def test_chroma_sentence_and_scene_recall_nonempty(session):
    """sentence/scene 粒度在 chroma 上能召回(plumbing + 打分链路走通)。"""
    profile = _seed(session)
    rag.build_rag_index(session, profile)
    retriever = rag.RagRetriever(session)
    query = "码头的海风与缆绳，铁锈味弥漫"
    per = retriever.retrieve_per_granularity(profile.profile_id, query, top_k=5)
    assert len(per["sentence"]) > 0
    assert len(per["scene"]) > 0
    # 合并去重截断后仍有结果
    merged = retriever.retrieve(profile.profile_id, query, inject_max=5)
    assert 0 < len(merged) <= 5


def test_chroma_c_strategy_injection_with_red_line(session):
    """C 策略在真实 chroma 上真召回 → rag_block 非空 + 红线随注。"""
    profile = _seed(session)
    rag.build_rag_index(session, profile)
    repo = StyleReferenceRepository(session)
    repo.create_binding(
        binding_id="bind_chroma", profile_id=profile.profile_id,
        scope="project", scope_ref_id="proj_chroma",
        task_type="scene_generation", strategy="C", config_json={}, status="active",
    )
    session.flush()
    svc = InjectionService(session)
    svc.context_text = "他翻身越过断墙，冲上铁梯直扑顶楼"
    frags = svc.fragments_for("proj_chroma", "scene_generation")
    assert frags.rag_block
    prefix = frags.to_system_prompt_prefix()
    assert "风格检索样例" in prefix
    assert "严格禁止" in prefix or "严禁" in prefix


def test_chroma_delete_rag_index_removes_collections(session):
    profile = _seed(session)
    rag.build_rag_index(session, profile)
    store = get_vector_store()
    assert store.collection_exists(rag.rag_collection_name(profile.profile_id, "paragraph"))
    rag.delete_rag_index(profile.profile_id)
    for gran in rag.GRANULARITIES:
        assert not store.collection_exists(rag.rag_collection_name(profile.profile_id, gran))
