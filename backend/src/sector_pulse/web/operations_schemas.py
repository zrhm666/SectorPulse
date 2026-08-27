from datetime import date, datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from sector_pulse.web.schemas import RunSummary


class OperationsDatabaseStatus(BaseModel):
    model_config = ConfigDict(frozen=True)

    backend: Literal["sqlite", "postgresql"]
    name: str


class OperationsLlmStatus(BaseModel):
    model_config = ConfigDict(frozen=True)

    provider: str
    model: str | None
    budget_cny_per_run: Decimal
    configured: bool


class OperationsConsentStatus(BaseModel):
    model_config = ConfigDict(frozen=True)

    live_data: bool
    live_llm: bool


class OperationsProviderStatus(BaseModel):
    model_config = ConfigDict(frozen=True)

    live_data_available: bool
    missing_requirements: tuple[str, ...] = ()


class OperationsRunSummary(BaseModel):
    model_config = ConfigDict(frozen=True)

    total: int = Field(ge=0)
    running: int = Field(ge=0)
    awaiting_review: int = Field(ge=0)
    failed: int = Field(ge=0)
    recent: list[RunSummary]


class OperationsCoreSummary(BaseModel):
    model_config = ConfigDict(frozen=True)

    total: int = Field(ge=0)
    completed_today: int = Field(ge=0)
    active: int = Field(ge=0)
    attention: int = Field(ge=0)


class OperationsTrendPoint(BaseModel):
    model_config = ConfigDict(frozen=True)

    date: date
    total: int = Field(ge=0)
    completed: int = Field(ge=0)
    failed: int = Field(ge=0)


class OperationsTrend(BaseModel):
    model_config = ConfigDict(frozen=True)

    available: bool
    reason: str | None
    points: tuple[OperationsTrendPoint, ...] = ()


class OperationsReadinessItem(BaseModel):
    model_config = ConfigDict(frozen=True)

    status: Literal["ready", "warning", "unavailable", "disabled"]
    label: str
    detail: str
    detail_path: str = "/system"


class OperationsReadiness(BaseModel):
    model_config = ConfigDict(frozen=True)

    database: OperationsReadinessItem
    live_data: OperationsReadinessItem
    llm: OperationsReadinessItem
    scheduler: OperationsReadinessItem


class OperationsRecentRun(BaseModel):
    model_config = ConfigDict(frozen=True)

    run_id: str
    kind: Literal["content", "data"]
    mode: str
    status: str
    provider: str
    requested_at: datetime
    finished_at: datetime | None
    elapsed_ms: int | None
    total_cost_cny: Decimal | None
    candidate_count: int | None = Field(default=None, ge=0)
    detail_path: str


class OperationsSummaryResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    database: OperationsDatabaseStatus
    llm: OperationsLlmStatus
    consent: OperationsConsentStatus
    providers: OperationsProviderStatus
    runs: OperationsRunSummary
    summary: OperationsCoreSummary
    trend: OperationsTrend
    readiness: OperationsReadiness
    recent_runs: tuple[OperationsRecentRun, ...]
    generated_at: datetime
