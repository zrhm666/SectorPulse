from datetime import date, datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field


class ShadowRunRequest(BaseModel):
    run_id: UUID
    trading_date: date
    mode: str = "intraday"
    provider_status: dict[str, Any] = Field(default_factory=dict)


class ShadowRunResponse(BaseModel):
    shadow_id: UUID
    run_id: UUID
    trading_date: date
    mode: str
    status: str
    created_at: datetime
