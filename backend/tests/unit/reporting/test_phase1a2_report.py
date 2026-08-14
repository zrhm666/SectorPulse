from datetime import UTC, datetime

from sector_pulse.application.news_quality import NewsQualityReport
from sector_pulse.application.phase1a2_probe import Phase1A2Report, SourceMetricSummary
from sector_pulse.domain.provider import DataStatus
from sector_pulse.domain.quality import QualityReport, QualityStatus
from sector_pulse.domain.time import AnalysisRun
from sector_pulse.reporting.phase1a2_report import render_phase1a2_markdown


def test_phase1a2_markdown_contains_auditable_metrics_without_raw_article_body() -> None:
    now = datetime(2026, 8, 14, 2, tzinfo=UTC)
    report = Phase1A2Report(
        run=AnalysisRun.create_as_of(now, now),
        run_kind="post_close",
        elapsed_ms=123,
        market_quality={"industry": QualityReport(status=QualityStatus.NORMAL, sector_count=2)},
        news_quality=NewsQualityReport(
            status=QualityStatus.NORMAL,
            document_count=2,
            event_count=1,
            citation_eligible_count=2,
            background_only_count=0,
            excluded_after_cutoff_count=0,
            source_statuses={"cls": DataStatus.SUCCESS},
        ),
        market_precandidate_count=20,
        final_candidate_count=3,
        source_metrics={
            "cls": SourceMetricSummary(
                status=DataStatus.SUCCESS,
                call_count=1,
                retry_count=0,
                duration_ms=10,
                document_count=2,
            )
        },
        document_count=2,
        event_count=1,
        link_count=1,
        deduplication_rate=0.5,
        mapping_rate=1.0,
        cutoff_violation_count=0,
        downgrade_reasons=(),
        ready_for_phase1b=True,
        evidence_pack_count=3,
    )
    markdown = render_phase1a2_markdown(report)
    assert "cutoff" in markdown
    assert "calls=1" in markdown
    assert "documents/events/links" in markdown
    assert "完整正文" not in markdown
