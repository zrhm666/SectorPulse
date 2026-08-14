from enum import StrEnum

from pydantic import BaseModel, ConfigDict, model_validator


class ReviewDecision(StrEnum):
    PASS = "PASS"
    REVISE = "REVISE"
    BLOCK = "BLOCK"


class IssueSeverity(StrEnum):
    INFO = "INFO"
    WARNING = "WARNING"
    BLOCKING = "BLOCKING"


class ReviewIssue(BaseModel):
    model_config = ConfigDict(frozen=True)
    issue_id: str
    severity: IssueSeverity
    code: str
    message: str
    section_id: str | None = None
    claim_id: str | None = None
    suggested_fix: str | None = None


class ReviewReport(BaseModel):
    model_config = ConfigDict(frozen=True)
    review_id: str
    draft_id: str
    draft_version: int
    decision: ReviewDecision
    issues: tuple[ReviewIssue, ...]
    revision_round: int

    @model_validator(mode="after")
    def validate_pass(self) -> "ReviewReport":
        has_blocking = any(issue.severity is IssueSeverity.BLOCKING for issue in self.issues)
        if self.decision is ReviewDecision.PASS and has_blocking:
            raise ValueError("PASS review cannot contain blocking issues")
        return self
