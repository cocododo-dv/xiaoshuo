"""pass5 R2/R4：versioning 状态机——释放不得复活已 superseded 版本（先红后绿）。

VER-G1: PromotionService.release_review 的重发前置只查 active_flag==1、不查
runtime_eligibility_basis=="superseded"。已被新版 supersede 的旧行 active_flag=0 →
闯过前置 → _activate_direct_row 复活旧行、把当前版打成 superseded（血缘倒退到陈旧内容）。
可达：操作者用新幂等键 release 重试 / 崩溃后 recovery 的 HumanReviewEvent 重放。
"""

from __future__ import annotations

import pytest

from novel_system.db.models import ReviewItem, StyleRule
from novel_system.services.errors import DomainError
from novel_system.services.versioning.promotion import PromotionService
from novel_system.services.versioning.review_materialization import ReviewMaterializationService


def _mk_direct_review(session, review_id: str, text: str, lineage: str = "LREL") -> None:
    session.add(ReviewItem(
        review_id=review_id,
        item_type="style_rule_set",
        status="pending",
        candidate_text=text,
        candidate_payload_json={
            "scope": "global", "scope_ref_id": "global",
            "lineage_key": lineage, "text": text,
        },
        active_on_approve=1,
    ))
    session.flush()


def test_release_does_not_resurrect_superseded_version(session):
    _mk_direct_review(session, "REL_R1", "v1-content")
    _mk_direct_review(session, "REL_R2", "v2-content")
    m1 = ReviewMaterializationService(session).materialize_review("REL_R1")  # v1 active
    m2 = ReviewMaterializationService(session).materialize_review("REL_R2")  # v2 active → v1 superseded
    row_a, row_b = m1["approved_item_row_id"], m2["approved_item_row_id"]
    a, b = session.get(StyleRule, row_a), session.get(StyleRule, row_b)
    assert a.active_flag == 0 and b.active_flag == 1, "前置：v1 应被 v2 supersede"
    assert a.runtime_eligibility_basis == "superseded"

    # 释放已 superseded 的旧 review 必须被拒（不得复活旧版、不得打掉当前版）
    with pytest.raises(DomainError):
        PromotionService(session).release_review("REL_R1")

    session.refresh(a)
    session.refresh(b)
    # 守卫后：旧版不复活、当前 v2 仍 active（后者即"不误伤当前版"对照）
    assert a.active_flag == 0, "已 superseded 的 v1 被复活 → 血缘倒退到陈旧内容"
    assert b.active_flag == 1, "当前 v2 被打掉"
    # 正常释放路径（非 superseded）由 chroma 门控的 test_review_release(WSL) 覆盖，不在此 Windows 套件重测。
