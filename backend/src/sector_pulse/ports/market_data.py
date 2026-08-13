from typing import Protocol

from sector_pulse.domain.market import SectorKind, SectorUniverseSnapshot
from sector_pulse.domain.provider import ProviderManifest, ProviderResult
from sector_pulse.domain.time import AnalysisMode


class MarketDataPort(Protocol):
    @property
    def manifest(self) -> ProviderManifest: ...
    async def fetch_sector_universe(
        self, kind: SectorKind, mode: AnalysisMode
    ) -> ProviderResult[SectorUniverseSnapshot]: ...
