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


class OperationsSummaryResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    database: OperationsDatabaseStatus
    llm: OperationsLlmStatus
    consent: OperationsConsentStatus
    providers: OperationsProviderStatus
    runs: OperationsRunSummary
