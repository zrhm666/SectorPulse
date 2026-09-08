import asyncio
from datetime import UTC, datetime, timedelta

import pytest
from sector_pulse.domain.market.market import SectorKind
from sector_pulse.domain.provider import DataStatus
from sector_pulse.domain.runs.time import AnalysisMode
from sector_pulse.infrastructure.news.akshare_adapters import (
    AkShareClsAdapter,
    AkShareEastmoneyNewsAdapter,
)
from sector_pulse.infrastructure.providers.real_data_factory import RealDataProviderFactory


@pytest.mark.asyncio
@pytest.mark.live
async def test_real_market_and_two_news_sources() -> None:
    # 通过真实数据工厂验证 Eastmoney -> THS 的主备回退链，而非绕过工厂直接实例化主源。
    market = RealDataProviderFactory().build().market
    industry, concept = await asyncio.gather(
        market.fetch_sector_universe(SectorKind.INDUSTRY, AnalysisMode.LIVE),
        market.fetch_sector_universe(SectorKind.CONCEPT, AnalysisMode.LIVE),
    )
    assert industry.status is DataStatus.SUCCESS and industry.data is not None
    assert concept.status is DataStatus.SUCCESS and concept.data is not None
    cutoff = datetime.now(UTC)
    start = cutoff - timedelta(hours=24)
    cls, eastmoney = await asyncio.gather(
        AkShareClsAdapter().fetch_global(cutoff),
        AkShareEastmoneyNewsAdapter().search("人工智能", start, cutoff),
    )
    usable_sources = sum(
        item.status in {DataStatus.SUCCESS, DataStatus.PARTIAL}
        for item in (cls, eastmoney)
    )
    assert usable_sources >= 2
