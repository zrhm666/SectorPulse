from pathlib import Path

import pytest
from sector_pulse.domain.market.market import SectorKind
from sector_pulse.domain.provider import DataStatus
from sector_pulse.domain.runs.time import AnalysisMode
from sector_pulse.infrastructure.providers.akshare.adapter import AkShareMarketDataAdapter

pytestmark = pytest.mark.live


@pytest.mark.skipif(
    not Path(".live-data-consent").is_file(),
    reason="provider terms consent file is absent",
)
@pytest.mark.parametrize(
    ("kind", "minimum"),
    [(SectorKind.INDUSTRY, 50), (SectorKind.CONCEPT, 100)],
)
async def test_akshare_live_sector_coverage(kind: SectorKind, minimum: int) -> None:
    result = await AkShareMarketDataAdapter().fetch_sector_universe(kind, AnalysisMode.LIVE)
    assert result.status is DataStatus.SUCCESS
    assert result.data is not None
    assert result.data.sector_count >= minimum
