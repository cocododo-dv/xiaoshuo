"""Wave 7（§5.9 / §11 规则 9）：导入时记录用户对文本的分析+发送权限声明。

不得默认拥有云端发送权；声明 send_rights=False 却选云端策略 → 拒绝。未声明 → 记录
`{declared: false}`（不改既有 cloud_policy 行为，向后兼容）。
"""
from __future__ import annotations

import pytest

from novel_system.db.session import SessionLocal
from novel_system.services.errors import DomainError
from novel_system.services.style_reference.ingest import IngestService

SAMPLE = "第一段参考文字。\n\n第二段参考文字，用于风格分析。"


def _ingest(seed, *, cloud_policy, rights=None):
    with SessionLocal() as session:
        svc = IngestService(session, llm_enabled=False)
        result = svc.ingest_upload(
            raw_bytes=(SAMPLE + seed).encode("utf-8"),
            file_name=f"s_{seed}.txt", title="t", author_label="a",
            cloud_policy=cloud_policy, rights_declaration=rights,
        )
        session.commit()
        return result.book


def test_rights_declaration_recorded_in_stats():
    book = _ingest("r1", cloud_policy="local_only",
                   rights={"analysis_rights": True, "send_rights": False, "declared_by": "作者"})
    decl = book.stats_json["rights_declaration"]
    assert decl["analysis_rights"] is True
    assert decl["send_rights"] is False
    assert decl["declared_by"] == "作者"
    assert decl["declared"] is True
    assert decl["declared_at"]


def test_undeclared_records_declared_false():
    book = _ingest("r2", cloud_policy="local_only", rights=None)
    decl = book.stats_json["rights_declaration"]
    assert decl["declared"] is False


def test_no_send_rights_but_cloud_policy_rejected():
    # 声明无发送权却选云端策略 → 矛盾，拒绝（§11 规则 9：不得默认云端发送权）
    with pytest.raises(DomainError) as exc:
        _ingest("r3", cloud_policy="allow_full_cloud",
                rights={"analysis_rights": True, "send_rights": False})
    assert "SEND" in str(exc.value.code).upper() or "RIGHTS" in str(exc.value.code).upper()


def test_send_rights_with_cloud_policy_ok():
    book = _ingest("r4", cloud_policy="allow_full_cloud",
                   rights={"analysis_rights": True, "send_rights": True})
    assert book.stats_json["rights_declaration"]["send_rights"] is True


def test_backward_compat_cloud_without_declaration_still_ingests():
    # 既有行为：未声明 + allow_cloud 仍可导入（cloud_policy 本就是用户显式选择）
    book = _ingest("r5", cloud_policy="allow_full_cloud", rights=None)
    assert book.stats_json["rights_declaration"]["declared"] is False
