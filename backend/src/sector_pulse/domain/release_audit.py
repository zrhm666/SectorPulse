from datetime import datetime
from enum import StrEnum
from typing import Any
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field


class ApprovalStatus(StrEnum):
    APPROVED_FOR_COPY = "APPROVED_FOR_COPY"
    REVOKED = "REVOKED"


class DraftApproval(BaseModel):
    model_config = ConfigDict(frozen=True)

    approval_id: UUID = Field(default_factory=uuid4)
    run_id: UUID
    draft_id: UUID
    version: int = Field(ge=1)
    governance_hash: str = Field(min_length=1)
    actor: str = Field(min_length=1)
    status: ApprovalStatus = ApprovalStatus.APPROVED_FOR_COPY
    approved_at: datetime


class AuditEvent(BaseModel):
    model_config = ConfigDict(frozen=True)

    event_id: UUID = Field(default_factory=uuid4)
    run_id: UUID
    draft_id: UUID
    version: int = Field(ge=1)
    event_type: str = Field(min_length=1)
    actor: str = Field(min_length=1)
    payload: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime


class DraftExport(BaseModel):
    model_config = ConfigDict(frozen=True)

    export_id: UUID = Field(default_factory=uuid4)
    run_id: UUID
    draft_id: UUID
    version: int = Field(ge=1)
    format: str = Field(pattern="^(json|md|txt)$")
    content_hash: str = Field(min_length=1)
    actor: str = Field(min_length=1)
    created_at: datetime
