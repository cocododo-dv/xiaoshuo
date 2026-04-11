from __future__ import annotations

from sqlalchemy.orm import Session

from novel_system.services.vector_store import VectorStore, get_vector_store
from novel_system.services.versioning import (
    PromotionService,
    ReviewMaterializationService,
    RuntimeRecoveryService,
    VectorLifecycleService,
)


class VersionManager:
    def __init__(self, session: Session, vector_store: VectorStore | None = None) -> None:
        self.session = session
        self.vector_store = vector_store or get_vector_store()
        self.review_materialization = ReviewMaterializationService(session, vector_store=self.vector_store)
        self.vector_lifecycle = VectorLifecycleService(session, vector_store=self.vector_store)
        self.promotion = PromotionService(session, vector_store=self.vector_store)
        self.runtime_recovery = RuntimeRecoveryService(session, vector_store=self.vector_store)

    def materialize_review(self, review_id: str) -> dict:
        return self.review_materialization.materialize_review(review_id)

    def run_reindex(self, job_id: str) -> dict:
        return self.vector_lifecycle.run_reindex(job_id)

    def run_verify(self, job_id: str) -> dict:
        return self.vector_lifecycle.run_verify(job_id)

    def release_review(self, review_id: str) -> dict:
        return self.promotion.release_review(review_id)

    def run_due_promotions(self) -> dict:
        return self.promotion.run_due_promotions()

    def recover_stuck_jobs(self) -> dict:
        return self.runtime_recovery.recover_stuck_jobs()
