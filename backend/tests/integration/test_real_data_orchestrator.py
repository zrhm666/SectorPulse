from sector_pulse.application.real_data_orchestrator import decide_terminal_status
from sector_pulse.domain.quality import QualityReport, QualityStatus


class Report:
    market_quality = {
        "industry": QualityReport(status=QualityStatus.NORMAL, sector_count=50),
        "concept": QualityReport(status=QualityStatus.NORMAL, sector_count=100),
    }
    ready_for_phase1b = True
    downgrade_reasons = ()


def test_ready_status_when_quality_passes() -> None:
    status, reasons = decide_terminal_status(Report())
    assert status.value == "READY_FOR_ATTRIBUTION"
    assert reasons == ()


def test_market_block_is_terminal_blocked() -> None:
    report = Report()
    report.market_quality["concept"] = QualityReport(
        status=QualityStatus.BLOCKED, sector_count=0
    )
    status, reasons = decide_terminal_status(report)
    assert status.value == "BLOCKED"
    assert reasons == ("CORE_MARKET_BLOCKED",)
