"""Validated actions at the boundary between model decisions and tools."""

from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter

from sector_pulse.domain.writing.attribution import SectorAnalysisCard


class StrictAction(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class SearchNews(StrictAction):
    action: Literal["search_news"]
    query: str = Field(min_length=2, max_length=120)


class ReadNewsDetail(StrictAction):
    action: Literal["read_news_detail"]
    document_id: str = Field(min_length=1, max_length=160)


class InspectMarket(StrictAction):
    action: Literal["inspect_market"]


class FinishAttribution(StrictAction):
    action: Literal["finish"]
    card: SectorAnalysisCard


AgentAction = Annotated[
    SearchNews | ReadNewsDetail | InspectMarket | FinishAttribution,
    Field(discriminator="action"),
]
ACTION_ADAPTER: TypeAdapter[AgentAction] = TypeAdapter(AgentAction)


class AgentDecision(StrictAction):
    next_action: AgentAction


class AgentLimits(StrictAction):
    max_decisions: int = Field(default=6, ge=1, le=12)
    max_tool_calls: int = Field(default=5, ge=0, le=10)
    timeout_seconds: float = Field(default=180, gt=0, le=600)
    max_observation_chars: int = Field(default=12000, ge=100, le=30000)


class ToolObservation(StrictAction):
    action: str
    status: Literal["success", "partial", "unavailable", "error"]
    data: dict[str, Any] = Field(default_factory=dict)
    error_code: str | None = None
