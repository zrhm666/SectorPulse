from datetime import UTC, datetime
from uuid import uuid4

import pytest
from sector_pulse.domain.news.news import NewsDocument, NewsEvent, SourceGrade
from sector_pulse.storage.postgres.news.news_repository import PostgresNewsRepository

from backend.tests.comparison_support import (
    comparison_postgres as comparison_postgres_fixture,  # noqa: F401
)

pytestmark = pytest.mark.postgres


def test_same_document_refreshes_metadata_without_replacing_canonical_identity(
    comparison_postgres,
) -> None:
    repository = PostgresNewsRepository(comparison_postgres)
    suffix = uuid4().hex
    now = datetime.now(UTC)
    original = NewsDocument(
        document_id=f"original-{suffix}",
        source_id="test",
        canonical_locator=f"https://example.test/{suffix}",
        title="Original title",
        summary="Original summary",
        published_at=now,
        collected_at=now,
        content_hash=suffix,
        source_grade=SourceGrade.REPUTABLE_MEDIA,
    )
    repository.save([original], [])
    updated = original.model_copy(update={"title": "Updated title", "summary": "Updated summary"})
    repository.save([updated], [])
    assert repository.get_documents([original.document_id])[original.document_id] == updated

    alias = updated.model_copy(update={"document_id": f"alias-{suffix}", "title": "Alias title"})
    event = NewsEvent(
        event_id=f"event-{suffix}",
        canonical_title="Event",
        first_published_at=now,
        document_ids=(alias.document_id, original.document_id),
        deduplication_reason="canonical URL",
    )
    repository.save([alias], [event])
    assert repository.get_documents([alias.document_id]) == {}
    assert repository.get_documents([original.document_id])[original.document_id] == updated
    saved_event = repository.get_event(event.event_id)
    assert saved_event is not None
    assert saved_event.document_ids == (original.document_id,)
