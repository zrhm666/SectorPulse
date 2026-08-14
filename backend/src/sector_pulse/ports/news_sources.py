from datetime import datetime
from typing import Protocol

from sector_pulse.domain.market import SectorKind
from sector_pulse.domain.news import NewsDocument
from sector_pulse.domain.provider import ProviderManifest, ProviderResult


class GlobalNewsDiscoveryPort(Protocol):
    @property
    def manifest(self) -> ProviderManifest: ...

    async def fetch_global(self, cutoff: datetime) -> ProviderResult[tuple[NewsDocument, ...]]: ...


class KeywordNewsSearchPort(Protocol):
    @property
    def manifest(self) -> ProviderManifest: ...

    async def search(
        self, query: str, start_at: datetime, cutoff: datetime
    ) -> ProviderResult[tuple[NewsDocument, ...]]: ...


class DisclosureSearchPort(Protocol):
    @property
    def manifest(self) -> ProviderManifest: ...

    async def search_disclosures(
        self, stock_codes: tuple[str, ...], start_at: datetime, cutoff: datetime
    ) -> ProviderResult[tuple[NewsDocument, ...]]: ...


class SectorConstituentPort(Protocol):
    async def fetch_constituents(
        self, sector_name: str, kind: SectorKind
    ) -> ProviderResult[tuple[tuple[str, str], ...]]: ...
