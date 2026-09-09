import hashlib
import json
from datetime import datetime, timedelta
from enum import StrEnum
from typing import Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from sector_pulse.domain.runs.real_data_run import RealDataCandidate


class CandidateSelectionMethod(StrEnum):
    DEFAULT = "DEFAULT"
    MANUAL = "MANUAL"


class CandidateSelectionVersionConflict(ValueError):
    """Raised when a caller appends against a stale or non-sequential version."""


class CandidateSelection(BaseModel):
    model_config = ConfigDict(frozen=True)

    run_id: UUID
    version: int = Field(ge=1)
    selected_sector_ids: tuple[str, ...] = Field(min_length=3, max_length=12)
    method: CandidateSelectionMethod
    confirmed_at: datetime
    data_version: str = Field(pattern=r"^[0-9a-f]{64}$")
    edit_count: int = Field(default=0, ge=0)

    @field_validator("confirmed_at")
    @classmethod
    def require_utc(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() != timedelta(0):
            raise ValueError("candidate selection confirmation time must use UTC")
        return value

    @model_validator(mode="after")
    def require_unique_sector_ids(self) -> Self:
        if len(set(self.selected_sector_ids)) != len(self.selected_sector_ids):
            raise ValueError("candidate selection sector ids must be unique")
        return self


def candidate_data_version(candidates: tuple[RealDataCandidate, ...]) -> str:
    payload = [
        {
            "sector_id": item.sector_id,
            "sector_kind": item.sector_kind.value,
            "rank": item.rank,
            "score": str(item.score),
        }
        for item in sorted(candidates, key=lambda item: (item.rank, item.sector_id))
    ]
    encoded = json.dumps(payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()
