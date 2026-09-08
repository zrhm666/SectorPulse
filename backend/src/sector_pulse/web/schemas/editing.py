from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field

from sector_pulse.domain.editing import DraftPatch


class DraftPatchRequest(BaseModel):
    base_version: int = Field(ge=1)
    operations: tuple[DraftPatch, ...]


class DraftPatchResponse(BaseModel):
    draft_id: UUID
    version: int
    status: str
    content: dict[str, Any]


class GovernanceResponse(BaseModel):
    status: str
    issues: tuple[dict[str, str], ...]
    rules_version: str
