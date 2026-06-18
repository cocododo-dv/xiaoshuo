from __future__ import annotations

from novel_system.db.models import (
    ChapterGoal,
    ChapterState,
    FinalScene,
    SceneCard,
    SceneRunState,
    StoryProject,
)
from novel_system.services.self_repetition import (
    CrossProjectExpressionBudget,
    LifetimeExpressionRegistry,
    MergedFreshnessBudget,
    SelfRepetitionDetector,
    format_merged_freshness_guidance,
    merge_freshness_budgets,
)


def _seed_two_scenes(session, *, shared_phrase: str = "") -> None:
    session.add(ChapterGoal(chapter_id="SR100", planned_scene_count=3, chapter_goal="test"))
    session.add(ChapterState(chapter_id="SR100", current_phase="drafting"))
    for idx in (1, 2):
        scene_id = f"SR100_SC0{idx}"
        final_row_id = f"final_{scene_id}"
        session.add(SceneCard(scene_id=scene_id, chapter_id="SR100", scene_seq=idx, scene_goal="test"))
        session.add(SceneRunState(scene_id=scene_id, scene_status="archived", current_final_scene_row_id=final_row_id))
        content = f"Unique content for scene {idx}. " + (shared_phrase if shared_phrase else f"Only in scene {idx}.")
        session.add(FinalScene(
            row_id=final_row_id, scene_id=scene_id, chapter_id="SR100",
            content=content, status="approved",
            source_bundle_id=f"b_{scene_id}", source_bundle_hash=f"h_{scene_id}",
        ))
    session.commit()


def test_self_repetition_detects_reused_phrases(session) -> None:
    shared = "The glass rain hammered the abandoned station roof while she counted the seconds"
    _seed_two_scenes(session, shared_phrase=shared)

    detector = SelfRepetitionDetector(session)
    new_text = f"She arrived. {shared}. Then she left."
    report = detector.check(new_text, "SR100_SC03", "SR100")

    assert report.passed is False
    assert len(report.hits) >= 1
    assert report.score < 1.0
    assert report.corpus_scene_count == 2


def test_self_repetition_passes_for_unique_text(session) -> None:
    _seed_two_scenes(session, shared_phrase="The glass rain hammered the abandoned station roof")

    detector = SelfRepetitionDetector(session)
    new_text = "Completely original text about a mountain sunrise and frozen rivers with no overlap at all."
    report = detector.check(new_text, "SR100_SC03", "SR100")

    assert report.passed is True
    assert len(report.hits) == 0
    assert report.score == 1.0


def test_self_repetition_empty_corpus(session) -> None:
    session.add(ChapterGoal(chapter_id="SR200", planned_scene_count=1, chapter_goal="test"))
    session.add(ChapterState(chapter_id="SR200", current_phase="drafting"))
    session.commit()

    detector = SelfRepetitionDetector(session)
    report = detector.check("Some new text here.", "SR200_SC01", "SR200")

    assert report.passed is True


def test_self_repetition_top_repeated_ngrams(session) -> None:
    shared = "The glass rain hammered the abandoned station roof while she counted"
    _seed_two_scenes(session, shared_phrase=shared)

    detector = SelfRepetitionDetector(session)
    ngrams = detector.top_repeated_ngrams("SR100")

    assert len(ngrams) >= 1


# ---------------------------------------------------------------------------
# Cross-project repetition detection tests
# ---------------------------------------------------------------------------

def _seed_project_with_scenes(session, project_id: str, scene_texts: list[str]) -> None:
    """Create a StoryProject with finalized scenes containing the given texts."""
    session.add(StoryProject(
        project_id=project_id,
        title=f"Novel {project_id}",
        outline_text="test outline",
    ))
    chapter_id = f"{project_id}_CH01"
    session.add(ChapterGoal(
        chapter_id=chapter_id,
        project_id=project_id,
        planned_scene_count=len(scene_texts),
        chapter_goal="test",
    ))
    session.add(ChapterState(chapter_id=chapter_id, current_phase="drafting"))
    for idx, text in enumerate(scene_texts, start=1):
        scene_id = f"{project_id}_SC{idx:02d}"
        final_row_id = f"final_{scene_id}"
        session.add(SceneCard(
            scene_id=scene_id, chapter_id=chapter_id,
            project_id=project_id, scene_seq=idx, scene_goal="test",
        ))
        session.add(SceneRunState(
            scene_id=scene_id, scene_status="archived",
            current_final_scene_row_id=final_row_id,
        ))
        session.add(FinalScene(
            row_id=final_row_id, scene_id=scene_id, chapter_id=chapter_id,
            content=text, status="approved",
            source_bundle_id=f"b_{scene_id}", source_bundle_hash=f"h_{scene_id}",
        ))
    session.commit()


def test_cross_project_finds_sibling_expressions(session) -> None:
    """Expressions from sibling projects appear in the cross-project budget."""
    _seed_project_with_scenes(session, "BOOK_A", [
        "她微微一笑，像春风拂过湖面。他轻叹一声，心如刀割。",
        "他皱眉看着窗外，仿佛在回忆什么。她摇头叹了口气。",
    ])
    _seed_project_with_scenes(session, "BOOK_B", [
        "她微微一笑，如同阳光穿过云层。他不由自主地握拳。",
    ])
    _seed_project_with_scenes(session, "BOOK_C", [
        "Unique content with no overlapping patterns.",
    ])

    reg = LifetimeExpressionRegistry(session)
    budget = reg.cross_project_banned_expressions("BOOK_A")

    assert isinstance(budget, CrossProjectExpressionBudget)
    assert budget.project_id == "BOOK_A"
    # BOOK_B and BOOK_C are siblings
    assert set(budget.sibling_project_ids) == {"BOOK_B", "BOOK_C"}
    # BOOK_B has "微微一笑" as an action habit — it should appear
    assert any("微微一笑" in expr or "握拳" in expr for expr in budget.flat_expressions)


