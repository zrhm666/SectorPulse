from datetime import UTC, datetime

from sector_pulse.domain.market.market import SectorKind
from sector_pulse.domain.provider import (
    AuthorizationStatus,
    DataStatus,
    ProviderError,
    ProviderManifest,
    ProviderResult,
)
from sector_pulse.domain.runs.time import AnalysisMode
from sector_pulse.infrastructure.providers.fallback import FallbackMarketDataAdapter


class _Provider:
    def __init__(self, result):
        self.result = result
        self.calls = 0

    @property
    def manifest(self):
        return ProviderManifest(
            provider_id=self.result.provider_id,
            version="test",
            capabilities=frozenset({"sector_universe.industry"}),
            authorization_status=AuthorizationStatus.RESEARCH_ONLY,
            supports_live=True,
            supports_as_of=False,
            source_attribution="test",
            retention_note="test",
        )

    async def fetch_sector_universe(self, kind, mode):
        self.calls += 1
        return self.result


def _failed(provider_id):
    return ProviderResult(
        provider_id=provider_id,
        capability="sector_universe.industry",
        status=DataStatus.FAILED,
        collected_at=datetime.now(UTC),
        error=ProviderError(code="x", message="failed", retriable=True),
    )


async def test_fallback_uses_secondary_after_primary_failure():
    primary = _Provider(_failed("eastmoney"))
    secondary = _Provider(_failed("ths"))
    result = await FallbackMarketDataAdapter(primary, secondary).fetch_sector_universe(
        SectorKind.INDUSTRY, AnalysisMode.LIVE
    )
    assert result.status is DataStatus.FAILED
    assert primary.calls == secondary.calls == 1
