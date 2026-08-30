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

from .client import PandasAkShareClient, PandasThsAkShareClient
from .mapper import map_sector_rows


class AkShareMarketDataAdapter:
    @property
    def manifest(self) -> ProviderManifest:
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

    def __init__(self, client: PandasAkShareClient | None = None) -> None:
        self._client = client or PandasAkShareClient()

    async def fetch_sector_universe(
        self, kind: SectorKind, mode: AnalysisMode
    ) -> ProviderResult[SectorUniverseSnapshot]:
        # AKShare 的实时板块列表没有可靠的历史截点能力，因此 AS_OF 明确拒绝且不触网。
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
                batch.rows,
                kind,
                batch.observed_at,
                batch.collected_at,
                batch.source_version,
                raw_artifact_sha256=batch.raw_artifact_sha256,
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
            # 将供应商异常压缩成可审核的统一错误语义，调用方不依赖第三方异常类型。
            return ProviderResult(
                provider_id=self.manifest.provider_id,
                capability=capability,
                status=DataStatus.FAILED,
                collected_at=datetime.now(UTC),
                error=ProviderError(code="AKSHARE_FETCH_FAILED", message=str(exc), retriable=True),
            )


class AkShareThsMarketDataAdapter(AkShareMarketDataAdapter):
    @property
    def manifest(self) -> ProviderManifest:
        return ProviderManifest(
            provider_id="akshare-ths",
            version="1.0.0",
            capabilities=frozenset({"sector_universe.industry", "sector_universe.concept"}),
            authorization_status=AuthorizationStatus.RESEARCH_ONLY,
            supports_live=True,
            supports_as_of=False,
            source_attribution="AKShare/同花顺",
            retention_note="local only",
        )

    def __init__(self, client: PandasThsAkShareClient | None = None) -> None:
        self._client = client or PandasThsAkShareClient()

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
                batch.rows, kind, batch.observed_at, batch.collected_at, batch.source_version,
                provider_id=self.manifest.provider_id, classification_prefix="ths",
                raw_artifact_sha256=batch.raw_artifact_sha256,
            )
            return ProviderResult(
                provider_id=self.manifest.provider_id, capability=capability,
                status=DataStatus.SUCCESS, data=universe,
                observed_at=batch.observed_at, collected_at=batch.collected_at,
                source_version=batch.source_version, raw_artifact_sha256=batch.raw_artifact_sha256,
            )
        except Exception as exc:
            return ProviderResult(
                provider_id=self.manifest.provider_id, capability=capability,
                status=DataStatus.FAILED, collected_at=datetime.now(UTC),
                error=ProviderError(
                    code="AKSHARE_THS_FETCH_FAILED", message=str(exc), retriable=True
                ),
            )
