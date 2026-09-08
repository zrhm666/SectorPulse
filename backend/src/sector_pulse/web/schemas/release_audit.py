from typing import Any

from pydantic import BaseModel


class ApprovalResponse(BaseModel):
    draft_id: str
    version: int
    status: str
    actor: str


class AuditEventResponse(BaseModel):
    event_type: str
    version: int
    actor: str
    created_at: str
    payload: dict[str, Any]
