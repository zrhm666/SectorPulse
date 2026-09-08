"""Read-only comparison contracts; unknown observations stay explicitly nullable."""

from datetime import datetime
from decimal import Decimal
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from sector_pulse.domain.market import SectorKind
from sector_pulse.domain.real_data_run import RealDataRunStatus

Provider = Literal["fixture", "live"]
RunMode = Literal["intraday", "post_close"]
Membership = Literal["BOTH", "ONLY_BASE", "ONLY_COMPARE"]
MembershipFilter = Literal["ALL", "BOTH", "ONLY_BASE", "ONLY_COMPARE"]
MissingReason = Literal["VALUE_MISSING", "FIELD_UNDECLARED", "SECTOR_MISSING"]
MetricUnit = Literal["percentage_points", "count"]
WarningCode = Literal[
    "SOURCE_VERSION_DIFF",
    "NEWS_WINDOW_DIFF",
    "CANDIDATE_LIMIT_DIFF",
    "RUN_PARTIAL",
    "CUTOFF_MISSING",
    "REVERSED_TIME",
    "CLASSIFICATION_MISMATCH",
    "SNAPSHOT_MISSING",
    "FIELD_SCHEMA_UNKNOWN",
    "NEWS_LINEAGE_UNVERIFIABLE",
    "CURRENT_NEWS_METADATA",
]


class ComparisonModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", allow_inf_nan=False)


class RunOption(ComparisonModel):
    run_id: UUID
    provider: Provider
    mode: RunMode
    status: RealDataRunStatus
    requested_at: datetime
    cutoff_at: datetime | None
    finished_at: datetime | None
    lookback_hours: int
    precandidate_limit: int
    final_candidate_limit: int
    error_code: str | None


class RunOptionPage(ComparisonModel):
    items: list[RunOption]
    total: int
    offset: int
    limit: int


class ComparisonWarning(ComparisonModel):
    code: WarningCode
    message: str
    side: Literal["BASE", "COMPARE", "BOTH"] = "BOTH"
    kind: SectorKind | None = None


class SnapshotContext(ComparisonModel):
    provider_id: str
    classification_version: str
    source_version: str
    observed_at: datetime
    collected_at: datetime
    available_fields: list[str]


class MetricDifference(ComparisonModel):
    base: Decimal | None
    compare: Decimal | None
    delta: Decimal | None
    unit: MetricUnit
    base_reason: MissingReason | None
    compare_reason: MissingReason | None


class SectorComparisonRow(ComparisonModel):
    sector_id: str
    kind: SectorKind
    base_name: str | None
    compare_name: str | None
    membership: Membership
    base_rank: int | None
    compare_rank: int | None
    rank_delta: int | None
    base_score: Decimal | None
    compare_score: Decimal | None
    base_leader: str | None
    compare_leader: str | None
    pct_change: MetricDifference
    turnover_rate: MetricDifference
    advancers: MetricDifference
    decliners: MetricDifference


class KindComparison(ComparisonModel):
    kind: SectorKind
    status: Literal["COMPARABLE", "UNAVAILABLE", "INCOMPATIBLE"]
    base: SnapshotContext | None
    compare: SnapshotContext | None
    rows: list[SectorComparisonRow]


class CandidateCounts(ComparisonModel):
    both: int
    only_base: int
    only_compare: int
    unavailable_kinds: int


class NewsCoverage(ComparisonModel):
    lineage: Literal["RECORDED", "UNVERIFIABLE"]
    recorded_count: int


class NewsCounts(ComparisonModel):
    both: int
    only_base: int
    only_compare: int


class RunComparisonView(ComparisonModel):
    base: RunOption
    compare: RunOption
    queried_at: datetime
    warnings: list[ComparisonWarning]
    candidates: CandidateCounts
    kinds: list[KindComparison]
    base_news: NewsCoverage
    compare_news: NewsCoverage
    news_counts: NewsCounts | None


class CurrentNewsMetadata(ComparisonModel):
    title: str
    source_id: str
    publisher: str | None
    summary: str | None
    citation_url: str | None
    published_at: datetime | None
    metadata_scope: Literal["CURRENT_STORED"] = "CURRENT_STORED"


class NewsComparisonRow(ComparisonModel):
    document_id: str
    membership: Membership
    metadata: CurrentNewsMetadata | None


class NewsComparisonPage(ComparisonModel):
    available: bool
    reason: Literal["LINEAGE_UNVERIFIABLE"] | None
    base_news: NewsCoverage
    compare_news: NewsCoverage
    counts: NewsCounts | None
    items: list[NewsComparisonRow]
    total: int | None
    offset: int
    limit: int


class EvidenceLinkView(ComparisonModel):
    relation_type: str
    mapping_confidence: str
    mapping_reason: str
    rule_version: str


class EvidenceComparisonRow(ComparisonModel):
    sector_id: str
    event_id: str
    kind: SectorKind
    membership: Membership
    base: EvidenceLinkView | None
    compare: EvidenceLinkView | None
    current_event_title: str | None
    metadata_scope: Literal["CURRENT_STORED"] = "CURRENT_STORED"


class EvidenceComparisonPage(ComparisonModel):
    items: list[EvidenceComparisonRow]
    total: int
    offset: int
    limit: int
    unavailable_kinds: list[SectorKind]
