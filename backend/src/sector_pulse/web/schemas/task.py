from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class ScheduleCreateRequest(BaseModel):
    model_config = ConfigDict(frozen=True)

    name: str = Field(min_length=1)
    mode: str
    timezone: str
    local_time: str
    trading_days: str = "weekdays"
    enabled: bool = True
    input_template: dict[str, object] = {}


class ScheduleResponse(ScheduleCreateRequest):
    schedule_id: UUID
    version: int
    next_run_at: datetime | None
    created_at: datetime
    updated_at: datetime


class TaskRunResponse(BaseModel):
    run_id: UUID
    status: str
    provider: str
    input_fingerprint: str
    requested_at: datetime
    started_at: datetime | None = None
    finished_at: datetime | None = None
    error_code: str | None = None
