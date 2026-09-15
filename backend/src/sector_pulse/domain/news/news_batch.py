from collections.abc import Mapping
from enum import StrEnum
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field

from sector_pulse.domain.market.quality import QualityStatus
from sector_pulse.domain.news.news_retrieval import SourceRunMetric
from sector_pulse.domain.provider import DataStatus


class NewsCollectionReason(StrEnum):
    INITIAL_CANDIDATES = "INITIAL_CANDIDATES"
    SOURCE_GAP = "SOURCE_GAP"
    COVERAGE_GAP = "COVERAGE_GAP"


class NewsBatchQuality(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    status: QualityStatus
    document_count: int = Field(ge=0)
    event_count: int = Field(ge=0)
    citation_eligible_count: int = Field(ge=0)
    background_only_count: int = Field(ge=0)
    excluded_after_cutoff_count: int = Field(ge=0)
    source_statuses: Mapping[str, DataStatus]
    blocking_reasons: tuple[str, ...] = ()


class NewsBatch(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    batch_id: UUID
    run_id: UUID
    candidate_batch_id: UUID
    input_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    collection_reason: NewsCollectionReason
    start_at: AwareDatetime
    cutoff_at: AwareDatetime
    document_ids: tuple[str, ...]
    event_ids: tuple[str, ...]
    link_count: int = Field(ge=0)
    source_metrics: tuple[SourceRunMetric, ...]
    quality: NewsBatchQuality
    created_at: AwareDatetime

    @property
    def document_count(self) -> int:
        return len(self.document_ids)

    @property
    def event_count(self) -> int:
        return len(self.event_ids)
