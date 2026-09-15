from enum import StrEnum
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field

from sector_pulse.domain.market.candidate import SectorCandidate


class CandidateRankingStage(StrEnum):
    MARKET = "MARKET"
    NEWS_ENRICHED = "NEWS_ENRICHED"


class CandidateBatch(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    batch_id: UUID
    run_id: UUID
    input_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    ranking_stage: CandidateRankingStage
    candidate_limit: int = Field(ge=1, le=50)
    created_at: AwareDatetime
    candidates: tuple[SectorCandidate, ...]
