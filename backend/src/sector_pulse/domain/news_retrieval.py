from datetime import datetime, timedelta
from enum import StrEnum
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from sector_pulse.domain.market import SectorKind
from sector_pulse.domain.news import SourceGrade
from sector_pulse.domain.provider import AuthorizationStatus, DataStatus


class QueryType(StrEnum):
    GLOBAL = "GLOBAL"
    KEYWORD = "KEYWORD"
    DISCLOSURE = "DISCLOSURE"


class MappingConfidence(StrEnum):
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"


class NewsSourceDefinition(BaseModel):
    model_config = ConfigDict(frozen=True)

    source_id: str
    provider_type: str
    enabled: bool = True
    authorization_status: AuthorizationStatus
    default_source_grade: SourceGrade
    timeout_seconds: float = Field(gt=0, le=30)
    max_retries: int = Field(ge=0, le=2)
    rate_limit_per_second: float = Field(gt=0, le=10)
    max_results_per_query: int = Field(gt=0, le=200)


class NewsQuery(BaseModel):
    model_config = ConfigDict(frozen=True)

    query_id: str
    query_type: QueryType
    source_id: str
    value: str
    sector_ids: tuple[str, ...] = ()
    priority: int = Field(ge=1, le=100)
    start_at: datetime
    cutoff_at: datetime

    @field_validator("start_at", "cutoff_at")
    @classmethod
    def require_utc(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() != timedelta(0):
            raise ValueError("query datetime must use UTC")
        return value

    @model_validator(mode="after")
    def validate_window(self) -> "NewsQuery":
        if self.cutoff_at < self.start_at:
            raise ValueError("query cutoff cannot precede start")
        return self


class NewsQueryPlan(BaseModel):
    model_config = ConfigDict(frozen=True)

    rule_version: str
    queries: tuple[NewsQuery, ...]
    keyword_budget: int = 24
    disclosure_code_budget: int = 12
    concurrency_per_provider: int = 4


class SectorEntityConfig(BaseModel):
    model_config = ConfigDict(frozen=True)

    version: str
    aliases: dict[str, tuple[str, ...]]
    industry_terms: dict[str, tuple[str, ...]]
    ambiguous_terms: tuple[str, ...]


class SectorEventLink(BaseModel):
    model_config = ConfigDict(frozen=True)

    run_id: UUID
    event_id: str
    sector_id: str
    sector_kind: SectorKind
    relation_type: str
    matched_entities: tuple[str, ...]
    mapping_confidence: MappingConfidence
    mapping_reason: str
    rule_version: str


class SourceRunMetric(BaseModel):
    model_config = ConfigDict(frozen=True)

    run_id: UUID
    source_id: str
    started_at: datetime
    completed_at: datetime
    call_count: int
    retry_count: int
    status: DataStatus
    duration_ms: int
    error_code: str | None = None

    @model_validator(mode="after")
    def validate_times(self) -> "SourceRunMetric":
        if self.started_at.tzinfo is None or self.completed_at.tzinfo is None:
            raise ValueError("source metric datetimes must use timezone")
        if self.completed_at < self.started_at:
            raise ValueError("source metric completed_at cannot precede started_at")
        return self
