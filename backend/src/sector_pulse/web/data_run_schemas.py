from datetime import datetime
from decimal import Decimal
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from sector_pulse.domain.candidate_selection import CandidateSelectionMethod


class NewDataRunRequest(BaseModel):
    mode: Literal["intraday", "post_close"]
    provider: Literal["fixture", "live"] = "live"
    lookback_hours: int | None = Field(default=None, ge=1, le=168)
    precandidate_limit: int = Field(default=30, ge=1, le=30)
    final_candidate_limit: int = Field(default=12, ge=1, le=12)


class GenerateDataRunRequest(BaseModel):
    sector_ids: list[str] | None = Field(default=None, min_length=3, max_length=12)


class CandidateSelectionConfirmRequest(BaseModel):
    sector_ids: list[str] = Field(min_length=3, max_length=12)
    expected_version: int = Field(ge=0)


class CandidateSelectionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    run_id: UUID
    confirmed: bool = True
    version: int
    selected_sector_ids: tuple[str, ...]
    method: CandidateSelectionMethod | None
    confirmed_at: datetime | None
    data_version: str
    edit_count: int


class DataRunCandidateWorkbenchItem(BaseModel):
    sector_id: str
    sector_kind: str
    rank: int
    score: Decimal
    reasons: tuple[str, ...]
    name: str | None
    pct_change: Decimal | None
    turnover_rate: Decimal | None
    total_market_cap: Decimal | None
    advancers: int | None
    decliners: int | None
    leader_name: str | None
    leader_pct_change: Decimal | None
    field_availability: dict[str, bool]
    news_count: int


class DataRunCandidatePageResponse(BaseModel):
    items: tuple[DataRunCandidateWorkbenchItem, ...]
    total: int
    offset: int
    limit: int
    query: str | None
    sort: str
    direction: str
    data_version: str


class DataRunWorkflowSummaryResponse(BaseModel):
    run_id: UUID
    status: str
    workflow_stage: str
    workflow_stage_index: int
    terminal: bool
    requested_at: datetime
    cutoff_at: datetime | None
    finished_at: datetime | None
    candidate_count: int


class DataRunNewsDetailResponse(BaseModel):
    document_id: str
    source_id: str
    citation_url: str | None
    title: str
    publisher: str | None
    summary: str | None
    content_kind: Literal["FULL_TEXT", "SUMMARY", "FLASH", "LINK_ONLY"]
    content: str | None
    content_available: bool
    published_at: datetime | None
    source_observed_at: datetime | None
    collected_at: datetime
    source_grade: str


class DataRunResponse(BaseModel):
    run_id: UUID
    mode: str
    status: str
    requested_at: datetime
    quality: dict[str, Any] = {}
    downgrade_reasons: list[str] = []


class DataRunCandidateResponse(BaseModel):
    sector_id: str
    sector_kind: str
    rank: int
    score: str
    reasons: list[str]
