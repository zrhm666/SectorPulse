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


class RecoveryDrillRequest(BaseModel):
    fault_type: str
    recovered: bool
    recovery_seconds: float
    notes: str = ""


class ComplianceRecordRequest(BaseModel):
    rules_version: str
    decision: str
    reviewer: str
    notes: str = ""


class ShadowProgressResponse(BaseModel):
    trading_days: int
    passed: int
    failed: int
    blocked: int
    remaining: int
    complete: bool


class ShadowRunUpdateRequest(BaseModel):
    status: str
    provider_status: dict[str, Any] = Field(default_factory=dict)
    cutoff_at: datetime | None = None
    metrics: dict[str, Any] = Field(default_factory=dict)
    failure_reason: str | None = None
