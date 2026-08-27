from datetime import datetime
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
