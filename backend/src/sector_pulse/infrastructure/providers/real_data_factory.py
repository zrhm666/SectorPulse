from pathlib import Path
from typing import NamedTuple

from pydantic import BaseModel, ConfigDict

from sector_pulse.infrastructure.news.akshare_adapters import (
    AkShareClsAdapter,
    AkShareCninfoAdapter,
    AkShareEastmoneyNewsAdapter,
)
from sector_pulse.infrastructure.providers.akshare.adapter import (
    AkShareMarketDataAdapter,
    AkShareThsMarketDataAdapter,
)
from sector_pulse.infrastructure.providers.akshare.constituents import (
    AkShareSectorConstituentAdapter,
)
from sector_pulse.infrastructure.providers.fallback import FallbackMarketDataAdapter
from sector_pulse.ports.market_data import MarketDataPort
from sector_pulse.ports.news_sources import (
    DisclosureSearchPort,
    GlobalNewsDiscoveryPort,
    KeywordNewsSearchPort,
    SectorConstituentPort,
)


class ProviderPreflightResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    available: bool
    missing: tuple[str, ...] = ()


class RealDataProviderBundle(NamedTuple):
    market: MarketDataPort
    constituents: SectorConstituentPort
    global_news: GlobalNewsDiscoveryPort
    keyword_news: KeywordNewsSearchPort
    disclosure_news: DisclosureSearchPort


class RealDataProviderFactory:
    """组装真实数据适配器；preflight 阶段不触发第三方网络请求。"""

    def __init__(self, consent_file: Path | None = None) -> None:
        self._consent_file = consent_file or Path(".live-data-consent")

    def preflight(self) -> ProviderPreflightResult:
        # consent 是显式运行门槛，结果只暴露缺失项，不返回配置或密钥值。
        if not self._consent_file.is_file():
            return ProviderPreflightResult(available=False, missing=("live-data-consent",))
        return ProviderPreflightResult(available=True)

    def build(self) -> RealDataProviderBundle:
        result = self.preflight()
        if not result.available:
            raise RuntimeError("live data preflight unavailable")
        return RealDataProviderBundle(
            market=FallbackMarketDataAdapter(
                AkShareMarketDataAdapter(), AkShareThsMarketDataAdapter()
            ),
            constituents=AkShareSectorConstituentAdapter(),
            global_news=AkShareClsAdapter(),
            keyword_news=AkShareEastmoneyNewsAdapter(),
            disclosure_news=AkShareCninfoAdapter(),
        )
