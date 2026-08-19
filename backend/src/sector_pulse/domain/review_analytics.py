from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class ReviewMetrics(BaseModel):
    model_config = ConfigDict(frozen=True)

    run_id: str | None = None
    review_duration_seconds: float = Field(ge=0)
    patch_count: int = Field(ge=0)
    revision_rounds: int = Field(ge=0)
    governance_failures: int = Field(ge=0)
    approval_count: int = Field(ge=0)
    export_count: int = Field(ge=0)
    llm_cost_cny: float = Field(ge=0)


class ReviewSummary(BaseModel):
    model_config = ConfigDict(frozen=True)

    from_at: datetime
    to_at: datetime
    runs: int = Field(ge=0)
    approval_rate: float = Field(ge=0, le=1)
    patch_count: int = Field(ge=0)
    governance_failures: int = Field(ge=0)
    export_count: int = Field(ge=0)
    review_duration_seconds: float = Field(ge=0)
