"""Deterministic no-network providers used by the multi-agent fixture runtime."""

from datetime import UTC, datetime
from typing import NamedTuple

from sector_pulse.domain.market.market import SectorKind
from sector_pulse.domain.news.news import NewsDocument
from sector_pulse.domain.news.news_detail import NewsDetail
from sector_pulse.domain.provider import (
    AuthorizationStatus,
    DataStatus,
    ProviderError,
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

    async def fetch_sector_universe(self, kind: SectorKind, mode: object) -> ProviderResult[object]:
        return ProviderResult(
            provider_id="fixture-market",
            capability="market.sector_universe",
            status=DataStatus.UNAVAILABLE,
            collected_at=datetime.now(UTC),
            error=ProviderError(
                code="FIXTURE_DATA_UNAVAILABLE", message=f"no {kind.value} fixture"
            ),
        )


class FixtureSectorConstituents:
    async def fetch_constituents(
        self, sector_name: str, kind: SectorKind
    ) -> ProviderResult[object]:
        return ProviderResult(
            provider_id="fixture-constituents",
            capability="market.sector_constituents",
            status=DataStatus.EMPTY,
            collected_at=datetime.now(UTC),
            data=(),
        )


class FixtureNewsSources:
    manifest = _manifest("fixture-news", "news.search")

    async def search(
        self, query: str, start_at: datetime, cutoff: datetime
    ) -> ProviderResult[tuple[NewsDocument, ...]]:
        del query, start_at, cutoff
        return ProviderResult(
            provider_id="fixture-news",
            capability="news.keyword.search",
            status=DataStatus.EMPTY,
            collected_at=datetime.now(UTC),
            data=(),
        )

    async def fetch_global(self, cutoff: datetime) -> ProviderResult[tuple[NewsDocument, ...]]:
        del cutoff
        return ProviderResult(
            provider_id="fixture-news",
            capability="news.global.search",
            status=DataStatus.EMPTY,
            collected_at=datetime.now(UTC),
            data=(),
        )

    async def search_disclosures(
        self,
        stock_codes: tuple[str, ...],
        start_at: datetime,
        cutoff: datetime,
    ) -> ProviderResult[tuple[NewsDocument, ...]]:
        del stock_codes, start_at, cutoff
        return ProviderResult(
            provider_id="fixture-news",
            capability="news.disclosure.search",
            status=DataStatus.EMPTY,
            collected_at=datetime.now(UTC),
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
