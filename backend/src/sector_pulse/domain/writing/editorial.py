from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from sector_pulse.domain.review.review import (
    GovernanceReport,
    ReviewDecision,
    ReviewIssue,
    ReviewReport,
)
from sector_pulse.domain.writing.article import ArticleDraft, ArticleOutline
from sector_pulse.domain.writing.attribution import Claim


class ArticleOutlineSubmission(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    sector_ids: tuple[str, ...] = Field(min_length=3, max_length=6)
    order_reasons: dict[str, str]
    title_directions: tuple[str, ...] = Field(min_length=1, max_length=6)
    thesis: str = Field(min_length=1)
    section_character_budgets: dict[str, int]
    excluded_sector_reasons: dict[str, str]

    @model_validator(mode="after")
    def validate_maps(self) -> "ArticleOutlineSubmission":
        selected = set(self.sector_ids)
        if len(selected) != len(self.sector_ids):
            raise ValueError("outline sector ids must be unique")
        if set(self.order_reasons) != selected or set(
            self.section_character_budgets
        ) != selected:
            raise ValueError("outline map keys must match selected sectors")
        if any(value <= 0 for value in self.section_character_budgets.values()):
            raise ValueError("section character budgets must be positive")
        return self


class EditorialOutlineArtifact(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    outline_id: UUID
    run_id: UUID
    task_id: UUID
    attempt: int = Field(ge=1)
    selection_version: int = Field(ge=1)
    input_analysis_ids: tuple[UUID, ...]
    input_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    outline_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    outline: ArticleOutline
    created_at: datetime


class ArticleSectionSubmission(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    section_id: str = Field(min_length=1)
    sector_id: str = Field(min_length=1)
    heading: str = Field(min_length=1)
    body: str = Field(min_length=1)
    claims: tuple[Claim, ...]
    source_ids: tuple[str, ...]


class ArticleDraftSubmission(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    titles: tuple[str, ...] = Field(min_length=1, max_length=6)
    introduction: str = Field(min_length=1)
    sections: tuple[ArticleSectionSubmission, ...] = Field(min_length=3, max_length=6)
    conclusion: str = Field(min_length=1)
    risk_notice: str = Field(min_length=1)


class EditorialDraftArtifact(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    artifact_id: UUID
    run_id: UUID
    task_id: UUID
    attempt: int = Field(ge=1)
    outline_id: UUID
    base_draft_artifact_id: UUID | None = None
    review_artifact_id: UUID | None = None
    revision_round: int = Field(default=0, ge=0, le=2)
    input_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    draft_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    draft: ArticleDraft
    created_at: datetime


class DraftRulesReport(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    draft_id: UUID
    draft_version: int = Field(ge=1)
    quality_issues: tuple[ReviewIssue, ...]
    governance: GovernanceReport


class DraftRulesArtifact(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    artifact_id: UUID
    run_id: UUID
    task_id: UUID
    attempt: int = Field(ge=1)
    draft_artifact_id: UUID
    input_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    report: DraftRulesReport
    created_at: datetime


class ReviewSubmission(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    decision: ReviewDecision
    issues: tuple[ReviewIssue, ...]


class IndependentReviewArtifact(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    artifact_id: UUID
    run_id: UUID
    task_id: UUID
    attempt: int = Field(ge=1)
    draft_artifact_id: UUID
    rules_artifact_id: UUID
    input_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    report: ReviewReport
    created_at: datetime


__all__ = [
    "ArticleDraftSubmission",
    "ArticleOutlineSubmission",
    "ArticleSectionSubmission",
    "EditorialDraftArtifact",
    "EditorialOutlineArtifact",
    "DraftRulesArtifact",
    "DraftRulesReport",
    "IndependentReviewArtifact",
    "ReviewSubmission",
]
