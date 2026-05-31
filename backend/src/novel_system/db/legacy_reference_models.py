from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import JSON, ForeignKey, Integer, String, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def utcnow() -> str:
    return datetime.now(UTC).isoformat()


class LegacyReferenceBase(DeclarativeBase):
    pass


class ReferenceBook(LegacyReferenceBase):
    __tablename__ = "reference_books"

    book_id: Mapped[str] = mapped_column(String, primary_key=True)
    title: Mapped[str] = mapped_column(String)
    author_label: Mapped[str | None] = mapped_column(String, nullable=True)
    source_kind: Mapped[str] = mapped_column(String)
    source_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    file_name: Mapped[str | None] = mapped_column(String, nullable=True)
    cloud_policy: Mapped[str] = mapped_column(String)
    analysis_focus: Mapped[str] = mapped_column(String, default="style_structure")
    text_checksum: Mapped[str] = mapped_column(String)
    status: Mapped[str] = mapped_column(String, default="imported")
    total_chars: Mapped[int] = mapped_column(Integer, default=0)
    total_segments: Mapped[int] = mapped_column(Integer, default=0)
    stats_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[str] = mapped_column(String, default=utcnow)
    updated_at: Mapped[str] = mapped_column(String, default=utcnow, onupdate=utcnow)


class ReferenceBookSegment(LegacyReferenceBase):
    __tablename__ = "reference_book_segments"

    segment_id: Mapped[str] = mapped_column(String, primary_key=True)
    book_id: Mapped[str] = mapped_column(ForeignKey("reference_books.book_id"))
    segment_index: Mapped[int] = mapped_column(Integer)
    chapter_hint: Mapped[str | None] = mapped_column(String, nullable=True)
    segment_kind: Mapped[str] = mapped_column(String)
    start_offset: Mapped[int] = mapped_column(Integer, default=0)
    end_offset: Mapped[int] = mapped_column(Integer, default=0)
    text: Mapped[str] = mapped_column(Text)
    selected_count: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[str] = mapped_column(String, default=utcnow)


class ReferenceLearningRun(LegacyReferenceBase):
    __tablename__ = "reference_learning_runs"

    run_id: Mapped[str] = mapped_column(String, primary_key=True)
    book_id: Mapped[str] = mapped_column(ForeignKey("reference_books.book_id"))
    status: Mapped[str] = mapped_column(String, default="running")
    batch_size: Mapped[int] = mapped_column(Integer, default=8)
    coverage_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    round_count: Mapped[int] = mapped_column(Integer, default=0)
    profile_id: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[str] = mapped_column(String, default=utcnow)
    updated_at: Mapped[str] = mapped_column(String, default=utcnow, onupdate=utcnow)


class ReferenceLearningRound(LegacyReferenceBase):
    __tablename__ = "reference_learning_rounds"

    round_id: Mapped[str] = mapped_column(String, primary_key=True)
    book_id: Mapped[str] = mapped_column(ForeignKey("reference_books.book_id"))
    run_id: Mapped[str] = mapped_column(ForeignKey("reference_learning_runs.run_id"))
    round_index: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String, default="waiting_review")
    segment_ids_json: Mapped[list[str]] = mapped_column(JSON, default=list)
    finding_ids_json: Mapped[list[str]] = mapped_column(JSON, default=list)
    created_at: Mapped[str] = mapped_column(String, default=utcnow)
    updated_at: Mapped[str] = mapped_column(String, default=utcnow, onupdate=utcnow)


class ReferenceFinding(LegacyReferenceBase):
    __tablename__ = "reference_findings"

    finding_id: Mapped[str] = mapped_column(String, primary_key=True)
    book_id: Mapped[str] = mapped_column(ForeignKey("reference_books.book_id"))
    run_id: Mapped[str] = mapped_column(ForeignKey("reference_learning_runs.run_id"))
    round_id: Mapped[str] = mapped_column(ForeignKey("reference_learning_rounds.round_id"))
    segment_id: Mapped[str] = mapped_column(ForeignKey("reference_book_segments.segment_id"))
    review_id: Mapped[str] = mapped_column(String)
    finding_type: Mapped[str] = mapped_column(String)
    dimension: Mapped[str] = mapped_column(String)
    summary: Mapped[str] = mapped_column(Text)
    evidence_preview: Mapped[str] = mapped_column(Text)
    candidate_payload_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    status: Mapped[str] = mapped_column(String, default="pending")
    created_at: Mapped[str] = mapped_column(String, default=utcnow)
    updated_at: Mapped[str] = mapped_column(String, default=utcnow, onupdate=utcnow)


class ReferenceProfile(LegacyReferenceBase):
    __tablename__ = "reference_profiles"

    profile_id: Mapped[str] = mapped_column(String, primary_key=True)
    book_id: Mapped[str] = mapped_column(ForeignKey("reference_books.book_id"))
    run_id: Mapped[str] = mapped_column(ForeignKey("reference_learning_runs.run_id"))
    title: Mapped[str] = mapped_column(String)
    status: Mapped[str] = mapped_column(String, default="ready")
    profile_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    coverage_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    source_finding_ids_json: Mapped[list[str]] = mapped_column(JSON, default=list)
    created_at: Mapped[str] = mapped_column(String, default=utcnow)
    updated_at: Mapped[str] = mapped_column(String, default=utcnow, onupdate=utcnow)
