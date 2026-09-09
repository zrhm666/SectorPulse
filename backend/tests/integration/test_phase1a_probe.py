from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

from sector_pulse.application.diagnostics.phase1a_probe import run_phase1a_probe
from sector_pulse.domain.market.market import SectorKind, SectorSnapshot, SectorUniverseSnapshot
from sector_pulse.domain.market.quality import QualityThresholds
from sector_pulse.domain.news.news import NewsDocument, SourceGrade
from sector_pulse.domain.provider import (
    AuthorizationStatus,
    DataStatus,
    ProviderManifest,
    ProviderResult,
)
from sector_pulse.domain.runs.time import AnalysisMode
from sector_pulse.storage.sqlite.database import SQLiteDatabase


class FakeMarketProvider:
    @property
    def manifest(self) -> ProviderManifest:
        return ProviderManifest(
            provider_id="fixture-market",
            version="1.0.0",
            capabilities=frozenset({"sector_universe.industry", "sector_universe.concept"}),
            authorization_status=AuthorizationStatus.RESEARCH_ONLY,
            supports_live=True,
            supports_as_of=False,
            source_attribution="fixture",
            retention_note="test",
        )

    async def fetch_sector_universe(self, kind: SectorKind, mode: AnalysisMode):
        observed = datetime.now(UTC)
        snapshot = SectorUniverseSnapshot(
            provider_id="fixture-market",
            classification_version="v1",
            source_version="v1",
            kind=kind,
            observed_at=observed,
            collected_at=observed,
            sectors=(
                SectorSnapshot(
                    provider_sector_id=f"{kind.value}-A",
                    name=f"{kind.value} 热点",
                    kind=kind,
                    pct_change=Decimal("3.0"),
                    turnover_rate=Decimal("4.0"),
                    advancers=8,
                    decliners=2,
                ),
            ),
        )
        return ProviderResult(
            provider_id="fixture-market",
            capability=f"sector_universe.{kind.value.lower()}",
            status=DataStatus.SUCCESS,
            data=snapshot,
            observed_at=observed,
            collected_at=observed,
            source_version="v1",
        )


class FakeNewsProvider:
    async def fetch_since(self, cutoff, source_ids):
        document = NewsDocument(
            document_id="doc-1",
            source_id="fixture-news",
            canonical_locator="https://example.com/news/1",
            citation_url="https://example.com/news/1",
            title="产业政策发布",
            published_at=cutoff,
            collected_at=cutoff,
            content_hash="a" * 64,
            source_grade=SourceGrade.PRIMARY,
        )
        return ProviderResult(
            provider_id="fixture-news",
            capability="news.discovery",
            status=DataStatus.SUCCESS,
            data=(document,),
            observed_at=cutoff,
            collected_at=cutoff,
            source_version="v1",
        )


async def test_phase1a_probe_persists_and_builds_auditable_chain(tmp_path: Path) -> None:
    database = SQLiteDatabase(tmp_path / "phase1a.db")
    report = await run_phase1a_probe(
        FakeMarketProvider(),
        FakeNewsProvider(),
        database,
        datetime.now(UTC),
        QualityThresholds(min_industry_count=1, min_concept_count=1),
        source_ids=("https://example.com/feed.xml",),
    )

    assert report.usable is True
    assert report.run.run_cutoff_at is not None
    assert report.event_count == 1
    assert report.candidate_count == 2
    assert report.evidence_pack_count == 2
    with database.connection() as connection:
        stored = connection.execute("SELECT COUNT(*) FROM evidence_packs").fetchone()[0]
    assert stored == 2
