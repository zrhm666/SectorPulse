import logging
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Protocol
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from sector_pulse.application.phase1a2_probe import (
    Phase1A2Dependencies,
    Phase1A2Report,
    Phase1A2Request,
    run_phase1a2_probe,
)
from sector_pulse.domain.evidence import EvidencePack
from sector_pulse.domain.quality import QualityStatus
from sector_pulse.domain.real_data_run import (
    RealDataCandidate,
    RealDataQualitySummary,
    RealDataRun,
    RealDataRunRequest,
    RealDataRunStatus,
)
from sector_pulse.storage.real_data_run_repository import SQLiteRealDataRunRepository

logger = logging.getLogger(__name__)


def decide_terminal_status(
    report: Phase1A2Report,
) -> tuple[RealDataRunStatus, tuple[str, ...]]:
    """把 Phase 1A.2 质量报告转换为真实数据运行的明确终态。"""
    if any(quality.status is QualityStatus.BLOCKED for quality in report.market_quality.values()):
        return RealDataRunStatus.BLOCKED, ("CORE_MARKET_BLOCKED",)
    if not report.ready_for_phase1b or report.downgrade_reasons:
        return RealDataRunStatus.DEGRADED, tuple(report.downgrade_reasons)
    return RealDataRunStatus.READY_FOR_ATTRIBUTION, ()


class ProgressSink(Protocol):
    def __call__(self, status: RealDataRunStatus) -> None: ...


class RealDataRunResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    run: RealDataRun
    status: RealDataRunStatus
    candidates: tuple = ()
    evidence: tuple[EvidencePack, ...] = ()
    quality: RealDataQualitySummary
    downgrade_reasons: tuple[str, ...] = ()


async def run_real_data_workflow(
    dependencies: Phase1A2Dependencies,
    request: RealDataRunRequest,
    progress_sink: Callable[[RealDataRunStatus], None] | None = None,
    run_id: UUID | None = None,
) -> RealDataRunResult:
    """复用已验证的采集链路，并在外层增加真实数据状态和持久化边界。"""
    real_run = RealDataRun(run_id=run_id or UUID(int=0), request=request)
    repository = SQLiteRealDataRunRepository(dependencies.database)
    repository.insert(real_run)

    def emit(status: RealDataRunStatus) -> None:
        nonlocal real_run
        real_run = real_run.model_copy(update={"status": status})
        repository.update_status(real_run.run_id, status)
        if progress_sink:
            progress_sink(status)

    try:
        emit(RealDataRunStatus.FETCHING_MARKET)
        report = await run_phase1a2_probe(
            dependencies,
            Phase1A2Request(
                requested_at=request.requested_at,
                run_kind=request.mode,
                lookback_hours=request.lookback_hours or 6,
                precandidate_limit=request.precandidate_limit,
                final_candidate_limit=request.final_candidate_limit,
                run_id=real_run.run_id,
            ),
        )
        repository.save_candidates(
            real_run.run_id,
            tuple(
                RealDataCandidate(
                    sector_id=item.provider_sector_id,
                    sector_kind=item.kind,
                    rank=item.rank,
                    score=item.score,
                    reasons=item.reasons,
                )
                for item in report.final_candidates
            ),
        )
        emit(RealDataRunStatus.FETCHING_NEWS)
        emit(RealDataRunStatus.BUILDING_EVIDENCE)
        status, reasons = decide_terminal_status(report)
        quality = RealDataQualitySummary(
            market_quality={key: value.status for key, value in report.market_quality.items()},
            news_quality={"news": report.news_quality.status},
            cutoff_violation_count=report.cutoff_violation_count,
            downgrade_reasons=reasons,
        )
        finished_at = datetime.now(UTC)
        real_run = real_run.model_copy(
            update={
                "status": status,
                "cutoff_at": report.run.run_cutoff_at,
                "quality": quality,
                "finished_at": finished_at,
            }
        )
        repository.update_status(
            real_run.run_id, status, cutoff_at=real_run.cutoff_at,
            quality=quality, finished_at=finished_at,
        )
        return RealDataRunResult(
            run=real_run, status=status, quality=quality, downgrade_reasons=reasons
        )
    except Exception as exc:
        logger.exception(
            "real data workflow failed: run_id=%s error_type=%s",
            real_run.run_id,
            type(exc).__name__,
        )
        # 异常只落安全错误码，避免把第三方响应或密钥写入数据库。
        finished_at = datetime.now(UTC)
        error_code = type(exc).__name__.upper()
        real_run = real_run.model_copy(
            update={
                "status": RealDataRunStatus.FAILED,
                "error_code": error_code,
                "finished_at": finished_at,
            }
        )
        repository.update_status(
            real_run.run_id, RealDataRunStatus.FAILED,
            error_code=error_code, finished_at=finished_at,
        )
        return RealDataRunResult(
            run=real_run,
            status=RealDataRunStatus.FAILED,
            quality=real_run.quality,
            downgrade_reasons=(error_code,),
        )
