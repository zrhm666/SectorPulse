from datetime import datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from sector_pulse.domain.news.evidence import EvidenceLevel
from sector_pulse.domain.news.news import NewsUse, SourceGrade
from sector_pulse.domain.writing.attribution import (
    AttributionContext,
    AttributionGateResult,
    Claim,
    SectorAnalysisCard,
)


class EvidenceDocumentView(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    document_id: str
    title: str
    publisher: str | None = None
    citation_url: str | None = None
    published_at: datetime | None = None
    source_grade: SourceGrade
    use: NewsUse
    detail_availability: str | None = None
    content: str = Field(default="", max_length=12000)
    historical_snapshot_verified: bool = False


class EvidenceInspectionReport(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    report_id: UUID
    run_id: UUID
    task_id: UUID
    attempt: int = Field(ge=1)
    sector_id: str
    selection_version: int = Field(ge=1)
    input_artifact_ids: tuple[UUID, ...]
    input_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    context: AttributionContext
    gate: AttributionGateResult
    document_views: tuple[EvidenceDocumentView, ...]
    created_at: datetime


class SectorAnalysisSubmission(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    attribution_level: EvidenceLevel
    confidence: Decimal = Field(ge=0, le=1)
    conclusion: str
    supporting_evidence_ids: tuple[str, ...] = ()
    uncertainties: tuple[str, ...] = ()
    background_event_ids: tuple[str, ...] = ()
    claims: tuple[Claim, ...] = ()
    forbidden_inferences: tuple[str, ...] = ()


class SectorAnalysisArtifact(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    analysis_id: UUID
    run_id: UUID
    task_id: UUID
    attempt: int = Field(ge=1)
    inspection_id: UUID
    input_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    card_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    card: SectorAnalysisCard
    created_at: datetime


__all__ = [
    "EvidenceDocumentView",
    "EvidenceInspectionReport",
    "SectorAnalysisArtifact",
    "SectorAnalysisSubmission",
]
