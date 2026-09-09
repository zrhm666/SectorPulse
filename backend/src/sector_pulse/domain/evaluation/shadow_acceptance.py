from datetime import date, datetime
from enum import StrEnum
from typing import Any
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field


class ShadowRunStatus(StrEnum):
    STARTED = "STARTED"
    PASSED = "PASSED"
    FAILED = "FAILED"
    BLOCKED = "BLOCKED"


class ShadowRun(BaseModel):
    model_config = ConfigDict(frozen=True)

    shadow_id: UUID = Field(default_factory=uuid4)
    run_id: UUID
    trading_date: date
    mode: str
    status: ShadowRunStatus = ShadowRunStatus.STARTED
    provider_status: dict[str, Any] = Field(default_factory=dict)
    cutoff_at: datetime | None = None
    metrics: dict[str, Any] = Field(default_factory=dict)
    failure_reason: str | None = None
    created_at: datetime
    finished_at: datetime | None = None


class RecoveryDrill(BaseModel):
    model_config = ConfigDict(frozen=True)

    drill_id: UUID = Field(default_factory=uuid4)
    shadow_id: UUID
    fault_type: str
    recovered: bool
    recovery_seconds: float = Field(ge=0)
    notes: str = ""
    created_at: datetime


class ComplianceRecord(BaseModel):
    model_config = ConfigDict(frozen=True)

    record_id: UUID = Field(default_factory=uuid4)
    shadow_id: UUID
    rules_version: str
    decision: str
    reviewer: str
    notes: str = ""
    created_at: datetime