def test_cross_project_empty_when_no_siblings(session) -> None:
    """No sibling projects means an empty budget."""
    _seed_project_with_scenes(session, "SOLO", [
        "她微微一笑，像春风拂过湖面。他轻叹一声。",
    ])

    reg = LifetimeExpressionRegistry(session)
    budget = reg.cross_project_banned_expressions("SOLO")

    assert budget.sibling_project_ids == []
    assert budget.flat_expressions == []


def test_cross_project_respects_max_sibling_projects(session) -> None:
    """The max_sibling_projects cap limits how many siblings are queried."""
    for i in range(6):
        _seed_project_with_scenes(session, f"SER_{i}", [
            f"他轻叹一声。Scene {i} content.",
        ])

    reg = LifetimeExpressionRegistry(session)
    budget = reg.cross_project_banned_expressions("SER_0", max_sibling_projects=3)

    assert len(budget.sibling_project_ids) == 3


def test_cross_project_excludes_trashed_projects(session) -> None:
    """Trashed projects should not be considered siblings."""
    _seed_project_with_scenes(session, "LIVE", [
        "她微微一笑。",
    ])
    _seed_project_with_scenes(session, "TRASHED", [
        "她微微一笑。他轻叹。",
    ])
    # Trash the second project
    proj = session.get(StoryProject, "TRASHED")
    proj.trashed_flag = 1
    session.commit()

    reg = LifetimeExpressionRegistry(session)
    budget = reg.cross_project_banned_expressions("LIVE")

    assert "TRASHED" not in budget.sibling_project_ids


def test_cross_project_avoidance_guidance_format(session) -> None:
    """The guidance string has the expected heading and structure."""
    _seed_project_with_scenes(session, "MAIN", [
        "Original content for the main book.",
    ])
    _seed_project_with_scenes(session, "SIDE", [
        "她微微一笑，仿佛花开。他皱眉看着远方。心如刀割的感觉涌上来。",
    ])

    reg = LifetimeExpressionRegistry(session)
    guidance = reg.get_cross_project_avoidance_guidance("MAIN")

    assert "跨作品系列级表达禁用清单" in guidance
    assert "1 部关联作品" in guidance


def test_merge_freshness_budgets_deduplicates(session) -> None:
    """Expressions in both budgets keep the higher (1.0) weight."""
    project_list = ["微微一笑", "轻叹"]
    cross_budget = CrossProjectExpressionBudget(
        project_id="TEST",
        sibling_project_ids=["OTHER"],
        expressions_by_category={},
        flat_expressions=["轻叹", "皱眉"],  # "轻叹" overlaps with project
    )

    merged = merge_freshness_budgets(project_list, cross_budget)

    assert isinstance(merged, MergedFreshnessBudget)
    expr_map = dict(merged.combined_expressions)
    # "轻叹" appears in both — should have weight 1.0 (not 0.5)
    assert expr_map["轻叹"] == 1.0
    # "微微一笑" only in project — weight 1.0
    assert expr_map["微微一笑"] == 1.0
    # "皱眉" only in cross-project — weight 0.5
    assert expr_map["皱眉"] == 0.5
    assert len(merged.combined_expressions) == 3


def test_merge_freshness_budgets_custom_penalty() -> None:
    """Custom penalty weight is applied to cross-project expressions."""
    cross_budget = CrossProjectExpressionBudget(
        project_id="TEST",
        sibling_project_ids=["OTHER"],
        expressions_by_category={},
        flat_expressions=["心如刀割"],
    )

    merged = merge_freshness_budgets([], cross_budget, cross_project_penalty=0.3)

    assert merged.cross_project_penalty == 0.3
    expr_map = dict(merged.combined_expressions)
    assert expr_map["心如刀割"] == 0.3


def test_merge_freshness_budgets_empty() -> None:
    """Empty inputs produce an empty merged budget."""
    cross_budget = CrossProjectExpressionBudget(
        project_id="TEST",
        sibling_project_ids=[],
        expressions_by_category={},
        flat_expressions=[],
    )

    merged = merge_freshness_budgets([], cross_budget)
    assert merged.combined_expressions == []


def test_format_merged_freshness_guidance_sections() -> None:
    """The formatted guidance separates strict and soft headings."""
    merged = MergedFreshnessBudget(
        project_expressions=["轻叹"],
        cross_project_expressions=["皱眉"],
        cross_project_penalty=0.5,
        combined_expressions=[("轻叹", 1.0), ("皱眉", 0.5)],
    )

    text = format_merged_freshness_guidance(merged)

    assert "禁止重复" in text
    assert "尽量避免" in text
    assert "轻叹" in text
    assert "皱眉" in text


def test_format_merged_freshness_guidance_empty() -> None:
    """Empty budget produces empty guidance string."""
    merged = MergedFreshnessBudget(
        project_expressions=[], cross_project_expressions=[],
        cross_project_penalty=0.5, combined_expressions=[],
    )
    assert format_merged_freshness_guidance(merged) == ""
