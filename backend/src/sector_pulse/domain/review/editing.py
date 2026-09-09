from datetime import datetime
from enum import StrEnum
from typing import Any
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, model_validator

EDITABLE_PATH_PREFIXES = (
    "titles",
    "introduction",
    "sections/",
    "conclusion",
    "risk_notice",
)
FORBIDDEN_PATH_PARTS = ("source_ids", "claim_ids", "citation_url", "cutoff")


class DraftPatch(BaseModel):
    model_config = ConfigDict(frozen=True)

    patch_id: UUID = Field(default_factory=uuid4)
    path: str = Field(min_length=1)
    old_value_hash: str = Field(min_length=1)
    value: Any

    @model_validator(mode="after")
    def validate_path(self) -> "DraftPatch":
        if not self.path.startswith(EDITABLE_PATH_PREFIXES) or any(
            part in self.path for part in FORBIDDEN_PATH_PARTS
        ):
            raise ValueError("path is not editable")
        return self


class EvidenceDecisionKind(StrEnum):
    KEEP = "KEEP"
    DOWNGRADE = "DOWNGRADE"
    REJECT = "REJECT"


class EvidenceDecision(BaseModel):
    model_config = ConfigDict(frozen=True)

    decision_id: UUID = Field(default_factory=uuid4)
    run_id: UUID
    draft_id: UUID
    draft_version: int = Field(ge=1)
    source_id: str
    decision: EvidenceDecisionKind
    reason: str = Field(min_length=1)
    affected_section_ids: tuple[str, ...] = ()
    created_at: datetime


class RewriteRequest(BaseModel):
    model_config = ConfigDict(frozen=True)

    rewrite_id: UUID = Field(default_factory=uuid4)
    run_id: UUID
    draft_id: UUID
    base_version: int = Field(ge=1)
    section_id: str
    status: str
    error_code: str | None = None
    result_version: int | None = None


class GovernanceCheck(BaseModel):
    model_config = ConfigDict(frozen=True)

    check_id: UUID = Field(default_factory=uuid4)
    draft_id: UUID
    draft_version: int = Field(ge=1)
    check_type: str
    status: str
    issues: tuple[dict[str, Any], ...] = ()
    rules_version: str
    created_at: datetime


class PreferenceCandidate(BaseModel):
    model_config = ConfigDict(frozen=True)

    candidate_id: UUID = Field(default_factory=uuid4)
    source_patch_id: UUID
    content: dict[str, Any]
    status: str = "PENDING"
    created_at: datetime


class PreferenceVersion(BaseModel):
    model_config = ConfigDict(frozen=True)

    version: int = Field(ge=1)
    content: dict[str, Any]
    adopted_at: datetime
    active: bool = True
