from datetime import UTC, datetime
from decimal import Decimal
from enum import StrEnum
from typing import Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, model_validator

from sector_pulse.domain.market import SectorKind
from sector_pulse.domain.quality import QualityStatus


class RealDataRunStatus(StrEnum):
    PREFLIGHT = "PREFLIGHT"
    FETCHING_MARKET = "FETCHING_MARKET"
    RANKING_PRE_CANDIDATES = "RANKING_PRE_CANDIDATES"
    FETCHING_NEWS = "FETCHING_NEWS"
    BUILDING_EVIDENCE = "BUILDING_EVIDENCE"
    READY_FOR_ATTRIBUTION = "READY_FOR_ATTRIBUTION"
    DEGRADED = "DEGRADED"
    BLOCKED = "BLOCKED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"
    INTERRUPTED = "INTERRUPTED"

    @property
    def is_terminal(self) -> bool:
        return self in {
            self.READY_FOR_ATTRIBUTION,
            self.DEGRADED,
            self.BLOCKED,
            self.FAILED,
            self.CANCELLED,
            self.INTERRUPTED,
        }


class RealDataRunRequest(BaseModel):
    """真实数据运行的不可变边界；模式默认值在入口统一展开。"""

    model_config = ConfigDict(frozen=True)

    mode: Literal["intraday", "post_close"]
    requested_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    lookback_hours: int | None = Field(default=None, ge=1, le=168)
    precandidate_limit: int = Field(default=30, ge=1, le=30)
    final_candidate_limit: int = Field(default=12, ge=1, le=12)

    @model_validator(mode="after")
    def apply_mode_default(self) -> "RealDataRunRequest":
        if self.lookback_hours is None:
            object.__setattr__(self, "lookback_hours", 6 if self.mode == "intraday" else 24)
        return self


class RealDataCandidate(BaseModel):
    model_config = ConfigDict(frozen=True)

    sector_id: str
    sector_kind: SectorKind
    rank: int = Field(ge=1)
    score: Decimal
    reasons: tuple[str, ...] = ()


class RealDataQualitySummary(BaseModel):
    model_config = ConfigDict(frozen=True)

    market_quality: dict[str, QualityStatus] = {}
    news_quality: dict[str, QualityStatus] = {}
    cutoff_violation_count: int = Field(default=0, ge=0)
    duplicate_document_count: int = Field(default=0, ge=0)
    downgrade_reasons: tuple[str, ...] = ()


class RealDataRun(BaseModel):
    model_config = ConfigDict(frozen=True)

    run_id: UUID = Field(default_factory=uuid4)
    provider: Literal["fixture", "live"] = "live"
    request: RealDataRunRequest
    status: RealDataRunStatus = RealDataRunStatus.PREFLIGHT
    cutoff_at: datetime | None = None
    quality: RealDataQualitySummary = Field(default_factory=RealDataQualitySummary)
    candidates: tuple[RealDataCandidate, ...] = ()
    error_code: str | None = None
    finished_at: datetime | None = None
