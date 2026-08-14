from datetime import datetime, timedelta
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, field_validator


class SourceGrade(StrEnum):
    PRIMARY = "PRIMARY"
    REPUTABLE_MEDIA = "REPUTABLE_MEDIA"
    DISCOVERY_ONLY = "DISCOVERY_ONLY"


class NewsUse(StrEnum):
    EVIDENCE = "EVIDENCE"
    BACKGROUND = "BACKGROUND"
    EXCLUDED = "EXCLUDED"


class NewsDocument(BaseModel):
    """规范化新闻元数据；正文内容不进入领域对象。"""

    model_config = ConfigDict(frozen=True)

    document_id: str
    source_id: str
    url: str
    title: str
    published_at: datetime | None
    observed_at: datetime
    content_hash: str
    source_grade: SourceGrade

    @field_validator("published_at", "observed_at")
    @classmethod
    def require_utc(cls, value: datetime | None) -> datetime | None:
        if value is not None and (
            value.tzinfo is None or value.utcoffset() != timedelta(0)
        ):
            raise ValueError("news datetime must use UTC")
        return value

    def use_at(self, cutoff: datetime) -> NewsUse:
        """决定新闻在指定 cutoff 下可用于证据、背景或必须排除。"""
        if cutoff.tzinfo is None or cutoff.utcoffset() != timedelta(0):
            raise ValueError("cutoff must use UTC")
        if self.observed_at > cutoff:
            return NewsUse.EXCLUDED
        if self.published_at is None:
            return NewsUse.BACKGROUND
        if self.published_at > cutoff:
            return NewsUse.EXCLUDED
        return NewsUse.EVIDENCE


class NewsEvent(BaseModel):
    """由一篇或多篇转载/改写文档聚合出的新闻事件。"""

    model_config = ConfigDict(frozen=True)

    event_id: str
    canonical_title: str
    first_published_at: datetime | None
    document_ids: tuple[str, ...]
    deduplication_reason: str
    sector_ids: tuple[str, ...] = ()

    @field_validator("first_published_at")
    @classmethod
    def require_utc(cls, value: datetime | None) -> datetime | None:
        if value is not None and (
            value.tzinfo is None or value.utcoffset() != timedelta(0)
        ):
            raise ValueError("event datetime must use UTC")
        return value
