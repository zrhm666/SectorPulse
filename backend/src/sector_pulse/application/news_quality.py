from collections.abc import Mapping, Sequence
from datetime import datetime

from pydantic import BaseModel, ConfigDict

from sector_pulse.domain.news import NewsDocument, NewsEvent, NewsUse
from sector_pulse.domain.provider import DataStatus
from sector_pulse.domain.quality import QualityStatus


class NewsQualityReport(BaseModel):
    model_config = ConfigDict(frozen=True)

    status: QualityStatus
    document_count: int
    event_count: int
    citation_eligible_count: int
    background_only_count: int
    excluded_after_cutoff_count: int
    source_statuses: Mapping[str, DataStatus]
    blocking_reasons: tuple[str, ...] = ()


def evaluate_news_quality(
    documents: Sequence[NewsDocument],
    events: Sequence[NewsEvent],
    source_statuses: Mapping[str, DataStatus],
    cutoff: datetime,
) -> NewsQualityReport:
    uses = tuple(document.use_at(cutoff) for document in documents)
    citation_count = sum(use is NewsUse.EVIDENCE for use in uses)
    background_count = sum(use is NewsUse.BACKGROUND for use in uses)
    excluded_count = sum(use is NewsUse.EXCLUDED for use in uses)
    blocking: list[str] = []
    if excluded_count:
        blocking.append("CUTOFF_VIOLATION")
    core_sources = {"cls", "eastmoney"}
    core_failures = {
        source_id
        for source_id, status in source_statuses.items()
        if source_id in core_sources and status in {DataStatus.FAILED, DataStatus.UNAVAILABLE}
    }
    if core_failures >= core_sources:
        blocking.append("CORE_SOURCES_UNAVAILABLE")
    if blocking:
        status = QualityStatus.BLOCKED
    elif any(
        status in {DataStatus.FAILED, DataStatus.UNAVAILABLE}
        for status in source_statuses.values()
    ):
        status = QualityStatus.DEGRADED
    else:
        status = QualityStatus.NORMAL
    return NewsQualityReport(
        status=status,
        document_count=len(documents),
        event_count=len(events),
        citation_eligible_count=citation_count,
        background_only_count=background_count,
        excluded_after_cutoff_count=excluded_count,
        source_statuses=dict(source_statuses),
        blocking_reasons=tuple(blocking),
    )
