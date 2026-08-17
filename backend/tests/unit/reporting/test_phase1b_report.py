from decimal import Decimal
from uuid import uuid4

import pytest
from sector_pulse.application.phase1b_pipeline import Phase1BRunResult
from sector_pulse.domain.article import ArticleDraft, ArticleSection, ArticleSource, DraftStatus
from sector_pulse.domain.llm import MoneyCny
from sector_pulse.domain.review import ReviewDecision, ReviewReport
from sector_pulse.reporting.phase1b_report import render_phase1b_markdown, render_phase1b_text


def ready_result() -> Phase1BRunResult:
    section = ArticleSection(
        section_id="industry-1",
        sector_id="industry-1",
        heading="行业观察",
        body="市场表现暂无可靠解释。" * 50,
        claims=(),
        source_ids=("source-1",),
        character_count=500,
    )
    draft = ArticleDraft(
        draft_id=uuid4(),
        run_id=uuid4(),
        version=1,
        status=DraftStatus.READY_FOR_HUMAN_REVIEW,
        titles=("今日板块观察",),
        introduction="导语",
        sections=(
            section,
            section.model_copy(
                update={"section_id": "industry-2", "sector_id": "industry-2"}
            ),
            section.model_copy(
                update={"section_id": "industry-3", "sector_id": "industry-3"}
            ),
        ),
        conclusion="总结",
        risk_notice="仅供信息交流，不构成投资建议。",
        sources=(ArticleSource(source_id="source-1", title="来源1", citation_url="https://example.test/1"),),
        character_count=1500,
    )
    return Phase1BRunResult(
        status="READY_FOR_HUMAN_REVIEW",
        analysis_cards=(),
        outline=None,
        draft=draft,
        review=ReviewReport(
            review_id="review-1",
            draft_id=str(draft.draft_id),
            draft_version=1,
            decision=ReviewDecision.PASS,
            issues=(),
            revision_round=0,
        ),
        total_cost_cny=MoneyCny(amount=Decimal("0")),
        elapsed_ms=10,
    )


def test_markdown_contains_inline_and_end_sources() -> None:
    markdown = render_phase1b_markdown(ready_result())
    assert "[来源1]" in markdown
    assert "## 来源清单" in markdown
    assert "https://example.test/1" in markdown
    assert "READY_FOR_HUMAN_REVIEW" in markdown


def test_blocked_result_cannot_render_publishable_text() -> None:
    result = ready_result()
    blocked = result.__class__(**{**result.__dict__, "status": "BLOCKED", "draft": None})
    with pytest.raises(ValueError, match="not ready for human review"):
        render_phase1b_text(blocked)
