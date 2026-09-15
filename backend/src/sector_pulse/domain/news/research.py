from datetime import datetime
from enum import StrEnum
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from sector_pulse.domain.market.market import SectorKind


class ResearchSearchStatus(StrEnum):
    SUCCESS = "SUCCESS"
    EMPTY = "EMPTY"
    FAILED = "FAILED"


class ResearchSearchBatch(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    batch_id: UUID
    run_id: UUID
    task_id: UUID
    attempt: int = Field(ge=1)
    sector_id: str
    sector_kind: SectorKind
    query: str
    start_at: datetime
    cutoff_at: datetime
    input_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    status: ResearchSearchStatus
    error_code: str | None = None
    document_ids: tuple[str, ...]
    event_ids: tuple[str, ...]
    created_at: datetime


class NewsDetailSnapshot(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    detail_id: UUID
    run_id: UUID
    task_id: UUID
    attempt: int = Field(ge=1)
    sector_id: str
    sector_kind: SectorKind
    document_id: str
    document_content_hash: str
    input_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    availability: Literal["full_text", "summary_only", "unavailable"]
    content: str = Field(max_length=12000)
    content_hash: str
    fetched_at: datetime
    truncated: bool = False
    historical_snapshot_verified: bool = False
    error_code: str | None = None
    created_at: datetime


__all__ = ["NewsDetailSnapshot", "ResearchSearchBatch", "ResearchSearchStatus"]
