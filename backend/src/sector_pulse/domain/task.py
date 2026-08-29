from datetime import datetime
from enum import StrEnum
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class ScheduleMode(StrEnum):
    INTRADAY = "intraday"
    POST_CLOSE = "post_close"
    MANUAL = "manual"


class TaskRunStatus(StrEnum):
    QUEUED = "QUEUED"
    RUNNING = "RUNNING"
    RETRY_WAITING = "RETRY_WAITING"
    DEGRADED = "DEGRADED"
    READY_FOR_HUMAN_REVIEW = "READY_FOR_HUMAN_REVIEW"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"
    INTERRUPTED = "INTERRUPTED"

    @property
    def is_terminal(self) -> bool:
        return self in {
            self.DEGRADED,
            self.READY_FOR_HUMAN_REVIEW,
            self.FAILED,
            self.CANCELLED,
            self.INTERRUPTED,
        }


class TaskStage(StrEnum):
    FETCHING_MARKET = "FETCHING_MARKET"
    FETCHING_NEWS = "FETCHING_NEWS"
    QUALITY_CHECKED = "QUALITY_CHECKED"
    ATTRIBUTING = "ATTRIBUTING"
    WRITING = "WRITING"


class TaskRunKey(BaseModel):
    model_config = ConfigDict(frozen=True)

    schedule_id: UUID | None = None
    trading_date: str | None = None
    planned_slot: str | None = None
    input_fingerprint: str = Field(min_length=1)


class StageAttempt(BaseModel):
    model_config = ConfigDict(frozen=True)

    run_id: UUID
    stage: TaskStage
    attempt_no: int = Field(ge=1)
    status: TaskRunStatus
    input_fingerprint: str
    provider: str | None = None
    error_code: str | None = None
    started_at: datetime
    finished_at: datetime | None = None


class Checkpoint(BaseModel):
    model_config = ConfigDict(frozen=True)

    checkpoint_id: UUID
    run_id: UUID
    stage: TaskStage
    input_fingerprint: str
    implementation_version: str
    payload: dict[str, Any]
    payload_sha256: str
    created_at: datetime
