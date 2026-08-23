from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field


class EvidenceDecisionRequest(BaseModel):
    source_id: str = Field(min_length=1)
    decision: Literal["KEEP", "DOWNGRADE", "REJECT"]
    reason: str = Field(min_length=1)


class EvidenceDecisionResponse(BaseModel):
    decision_id: UUID
    run_id: UUID
    draft_id: UUID
    draft_version: int
    source_id: str
    decision: str
    reason: str
    affected_section_ids: tuple[str, ...]
    created_at: datetime


class ReturnDraftRequest(BaseModel):
    reason: str = Field(min_length=1)


class ReturnDraftResponse(BaseModel):
    draft_id: UUID
    version: int
    status: str
    actor: str
