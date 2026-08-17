from datetime import UTC, datetime
from decimal import Decimal

from sector_pulse.application.phase0_probe import run_phase0_probe
from sector_pulse.domain.market import SectorKind, SectorSnapshot, SectorUniverseSnapshot
from sector_pulse.domain.provider import (
    AuthorizationStatus,
    DataStatus,
    ProviderManifest,
    ProviderResult,
)
from sector_pulse.domain.quality import QualityThresholds
from sector_pulse.domain.time import AnalysisMode


class FakeMarketPort:
    @property
    def manifest(self) -> ProviderManifest:
        return ProviderManifest(
            provider_id="fixture",
            version="1.0.0",
            capabilities=frozenset({"sector_universe.industry", "sector_universe.concept"}),
            authorization_status=AuthorizationStatus.RESEARCH_ONLY,
            supports_live=True,
            supports_as_of=False,
            source_attribution="fixture",
            retention_note="test",
        )

    async def fetch_sector_universe(
        self, kind: SectorKind, mode: AnalysisMode
    ) -> ProviderResult[SectorUniverseSnapshot]:
        assert mode is AnalysisMode.LIVE
        now = datetime.now(UTC)
        count = 50 if kind is SectorKind.INDUSTRY else 100
        observed = now
        sectors = tuple(
            SectorSnapshot(
                provider_sector_id=f"{kind.value}-{index}",
                name=f"板块-{index}",
                kind=kind,
                pct_change=Decimal(index) / Decimal("10"),
                turnover_rate=Decimal("2"),
                advancers=10,
                decliners=5,
            )
            for index in range(count)
        )
        universe = SectorUniverseSnapshot(
            provider_id="fixture",
            classification_version="v1",
            source_version="v1",
            kind=kind,
            observed_at=observed,
            collected_at=observed,
            sectors=sectors,
        )
        return ProviderResult(
            provider_id="fixture",
            capability=f"sector_universe.{kind.value.lower()}",
            status=DataStatus.SUCCESS,
            data=universe,
            observed_at=observed,
            collected_at=observed,
            source_version="v1",
        )


async def test_probe_locks_cutoff_and_writes_sanitized_artifacts(tmp_path) -> None:
    report = await run_phase0_probe(
        FakeMarketPort(),
        tmp_path,
        datetime.now(UTC),
        QualityThresholds(min_industry_count=50, min_concept_count=100),
        60,
    )
    assert report.usable is True
    assert report.run.run_cutoff_at is not None
    assert {path.name for path in tmp_path.iterdir()} == {
        "concept.json",
        "industry.json",
        "probe.json",
        "radar.json",
    }
