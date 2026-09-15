from datetime import UTC, datetime
from decimal import Decimal
from typing import cast

import pytest
from sector_pulse.application.orchestration.data_tools import (
    CollectMarketService,
    InspectDataQualityService,
    MarketCollectionRequest,
)
from sector_pulse.domain.market.market import SectorKind, SectorSnapshot, SectorUniverseSnapshot
from sector_pulse.domain.market.quality import QualityStatus, QualityThresholds
from sector_pulse.domain.provider import DataStatus, ProviderResult
from sector_pulse.domain.runs.time import AnalysisMode
from sector_pulse.ports.market_data import MarketDataPort

NOW = datetime(2026, 9, 13, 8, tzinfo=UTC)


class MarketProvider:
    def __init__(self) -> None:
        self.calls: list[SectorKind] = []

    async def fetch_sector_universe(
        self, kind: SectorKind, mode: AnalysisMode
    ) -> ProviderResult[SectorUniverseSnapshot]:
        assert mode is AnalysisMode.LIVE
        self.calls.append(kind)
        return ProviderResult(
            provider_id="fixture-market",
            capability="market.sector_universe",
            status=DataStatus.SUCCESS,
            data=SectorUniverseSnapshot(
                provider_id="fixture-market",
                classification_version="v1",
                source_version="v1",
                kind=kind,
                observed_at=NOW,
                collected_at=NOW,
                sectors=(
                    SectorSnapshot(
                        provider_sector_id=f"{kind.value}-1",
                        name="测试板块",
                        kind=kind,
                        pct_change=Decimal("1.2"),
                        turnover_rate=None,
                    ),
                ),
                available_fields=frozenset({"pct_change"}),
            ),
            observed_at=NOW,
            collected_at=NOW,
            source_version="v1",
        )


@pytest.mark.asyncio
async def test_collect_market_only_fetches_requested_approved_gap() -> None:
    provider = MarketProvider()
    service = CollectMarketService(cast(MarketDataPort, provider), mode=AnalysisMode.LIVE)

    result = await service.collect(MarketCollectionRequest(kinds=(SectorKind.CONCEPT,)))

    assert provider.calls == [SectorKind.CONCEPT]
    snapshot = result.results[SectorKind.CONCEPT].data
    assert snapshot is not None
    assert snapshot.sectors[0].turnover_rate is None


def test_collect_market_rejects_empty_or_duplicate_kinds() -> None:
    with pytest.raises(ValueError, match="MARKET_KINDS_INVALID"):
        MarketCollectionRequest(kinds=())
    with pytest.raises(ValueError, match="MARKET_KINDS_INVALID"):
        MarketCollectionRequest(kinds=(SectorKind.INDUSTRY, SectorKind.INDUSTRY))


def test_inspect_quality_uses_server_thresholds_and_preserves_blocking() -> None:
    result = ProviderResult[SectorUniverseSnapshot](
        provider_id="fixture-market",
        capability="market.sector_universe",
        status=DataStatus.EMPTY,
        collected_at=NOW,
    )
    service = InspectDataQualityService(
        QualityThresholds(min_industry_count=1, min_concept_count=1)
    )

    report = service.inspect(result)

    assert report.status is QualityStatus.BLOCKED
    assert report.issues == ("EMPTY",)


def test_quality_api_does_not_accept_model_supplied_thresholds() -> None:
    service = InspectDataQualityService(QualityThresholds())
    assert tuple(service.inspect.__annotations__) == ("result", "return")
