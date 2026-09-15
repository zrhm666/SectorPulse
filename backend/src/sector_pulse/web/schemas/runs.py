# backend/src/sector_pulse/web/schemas.py
from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from sector_pulse.domain.writing.attribution_mode import AttributionMode


class NewRunRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    input_json: dict[str, Any]
    provider: Literal["fixture", "live"] = "fixture"
    selection_policy: Literal["manual", "server_default"] = "manual"

    @model_validator(mode="before")
    @classmethod
    def reject_removed_execution_mode(cls, value: Any) -> Any:
        if not isinstance(value, dict):
            return value
        nested = value.get("input_json")
        nested_input = nested if isinstance(nested, dict) else {}
        for legacy_key in ("attribution_mode", "workflow", "agent"):
            if legacy_key in value or legacy_key in nested_input:
                raise ValueError(
                    f"{legacy_key} has been removed; all new runs use the multi-agent engine"
                )
        return value


class NewRunResponse(BaseModel):
    run_id: UUID
    execution_engine: Literal["multi_agent", "legacy"]


class RunCandidateItem(BaseModel):
    sector_id: str
    sector_kind: str
    name: str
    rank: int
    score: str
    explanation: str


class RunSelectionProposalResponse(BaseModel):
    run_id: UUID
    proposal_id: UUID
    proposal_artifact_id: UUID
    selection_version: int
    attempt: int
    items: tuple[RunCandidateItem, ...]


class RunSelectionConfirmRequest(BaseModel):
    proposal_id: UUID
    sector_ids: tuple[str, ...] = Field(min_length=3, max_length=12)
    expected_selection_version: int = Field(ge=0)
    expected_attempt: int = Field(ge=1)


class RunSelectionAcceptedResponse(BaseModel):
    run_id: UUID
    accepted: Literal[True] = True
    next_attempt: int


class RunSummary(BaseModel):
    attribution_mode: AttributionMode | None = None
    run_id: UUID
    execution_engine: Literal["multi_agent", "legacy"] = "legacy"
    requested_at: datetime
    provider: str
    status: str
    elapsed_ms: int | None
    total_cost_cny: str | None
    draft_id: UUID | None
    retry_of_run_id: UUID | None = None


class RunDetail(RunSummary):
    input_json_hash: str | None
    error_message: str | None
    sector_count: int
    review_decision: str | None
    retryable: bool


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
