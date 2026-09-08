from datetime import UTC, datetime

from sector_pulse.application.diagnostics.phase0_probe import Phase0ProbeReport
from sector_pulse.domain.market.quality import QualityReport, QualityStatus
from sector_pulse.domain.provider import AuthorizationStatus
from sector_pulse.domain.runs.time import AnalysisRun
from sector_pulse.reporting.phase0_report import render_phase0_markdown


def test_markdown_includes_blocking_issue_codes() -> None:
    now = datetime(2026, 8, 13, 9, 50, tzinfo=UTC)
    report = Phase0ProbeReport(
        run=AnalysisRun.create_live(now),
        provider_id="fixture",
        provider_version="1.0.0",
        provider_authorization=AuthorizationStatus.RESEARCH_ONLY,
        industry_source_version=None,
        concept_source_version=None,
        industry_quality=QualityReport(
            status=QualityStatus.BLOCKED, sector_count=0, issues=("FAILED",)
        ),
        concept_quality=QualityReport(
            status=QualityStatus.BLOCKED, sector_count=0, issues=("FAILED",)
        ),
        usable=False,
    )
    markdown = render_phase0_markdown(report)
    assert "- INDUSTRY issues: `FAILED`" in markdown
    assert "- CONCEPT issues: `FAILED`" in markdown
