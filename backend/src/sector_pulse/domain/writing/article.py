from enum import StrEnum
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from sector_pulse.domain.writing.attribution import Claim


class DraftStatus(StrEnum):
    INCOMPLETE = "INCOMPLETE"
    REVISE_REQUIRED = "REVISE_REQUIRED"
    UNREVIEWED = "UNREVIEWED"
    BLOCKED = "BLOCKED"
    READY_FOR_HUMAN_REVIEW = "READY_FOR_HUMAN_REVIEW"


class ArticleSection(BaseModel):
    model_config = ConfigDict(frozen=True)
    section_id: str
    sector_id: str
    heading: str
    body: str
    claims: tuple[Claim, ...]
    source_ids: tuple[str, ...]
    character_count: int = Field(ge=0)


class ArticleSource(BaseModel):
    model_config = ConfigDict(frozen=True)
    source_id: str
    title: str
    publisher: str | None = None
    citation_url: str | None = None
    published_at: str | None = None


class ArticleOutline(BaseModel):
    model_config = ConfigDict(frozen=True)
    outline_id: UUID
    run_id: UUID
    sector_ids: tuple[str, ...]
    order_reasons: dict[str, str]
    title_directions: tuple[str, ...]
    thesis: str
    section_character_budgets: dict[str, int]
    excluded_sector_reasons: dict[str, str]

    @model_validator(mode="after")
    def validate_sector_count(self) -> "ArticleOutline":
        if not 3 <= len(self.sector_ids) <= 6:
            raise ValueError("outline must contain 3 to 6 sectors")
        if len(set(self.sector_ids)) != len(self.sector_ids):
            raise ValueError("outline sector ids must be unique")
        return self


class ArticleDraft(BaseModel):
    model_config = ConfigDict(frozen=True)
    draft_id: UUID
    run_id: UUID
    version: int = Field(ge=1)
    status: DraftStatus
    titles: tuple[str, ...]
    introduction: str
    sections: tuple[ArticleSection, ...]
    conclusion: str
    risk_notice: str
    sources: tuple[ArticleSource, ...]
    character_count: int = Field(ge=0)

    @model_validator(mode="after")
    def validate_ready_shape(self) -> "ArticleDraft":
        if self.status is DraftStatus.READY_FOR_HUMAN_REVIEW:
            if not 3 <= len(self.sections) <= 6:
                raise ValueError("ready draft must contain 3 to 6 sections")
            if not 1000 <= self.character_count <= 1800:
                raise ValueError("ready draft must contain 1000 to 1800 characters")
            if not self.sources:
                raise ValueError("ready draft requires sources")
        return self
