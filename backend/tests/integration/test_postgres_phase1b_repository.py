import os
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sector_pulse.domain.market.market import SectorKind
from sector_pulse.domain.review.review import (
    IssueSeverity,
    ReviewDecision,
    ReviewIssue,
    ReviewReport,
)
from sector_pulse.domain.writing.article import ArticleDraft, DraftStatus
from sector_pulse.domain.writing.attribution import AttributionContext
from sector_pulse.storage.postgres.database import PostgresDatabase
from sector_pulse.storage.postgres.writing.phase1b_repository import PostgresPhase1BRepository
from sector_pulse.web.app import create_app
from sqlalchemy import text


def test_postgres_phase1b_repository_empty_reads() -> None:
    url = os.environ.get("SECTOR_PULSE_DATABASE_URL")
    if not url:
        pytest.skip("requires SECTOR_PULSE_DATABASE_URL")
    database = PostgresDatabase(url)
    database.initialize()
    repository = PostgresPhase1BRepository(database)
    run_id = uuid4()
    assert repository.get_contexts(run_id) == ()
    assert repository.get_gates(run_id) == ()
    assert repository.get_cards(run_id) == ()
    assert repository.get_outline(run_id) is None
    assert repository.get_drafts(run_id) == ()
    assert repository.get_review(run_id) is None
    database.close()


def test_postgres_phase1b_contexts_are_upserted_by_primary_key() -> None:
    url = os.environ.get("SECTOR_PULSE_DATABASE_URL")
    if not url:
        pytest.skip("requires SECTOR_PULSE_DATABASE_URL")

    database = PostgresDatabase(url)
    database.initialize()
    run_id = uuid4()
    context = AttributionContext(
        run_id=run_id,
        sector_id="concept-test",
        sector_kind=SectorKind.CONCEPT,
        cutoff_at=datetime.now(UTC),
        market_facts={},
        event_ids=(),
        eligible_event_ids=(),
        background_event_ids=(),
        excluded_event_ids=(),
        source_grades={},
        counter_evidence=(),
    )
    repository = PostgresPhase1BRepository(database)
    try:
        repository.save_contexts((context,))
        repository.save_contexts((context,))
        assert repository.get_contexts(run_id) == (context,)
    finally:
        with database.start().begin() as connection:
            connection.execute(
                text("DELETE FROM attribution_contexts WHERE run_id = :run_id"),
                {"run_id": str(run_id)},
            )
        database.close()


def test_postgres_phase1b_review_is_saved_with_issues_and_can_be_replayed() -> None:
    url = os.environ.get("SECTOR_PULSE_DATABASE_URL")
    if not url:
        pytest.skip("requires SECTOR_PULSE_DATABASE_URL")

    database = PostgresDatabase(url)
    database.initialize()
    repository = PostgresPhase1BRepository(database)
    draft = ArticleDraft(
        draft_id=uuid4(),
        run_id=uuid4(),
        version=1,
        status=DraftStatus.UNREVIEWED,
        titles=("待审核标题",),
        introduction="导语",
        sections=(),
        conclusion="结论",
        risk_notice="风险提示",
        sources=(),
        character_count=8,
    )
    review = ReviewReport(
        review_id=str(uuid4()),
        draft_id=str(draft.draft_id),
        draft_version=draft.version,
        decision=ReviewDecision.REVISE,
        issues=(
            ReviewIssue(
                issue_id="issue-1",
                severity=IssueSeverity.WARNING,
                code="NEEDS_SOURCE",
                message="需要补充来源。",
                section_id="section-1",
            ),
        ),
        revision_round=0,
    )

    try:
        repository.save_draft(draft)
        repository.save_review(review)
        repository.save_review(review)

        assert repository.get_review(draft.run_id) == review
        with database.start().connect() as connection:
            rows = connection.execute(
                text(
                    "SELECT issue_id FROM review_issues "
                    "WHERE review_id = :review_id ORDER BY issue_id"
                ),
                {"review_id": review.review_id},
            )
            assert [row[0] for row in rows.fetchall()] == ["issue-1"]
    finally:
        with database.start().begin() as connection:
            connection.execute(
                text("DELETE FROM review_issues WHERE review_id = :review_id"),
                {"review_id": review.review_id},
            )
            connection.execute(
                text("DELETE FROM review_reports WHERE review_id = :review_id"),
                {"review_id": review.review_id},
            )
            connection.execute(
                text("DELETE FROM article_drafts WHERE draft_id = :draft_id"),
                {"draft_id": str(draft.draft_id)},
            )
        database.close()


def test_postgres_governance_endpoint_reads_drafts_through_runtime_storage() -> None:
    url = os.environ.get("SECTOR_PULSE_DATABASE_URL")
    if not url:
        pytest.skip("requires SECTOR_PULSE_DATABASE_URL")

    database = PostgresDatabase(url)
    database.initialize()
    repository = PostgresPhase1BRepository(database)
    draft = ArticleDraft(
        draft_id=uuid4(),
        run_id=uuid4(),
        version=1,
        status=DraftStatus.UNREVIEWED,
        titles=("治理检查标题",),
        introduction="导语",
        sections=(),
        conclusion="结论",
        risk_notice="风险提示",
        sources=(),
        character_count=8,
    )

    try:
        repository.save_draft(draft)
        with TestClient(create_app(static_dir=None)) as client:
            response = client.get(f"/api/runs/{draft.run_id}/governance")

        assert response.status_code == 200
        assert response.json()["status"] == "FAIL"
    finally:
        with database.start().begin() as connection:
            connection.execute(
                text("DELETE FROM article_drafts WHERE draft_id = :draft_id"),
                {"draft_id": str(draft.draft_id)},
            )
        database.close()
