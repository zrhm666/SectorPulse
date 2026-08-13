from datetime import datetime, timezone
from enum import StrEnum
from pydantic import BaseModel
from sector_pulse.domain.market import SectorKind, SectorUniverseSnapshot
from sector_pulse.domain.provider import DataStatus, ProviderResult
from sector_pulse.domain.time import AnalysisRun
class QualityStatus(StrEnum): NORMAL="NORMAL"; DEGRADED="DEGRADED"; BLOCKED="BLOCKED"
class QualityThresholds(BaseModel): min_industry_count:int=50; min_concept_count:int=100
class QualityReport(BaseModel): status:QualityStatus; sector_count:int; issues:tuple[str,...]=()
def evaluate_universe(result, thresholds):
    minimum=thresholds.min_industry_count if result.data and result.data.kind is SectorKind.INDUSTRY else thresholds.min_concept_count
    if result.status is DataStatus.FAILED or result.data is None:return QualityReport(status=QualityStatus.BLOCKED,sector_count=0,issues=(result.status.value,))
    return QualityReport(status=QualityStatus.NORMAL if result.data.sector_count>=minimum else QualityStatus.BLOCKED,sector_count=result.data.sector_count,issues=() if result.data.sector_count>=minimum else ("INSUFFICIENT_COVERAGE",))
def lock_cutoff_from_core_market(run, results, locked_at, max_skew_seconds):
    observations=[r.observed_at for r in results if r.observed_at is not None]
    if len(observations)!=len(results) or (max(o for o in observations)-min(observations)).total_seconds()>max_skew_seconds: raise ValueError("observation skew exceeds limit")
    return run.lock_live_cutoff(max(observations),locked_at)
