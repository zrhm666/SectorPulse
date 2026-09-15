from datetime import UTC, datetime

from sector_pulse.domain.news.news import NewsDocument
from sector_pulse.domain.provider import (
    AuthorizationStatus,
    DataStatus,
    ProviderManifest,
    ProviderResult,
)


class FixtureAgentNewsSearch:
    """An explicit empty search for offline workflow demonstrations."""

    @property
    def manifest(self) -> ProviderManifest:
        return ProviderManifest(
            provider_id="fixture-agent-news",
            version="1",
            capabilities=frozenset({"news.keyword.search"}),
            authorization_status=AuthorizationStatus.RESEARCH_ONLY,
            supports_live=False,
            supports_as_of=False,
            source_attribution="Offline fixture; no live search",
            retention_note="Synthetic demonstration only",
        )

    async def search(
        self, query: str, start_at: datetime, cutoff: datetime
    ) -> ProviderResult[tuple[NewsDocument, ...]]:
        return ProviderResult[tuple[NewsDocument, ...]](
            provider_id="fixture-agent-news",
            capability="news.keyword.search",
            status=DataStatus.EMPTY,
            collected_at=datetime.now(UTC),
            data=(),
        )
