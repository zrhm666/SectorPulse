from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field


class NewDataRunRequest(BaseModel):
    mode: Literal["intraday", "post_close"]
    provider: Literal["fixture", "live"] = "live"
    lookback_hours: int | None = Field(default=None, ge=1, le=168)
    precandidate_limit: int = Field(default=30, ge=1, le=30)
    final_candidate_limit: int = Field(default=12, ge=1, le=12)


class GenerateDataRunRequest(BaseModel):
    sector_ids: list[str] | None = Field(default=None, min_length=3, max_length=12)


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
