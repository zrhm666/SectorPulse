from datetime import UTC, datetime

from sector_pulse.domain.market import SectorKind, SectorUniverseSnapshot
from sector_pulse.domain.provider import (
    AuthorizationStatus,
    DataStatus,
    ProviderError,
    ProviderManifest,
    ProviderResult,
)
from sector_pulse.domain.time import AnalysisMode

from .client import PandasAkShareClient
from .mapper import map_sector_rows


class AkShareMarketDataAdapter:
    @property
    def manifest(self):
        return ProviderManifest(
            provider_id="akshare-eastmoney",
            version="1.0.0",
            capabilities=frozenset({"sector_universe.industry", "sector_universe.concept"}),
            authorization_status=AuthorizationStatus.RESEARCH_ONLY,
            supports_live=True,
            supports_as_of=False,
            source_attribution="AKShare",
            retention_note="local only",
        )

    def __init__(self, client=None):
        self._client = client or PandasAkShareClient()

    async def fetch_sector_universe(
        self, kind: SectorKind, mode: AnalysisMode
    ) -> ProviderResult[SectorUniverseSnapshot]:
        capability = f"sector_universe.{kind.value.lower()}"
        now = datetime.now(UTC)
        if mode is AnalysisMode.AS_OF:
            return ProviderResult(
                provider_id=self.manifest.provider_id,
                capability=capability,
                status=DataStatus.UNAVAILABLE,
                collected_at=now,
            )
        try:
            batch = await self._client.fetch(kind)
            if not batch.rows:
                return ProviderResult(
                    provider_id=self.manifest.provider_id,
                    capability=capability,
                    status=DataStatus.EMPTY,
                    collected_at=batch.collected_at,
                )
            universe = map_sector_rows(
                batch.rows, kind, batch.observed_at, batch.collected_at, batch.source_version
            )
            return ProviderResult(
                provider_id=self.manifest.provider_id,
                capability=capability,
                status=DataStatus.SUCCESS,
                data=universe,
                observed_at=batch.observed_at,
                collected_at=batch.collected_at,
                source_version=batch.source_version,
                raw_artifact_sha256=batch.raw_artifact_sha256,
            )
        except Exception as exc:
            return ProviderResult(
                provider_id=self.manifest.provider_id,
                capability=capability,
                status=DataStatus.FAILED,
                collected_at=datetime.now(UTC),
                error=ProviderError(code="AKSHARE_FETCH_FAILED", message=str(exc), retriable=True),
            )
