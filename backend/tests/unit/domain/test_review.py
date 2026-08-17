import pytest
from sector_pulse.domain.review import ReviewDecision, ReviewReport


def test_pass_review_cannot_contain_blocking_issue() -> None:
    with pytest.raises(ValueError, match="blocking"):
        ReviewReport(
            review_id="review-1",
            draft_id="draft-1",
            draft_version=1,
            decision=ReviewDecision.PASS,
            issues=(
                {
                    "issue_id": "issue-1",
                    "severity": "BLOCKING",
                    "code": "BAD_CITATION",
                    "message": "来源缺失",
                    "section_id": "industry-1",
                    "claim_id": None,
                    "suggested_fix": "补充来源",
                },
            ),
            revision_round=0,
        )

