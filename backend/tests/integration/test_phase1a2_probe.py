import asyncio
from datetime import UTC, datetime
from decimal import Decimal
from types import SimpleNamespace

from sector_pulse.application.data_runs.phase1a2_probe import Phase1A2Request, run_phase1a2_probe
from sector_pulse.domain.market import SectorKind, SectorSnapshot, SectorUniverseSnapshot
from sector_pulse.domain.news import NewsDocument, SourceGrade
from sector_pulse.domain.provider import (
    AuthorizationStatus,
    DataStatus,
    ProviderManifest,
    ProviderResult,
)
from sector_pulse.domain.time import AnalysisMode
from sector_pulse.storage.sqlite.database import SQLiteDatabase

NOW = datetime(2026, 8, 14, 2, tzinfo=UTC)


def manifest(provider_id: str, capabilities: set[str]) -> ProviderManifest:
    return ProviderManifest(
        provider_id=provider_id,
        version="fixture",
        capabilities=frozenset(capabilities),
        authorization_status=AuthorizationStatus.RESEARCH_ONLY,
        supports_live=True,
        supports_as_of=False,
        source_attribution="fixture",
        retention_note="test",
    )


class Market:
    manifest = manifest("market", {"market.sector_universe"})

    async def fetch_sector_universe(self, kind: SectorKind, mode: AnalysisMode):
        del mode
        return ProviderResult(
            provider_id="market",
            capability="market.sector_universe",
            status=DataStatus.SUCCESS,
            data=SectorUniverseSnapshot(
                provider_id="market",
                classification_version="v1",
                source_version="v1",
                kind=kind,
                observed_at=NOW,
                collected_at=NOW,
                sectors=tuple(
                    SectorSnapshot(
                        provider_sector_id=f"{kind.value}-1",
                        name=f"热门{kind.value}",
                        kind=kind,
                        pct_change=Decimal("5"),
                        turnover_rate=Decimal("6"),
                        advancers=8,
                        decliners=1,
                    )
                    for _ in range(20)
                ),
            ),
            collected_at=NOW,
            observed_at=NOW,
        )


class Constituents:
    async def fetch_constituents(self, sector_name, kind):
        del sector_name, kind
        return ProviderResult(
            provider_id="constituents",
            capability="sector_constituents",
            status=DataStatus.SUCCESS,
            data=(("600001", "测试股"),),
            collected_at=NOW,
        )


class News:
    manifest = manifest(
        "news", {"news.global.discovery", "news.keyword.search", "news.disclosure.search"}
    )

    def _doc(self):
        return NewsDocument(
            document_id="doc-1",
            source_id="eastmoney",
            canonical_locator="urn:fixture:doc-1",
            citation_url="https://example.test/doc-1",
            title="热门行业新闻",
            publisher="证券时报",
            summary="摘要",
            published_at=NOW,
            source_observed_at=NOW,
            collected_at=NOW,
            content_hash="hash-1",
            source_grade=SourceGrade.REPUTABLE_MEDIA,
        )

    async def fetch_global(self, cutoff):
        return ProviderResult(
            provider_id="cls",
            capability="news.global.discovery",
            status=DataStatus.SUCCESS,
            data=(self._doc(),),
            collected_at=cutoff,
        )

    async def search(self, query, start_at, cutoff):
        del query, start_at
        return ProviderResult(
            provider_id="eastmoney",
            capability="news.keyword.search",
            status=DataStatus.EMPTY,
            collected_at=cutoff,
        )

    async def search_disclosures(self, stock_codes, start_at, cutoff):
        del stock_codes, start_at
        return ProviderResult(
            provider_id="cninfo",
            capability="news.disclosure.search",
            status=DataStatus.EMPTY,
            collected_at=cutoff,
        )


def test_phase1a2_probe_fixture_end_to_end(tmp_path) -> None:
    deps = SimpleNamespace(
        market=Market(),
        constituents=Constituents(),
        global_news=News(),
        keyword_news=News(),
        disclosure_news=News(),
        database=SQLiteDatabase(tmp_path / "probe.db"),
        entity_config=__import__(
            "sector_pulse.domain.news_retrieval", fromlist=["SectorEntityConfig"]
        ).SectorEntityConfig(version="fixture", aliases={}, industry_terms={}, ambiguous_terms=()),
    )
    report = asyncio.run(
        run_phase1a2_probe(
            deps,
            Phase1A2Request(
                requested_at=NOW,
                run_kind="post_close",
                min_industry_count=1,
                min_concept_count=1,
            ),
        )
    )
    assert report.market_precandidate_count == 30
    assert report.final_candidate_count <= 12
    assert report.cutoff_violation_count == 0
    assert report.source_metrics["cls"].call_count == 1
    assert report.source_metrics["eastmoney"].call_count <= 24
    assert report.source_metrics["cninfo"].call_count <= 12
