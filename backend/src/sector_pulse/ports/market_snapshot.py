from typing import Protocol
from uuid import UUID

from sector_pulse.domain.market.market import SectorKind, SectorUniverseSnapshot
from sector_pulse.domain.provider import ProviderResult
from sector_pulse.domain.runs.time import AnalysisRun


class SnapshotAfterCutoffError(ValueError):
    """行情观察时间晚于本轮锁定 cutoff。"""


class MarketSnapshotRepository(Protocol):
    """行情快照持久化 Port。"""

    def save(
        self,
        run: AnalysisRun,
        result: ProviderResult[SectorUniverseSnapshot],
    ) -> None: ...

    def get(
        self, run_id: UUID, kind: SectorKind
    ) -> SectorUniverseSnapshot | None: ...
