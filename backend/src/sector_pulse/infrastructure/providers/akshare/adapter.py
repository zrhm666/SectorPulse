from datetime import datetime, timezone
from sector_pulse.domain.provider import AuthorizationStatus, DataStatus, ProviderError, ProviderManifest, ProviderResult
from sector_pulse.domain.time import AnalysisMode
class AkShareMarketDataAdapter:
    @property
    def manifest(self):
        return ProviderManifest(provider_id="akshare-eastmoney", version="1.0.0", capabilities=frozenset({"sector_universe.industry", "sector_universe.concept"}), authorization_status=AuthorizationStatus.RESEARCH_ONLY, supports_live=True, supports_as_of=False, source_attribution="AKShare", retention_note="local only")
    async def fetch_sector_universe(self, kind, mode):
        status = DataStatus.UNAVAILABLE if mode is AnalysisMode.AS_OF else DataStatus.FAILED
        return ProviderResult(provider_id=self.manifest.provider_id, capability=f"sector_universe.{kind.value.lower()}", status=status, collected_at=datetime.now(timezone.utc), error=None if status is DataStatus.UNAVAILABLE else ProviderError(code="NOT_IMPLEMENTED", message="live adapter pending", retriable=True))
