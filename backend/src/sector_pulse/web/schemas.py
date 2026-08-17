# backend/src/sector_pulse/web/schemas.py
from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel


class NewRunRequest(BaseModel):
    input_json: dict[str, Any]
    provider: str = "fixture"


class NewRunResponse(BaseModel):
    run_id: UUID


class RunSummary(BaseModel):
    run_id: UUID
    requested_at: datetime
    provider: str
    status: str
    elapsed_ms: int | None
    total_cost_cny: str | None
    draft_id: UUID | None


class RunDetail(RunSummary):
    input_json_hash: str | None
    error_message: str | None
    sector_count: int
    review_decision: str | None


class RadarCard(BaseModel):
    sector_id: str
    sector_kind: str
    attribution_level: str
    allowed_max_level: str
    confidence: str
    conclusion: str
    supporting_evidence_ids: list[str]
    counter_evidence: list[str]
    uncertainties: list[str]
    forbidden_inferences: list[str]
    claims: list[dict[str, Any]]


class RadarResponse(BaseModel):
    cards: list[RadarCard]


class DraftVersion(BaseModel):
    version: int
    status: str
    titles: list[str]
    introduction: str
    sections: list[dict[str, Any]]
    conclusion: str
    risk_notice: str
    sources: list[dict[str, Any]]
    character_count: int


class DraftResponse(BaseModel):
    versions: list[DraftVersion]


class EvidenceResponse(BaseModel):
    sectors: list[dict[str, Any]]
    events: list[dict[str, Any]]
    invocations: list[dict[str, Any]]


class ReviewResponse(BaseModel):
    decision: str | None
    revision_round: int | None
    issues: list[dict[str, Any]]
