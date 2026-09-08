import hashlib
import re
from collections.abc import Sequence
from difflib import SequenceMatcher

from sector_pulse.domain.news import NewsDocument, NewsEvent
from sector_pulse.domain.provider import DataStatus, ProviderResult
from sector_pulse.domain.time import AnalysisRun
from sector_pulse.ports.news import NewsPort
from sector_pulse.storage.sqlite.news_repository import SQLiteNewsRepository


def _normalize_title(title: str) -> str:
    return re.sub(r"[^\w\u4e00-\u9fff]", "", title).lower()


def deduplicate_documents(
    documents: Sequence[NewsDocument],
) -> tuple[NewsEvent, ...]:
    """按内容哈希和标题相似度聚合转载，输出顺序由最早文档决定。"""
    groups: list[list[NewsDocument]] = []
    for document in documents:
        normalized = _normalize_title(document.title)
        target: list[NewsDocument] | None = None
        reason = "content_hash"
        for group in groups:
            first = group[0]
            if document.content_hash == first.content_hash:
                target = group
                break
            if SequenceMatcher(None, normalized, _normalize_title(first.title)).ratio() >= 0.8:
                target = group
                reason = "similar_title"
                break
        if target is None:
            groups.append([document])
        else:
            target.append(document)

    events: list[NewsEvent] = []
    for group in groups:
        ordered = sorted(
            group, key=lambda item: (item.published_at is None, item.published_at, item.document_id)
        )
        first = ordered[0]
        identity = "|".join(sorted(item.content_hash for item in group))
        event_id = hashlib.sha256(identity.encode("utf-8")).hexdigest()[:24]
        reason = (
            "content_hash" if len({item.content_hash for item in group}) == 1 else "similar_title"
        )
        events.append(
            NewsEvent(
                event_id=f"event-{event_id}",
                canonical_title=first.title,
                first_published_at=first.published_at,
                document_ids=tuple(item.document_id for item in ordered),
                deduplication_reason=reason,
            )
        )
    return tuple(events)


async def ingest_news(
    provider: NewsPort,
    repository: SQLiteNewsRepository,
    run: AnalysisRun,
    source_ids: Sequence[str],
) -> ProviderResult[tuple[NewsEvent, ...]]:
    """在锁定 cutoff 后采集、去重并幂等保存新闻事件。"""
    if run.run_cutoff_at is None:
        raise ValueError("news ingestion requires a locked run cutoff")
    result = await provider.fetch_since(run.run_cutoff_at, source_ids)
    if result.status is not DataStatus.SUCCESS or result.data is None:
        return ProviderResult(
            provider_id=result.provider_id,
            capability="news.events",
            status=result.status,
            collected_at=result.collected_at,
            error=result.error,
        )
    events = deduplicate_documents(result.data)
    repository.save(result.data, events)
    return ProviderResult(
        provider_id=result.provider_id,
        capability="news.events",
        status=DataStatus.SUCCESS if events else DataStatus.EMPTY,
        data=events if events else None,
        observed_at=result.observed_at,
        collected_at=result.collected_at,
        source_version=result.source_version,
    )
