from datetime import UTC, datetime

from sector_pulse.domain.market.market import SectorKind, SectorUniverseSnapshot
from sector_pulse.domain.provider import DataStatus, ProviderError, ProviderManifest, ProviderResult
from sector_pulse.domain.runs.time import AnalysisMode
from sector_pulse.ports.market_data import MarketDataPort


class FallbackMarketDataAdapter:
    """按优先级尝试市场数据来源，不合并不同来源的快照。"""

    def __init__(self, primary: MarketDataPort, secondary: MarketDataPort) -> None:
        self._primary = primary
        self._secondary = secondary

    @property
    def manifest(self) -> ProviderManifest:
        primary = self._primary.manifest
        secondary = self._secondary.manifest
        return primary.model_copy(
            update={"provider_id": f"fallback:{primary.provider_id}|{secondary.provider_id}"}
        )

    async def fetch_sector_universe(
        self, kind: SectorKind, mode: AnalysisMode
    ) -> ProviderResult[SectorUniverseSnapshot]:
        primary = await self._primary.fetch_sector_universe(kind, mode)
        if primary.status not in {DataStatus.FAILED, DataStatus.EMPTY, DataStatus.UNAVAILABLE}:
            return primary
        secondary = await self._secondary.fetch_sector_universe(kind, mode)
        if secondary.status not in {DataStatus.FAILED, DataStatus.EMPTY, DataStatus.UNAVAILABLE}:
            return secondary
        return ProviderResult(
            provider_id=self.manifest.provider_id,
            capability=f"sector_universe.{kind.value.lower()}",
            status=DataStatus.FAILED,
            collected_at=datetime.now(UTC),
            error=ProviderError(
                code="MARKET_PROVIDERS_FAILED",
                message=(
                    f"primary={primary.error.message if primary.error else primary.status.value}; "
                    "secondary="
                    f"{secondary.error.message if secondary.error else secondary.status.value}"
                ),
                retriable=True,
            ),
        )
