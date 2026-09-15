"""Deterministic no-network providers used by the multi-agent fixture runtime."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import NamedTuple

from sector_pulse.domain.market.market import (
    SectorKind,
    SectorSnapshot,
    SectorUniverseSnapshot,
)
from sector_pulse.domain.news.news import NewsDocument, SourceGrade
from sector_pulse.domain.news.news_detail import NewsDetail
from sector_pulse.domain.provider import (
    AuthorizationStatus,
    DataStatus,
    ProviderManifest,
    ProviderResult,
)
from sector_pulse.ports.news_detail import NewsDetailPort


def _manifest(provider_id: str, capability: str) -> ProviderManifest:
    return ProviderManifest(
        provider_id=provider_id,
        version="fixture-1",
        capabilities=frozenset({capability}),
        authorization_status=AuthorizationStatus.RESEARCH_ONLY,
        supports_live=False,
        supports_as_of=False,
        source_attribution="Offline fixture; no external data",
        retention_note="Synthetic fixture only",
    )


class FixtureMarketData:
    manifest = _manifest("fixture-market", "market.sector_universe")

    async def fetch_sector_universe(
        self, kind: SectorKind, mode: object
    ) -> ProviderResult[SectorUniverseSnapshot]:
        del mode
        # The collection service captures its lock time immediately before invoking
        # providers, so fixture observations must already exist at that instant.
        now = datetime.now(UTC) - timedelta(seconds=1)
        prefix = "行业" if kind is SectorKind.INDUSTRY else "概念"
        return ProviderResult(
            provider_id="fixture-market",
            capability="market.sector_universe",
            status=DataStatus.SUCCESS,
            data=SectorUniverseSnapshot(
                provider_id="fixture-market",
                classification_version="fixture-v1",
                source_version=f"fixture-{kind.value.lower()}-v1",
                kind=kind,
                observed_at=now,
                collected_at=now,
                sectors=tuple(
                    SectorSnapshot(
                        provider_sector_id=f"{kind.value}-{index}",
                        name=f"{prefix}样例 {index}",
                        kind=kind,
                        pct_change=Decimal(index),
                        turnover_rate=Decimal(index) / Decimal("10"),
                        advancers=index + 2,
                        decliners=4 - index,
                        leader_name=f"样例股 {index}",
                        leader_pct_change=Decimal(index + 1),
                    )
                    for index in range(1, 4)
                ),
                available_fields=frozenset(
                    {
                        "pct_change",
                        "turnover_rate",
                        "advancers",
                        "decliners",
                        "leader_name",
                        "leader_pct_change",
                    }
                ),
            ),
            observed_at=now,
            collected_at=now,
            source_version=f"fixture-{kind.value.lower()}-v1",
        )


class FixtureSectorConstituents:
    async def fetch_constituents(
        self, sector_name: str, kind: SectorKind
    ) -> ProviderResult[tuple[tuple[str, str], ...]]:
        del sector_name, kind
        now = datetime.now(UTC)
        return ProviderResult(
            provider_id="fixture-constituents",
            capability="market.sector_constituents",
            status=DataStatus.SUCCESS,
            collected_at=now,
            data=(("600001", "样例股份"),),
        )


class FixtureNewsSources:
    manifest = _manifest("fixture-news", "news.search")

    @staticmethod
    def _documents(cutoff: datetime) -> tuple[NewsDocument, ...]:
        observed = cutoff - timedelta(minutes=1)
        return (
            NewsDocument(
                document_id="fixture-news-1",
                source_id="cls",
                canonical_locator="urn:sector-pulse:fixture-news-1",
                citation_url="https://example.test/sector-pulse/fixture-news-1",
                title="行业样例 3 出现政策与订单催化",
                publisher="Fixture 财经媒体",
                summary="固定样例新闻，用于离线验证完整父子 Agent 链路。",
                published_at=cutoff - timedelta(minutes=10),
                source_observed_at=observed,
                collected_at=cutoff,
                content_hash="fixture-news-content-v1",
                source_grade=SourceGrade.REPUTABLE_MEDIA,
            ),
        )

    async def search(
        self, query: str, start_at: datetime, cutoff: datetime
    ) -> ProviderResult[tuple[NewsDocument, ...]]:
        del query, start_at
        return ProviderResult(
            provider_id="fixture-news",
            capability="news.keyword.search",
            status=DataStatus.EMPTY,
            collected_at=cutoff,
            data=(),
        )

    async def fetch_global(self, cutoff: datetime) -> ProviderResult[tuple[NewsDocument, ...]]:
        return ProviderResult(
            provider_id="fixture-news",
            capability="news.global.search",
            status=DataStatus.SUCCESS,
            collected_at=cutoff,
            data=self._documents(cutoff),
        )

    async def search_disclosures(
        self,
        stock_codes: tuple[str, ...],
        start_at: datetime,
        cutoff: datetime,
    ) -> ProviderResult[tuple[NewsDocument, ...]]:
        del stock_codes, start_at
        return ProviderResult(
            provider_id="fixture-news",
            capability="news.disclosure.search",
            status=DataStatus.EMPTY,
            collected_at=cutoff,
            data=(),
        )


class FixtureNewsDetailReader(NewsDetailPort):
    async def read(self, document: NewsDocument) -> NewsDetail:
        return NewsDetail(
            document_id=document.document_id,
            availability="unavailable",
            content="",
            fetched_at=datetime.now(UTC),
            content_hash="",
            error_code="FIXTURE_DETAIL_UNAVAILABLE",
        )


class FixtureProviderBundle(NamedTuple):
    market: FixtureMarketData
    constituents: FixtureSectorConstituents
    global_news: FixtureNewsSources
    keyword_news: FixtureNewsSources
    disclosure_news: FixtureNewsSources
    detail: FixtureNewsDetailReader


def build_fixture_provider_bundle() -> FixtureProviderBundle:
    news = FixtureNewsSources()
    return FixtureProviderBundle(
        market=FixtureMarketData(),
        constituents=FixtureSectorConstituents(),
        global_news=news,
        keyword_news=news,
        disclosure_news=news,
        detail=FixtureNewsDetailReader(),
    )


__all__ = ["FixtureProviderBundle", "build_fixture_provider_bundle"]
