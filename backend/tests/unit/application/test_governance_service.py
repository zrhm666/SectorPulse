from uuid import uuid4

from sector_pulse.application.governance_service import GovernanceService
from sector_pulse.domain.article import ArticleDraft, DraftStatus


def make_draft(conclusion="总结", source_ids=()):
    return ArticleDraft(
        draft_id=uuid4(), run_id=uuid4(), version=1, status=DraftStatus.INCOMPLETE,
        titles=("标题",), introduction="导语", sections=(), conclusion=conclusion,
        risk_notice="风险", sources=(), character_count=8,
    )


def test_governance_blocks_unbound_source():
    report = GovernanceService().check(make_draft())
    assert report.status == "FAIL"
    assert any(issue["code"] == "SOURCE_UNBOUND" for issue in report.issues)


def test_governance_blocks_forbidden_trading_language():
    report = GovernanceService().check(make_draft("建议买入"))
    assert report.status == "FAIL"
    assert any(issue["code"] == "FORBIDDEN_TRADING_LANGUAGE" for issue in report.issues)
