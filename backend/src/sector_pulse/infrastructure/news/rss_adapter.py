import asyncio
import hashlib
import xml.etree.ElementTree as ElementTree
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urldefrag, urlsplit, urlunsplit

from sector_pulse.domain.news import NewsDocument
from sector_pulse.domain.provider import (
    AuthorizationStatus,
    DataStatus,
    ProviderError,
    ProviderManifest,
    ProviderResult,
)
from sector_pulse.infrastructure.news.rss_client import RssHttpClient


def _parse_datetime(value: Any) -> datetime | None:
    if not value:
        return None
    parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("RSS published datetime must include timezone")
    return parsed.astimezone(UTC)


def _canonical_url(url: str) -> str:
    base, _ = urldefrag(url.strip())
    parsed = urlsplit(base)
    return urlunsplit((parsed.scheme.lower(), parsed.netloc.lower(), parsed.path, parsed.query, ""))


class RssNewsAdapter:
    """将固定来源的 RSS 条目映射为 cutoff 内的新闻元数据。"""

    def __init__(self, client: RssHttpClient | None = None, source_id: str = "rss") -> None:
        self._client = client or RssHttpClient()
        self._source_id = source_id

    @property
    def manifest(self) -> ProviderManifest:
        return ProviderManifest(
            provider_id="rss-news",
            version="1.0.0",
            capabilities=frozenset({"news.discovery"}),
            authorization_status=AuthorizationStatus.RESEARCH_ONLY,
            supports_live=True,
            supports_as_of=True,
            source_attribution="Configured RSS feeds",
            retention_note="Metadata and hashes only in Phase 1A",
        )

    def map_items(
        self,
        rows: Sequence[Mapping[str, Any]],
        cutoff: datetime,
        observed_at: datetime,
    ) -> ProviderResult[tuple[NewsDocument, ...]]:
        documents: list[NewsDocument] = []
        for row in rows:
            published_at = _parse_datetime(row.get("published"))
            document = NewsDocument(
                document_id=str(row.get("id") or hashlib.sha256(str(row).encode()).hexdigest()),
                source_id=self._source_id,
                url=_canonical_url(str(row["link"])),
                title=str(row["title"]).strip(),
                published_at=published_at,
                observed_at=observed_at,
                content_hash=hashlib.sha256(
                    f"{row['title']}\n{row['link']}".encode()
                ).hexdigest(),
                source_grade=row.get("source_grade", "DISCOVERY_ONLY"),
            )
            if document.use_at(cutoff).value != "EXCLUDED":
                documents.append(document)
        if not documents:
            return ProviderResult(
                provider_id=self.manifest.provider_id,
                capability="news.discovery",
                status=DataStatus.EMPTY,
                collected_at=observed_at,
            )
        return ProviderResult(
            provider_id=self.manifest.provider_id,
            capability="news.discovery",
            status=DataStatus.SUCCESS,
            data=tuple(documents),
            observed_at=observed_at,
            collected_at=observed_at,
            source_version=self.manifest.version,
        )

    async def fetch_since(
        self, cutoff: datetime, source_ids: Sequence[str]
    ) -> ProviderResult[tuple[NewsDocument, ...]]:
        observed_at = datetime.now(UTC)
        try:
            rows: list[dict[str, Any]] = []
            for source_id in source_ids:
                content = await asyncio.to_thread(self._client.fetch, source_id)
                root = ElementTree.fromstring(content)
                for item in root.findall(".//item"):
                    rows.append(
                        {
                            "id": item.findtext("guid") or item.findtext("link"),
                            "title": item.findtext("title") or "",
                            "link": item.findtext("link") or "",
                            "published": item.findtext("pubDate") or item.findtext("published"),
                        }
                    )
            return self.map_items(rows, cutoff, observed_at)
        except Exception as exc:
            return ProviderResult(
                provider_id=self.manifest.provider_id,
                capability="news.discovery",
                status=DataStatus.FAILED,
                collected_at=observed_at,
                error=ProviderError(code="RSS_FETCH_FAILED", message=str(exc), retriable=True),
            )
