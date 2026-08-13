from collections.abc import Sequence
from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel

from sector_pulse.domain.market import SectorKind, SectorUniverseSnapshot
from sector_pulse.domain.provider import ProviderResult
from sector_pulse.domain.time import AnalysisRun


class QualityStatus(StrEnum):
    NORMAL = "NORMAL"
    DEGRADED = "DEGRADED"
    BLOCKED = "BLOCKED"


class QualityThresholds(BaseModel):
    min_industry_count: int = 50
    min_concept_count: int = 100


class QualityReport(BaseModel):
    status: QualityStatus
    sector_count: int
    issues: tuple[str, ...] = ()


def evaluate_universe(
    result: ProviderResult[SectorUniverseSnapshot], thresholds: QualityThresholds
) -> QualityReport:
    """按板块类型核验覆盖率；供应商失败绝不降级为“无数据”。"""
    if result.data is None:
        return QualityReport(
            status=QualityStatus.BLOCKED,
            sector_count=0,
            issues=(result.status.value,),
        )
    minimum = (
        thresholds.min_industry_count
        if result.data.kind is SectorKind.INDUSTRY
        else thresholds.min_concept_count
    )
    if result.data.sector_count < minimum:
        return QualityReport(
            status=QualityStatus.BLOCKED,
            sector_count=result.data.sector_count,
            issues=("INSUFFICIENT_COVERAGE",),
        )
    return QualityReport(status=QualityStatus.NORMAL, sector_count=result.data.sector_count)


def lock_cutoff_from_core_market(
    run: AnalysisRun,
    results: Sequence[ProviderResult[SectorUniverseSnapshot]],
    locked_at: datetime,
    max_skew_seconds: int,
) -> AnalysisRun:
    """只有行业和概念快照时间差在阈值内，才锁定本次 LIVE cutoff。"""
    observations = [item.observed_at for item in results if item.observed_at is not None]
    if len(observations) != len(results):
        raise ValueError("core market observations are missing")
    if (max(observations) - min(observations)).total_seconds() > max_skew_seconds:
        raise ValueError("observation skew exceeds limit")
    return run.lock_live_cutoff(max(observations), locked_at)
