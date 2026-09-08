from sector_pulse.domain.market.market import SectorKind
from sector_pulse.domain.provider import DataStatus
from sector_pulse.domain.runs.time import AnalysisMode
from sector_pulse.infrastructure.providers.akshare.adapter import (
    AkShareMarketDataAdapter,
    AkShareThsMarketDataAdapter,
)


class _FakeClient:
    def __init__(self, rows):
        self.rows = rows

    async def fetch(self, kind):
        from datetime import UTC, datetime

        from sector_pulse.infrastructure.providers.akshare.client import RawSectorBatch

        now = datetime.now(UTC)
        return RawSectorBatch(self.rows, now, now, "test", "hash")


async def test_as_of_is_unavailable_without_network_call() -> None:
    result = await AkShareMarketDataAdapter().fetch_sector_universe(
        SectorKind.INDUSTRY, AnalysisMode.AS_OF
    )
    assert result.status is DataStatus.UNAVAILABLE
    assert result.data is None


async def test_ths_live_rows_are_mapped_and_identified() -> None:
    result = await AkShareThsMarketDataAdapter(
        client=_FakeClient(
            [{"代码": "THS1", "名称": "测试行业", "涨跌幅": 1.2, "换手率": 3.4}]
        )
    ).fetch_sector_universe(SectorKind.INDUSTRY, AnalysisMode.LIVE)
    assert result.status is DataStatus.SUCCESS
    assert result.data is not None
    assert result.data.provider_id == "akshare-ths"
    assert result.data.sectors[0].provider_sector_id == "THS1"
    assert str(result.data.sectors[0].pct_change) == "1.2"
    assert result.data.raw_artifact_sha256 == "hash"
