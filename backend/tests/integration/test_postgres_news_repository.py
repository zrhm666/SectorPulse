import os
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from sector_pulse.domain.news import NewsDocument, NewsEvent, SourceGrade
from sector_pulse.storage.postgres import PostgresDatabase
from sector_pulse.storage.postgres_news_repository import PostgresNewsRepository
from sqlalchemy import text


@pytest.mark.asyncio
async def test_postgres_news_save_deduplicates_event_documents() -> None:
    url = os.environ.get("SECTOR_PULSE_DATABASE_URL")
    if not url:
        pytest.skip("requires SECTOR_PULSE_DATABASE_URL")

    suffix = uuid4().hex
    document_id = f"document-{suffix}"
    event_id = f"event-{suffix}"
    now = datetime.now(UTC)
    document = NewsDocument(
        document_id=document_id,
        source_id="eastmoney",
        canonical_locator=f"https://example.test/{suffix}",
        citation_url=f"https://example.test/{suffix}",
        title="测试新闻",
        publisher="测试来源",
        summary="测试摘要",
        published_at=now,
        source_observed_at=now,
        collected_at=now,
        content_hash=f"hash-{suffix}",
        source_grade=SourceGrade.REPUTABLE_MEDIA,
    )
    event = NewsEvent(
        event_id=event_id,
        canonical_title="测试事件",
        first_published_at=now,
        document_ids=(document_id, document_id),
        deduplication_reason="test",
    )
    database = PostgresDatabase(url)
    await database.initialize()
    repository = PostgresNewsRepository(database)

    try:
        await repository.save((document,), (event,))
        loaded = await repository.get_event(event_id)
        assert loaded is not None
        assert loaded.document_ids == (document_id,)

        async with database.engine.connect() as connection:
            count = (
                await connection.execute(
                    text("SELECT count(*) FROM news_event_documents WHERE event_id = :event_id"),
                    {"event_id": event_id},
                )
            ).scalar_one()
        assert count == 1
    finally:
        async with database.engine.begin() as connection:
            await connection.execute(
                text("DELETE FROM news_event_documents WHERE event_id = :event_id"),
                {"event_id": event_id},
            )
            await connection.execute(
                text("DELETE FROM news_events WHERE event_id = :event_id"),
                {"event_id": event_id},
            )
            await connection.execute(
                text("DELETE FROM news_documents WHERE document_id = :document_id"),
                {"document_id": document_id},
            )
        await database.close()
