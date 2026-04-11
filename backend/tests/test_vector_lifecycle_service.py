from __future__ import annotations

import pytest

from novel_system.services.errors import DomainError
from novel_system.services.versioning import VectorLifecycleService
from novel_system.services.vector_store import get_vector_store
from tests.test_review_release import (
    approve_review,
    expected_global_collection_alias,
    import_style_review,
    job_ids_for_review,
    promote_active_alias,
)


def test_run_reindex_rejects_stale_job_target_after_new_candidate_claim(client, session) -> None:
    promote_active_alias(client)

    review_id_old = import_style_review(
        client,
        review_id="review_style_old_reindex_service",
        lineage_key="STY_OLD_REINDEX_SERVICE",
        candidate_text="old reindex should not overwrite the new collection",
        active_on_approve=1,
    )
    approve_review(client, review_id_old, idempotency_key="approve-review-style-old-reindex-service")
    old_jobs = job_ids_for_review(client, review_id_old)

    review_id_new = import_style_review(
        client,
        review_id="review_style_new_reindex_service",
        lineage_key="STY_NEW_REINDEX_SERVICE",
        candidate_text="new reindex owns the current candidate collection",
        active_on_approve=1,
    )
    new_row_id = approve_review(client, review_id_new, idempotency_key="approve-review-style-new-reindex-service")

    alias_before = client.get("/api/v1/index/alias-scopes/style_observation:global:global").json()["data"]
    assert alias_before["candidate_alias"] == expected_global_collection_alias(new_row_id)
    documents_before = get_vector_store().load_collection(alias_before["candidate_alias"])
    indexed_ids_before = {item["id"] for item in documents_before}
    assert new_row_id in indexed_ids_before

    with pytest.raises(DomainError) as exc_info:
        VectorLifecycleService(session).run_reindex(old_jobs["reindex"])

    assert exc_info.value.code == "INDEX_JOB_TARGET_STALE"

    alias_after = client.get("/api/v1/index/alias-scopes/style_observation:global:global").json()["data"]
    documents_after = get_vector_store().load_collection(alias_after["candidate_alias"])
    indexed_ids_after = {item["id"] for item in documents_after}

    assert alias_after == alias_before
    assert indexed_ids_after == indexed_ids_before
