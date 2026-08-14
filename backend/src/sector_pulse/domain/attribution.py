from collections.abc import Mapping
from datetime import datetime, timedelta
from decimal import Decimal
from enum import StrEnum
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from sector_pulse.domain.evidence import EvidenceLevel
from sector_pulse.domain.market import SectorKind
from sector_pulse.domain.news import SourceGrade

LEVEL_RANK = {
    EvidenceLevel.NO_RELIABLE_EXPLANATION: 0,
    EvidenceLevel.MARKET_ASSOCIATION: 1,
    EvidenceLevel.POSSIBLE_CATALYST: 2,
    EvidenceLevel.EXPLICIT_DRIVER: 3,
}


class ClaimKind(StrEnum):
    MARKET_FACT = "MARKET_FACT"
    NEWS_FACT = "NEWS_FACT"
    ATTRIBUTION = "ATTRIBUTION"
    BACKGROUND = "BACKGROUND"


class Claim(BaseModel):
    model_config = ConfigDict(frozen=True)
    claim_id: str
    kind: ClaimKind
    text: str
    fact_keys: tuple[str, ...] = ()
    evidence_ids: tuple[str, ...] = ()
    attribution_level: EvidenceLevel | None = None


class AttributionContext(BaseModel):
    model_config = ConfigDict(frozen=True)
    run_id: UUID
    sector_id: str
    sector_kind: SectorKind
    cutoff_at: datetime
    market_facts: Mapping[str, Any]
    event_ids: tuple[str, ...]
    eligible_event_ids: tuple[str, ...]
    background_event_ids: tuple[str, ...]
    excluded_event_ids: tuple[str, ...]
    source_grades: Mapping[str, SourceGrade]
    counter_evidence: tuple[str, ...]

    @field_validator("cutoff_at")
    @classmethod
    def require_utc(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() != timedelta(0):
            raise ValueError("cutoff must use UTC")
        return value


class AttributionGateResult(BaseModel):
    model_config = ConfigDict(frozen=True)
    run_id: UUID
    sector_id: str
    allowed_max_level: EvidenceLevel
    reasons: tuple[str, ...]
    eligible_evidence_ids: tuple[str, ...]
    excluded_evidence_ids: tuple[str, ...]
    counter_evidence: tuple[str, ...]


class SectorAnalysisCard(BaseModel):
    model_config = ConfigDict(frozen=True)
    run_id: UUID
    sector_id: str
    sector_kind: SectorKind
    allowed_max_level: EvidenceLevel
    attribution_level: EvidenceLevel
    confidence: Decimal = Field(ge=0, le=1)
    conclusion: str
    supporting_evidence_ids: tuple[str, ...]
    counter_evidence: tuple[str, ...]
    uncertainties: tuple[str, ...]
    background_event_ids: tuple[str, ...]
    claims: tuple[Claim, ...]
    forbidden_inferences: tuple[str, ...]

    @model_validator(mode="after")
    def enforce_level_ceiling(self) -> "SectorAnalysisCard":
        if LEVEL_RANK[self.attribution_level] > LEVEL_RANK[self.allowed_max_level]:
            raise ValueError("attribution level exceeds allowed maximum")
        return self
