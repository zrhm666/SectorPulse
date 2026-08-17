from sector_pulse.domain.market import SectorKind
from sector_pulse.domain.provider import DataStatus
from sector_pulse.domain.time import AnalysisMode
from sector_pulse.infrastructure.providers.akshare.adapter import AkShareMarketDataAdapter


async def test_as_of_is_unavailable_without_network_call() -> None:
    result = await AkShareMarketDataAdapter().fetch_sector_universe(
        SectorKind.INDUSTRY, AnalysisMode.AS_OF
    )
    assert result.status is DataStatus.UNAVAILABLE
    assert result.data is None
